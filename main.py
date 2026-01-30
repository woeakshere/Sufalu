#!/usr/bin/env python3
"""
Main bot orchestrator with dual Telegram client setup and graceful shutdown.
"""
import asyncio
import logging
import signal
import sys
import os
from typing import Dict, Any

# Add project root to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, 
    ContextTypes, MessageHandler, filters
)
from pyrogram import Client

from config import (
    BOT_TOKEN, API_ID, API_HASH, OWNER_ID, ADMIN_IDS,
    MAX_CONCURRENT_DOWNLOADS, LOG_LEVEL, CHANNEL_ID
)
from search import searcher
from transfer import TransferManager, DownloadTask
from healthcheck import register_component

# Setup logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=getattr(logging, LOG_LEVEL, logging.INFO)
)
logger = logging.getLogger(__name__)

# Global instances
transfer_mgr: TransferManager = None
application: Application = None
pyro_client: Client = None
background_tasks = set()

class TelegramBotHandler:
    """Handler for sending messages back to users via Telegram."""
    
    def __init__(self, app: Application):
        self.app = app
    
    async def send_message(self, chat_id: int, text: str, parse_mode: str = 'Markdown', 
                         reply_markup=None, disable_web_page_preview: bool = True):
        """Send message to user."""
        try:
            await self.app.bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode=parse_mode,
                reply_markup=reply_markup,
                disable_web_page_preview=disable_web_page_preview
            )
        except Exception as e:
            logger.error(f"Failed to send message to {chat_id}: {e}")
    
    async def edit_message(self, chat_id: int, message_id: int, text: str, 
                          parse_mode: str = 'Markdown', reply_markup=None):
        """Edit existing message."""
        try:
            await self.app.bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=text,
                parse_mode=parse_mode,
                reply_markup=reply_markup
            )
        except Exception as e:
            logger.error(f"Failed to edit message {message_id}: {e}")

telegram_handler = None

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command."""
    welcome_msg = (
        "🎬 *Anime Leech Bot*\n\n"
        "Download anime episodes directly to Telegram channel!\n\n"
        "*Commands:*\n"
        "/download <anime> - Search and download anime\n"
        "/cancel - Cancel current operation\n"
        "/status - Check active downloads\n"
        "/stats - Bot statistics (Admin)\n"
        "/help - Show help message\n\n"
        "Made with ❤️ for anime lovers"
    )
    
    await update.message.reply_text(
        welcome_msg,
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📚 Search Anime", callback_data="search_now")],
            [InlineKeyboardButton("📊 View Stats", callback_data="view_stats")]
        ])
    )

async def download_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /download command with improved error handling."""
    try:
        if not context.args:
            await update.message.reply_text(
                "Please provide anime name:\n`/download Attack on Titan`",
                parse_mode='Markdown'
            )
            return
        
        # Check if user is already downloading
        user_id = update.effective_user.id
        if transfer_mgr and user_id in transfer_mgr.active_processes:
            await update.message.reply_text(
                "⏳ You already have an active download. Please wait for it to complete.",
                parse_mode='Markdown'
            )
            return
        
        keyword = " ".join(context.args)
        
        # Send searching message
        msg = await update.message.reply_text(
            f"🔍 *Searching for '{keyword}'...*\n"
            f"Checking multiple anime sites...",
            parse_mode='Markdown'
        )
        
        # Perform search
        results = await searcher.search(keyword)
        
        if not results:
            await msg.edit_text(
                f"❌ *No results found for '{keyword}'*\n\n"
                f"Try different keywords or check spelling.",
                parse_mode='Markdown'
            )
            return
        
        # Create selection keyboard
        keyboard = []
        for i, result in enumerate(results[:8]):
            title = result.title[:40] + "..." if len(result.title) > 40 else result.title
            site_info = f" ({result.site})" if result.site else ""
            keyboard.append([InlineKeyboardButton(
                f"{i+1}. {title}{site_info}",
                callback_data=f"select:{i}:{user_id}"
            )])
        
        keyboard.append([InlineKeyboardButton("❌ Cancel", callback_data=f"cancel:{user_id}")])
        
        await msg.edit_text(
            f"✅ *Found {len(results)} results for '{keyword}':*\n"
            f"Select an anime from below:",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        
        # Store user context
        context.user_data['search_results'] = results
        context.user_data['search_message_id'] = msg.message_id
        
    except Exception as e:
        logger.error(f"Download command error: {e}", exc_info=True)
        await update.message.reply_text(
            f"❌ *Error searching:*\n`{str(e)[:100]}`",
            parse_mode='Markdown'
        )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle inline button callbacks."""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    user_id = query.from_user.id
    
    try:
        if data == "search_now":
            await query.edit_message_text(
                "Enter the anime name you want to search:",
                parse_mode='Markdown'
            )
            
        elif data == "view_stats":
            if user_id not in [OWNER_ID] + ADMIN_IDS:
                await query.edit_message_text("❌ Admin only feature.")
                return
            
            if not transfer_mgr:
                await query.edit_message_text("❌ Transfer manager not initialized.")
                return
            
            stats = transfer_mgr.get_stats()
            import psutil
            memory = psutil.virtual_memory()
            
            stats_text = (
                f"📊 *Bot Statistics*\n\n"
                f"*System:*\n"
                f"• Memory: {memory.percent}% used\n"
                f"• Queue size: {stats['queue_size']}\n"
                f"• Active downloads: {stats['active_processes']}\n"
                f"• Total processed: {stats['total_processed']}\n"
                f"• Uptime: {stats['uptime_hours']:.1f} hours\n"
            )
            
            await query.edit_message_text(stats_text, parse_mode='Markdown')
            
        elif data.startswith("select:"):
            # User selected an anime
            _, idx_str, target_user = data.split(":")
            idx = int(idx_str)
            
            if user_id != int(target_user):
                await query.edit_message_text("❌ This selection is not for you.")
                return
            
            results = context.user_data.get('search_results')
            if not results or idx >= len(results):
                await query.edit_message_text("❌ Invalid selection.")
                return
            
            selected = results[idx]
            
            # Get episodes
            await query.edit_message_text(
                f"⏳ *Fetching episodes for {selected.title}...*",
                parse_mode='Markdown'
            )
            
            episodes = await searcher.fetch_episode_links(selected.url)
            if not episodes:
                await query.edit_message_text("❌ No episodes found.")
                return
            
            context.user_data['selected_anime'] = selected
            context.user_data['episodes'] = episodes
            
            # Ask for quality
            keyboard = [
                [InlineKeyboardButton("720p", callback_data=f"quality:720p:{user_id}")],
                [InlineKeyboardButton("1080p", callback_data=f"quality:1080p:{user_id}")],
                [InlineKeyboardButton("480p", callback_data=f"quality:480p:{user_id}")],
                [InlineKeyboardButton("❌ Cancel", callback_data=f"cancel:{user_id}")]
            ]
            
            await query.edit_message_text(
                f"🎬 *{selected.title}*\n"
                f"Found {len(episodes)} episodes\n\n"
                f"Select quality (applies to all episodes):",
                parse_mode='Markdown',
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            
        elif data.startswith("quality:"):
            # User selected quality
            _, quality, target_user = data.split(":")
            
            if user_id != int(target_user):
                return
            
            selected = context.user_data.get('selected_anime')
            episodes = context.user_data.get('episodes', [])
            
            if not selected or not episodes:
                await query.edit_message_text("❌ Session expired.")
                return
            
            # Queue all episodes
            await query.edit_message_text(
                f"⏳ *Queueing {len(episodes)} episodes at {quality}...*\n\n"
                f"Progress will be shown here.",
                parse_mode='Markdown'
            )
            
            for i, ep_url in enumerate(episodes, 1):
                task = DownloadTask(
                    episode_url=ep_url,
                    quality=quality,
                    user_id=user_id,
                    anime_title=selected.title,
                    episode_num=i,
                    chat_id=query.message.chat_id,
                    message_id=query.message.message_id
                )
                await transfer_mgr.queue.put(task)
            
            # Clear user data
            context.user_data.clear()
            
        elif data.startswith("cancel:"):
            target_user = int(data.split(":")[1])
            if user_id == target_user:
                await query.edit_message_text("✅ Operation cancelled.")
                context.user_data.clear()
                
    except Exception as e:
        logger.error(f"Button handler error: {e}", exc_info=True)
        await query.edit_message_text(f"❌ Error: `{str(e)[:100]}`")

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /status command to show user's active downloads."""
    user_id = update.effective_user.id
    
    if not transfer_mgr:
        await update.message.reply_text("❌ Transfer manager not initialized.")
        return
    
    # Get user's active processes
    active_count = 0
    queue_position = 0
    
    # Check queue
    for i in range(transfer_mgr.queue.qsize()):
        try:
            task = await asyncio.wait_for(transfer_mgr.queue.get(), timeout=0.1)
            transfer_mgr.queue.task_done()
            # Put it back
            await transfer_mgr.queue.put(task)
            
            if task.user_id == user_id:
                queue_position = i + 1
                active_count += 1
        except (asyncio.TimeoutError, AttributeError):
            break
    
    # Check active processes
    if user_id in transfer_mgr.active_processes:
        active_count += 1
    
    if active_count == 0:
        await update.message.reply_text(
            "📊 *Your Status*\n\n"
            "✅ No active downloads\n"
            "⏳ No queued episodes",
            parse_mode='Markdown'
        )
    else:
        await update.message.reply_text(
            f"📊 *Your Status*\n\n"
            f"🔄 Active downloads: {active_count}\n"
            f"📋 Queue position: {queue_position}\n\n"
            f"Use /cancel to stop all downloads.",
            parse_mode='Markdown'
        )

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /stats command (Admin only)."""
    user_id = update.effective_user.id
    
    if user_id not in [OWNER_ID] + ADMIN_IDS:
        await update.message.reply_text("❌ Admin only command.")
        return
    
    if not transfer_mgr:
        await update.message.reply_text("❌ Transfer manager not initialized.")
        return
    
    # Get system stats
    import psutil
    import platform
    
    cpu_percent = psutil.cpu_percent()
    memory = psutil.virtual_memory()
    disk = psutil.disk_usage('/')
    
    # Bot stats
    stats = transfer_mgr.get_stats()
    queue_size = transfer_mgr.queue.qsize()
    active_tasks = len(transfer_mgr.active_processes)
    
    stats_text = (
        f"🤖 *Bot Statistics*\n\n"
        f"*System:*\n"
        f"• CPU Usage: {cpu_percent}%\n"
        f"• Memory: {memory.percent}% used\n"
        f"• Disk: {disk.percent}% used\n\n"
        f"*Bot Operations:*\n"
        f"• Queue size: {queue_size}\n"
        f"• Active downloads: {active_tasks}\n"
        f"• Total processed: {stats['total_processed']}\n"
        f"• Total failed: {stats['total_failed']}\n"
        f"• Uptime: {stats['uptime_hours']:.1f} hours\n\n"
        f"*Configuration:*\n"
        f"• Max concurrent: {MAX_CONCURRENT_DOWNLOADS}\n"
        f"• Channel ID: {CHANNEL_ID}\n"
    )
    
    await update.message.reply_text(stats_text, parse_mode='Markdown')

async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /cancel command."""
    user_id = update.effective_user.id
    
    # Cancel user's active processes
    if transfer_mgr:
        await transfer_mgr.cancel_user_tasks(user_id)
    
    # Clear user state
    context.user_data.clear()
    
    await update.message.reply_text(
        "✅ *All operations cancelled*\n\n"
        "Your downloads have been stopped and session cleared.",
        parse_mode='Markdown'
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /help command."""
    help_text = (
        "🎬 *Anime Leech Bot Help*\n\n"
        "*Available Commands:*\n"
        "`/download <anime>` - Search and download anime\n"
        "`/status` - Check your active downloads\n"
        "`/cancel` - Cancel all your operations\n"
        "`/stats` - Bot statistics (Admin only)\n"
        "`/help` - Show this message\n\n"
        "*Usage Tips:*\n"
        "• Use specific anime names for better results\n"
        "• Downloads go to private channel\n"
        "• Progress updates appear in this chat\n\n"
        "*Note:* Downloading copyrighted content may violate terms of service."
    )
    
    await update.message.reply_text(help_text, parse_mode='Markdown')

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Log errors."""
    logger.error(f"Update {update} caused error {context.error}", exc_info=True)
    
    # Notify user
    if update and update.effective_message:
        await update.effective_message.reply_text(
            f"❌ An error occurred:\n`{str(context.error)[:200]}`",
            parse_mode='Markdown'
        )

async def shutdown_handler(signal_name: str = None):
    """Graceful shutdown handler."""
    logger.info(f"Received shutdown signal {signal_name}")
    
    global transfer_mgr, application, pyro_client
    
    # Stop accepting new messages
    if application:
        await application.stop()
        await application.shutdown()
    
    # Stop transfer manager
    if transfer_mgr:
        # Cancel all user tasks
        for user_id in list(transfer_mgr.active_processes.keys()):
            await transfer_mgr.cancel_user_tasks(user_id)
        
        # Wait for queue to empty with timeout
        try:
            await asyncio.wait_for(transfer_mgr.queue.join(), timeout=30)
        except asyncio.TimeoutError:
            logger.warning("Queue timeout during shutdown")
        
        await transfer_mgr.close()
    
    # Stop Pyrogram client
    if pyro_client:
        await pyro_client.stop()
    
    # Cancel all background tasks
    for task in background_tasks:
        task.cancel()
    
    # Wait for tasks to complete
    if background_tasks:
        await asyncio.gather(*background_tasks, return_exceptions=True)
    
    logger.info("Shutdown complete")

def setup_signal_handlers():
    """Setup signal handlers for graceful shutdown."""
    if sys.platform != 'win32':
        loop = asyncio.get_event_loop()
        
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(
                sig,
                lambda s=sig: asyncio.create_task(shutdown_handler(s.name))
            )

async def start_background_tasks():
    """Start all background tasks."""
    # Start transfer workers
    for i in range(MAX_CONCURRENT_DOWNLOADS):
        task = asyncio.create_task(transfer_mgr._worker(f"worker-{i}"))
        background_tasks.add(task)
        task.add_done_callback(background_tasks.discard)
    
    # Start cleanup task
    from cleanup import cleaner
    cleanup_task = asyncio.create_task(cleaner.cleanup_task())
    background_tasks.add(cleanup_task)
    cleanup_task.add_done_callback(background_tasks.discard)
    
    # Start health check
    from healthcheck import start_health_check
    health_task = asyncio.create_task(start_health_check())
    background_tasks.add(health_task)
    health_task.add_done_callback(background_tasks.discard)
    
    logger.info(f"Started {MAX_CONCURRENT_DOWNLOADS} workers")

def main():
    """Main entry point."""
    global transfer_mgr, application, pyro_client, telegram_handler
    
    try:
        # Initialize Pyrogram client
        pyro_client = Client(
            "anime_leech_session",
            api_id=API_ID,
            api_hash=API_HASH,
            bot_token=BOT_TOKEN,
            no_updates=True
        )
        
        # Initialize transfer manager
        transfer_mgr = TransferManager(pyro_client)
        
        # Create main bot application
        application = Application.builder().token(BOT_TOKEN).build()
        telegram_handler = TelegramBotHandler(application)
        
        # Register components for health check
        from healthcheck import register_component
        register_component('transfer_manager', transfer_mgr)
        register_component('searcher', searcher)
        from cleanup import cleaner
        register_component('cleaner', cleaner)
        
        # Add command handlers
        application.add_handler(CommandHandler('start', start))
        application.add_handler(CommandHandler('download', download_command))
        application.add_handler(CommandHandler('status', status_command))
        application.add_handler(CommandHandler('stats', stats_command))
        application.add_handler(CommandHandler('cancel', cancel_command))
        application.add_handler(CommandHandler('help', help_command))
        application.add_handler(CallbackQueryHandler(button_handler))
        
        # Add error handler
        application.add_error_handler(error_handler)
        
        # Setup signal handlers
        setup_signal_handlers()
        
        # Run bot
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        async def run():
            # Start Pyrogram
            await pyro_client.start()
            
            # Start background tasks
            await start_background_tasks()
            
            # Start bot
            await application.initialize()
            await application.start()
            await application.updater.start_polling()
            
            logger.info("Bot started successfully!")
            
            # Keep running
            await asyncio.Event().wait()
        
        loop.run_until_complete(run())
        
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
    finally:
        # Clean shutdown
        if 'loop' in locals():
            loop.run_until_complete(shutdown_handler())
            loop.close()

if __name__ == '__main__':
    main()