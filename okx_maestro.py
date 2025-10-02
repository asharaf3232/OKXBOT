# -*- coding: utf-8 -*-
# =======================================================================================
# --- 🚀 Wise Maestro Bot | v400.0 (Ecosystem Final Version) 🚀 ---
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
import pandas as pd
import ccxt.async_support as ccxt
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters, CallbackQueryHandler
from telegram.constants import ParseMode
from telegram.error import Forbidden

# --- تم حذف `dotenv` لأنه لم يعد مطلوبًا مع ملف ecosystem ---

# --- استيراد الوحدات المنفصلة ---
from settings_config import *
from strategy_scanners import SCANNERS, find_col
from ai_market_brain import get_market_mood, get_okx_markets
from smart_engine import EvolutionaryEngine
import ui_handlers
from wise_maestro_guardian import TradeGuardian, PublicWebSocketManager, PrivateWebSocketManager

# --- جلب المتغيرات مباشرة من بيئة التشغيل التي يوفرها PM2 ---
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
OKX_API_KEY = os.getenv('OKX_API_KEY')
OKX_API_SECRET = os.getenv('OKX_API_SECRET')
OKX_API_PASSPHRSE = os.getenv('OKX_API_PASSPHRSE')
# --- جلب المتغيرات ---
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
OKX_API_KEY = os.getenv('OKX_API_KEY')
OKX_API_SECRET = os.getenv('OKX_API_SECRET')
OKX_API_PASSPHRSE = os.getenv('OKX_API_PASSPHRSE')

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
    bot_data.settings = copy.deepcopy(DEFAULT_SETTINGS)
    try:
        if os.path.exists(SETTINGS_FILE):
            with open(SETTINGS_FILE, 'r') as f:
                user_settings = json.load(f)
                for key, value in user_settings.items():
                    if isinstance(value, dict) and key in bot_data.settings:
                        bot_data.settings[key].update(value)
                    else:
                        bot_data.settings[key] = value
    except Exception as e:
        logger.error(f"Could not load settings file, using defaults. Error: {e}")
    
    with open(SETTINGS_FILE, 'w') as f:
        json.dump(bot_data.settings, f, indent=4)
    logger.info("Settings loaded and verified successfully.")

async def init_database():
    try:
        async with aiosqlite.connect(DB_FILE) as conn:
            await conn.execute('CREATE TABLE IF NOT EXISTS trades (id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT, symbol TEXT, entry_price REAL, take_profit REAL, stop_loss REAL, quantity REAL, status TEXT, reason TEXT, order_id TEXT, highest_price REAL DEFAULT 0, trailing_sl_active BOOLEAN DEFAULT 0, close_price REAL, pnl_usdt REAL, last_profit_notification_price REAL DEFAULT 0)')
            await conn.commit(); logger.info("Database initialized successfully.")
    except Exception as e: logger.critical(f"Database initialization failed: {e}")

async def maestro_job(context: ContextTypes.DEFAULT_TYPE):
    logger.info("🧠 Maestro: Running market regime analysis...")
    pass

async def worker_batch(queue, signals_list, errors_list):
    settings, exchange = bot_data.settings, bot_data.exchange
    while not queue.empty():
        try:
            item = await queue.get()
            market, ohlcv = item['market'], item['ohlcv']
            symbol = market['symbol']
            
            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            if len(df) < 50:
                queue.task_done(); continue
            
            # --- سلسلة الفلاتر ---
            last_close = df['close'].iloc[-1]
            if last_close == 0:
                queue.task_done(); continue

            # Volatility Filter
            df.ta.atr(length=settings['volatility_filters']['atr_period_for_filter'], append=True)
            atr_col = find_col(df.columns, f"ATRr_{settings['volatility_filters']['atr_period_for_filter']}")
            if not atr_col or pd.isna(df[atr_col].iloc[-1]):
                queue.task_done(); continue
            atr_percent = (df[atr_col].iloc[-1] / last_close) * 100
            if atr_percent < settings['volatility_filters']['min_atr_percent']:
                queue.task_done(); continue

            # Liquidity Filter (RVol)
            df['volume_sma'] = df['volume'].rolling(20).mean()
            if pd.isna(df['volume_sma'].iloc[-1]) or df['volume_sma'].iloc[-1] == 0:
                queue.task_done(); continue
            rvol = df['volume'].iloc[-1] / df['volume_sma'].iloc[-1]
            if rvol < settings['liquidity_filters']['min_rvol']:
                queue.task_done(); continue

            # ADX Filter
            adx_value = 0
            if settings['adx_filter_enabled']:
                df.ta.adx(append=True)
                adx_col_name = find_col(df.columns, "ADX_")
                if adx_col_name and pd.notna(df[adx_col_name].iloc[-1]):
                    adx_value = df[adx_col_name].iloc[-1]
                if adx_value < settings['adx_filter_level']:
                    queue.task_done(); continue

            # --- تشغيل الماسحات ---
            confirmed_reasons = []
            for name in settings['active_scanners']:
                if not (strategy_func := SCANNERS.get(name)): continue
                
                func_args = {'df': df.copy(), 'params': {}, 'rvol': rvol, 'adx_value': adx_value}
                if name in ['support_rebound']:
                    func_args.update({'exchange': exchange, 'symbol': symbol})
                
                result = await strategy_func(**func_args) if asyncio.iscoroutinefunction(strategy_func) else strategy_func(**{k: v for k, v in func_args.items() if k not in ['exchange', 'symbol']})
                if result: confirmed_reasons.append(result['reason'])

            # --- تجميع الإشارة ---
            if confirmed_reasons:
                reason_str = ' + '.join(set(confirmed_reasons))
                entry_price = last_close
                atr_value = df[atr_col].iloc[-1]
                risk = atr_value * settings['atr_sl_multiplier']
                stop_loss, take_profit = entry_price - risk, entry_price + (risk * settings['risk_reward_ratio'])
                signals_list.append({"symbol": symbol, "entry_price": entry_price, "take_profit": take_profit, "stop_loss": stop_loss, "reason": reason_str})
            
            queue.task_done()
        except Exception as e:
            symbol_name = locals().get('symbol', 'N/A')
            logger.error(f"Error processing symbol {symbol_name}: {e}", exc_info=True)
            if not queue.empty(): queue.task_done()

async def initiate_real_trade(signal):
    if not bot_data.trading_enabled: return False
    try:
        settings, exchange = bot_data.settings, bot_data.exchange
        trade_size = settings['real_trade_size_usdt']
        
        balance = await exchange.fetch_balance()
        usdt_balance = balance.get('USDT', {}).get('free', 0.0)
        if usdt_balance < trade_size:
            logger.warning(f"Insufficient USDT for {signal['symbol']}. Have: {usdt_balance}, Need: {trade_size}")
            return False

        base_amount = trade_size / signal['entry_price']
        formatted_amount = exchange.amount_to_precision(signal['symbol'], base_amount)
        
        params = {'tdMode': 'cash'}
        buy_order = await exchange.create_market_buy_order(signal['symbol'], formatted_amount, params=params)
        
        if await bot_data.guardian.log_pending_trade_to_db(signal, buy_order):
            await bot_data.guardian.safe_send_message(f"🚀 تم إرسال أمر شراء لـ `{signal['symbol']}`.")
            return True
        else:
            await exchange.cancel_order(buy_order['id'], signal['symbol']); return False
    except Exception as e:
        logger.error(f"REAL TRADE FAILED {signal['symbol']}: {e}", exc_info=True)
        return False

async def perform_scan(context: ContextTypes.DEFAULT_TYPE, manual_run=False):
    if scan_lock.locked():
        if manual_run: await context.bot.send_message(TELEGRAM_CHAT_ID, "⚠️ **يوجد فحص آخر قيد التنفيذ.**")
        return

    async with scan_lock:
        if not bot_data.trading_enabled: return

        start_time = time.time()
        
        market_mood = await get_market_mood(bot_data)
        if market_mood["mood"] != "POSITIVE":
            logger.warning(f"Scan skipped: Market mood is {market_mood['mood']}. Reason: {market_mood['reason']}")
            if manual_run: await context.bot.send_message(TELEGRAM_CHAT_ID, f"⏸️ **إيقاف البحث:** {market_mood['reason']}")
            return

        async with aiosqlite.connect(DB_FILE) as conn:
            active_trades_count = (await (await conn.execute("SELECT COUNT(*) FROM trades WHERE status = 'active' OR status = 'pending'")).fetchone())[0]
        
        if active_trades_count >= bot_data.settings['max_concurrent_trades']: return

        top_markets = await get_okx_markets(bot_data)
        if not top_markets: return

        symbols_to_scan = [m['symbol'] for m in top_markets]
        ohlcv_results = await asyncio.gather(*[bot_data.exchange.fetch_ohlcv(s, TIMEFRAME, limit=100) for s in symbols_to_scan], return_exceptions=True)
        
        queue, signals_found, analysis_errors = asyncio.Queue(), [], []
        for i, market in enumerate(top_markets):
            if isinstance(ohlcv_results[i], list) and ohlcv_results[i]:
                await queue.put({'market': market, 'ohlcv': ohlcv_results[i]})

        worker_tasks = [asyncio.create_task(worker_batch(queue, signals_found, analysis_errors)) for _ in range(bot_data.settings.get("worker_threads", 10))]
        await queue.join(); [task.cancel() for task in worker_tasks]

        trades_opened_count = 0
        for signal in signals_found:
            if active_trades_count >= bot_data.settings['max_concurrent_trades']: break
            if await initiate_real_trade(signal):
                active_trades_count += 1; trades_opened_count += 1
                await asyncio.sleep(2)

        duration = time.time() - start_time
        bot_data.last_scan_info = {'duration_seconds': f"{duration:.2f}", 'checked_symbols': len(top_markets), 'found_signals': len(signals_found), 'opened_trades': trades_opened_count}
        logger.info(f"Scan finished in {duration:.2f}s. Found {len(signals_found)} signals, opened {trades_opened_count} trades.")

        if manual_run:
            report = (f"✅ **اكتمل الفحص!**\n\n"
                      f"⏱️ **المدة:** {duration:.2f} ثانية\n📊 **العملات المفحوصة:** {len(top_markets)}\n"
                      f"💡 **الفرص المكتشفة:** {len(signals_found)}\n"
                      f"🚀 **صفقات تم فتحها:** {trades_opened_count}")
            await context.bot.send_message(TELEGRAM_CHAT_ID, report, parse_mode=ParseMode.MARKDOWN)

async def post_init(application: Application):
    logger.info("--- Bot post-initialization started ---")
    if not all([TELEGRAM_BOT_TOKEN, OKX_API_KEY, OKX_API_SECRET, OKX_API_PASSPHRSE, TELEGRAM_CHAT_ID]):
        logger.critical("FATAL: Missing critical environment variables. Please check your .env file or server configuration."); return

    bot_data.application = application
    
    try:
        config = {'apiKey': OKX_API_KEY, 'secret': OKX_API_SECRET, 'password': OKX_API_PASSPHRSE, 'enableRateLimit': True}
        bot_data.exchange = ccxt.okx(config)
        await bot_data.exchange.load_markets()
        logger.info("✅ Step 1/5: Successfully connected to OKX.")
    except Exception as e:
        logger.critical(f"🔥 FATAL: Could not connect to OKX: {e}", exc_info=True); return

    load_settings()
    await init_database()
    logger.info("✅ Step 2/5: Settings and database initialized.")
    
    bot_data.guardian = TradeGuardian(bot_data.exchange, application, bot_data, DB_FILE)
    bot_data.smart_brain = EvolutionaryEngine(bot_data.exchange, application, DB_FILE)
    logger.info("✅ Step 3/5: Guardian and Smart Brain are ready.")

    bot_data.public_ws = PublicWebSocketManager(bot_data.guardian.handle_ticker_update)
    bot_data.private_ws = PrivateWebSocketManager(OKX_API_KEY, OKX_API_SECRET, OKX_API_PASSPHRSE)
    asyncio.create_task(bot_data.public_ws.run())
    asyncio.create_task(bot_data.private_ws.run())
    logger.info("✅ Step 4/5: WebSockets initiated.")

    logger.info("Waiting 5s for WebSocket connections to establish before syncing...")
    await asyncio.sleep(5)
    await bot_data.guardian.sync_subscriptions()
    
    jq = application.job_queue
    jq.run_repeating(perform_scan, interval=SCAN_INTERVAL_SECONDS, first=10, name="perform_scan")
    jq.run_repeating(bot_data.guardian.the_supervisor_job, interval=SUPERVISOR_INTERVAL_SECONDS, first=30, name="supervisor_job")
    jq.run_repeating(maestro_job, interval=MAESTRO_INTERVAL_HOURS * 3600, first=60, name="maestro_job")
    logger.info("✅ Step 5/5: All periodic jobs have been scheduled.")

    try:
        await application.bot.send_message(TELEGRAM_CHAT_ID, "*🤖 Wise Maestro Bot (v304 - Final) is online.*", parse_mode=ParseMode.MARKDOWN)
    except Forbidden:
        logger.critical(f"FATAL: Bot not authorized for chat ID {TELEGRAM_CHAT_ID}."); return
    
    logger.info("--- Bot is now fully operational ---")

async def post_shutdown(application: Application):
    if bot_data.exchange: await bot_data.exchange.close()
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
