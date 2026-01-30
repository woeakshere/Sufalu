"""
Progress bar utilities for Telegram messages with zero division fix.
"""
import math
from typing import Optional
from datetime import datetime, timedelta

def create_progress_bar(percentage: float, length: int = 10) -> str:
    """
    Create a visual progress bar.
    
    Args:
        percentage: 0-100
        length: Number of characters in the bar
    
    Returns:
        Visual progress bar string
    """
    percentage = max(0, min(100, percentage))
    filled = int(length * percentage / 100)
    
    # Use different characters for better appearance
    bar_chars = ['░'] * length
    for i in range(filled):
        if i == filled - 1 and percentage < 100:
            bar_chars[i] = '▒'  # Current position
        else:
            bar_chars[i] = '▓'  # Completed
    
    return f"[{''.join(bar_chars)}] {percentage:.1f}%"

def format_file_size(size_bytes: int) -> str:
    """Convert bytes to human readable format."""
    if size_bytes == 0:
        return "0 B"
    
    size_names = ['B', 'KB', 'MB', 'GB', 'TB']
    i = int(math.floor(math.log(size_bytes, 1024)))
    p = math.pow(1024, i)
    s = round(size_bytes / p, 2)
    
    return f"{s} {size_names[i]}"

def format_speed(speed_bytes: float) -> str:
    """Format speed in human readable format."""
    return f"{format_file_size(int(speed_bytes))}/s"

def format_time(seconds: float) -> str:
    """Format seconds to human readable time."""
    if seconds <= 0:
        return "00:00:00"
    
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    else:
        return f"{minutes:02d}:{secs:02d}"

def create_progress_message(task, current: int, total: int, 
                           speed: float = 0, eta: Optional[float] = None) -> str:
    """
    Create a comprehensive progress message for Telegram.
    Handles zero total case gracefully.
    """
    # Handle zero total to avoid division by zero
    if total <= 0:
        percentage = 0
        progress_bar = "[░░░░░░░░░░] 0.0%"
        size_info = f"📦 `{format_file_size(current)}`"
    else:
        percentage = min(100, (current / total * 100))
        progress_bar = create_progress_bar(percentage)
        size_info = f"📦 `{format_file_size(current)} / {format_file_size(total)}`"
    
    message_parts = [
        f"🎬 *{task.anime_title}*",
        f"📺 Episode {task.episode_num} [{task.quality}]",
        ""
    ]
    
    message_parts.append(f"**Upload Progress:**")
    message_parts.append(progress_bar)
    message_parts.append(size_info)
    
    # Speed and ETA (only show if we have data)
    if speed > 0:
        message_parts.append(f"⚡ {format_speed(speed)}")
    
    if eta and eta > 0:
        eta_time = datetime.now() + timedelta(seconds=eta)
        message_parts.append(f"⏳ ETA: {format_time(eta)} ({eta_time.strftime('%H:%M:%S')})")
    
    # Percentage (only if total > 0)
    if total > 0:
        message_parts.append(f"`{percentage:.1f}% complete`")
    
    return "\n".join(message_parts)

def create_completion_message(task, file_size: int, duration: float) -> str:
    """
    Create completion message for finished upload.
    
    Args:
        task: DownloadTask object
        file_size: Final file size in bytes
        duration: Upload duration in seconds
    
    Returns:
        Formatted completion message
    """
    avg_speed = file_size / duration if duration > 0 else 0
    
    message = [
        f"✅ *Upload Complete!*\n",
        f"🎬 {task.anime_title}",
        f"📺 Episode {task.episode_num} [{task.quality}]",
        f"📊 {format_file_size(file_size)}",
        f"⚡ Average: {format_speed(avg_speed)}",
        f"⏱️ Duration: {format_time(duration)}",
        f"📅 {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "",
        f"🔗 Episode uploaded to channel"
    ]
    
    return "\n".join(message)

def create_error_message(task, error_msg: str) -> str:
    """
    Create error message for failed upload.
    
    Args:
        task: DownloadTask object
        error_msg: Error message
    
    Returns:
        Formatted error message
    """
    message = [
        f"❌ *Upload Failed*\n",
        f"🎬 {task.anime_title}",
        f"📺 Episode {task.episode_num} [{task.quality}]",
        "",
        f"**Error:**",
        f"`{error_msg[:150]}`",
        "",
        f"⚠️ Please try again or contact admin."
    ]
    
    return "\n".join(message)

def create_queue_message(position: int, total_in_queue: int, estimated_wait: float = 0) -> str:
    """
    Create queue status message.
    
    Args:
        position: Position in queue (1-based)
        total_in_queue: Total items in queue
        estimated_wait: Estimated wait time in seconds
    
    Returns:
        Formatted queue message
    """
    message = [
        f"📋 *Queue Status*",
        f"Position: `{position}` of `{total_in_queue}`"
    ]
    
    if estimated_wait > 0:
        message.append(f"Estimated wait: `{format_time(estimated_wait)}`")
    
    message.append("")
    message.append("Your download will start soon...")
    
    return "\n".join(message)