"""
Configuration manager for the anime leech bot.
Loads settings from environment variables with defaults.
"""
import os
import logging
from typing import List, Optional
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# ============ Telegram Configuration ============
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
API_ID = int(os.getenv("API_ID", 0))
API_HASH = os.getenv("API_HASH", "")
CHANNEL_ID = int(os.getenv("CHANNEL_ID", 0))

# ============ Search Configuration ============
SITES = [
    "9animetv.to",
    "gogoanimes.cv", 
    "anikai.to",
    "anigo.to",
    "animixplay.by"
]

SEARCH_PATTERNS = [
    "/?s=",
    "/browser?keyword=", 
    "/"
]

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.5',
    'Accept-Encoding': 'gzip, deflate, br',
    'DNT': '1',
    'Connection': 'keep-alive',
    'Upgrade-Insecure-Requests': '1',
    'Sec-Fetch-Dest': 'document',
    'Sec-Fetch-Mode': 'navigate',
    'Sec-Fetch-Site': 'none',
    'Sec-Fetch-User': '?1',
    'Cache-Control': 'max-age=0'
}

# ============ Bot Behavior ============
MAX_CONCURRENT_DOWNLOADS = int(os.getenv("MAX_CONCURRENT_DOWNLOADS", 2))
MAX_EPISODES_PER_BATCH = int(os.getenv("MAX_EPISODES_PER_BATCH", 12))
TEMP_DIR = os.getenv("TEMP_DIR", "/tmp/anime_leech_bot")

# ============ User Management ============
OWNER_ID = int(os.getenv("OWNER_ID", 0))
ADMIN_IDS = [int(id.strip()) for id in os.getenv("ADMIN_IDS", "").split(",") if id.strip()]

# ============ Logging ============
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

# ============ FFmpeg Settings ============
FFMPEG_PATH = os.getenv("FFMPEG_PATH", "ffmpeg")
FFMPEG_TIMEOUT = int(os.getenv("FFMPEG_TIMEOUT", 300))

# ============ Progress Settings ============
PROGRESS_UPDATE_INTERVAL = int(os.getenv("PROGRESS_UPDATE_INTERVAL", 2))
PROGRESS_BAR_LENGTH = int(os.getenv("PROGRESS_BAR_LENGTH", 10))

# ============ Health Check ============
PORT = int(os.getenv("PORT", 8080))

# ============ Validation ============
def validate_config():
    """Validate configuration and set defaults."""
    errors = []
    
    if not BOT_TOKEN:
        errors.append("BOT_TOKEN is required")
    
    if not API_ID:
        errors.append("API_ID is required")
    
    if not API_HASH:
        errors.append("API_HASH is required")
    
    if not CHANNEL_ID:
        errors.append("CHANNEL_ID is required")
    
    if errors:
        raise ValueError(f"Configuration errors: {', '.join(errors)}")
    
    # Create temp directory if it doesn't exist
    os.makedirs(TEMP_DIR, exist_ok=True)
    
    # Set logging level
    logging.basicConfig(
        level=getattr(logging, LOG_LEVEL, logging.INFO),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    logger = logging.getLogger(__name__)
    logger.info("Configuration loaded successfully")
    
    # Log important settings (without sensitive data)
    logger.info(f"Max concurrent downloads: {MAX_CONCURRENT_DOWNLOADS}")
    logger.info(f"Temp directory: {TEMP_DIR}")
    logger.info(f"Channel ID: {CHANNEL_ID}")

# Validate on import
validate_config()