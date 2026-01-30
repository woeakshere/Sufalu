
"""
Core transfer module with graceful FFmpeg termination.
"""
import asyncio
import os
import re
import time
import signal
import platform
import logging
from dataclasses import dataclass
from typing import Optional, Dict, Any
from datetime import datetime

import aiohttp
from pyrogram import Client
from pyrogram.errors import FloodWait

from config import (
    MAX_CONCURRENT_DOWNLOADS, API_ID, API_HASH, 
    CHANNEL_ID, BOT_TOKEN, LOG_LEVEL,
    FFMPEG_PATH, FFMPEG_TIMEOUT, OWNER_ID, ADMIN_IDS
)

logger = logging.getLogger(__name__)

@dataclass(slots=True)
class DownloadTask:
    """Memory-efficient task container."""
    episode_url: str
    quality: str
    user_id: int
    anime_title: str
    episode_num: int
    chat_id: Optional[int] = None
    message_id: Optional[int] = None
    subtitle_url: Optional[str] = None

class TransferManager:
    def __init__(self, pyro_app: Client):
        self.queue = asyncio.Queue()
        self.pyro_app = pyro_app
        self.active_processes: Dict[int, asyncio.subprocess.Process] = {}
        self._session: Optional[aiohttp.ClientSession] = None
        self.task_progress: Dict[str, Dict[str, Any]] = {}
        
        # Statistics
        self.stats = {
            'total_processed': 0,
            'total_failed': 0,
            'total_size': 0,
            'start_time': time.time()
        }
    
    @property
    async def session(self):
        """Lazy-load aiohttp session."""
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=30)
            self._session = aiohttp.ClientSession(timeout=timeout)
        return self._session
    
    async def start_workers(self, count: int = None):
        """Start worker coroutines."""
        worker_count = count or MAX_CONCURRENT_DOWNLOADS
        for i in range(worker_count):
            asyncio.create_task(self._worker(f"worker-{i}"))
        logger.info(f"Started {worker_count} transfer workers")
    
    async def _worker(self, name: str):
        """Worker process: handles download, processing, and upload."""
        while True:
            task: DownloadTask = await self.queue.get()
            task_id = f"{task.anime_title}_Ep{task.episode_num}"
            
            try:
                logger.info(f"[{name}] Processing {task_id}")
                
                # 1. Extract m3u8 URL using searcher
                from search import searcher
                m3u8_url = await searcher.extract_m3u8(task.episode_url)
                
                if not m3u8_url:
                    await self._notify_user(
                        task, 
                        f"❌ Failed to extract video for {task_id}",
                        is_error=True
                    )
                    self.stats['total_failed'] += 1
                    continue
                
                # 2. Stream and upload
                success = await self._stream_and_upload(m3u8_url, task)
                
                if success:
                    await self._notify_user(
                        task,
                        f"✅ Uploaded {task_id} [{task.quality}]"
                    )
                    self.stats['total_processed'] += 1
                else:
                    await self._notify_user(
                        task,
                        f"❌ Failed to upload {task_id}",
                        is_error=True
                    )
                    self.stats['total_failed'] += 1
                    
            except Exception as e:
                logger.error(f"[{name}] Error processing {task_id}: {e}", exc_info=True)
                await self._notify_user(
                    task,
                    f"⚠️ Error processing {task_id}: {str(e)[:100]}",
                    is_error=True
                )
                self.stats['total_failed'] += 1
            finally:
                self.queue.task_done()
                # Cleanup task progress
                task_key = f"{task.user_id}_{task.episode_num}"
                if task_key in self.task_progress:
                    del self.task_progress[task_key]
    
    async def _stream_and_upload(self, m3u8_url: str, task: DownloadTask) -> bool:
        """Stream from m3u8 and upload to Telegram with graceful FFmpeg termination."""
        # Build FFmpeg command with additional flags for graceful termination
        cmd = [
            FFMPEG_PATH,
            '-i', m3u8_url,
            '-c', 'copy',
            '-f', 'mp4',
            '-movflags', 'frag_keyframe+empty_moov+default_base_moof',
            '-loglevel', 'error',
            '-flush_packets', '1',  # Flush packets immediately
            'pipe:1'
        ]
        
        logger.debug(f"FFmpeg command: {' '.join(cmd)}")
        
        # Start FFmpeg process
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            stdin=asyncio.subprocess.PIPE,  # Add stdin for graceful shutdown
            limit=10 * 1024 * 1024  # 10MB buffer
        )
        
        self.active_processes[task.user_id] = process
        
        try:
            # Upload with progress tracking
            upload_task = asyncio.create_task(
                self.pyro_app.send_document(
                    chat_id=CHANNEL_ID,
                    document=process.stdout,
                    file_name=f"{task.anime_title}_Ep{task.episode_num}_{task.quality}.mp4",
                    caption=f"🎬 {task.anime_title}\n📺 Episode {task.episode_num} [{task.quality}]\n🕐 {datetime.now().strftime('%Y-%m-%d %H:%M')}",
                    progress=self._upload_progress_callback,
                    progress_args=(task,)
                )
            )
            
            # Monitor process
            _, stderr = await asyncio.gather(
                upload_task,
                process.stderr.read()
            )
            
            # Check FFmpeg exit code
            return_code = await process.wait()
            
            if return_code == 0:
                logger.info(f"Successfully uploaded {task.anime_title} Ep {task.episode_num}")
                return True
            else:
                if stderr:
                    logger.error(f"FFmpeg failed with code {return_code}: {stderr.decode()[:200]}")
                return False
                
        except asyncio.CancelledError:
            logger.info(f"Upload cancelled for {task.anime_title}")
            raise
        except FloodWait as e:
            logger.warning(f"Flood wait: {e}")
            await asyncio.sleep(e.value)
            return False
        except Exception as e:
            logger.error(f"Upload failed: {e}")
            return False
        finally:
            # Graceful termination
            await self._terminate_ffmpeg_gracefully(process)
            if task.user_id in self.active_processes:
                del self.active_processes[task.user_id]
    
    async def _terminate_ffmpeg_gracefully(self, process: asyncio.subprocess.Process):
        """Terminate FFmpeg process gracefully."""
        if process.returncode is None:
            try:
                # Send 'q' to stdin to signal FFmpeg to quit gracefully
                if process.stdin and not process.stdin.is_closing():
                    process.stdin.write(b'q')
                    await process.stdin.drain()
                    await process.stdin.wait_closed()
                
                # Wait for graceful exit
                try:
                    await asyncio.wait_for(process.wait(), timeout=5)
                except asyncio.TimeoutError:
                    # Force terminate if not responding
                    if platform.system() != 'Windows':
                        try:
                            process.send_signal(signal.SIGINT)
                            await asyncio.sleep(1)
                        except ProcessLookupError:
                            pass
                    
                    try:
                        process.terminate()
                        await asyncio.wait_for(process.wait(), timeout=2)
                    except (asyncio.TimeoutError, ProcessLookupError):
                        try:
                            process.kill()
                        except ProcessLookupError:
                            pass
                        
            except Exception as e:
                logger.debug(f"Error during graceful termination: {e}")
    
    async def _upload_progress_callback(self, current: int, total: int, task: DownloadTask):
        """Upload progress callback with throttling."""
        # Throttle updates (max once per 2 seconds)
        task_key = f"{task.user_id}_{task.episode_num}"
        last_update = self.task_progress.get(task_key, {}).get('last_update', 0)
        
        current_time = time.time()
        if current_time - last_update < 2 and current < total:
            return
        
        # Update progress info
        self.task_progress[task_key] = {
            'current': current,
            'total': total,
            'last_update': current_time,
            'speed': self._calculate_speed(task_key, current, current_time)
        }
        
        # Send progress update via main bot
        if task.chat_id and task.message_id:
            try:
                from utils.progress_bar import create_progress_message
                progress_info = self.task_progress.get(task_key, {})
                speed = progress_info.get('speed', 0)
                
                # Calculate ETA
                eta = None
                if total > 0 and speed > 0:
                    remaining = total - current
                    eta = remaining / speed
                
                message = create_progress_message(task, current, total, speed, eta)
                
                # Import main bot instance
                from main import telegram_handler
                if telegram_handler:
                    await telegram_handler.edit_message(
                        chat_id=task.chat_id,
                        message_id=task.message_id,
                        text=message
                    )
                    
            except Exception as e:
                logger.error(f"Failed to update progress: {e}")
    
    def _calculate_speed(self, task_key: str, current_bytes: int, current_time: float) -> float:
        """Calculate upload speed in bytes/second."""
        if task_key in self.task_progress:
            prev = self.task_progress[task_key]
            time_diff = current_time - prev.get('last_update', current_time)
            bytes_diff = current_bytes - prev.get('current', 0)
            
            if time_diff > 0:
                return bytes_diff / time_diff
        
        return 0
    
    async def _notify_user(self, task: DownloadTask, message: str, is_error: bool = False):
        """Send notification to user."""
        if task.chat_id:
            try:
                from main import telegram_handler
                if telegram_handler:
                    prefix = "❌ " if is_error else "✅ "
                    await telegram_handler.send_message(
                        chat_id=task.chat_id,
                        text=f"{prefix}{message}"
                    )
            except Exception as e:
                logger.error(f"Failed to notify user: {e}")
    
    async def cancel_user_tasks(self, user_id: int):
        """Cancel all tasks for a specific user gracefully."""
        if user_id in self.active_processes:
            process = self.active_processes[user_id]
            await self._terminate_ffmpeg_gracefully(process)
            if user_id in self.active_processes:
                del self.active_processes[user_id]
            logger.info(f"Cancelled tasks for user {user_id}")
    
    def get_stats(self) -> Dict[str, Any]:
        """Get transfer manager statistics."""
        uptime = time.time() - self.stats['start_time']
        
        return {
            'queue_size': self.queue.qsize(),
            'active_processes': len(self.active_processes),
            'total_processed': self.stats['total_processed'],
            'total_failed': self.stats['total_failed'],
            'uptime_hours': uptime / 3600,
            'avg_per_hour': self.stats['total_processed'] / (uptime / 3600) if uptime > 0 else 0
        }
    
    async def close(self):
        """Cleanup resources."""
        if self._session and not self._session.closed:
            await self._session.close()
        
        # Terminate all active processes
        for user_id, process in list(self.active_processes.items()):
            if process.returncode is None:
                await self._terminate_ffmpeg_gracefully(process)
                if user_id in self.active_processes:
                    del self.active_processes[user_id]