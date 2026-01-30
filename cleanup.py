"""
Resource cleanup manager for temporary files.
Handles cleanup of temp files and periodic maintenance.
"""
import asyncio
import os
import time
import shutil
import logging
from typing import Set, List
from pathlib import Path

from config import TEMP_DIR, LOG_LEVEL

logger = logging.getLogger(__name__)

class CleanupManager:
    def __init__(self):
        self.files_to_clean: Set[str] = set()
        self.cleanup_interval = 300  # 5 minutes
        self.max_temp_age = 3600  # 1 hour
    
    async def schedule_cleanup(self, *file_paths: str):
        """Schedule files for deletion."""
        self.files_to_clean.update(file_paths)
    
    async def execute_cleanup(self):
        """Delete all scheduled files."""
        for file_path in self.files_to_clean.copy():
            try:
                if os.path.exists(file_path):
                    os.remove(file_path)
                    logger.debug(f"Cleaned up: {file_path}")
                    
                    # Also clean up related files
                    base_name = os.path.splitext(file_path)[0]
                    for ext in ['.srt', '.meta', '.ts', '.jpg', '.png', '.ass', '.vtt']:
                        related = base_name + ext
                        if os.path.exists(related):
                            os.remove(related)
                            
                    # Clean up empty directories
                    parent_dir = os.path.dirname(file_path)
                    if os.path.exists(parent_dir) and not os.listdir(parent_dir):
                        os.rmdir(parent_dir)
                        
            except OSError as e:
                logger.error(f"Cleanup error for {file_path}: {e}")
            finally:
                self.files_to_clean.discard(file_path)
    
    async def cleanup_task(self):
        """Background task to clean TEMP_DIR of old files periodically."""
        while True:
            try:
                await self._cleanup_temp_dir()
                await asyncio.sleep(self.cleanup_interval)
            except Exception as e:
                logger.error(f"Periodic cleanup error: {e}")
                await asyncio.sleep(60)
    
    async def _cleanup_temp_dir(self):
        """Clean up old files in TEMP_DIR."""
        if not os.path.exists(TEMP_DIR):
            return
        
        current_time = time.time()
        removed_count = 0
        
        for root, dirs, files in os.walk(TEMP_DIR):
            for file in files:
                file_path = os.path.join(root, file)
                
                try:
                    file_age = current_time - os.path.getmtime(file_path)
                    
                    if file_age > self.max_temp_age:
                        os.remove(file_path)
                        removed_count += 1
                        logger.debug(f"Removed old temp file: {file_path}")
                        
                except OSError as e:
                    logger.error(f"Error removing {file_path}: {e}")
            
            # Remove empty directories
            for dir_name in dirs:
                dir_path = os.path.join(root, dir_name)
                try:
                    if not os.listdir(dir_path):
                        os.rmdir(dir_path)
                        logger.debug(f"Removed empty directory: {dir_path}")
                except OSError:
                    pass
        
        if removed_count > 0:
            logger.info(f"Cleaned up {removed_count} old temp files")
    
    async def emergency_cleanup(self, min_free_space_gb: float = 5):
        """
        Emergency cleanup when disk space is low.
        
        Args:
            min_free_space_gb: Minimum free space in GB to maintain
        """
        import psutil
        
        disk = psutil.disk_usage('/')
        free_space_gb = disk.free / (1024 ** 3)
        
        if free_space_gb < min_free_space_gb:
            logger.warning(f"Low disk space: {free_space_gb:.2f} GB free")
            
            # Delete all temp files regardless of age
            if os.path.exists(TEMP_DIR):
                for root, dirs, files in os.walk(TEMP_DIR):
                    for file in files:
                        file_path = os.path.join(root, file)
                        try:
                            os.remove(file_path)
                        except OSError:
                            pass
                
                # Try to remove the directory
                try:
                    shutil.rmtree(TEMP_DIR, ignore_errors=True)
                except:
                    pass
                
                # Recreate directory
                os.makedirs(TEMP_DIR, exist_ok=True)
                logger.info("Emergency cleanup completed")
    
    def get_temp_usage(self) -> dict:
        """Get temporary directory usage statistics."""
        if not os.path.exists(TEMP_DIR):
            return {'exists': False, 'size_gb': 0, 'file_count': 0}
        
        total_size = 0
        file_count = 0
        
        for root, dirs, files in os.walk(TEMP_DIR):
            for file in files:
                file_path = os.path.join(root, file)
                try:
                    total_size += os.path.getsize(file_path)
                    file_count += 1
                except OSError:
                    pass
        
        return {
            'exists': True,
            'size_gb': total_size / (1024 ** 3),
            'file_count': file_count,
            'scheduled_cleanup': len(self.files_to_clean)
        }

# Global instance
cleaner = CleanupManager()