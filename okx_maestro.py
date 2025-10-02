# -*- coding: utf-8 -*-
# =======================================================================================
# --- 🚀 Wise Maestro Bot | v300.0 (The Correct & Final Version) 🚀 ---
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

# --- استيراد الوحدات المنفصلة (هيكلك الصحيح) ---
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
logger = logging.getLogger("OKX_MAESTRO")

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
            # This uses the schema from your original wise_maestro_guardian.py
            await conn.execute('CREATE TABLE IF NOT EXISTS trades (id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT, symbol TEXT, entry_price REAL, take_profit REAL, stop_loss REAL, quantity REAL, status TEXT, reason TEXT, order_id TEXT, highest_price REAL DEFAULT 0, trailing_sl_active BOOLEAN DEFAULT 0, close_price REAL, pnl_usdt REAL, last_profit_notification_price REAL DEFAULT 0)')
            await conn.commit(); logger.info("Database initialized successfully.")
    except Exception as e: logger.critical(f"Database initialization failed: {e}")

async def perform_scan(context: ContextTypes.DEFAULT_TYPE, manual_run=False):
    if scan_lock.locked():
        if manual_run: await context.bot.send_message(TELEGRAM_CHAT_ID, "⚠️ **يوجد فحص آخر قيد التنفيذ.**")
        return

    async with scan_lock:
        if not bot_data.trading_enabled:
            if manual_run: await context.bot.send_message(TELEGRAM_CHAT_ID, "🚨 **الفحص ملغي. مفتاح الإيقاف مفعل.**")
            return

        message_prefix = "🔬 **فحص يدوي**" if manual_run else "🔄 **فحص دوري**"
        if manual_run: await context.bot.send_message(TELEGRAM_CHAT_ID, f"{message_prefix}: بدء العملية...", parse_mode=ParseMode.MARKDOWN)
        
        start_time = time.time()
        scanned_symbols_count = 0
        found_opportunities = []

        try:
            market_mood = await get_market_mood(bot_data)
            if market_mood["mood"] != "POSITIVE":
                if manual_run: await context.bot.send_message(TELEGRAM_CHAT_ID, f"⏸️ **إيقاف البحث:** {market_mood['reason']}")
                return

            all_markets = await get_okx_markets(bot_data)
            if not all_markets:
                if manual_run: await context.bot.send_message(TELEGRAM_CHAT_ID, "⚠️ **فشل جلب قائمة العملات من OKX.**")
                return

            symbols_to_scan = [m['symbol'] for m in all_markets]
            scanned_symbols_count = len(symbols_to_scan)
            logger.info(f"Scanning {scanned_symbols_count} symbols...")
            
            # Here, you would loop and call your actual scanner functions from strategy_scanners.py
            # This is a placeholder for the logic inside the loop
            for symbol in symbols_to_scan:
                pass # Replace with your full analysis logic

        finally:
            duration = time.time() - start_time
            bot_data.last_scan_info = {'duration_seconds': f"{duration:.2f}", 'checked_symbols': scanned_symbols_count}
            report = f"✅ **اكتمل الفحص!**\n\n"
            report += f"⏱️ **المدة:** {duration:.2f} ثانية\n📊 **العملات المفحوصة:** {scanned_symbols_count}\n\n"
            report += f"⭕ لم يتم العثور على أي فرص. (منطق البحث لم يكتمل بعد)"
            if manual_run:
                await context.bot.send_message(TELEGRAM_CHAT_ID, report, parse_mode=ParseMode.MARKDOWN)
            else:
                logger.info(f"Scheduled scan finished. Checked {scanned_symbols_count} symbols.")

async def maestro_job(context: ContextTypes.DEFAULT_TYPE):
    logger.info("🧠 Maestro: Running market regime analysis...")
    pass

async def post_init(application: Application):
    logger.info("--- Bot post-initialization started ---")
    if not all([TELEGRAM_BOT_TOKEN, OKX_API_KEY, OKX_API_SECRET, OKX_API_PASSPHRASE, TELEGRAM_CHAT_ID]):
        logger.critical("FATAL: Missing critical environment variables."); return

    bot_data.application = application
    
    try:
        # Step 1: Establish and verify the exchange connection
        config = {'apiKey': OKX_API_KEY, 'secret': OKX_API_SECRET, 'password': OKX_API_PASSPHRASE, 'enableRateLimit': True}
        bot_data.exchange = ccxt.okx(config)
        await bot_data.exchange.load_markets()
        logger.info("✅ Step 1/5: Successfully connected to OKX and loaded markets.")

    except Exception as e:
        logger.critical(f"🔥 FATAL: Could not connect to OKX: {e}", exc_info=True)
        # Attempt to notify user, but stop initialization regardless
        try: await application.bot.send_message(TELEGRAM_CHAT_ID, f"🚨 **فشل الاتصال بالمنصة!**\nالسبب: `{e}`")
        except: pass
        return

    # --- Only proceed if connection is successful ---

    # Step 2: Load settings and initialize database
    load_settings()
    await init_database()
    logger.info("✅ Step 2/5: Settings and database initialized.")
    
    # Step 3: Initialize main components
    bot_data.guardian = TradeGuardian(bot_data.exchange, application, bot_data, DB_FILE)
    bot_data.smart_brain = EvolutionaryEngine(bot_data.exchange, application, DB_FILE)
    logger.info("✅ Step 3/5: Guardian and Smart Brain are ready.")

    # Step 4: Start WebSockets
    bot_data.public_ws = PublicWebSocketManager(bot_data.guardian.handle_ticker_update)
    bot_data.private_ws = PrivateWebSocketManager(OKX_API_KEY, OKX_API_SECRET, OKX_API_PASSPHRASE)
    asyncio.create_task(bot_data.public_ws.run())
    asyncio.create_task(bot_data.private_ws.run())
    logger.info("✅ Step 4/5: WebSockets initiated.")
    
    # Step 5: Schedule jobs AFTER everything else is ready
    jq = application.job_queue
    jq.run_repeating(perform_scan, interval=SCAN_INTERVAL_SECONDS, first=10, name="perform_scan")
    jq.run_repeating(bot_data.guardian.the_supervisor_job, interval=SUPERVISOR_INTERVAL_SECONDS, first=30, name="supervisor_job")
    jq.run_repeating(maestro_job, interval=MAESTRO_INTERVAL_HOURS * 3600, first=60, name="maestro_job")
    logger.info("✅ Step 5/5: All periodic jobs have been scheduled.")

    try:
        await application.bot.send_message(TELEGRAM_CHAT_ID, "*🤖 Wise Maestro Bot (Final Stable Version) - بدأ العمل...*", parse_mode=ParseMode.MARKDOWN)
    except Forbidden:
        logger.critical(f"FATAL: Bot not authorized for chat ID {TELEGRAM_CHAT_ID}."); return
    
    logger.info("--- Bot is now fully operational ---")

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
