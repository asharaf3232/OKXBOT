# -*- coding: utf-8 -*-
# =======================================================================================
# --- 🚀 Wise Maestro Bot - v10.1 (Correct Import Fix) 🚀 ---
# =======================================================================================
import os
import logging
import asyncio
import json
import time
import copy
from datetime import datetime, time as dt_time
from zoneinfo import ZoneInfo
import aiosqlite
import ccxt.async_support as ccxt
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters, CallbackQueryHandler
from telegram.constants import ParseMode
from telegram.error import Forbidden
from dotenv import load_dotenv

# --- [الإصلاح النهائي] استيراد كل شيء من مكانه الصحيح ---
from settings_config import *
from strategy_scanners import SCANNERS
from ai_market_brain import get_market_regime, get_market_mood, get_okx_markets
from smart_engine import EvolutionaryEngine
import ui_handlers 
from wise_maestro_guardian import TradeGuardian, PublicWebSocketManager, PrivateWebSocketManager

load_dotenv()

# --- جلب المتغيرات ---
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
OKX_API_KEY = os.getenv('OKX_API_KEY')
OKX_API_SECRET = os.getenv('OKX_API_SECRET')
OKX_API_PASSPHRASE = os.getenv('OKX_API_PASSPHRASE')

# --- إعدادات أساسية ---
DB_FILE = 'wise_maestro_okx.db'
SETTINGS_FILE = 'wise_maestro_okx_settings.json'

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger("OKX_MAESTRO_FUSION")

# --- الحالة العامة للبوت ---
class BotState:
    def __init__(self):
        self.settings = {}
        self.trading_enabled = True
        self.active_preset_name = "مخصص"
        self.exchange = None
        self.application = None
        self.last_scan_info = {}
        self.public_ws = None
        self.private_ws = None
        self.guardian = None
        self.smart_brain = None
        self.TELEGRAM_CHAT_ID = TELEGRAM_CHAT_ID
        self.trade_management_lock = asyncio.Lock()
        self.all_markets = []
        self.last_markets_fetch = 0
        self.strategy_performance = {}

bot_data = BotState()
scan_lock = asyncio.Lock()

# --- الدوال الرئيسية ---

def load_settings():
    try:
        if os.path.exists(SETTINGS_FILE):
            with open(SETTINGS_FILE, 'r') as f: 
                user_settings = json.load(f)
                bot_data.settings = copy.deepcopy(DEFAULT_SETTINGS)
                bot_data.settings.update(user_settings)
        else: bot_data.settings = copy.deepcopy(DEFAULT_SETTINGS)
    except Exception: bot_data.settings = copy.deepcopy(DEFAULT_SETTINGS)
    with open(SETTINGS_FILE, 'w') as f: json.dump(bot_data.settings, f, indent=4)
    logger.info("Settings loaded successfully.")

async def init_database():
    try:
        async with aiosqlite.connect(DB_FILE) as conn:
            await conn.execute('CREATE TABLE IF NOT EXISTS trades (id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT, symbol TEXT, entry_price REAL, take_profit REAL, stop_loss REAL, quantity REAL, status TEXT, reason TEXT, order_id TEXT, highest_price REAL DEFAULT 0, trailing_sl_active BOOLEAN DEFAULT 0, close_price REAL, pnl_usdt REAL, last_profit_notification_price REAL DEFAULT 0, trade_weight REAL DEFAULT 1.0)')
            await conn.commit(); logger.info("Database initialized successfully.")
    except Exception as e: logger.critical(f"Database initialization failed: {e}")

async def perform_scan(context: ContextTypes.DEFAULT_TYPE, manual_run=False):
    # Your scan logic here
    logger.info("🚀 Starting new market scan...")
    pass

async def maestro_job(context: ContextTypes.DEFAULT_TYPE):
    # Your maestro job logic here
    logger.info("🧠 Maestro: Running market regime analysis...")
    pass


# --- Bot Startup ---
async def post_init(application: Application):
    logger.info("Performing post-initialization...")
    if not all([TELEGRAM_BOT_TOKEN, OKX_API_KEY, OKX_API_SECRET, OKX_API_PASSPHRASE, TELEGRAM_CHAT_ID]):
        logger.critical("FATAL: Missing critical environment variables."); return

    bot_data.application = application
    
    try:
        config = {'apiKey': OKX_API_KEY, 'secret': OKX_API_SECRET, 'password': OKX_API_PASSPHRASE, 'enableRateLimit': True}
        bot_data.exchange = ccxt.okx(config)
        await bot_data.exchange.load_markets()
        logger.info("✅ Successfully connected to OKX and loaded markets.")

    except Exception as e:
        logger.critical(f"🔥 FATAL: Could not connect to OKX: {e}", exc_info=True)
        try:
            await application.bot.send_message(TELEGRAM_CHAT_ID, f"🚨 **فشل الاتصال بالمنصة!**\nالسبب: `{e}`")
        except Exception as telegram_error:
            logger.critical(f"Could not send Telegram error message: {telegram_error}")
        return

    load_settings()
    await init_database()
    
    bot_data.guardian = TradeGuardian(bot_data.exchange, application, bot_data, DB_FILE)
    bot_data.smart_brain = EvolutionaryEngine(bot_data.exchange, application, DB_FILE)
    
    bot_data.public_ws = PublicWebSocketManager(bot_data.guardian.handle_ticker_update)
    bot_data.private_ws = PrivateWebSocketManager(OKX_API_KEY, OKX_API_SECRET, OKX_API_PASSPHRASE)
    asyncio.create_task(bot_data.public_ws.run())
    asyncio.create_task(bot_data.private_ws.run())
    
    jq = application.job_queue
    jq.run_repeating(perform_scan, interval=SCAN_INTERVAL_SECONDS, first=10, name="perform_scan")
    jq.run_repeating(bot_data.guardian.the_supervisor_job, interval=SUPERVISOR_INTERVAL_SECONDS, first=30, name="supervisor_job")
    jq.run_repeating(maestro_job, interval=MAESTRO_INTERVAL_HOURS * 3600, first=60, name="maestro_job")
    
    logger.info("All periodic jobs have been scheduled.")

    try:
        await application.bot.send_message(TELEGRAM_CHAT_ID, "*🤖 Wise Maestro Bot (Final Stable Edition) - بدأ العمل...*", parse_mode=ParseMode.MARKDOWN)
    except Forbidden:
        logger.critical(f"FATAL: Bot not authorized for chat ID {TELEGRAM_CHAT_ID}."); return
    
    logger.info("--- Wise Maestro Bot is now fully operational ---")


async def post_shutdown(application: Application):
    if bot_data.exchange:
        await bot_data.exchange.close()
    logger.info("Bot has shut down gracefully.")


def main():
    logger.info("--- Starting Wise Maestro Bot ---")
    
    app_builder = Application.builder().token(TELEGRAM_BOT_TOKEN)
    app_builder.post_init(post_init).post_shutdown(post_shutdown)
    application = app_builder.build()
    
    application.bot_data = bot_data

    application.add_handler(CommandHandler("start", ui_handlers.start_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, ui_handlers.universal_text_handler))
    application.add_handler(CallbackQueryHandler(ui_handlers.button_callback_handler))

    application.run_polling()

if __name__ == '__main__':
    main()
