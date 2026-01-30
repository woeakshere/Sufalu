"""
Utility functions for the anime leech bot.
"""
import re
import hashlib
import asyncio
from typing import Optional, Dict, Any
from urllib.parse import urlparse, parse_qs, urlencode

def sanitize_filename(filename: str) -> str:
    """
    Sanitize filename for safe filesystem usage.
    
    Args:
        filename: Original filename
    
    Returns:
        Sanitized filename
    """
    # Remove invalid characters
    invalid_chars = '<>:"/\\|?*'
    for char in invalid_chars:
        filename = filename.replace(char, '_')
    
    # Limit length
    if len(filename) > 200:
        name, ext = filename.rsplit('.', 1) if '.' in filename else (filename, '')
        name = name[:200 - len(ext) - 1]
        filename = f"{name}.{ext}" if ext else name
    
    return filename.strip()

def extract_domain(url: str) -> str:
    """Extract domain from URL."""
    parsed = urlparse(url)
    return parsed.netloc

def generate_task_id(user_id: int, anime_title: str, episode_num: int) -> str:
    """Generate unique task ID."""
    content = f"{user_id}_{anime_title}_{episode_num}"
    return hashlib.md5(content.encode()).hexdigest()[:8]

async def async_retry(func, max_retries: int = 3, delay: float = 1.0, 
                     exceptions=(Exception,)):
    """
    Retry async function with exponential backoff.
    
    Args:
        func: Async function to retry
        max_retries: Maximum retry attempts
        delay: Initial delay between retries
        exceptions: Exceptions to catch
    
    Returns:
        Function result
    
    Raises:
        Last exception if all retries fail
    """
    last_exception = None
    
    for attempt in range(max_retries):
        try:
            return await func()
        except exceptions as e:
            last_exception = e
            if attempt < max_retries - 1:
                wait_time = delay * (2 ** attempt)  # Exponential backoff
                await asyncio.sleep(wait_time)
    
    raise last_exception

def parse_episode_range(range_str: str) -> Optional[tuple]:
    """
    Parse episode range string.
    
    Args:
        range_str: Range string like "1-12", "5", or "all"
    
    Returns:
        Tuple of (start, end) or None
    """
    range_str = range_str.strip().lower()
    
    if range_str == 'all':
        return (1, None)  # All episodes
    
    if '-' in range_str:
        try:
            start_str, end_str = range_str.split('-')
            start = int(start_str.strip())
            end = int(end_str.strip())
            return (start, end)
        except ValueError:
            return None
    
    try:
        ep_num = int(range_str)
        return (ep_num, ep_num)
    except ValueError:
        return None

def format_duration(seconds: float) -> str:
    """Format duration in seconds to human readable string."""
    if seconds < 60:
        return f"{seconds:.1f}s"
    elif seconds < 3600:
        minutes = seconds / 60
        return f"{minutes:.1f}m"
    else:
        hours = seconds / 3600
        return f"{hours:.1f}h"

def build_url(base: str, params: Dict[str, Any]) -> str:
    """Build URL with query parameters."""
    query_string = urlencode({k: str(v) for k, v in params.items() if v is not None})
    return f"{base}?{query_string}" if query_string else base