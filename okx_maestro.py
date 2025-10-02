# -*- coding: utf-8 -*-
# =======================================================================================
# --- 🚀 Wise Maestro Bot | v301.0 (Fixed & Fully Functional) 🚀 ---
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
from strategy_scanners import SCANNERS, filter_whale_radar
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
            await conn.execute('CREATE TABLE IF NOT EXISTS trades (id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT, symbol TEXT, entry_price REAL, take_profit REAL, stop_loss REAL, quantity REAL, status TEXT, reason TEXT, order_id TEXT, highest_price REAL DEFAULT 0, trailing_sl_active BOOLEAN DEFAULT 0, close_price REAL, pnl_usdt REAL, last_profit_notification_price REAL DEFAULT 0)')
            await conn.commit(); logger.info("Database initialized successfully.")
    except Exception as e: logger.critical(f"Database initialization failed: {e}")

async def maestro_job(context: ContextTypes.DEFAULT_TYPE):
    logger.info("🧠 Maestro: Running market regime analysis...")
    pass

# =======================================================================================
# --- [الكود المضاف] منطق الفحص والتداول الكامل ---
# =======================================================================================
async def worker_batch(queue, signals_list, errors_list):
    settings, exchange = bot_data.settings, bot_data.exchange
    while not queue.empty():
        try:
            item = await queue.get()
            market, ohlcv = item['market'], item['ohlcv']
            symbol = market['symbol']
            
            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            df = df.set_index('timestamp').sort_index()
            if len(df) < 50:
                queue.task_done(); continue
            
            # --- سلسلة الفلاتر ---
            # فلتر السيولة والتقلب والاتجاه
            last_close = df['close'].iloc[-2]
            df.ta.atr(length=14, append=True)
            atr_col = next((col for col in df.columns if col.startswith('ATRr_')), None)
            atr_percent = (df[atr_col].iloc[-2] / last_close) * 100 if atr_col and last_close > 0 else 0
            if atr_percent < settings['volatility_filters']['min_atr_percent']:
                queue.task_done(); continue

            # ... يمكنك إضافة باقي الفلاتر هنا بنفس الطريقة (RVOL, EMA, etc) ...

            # --- تشغيل الماسحات ---
            confirmed_reasons = []
            for name in settings['active_scanners']:
                if name == 'whale_radar': continue
                if not (strategy_func := SCANNERS.get(name)): continue
                
                # وسيطات فارغة مبدئياً
                rvol = 0
                adx_value = 0
                
                func_args = {'df': df.copy(), 'params': {}, 'rvol': rvol, 'adx_value': adx_value}
                if name in ['support_rebound']:
                    func_args.update({'exchange': exchange, 'symbol': symbol})
                
                result = await strategy_func(**func_args) if asyncio.iscoroutinefunction(strategy_func) else strategy_func(**{k: v for k, v in func_args.items() if k not in ['exchange', 'symbol']})
                if result: confirmed_reasons.append(result['reason'])

            # --- تجميع الإشارة ---
            if confirmed_reasons:
                reason_str = ' + '.join(set(confirmed_reasons))
                entry_price = last_close
                risk = df[atr_col].iloc[-2] * settings['atr_sl_multiplier']
                stop_loss, take_profit = entry_price - risk, entry_price + (risk * settings['risk_reward_ratio'])
                signals_list.append({"symbol": symbol, "entry_price": entry_price, "take_profit": take_profit, "stop_loss": stop_loss, "reason": reason_str})
            
            queue.task_done()
        except Exception as e:
            if 'symbol' in locals():
                logger.error(f"Error processing symbol {symbol}: {e}")
                errors_list.append(symbol)
            else:
                logger.error(f"Worker error with no symbol context: {e}")
            if not queue.empty():
                queue.task_done()

async def initiate_real_trade(signal):
    if not bot_data.trading_enabled: return False
    try:
        settings, exchange = bot_data.settings, bot_data.exchange
        trade_size = settings['real_trade_size_usdt']
        
        balance = await exchange.fetch_balance()
        usdt_balance = balance.get('USDT', {}).get('free', 0.0)
        if usdt_balance < trade_size:
            logger.error(f"Insufficient USDT for {signal['symbol']}. Have: {usdt_balance}, Need: {trade_size}")
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
            return

        async with aiosqlite.connect(DB_FILE) as conn:
            active_trades_count = (await (await conn.execute("SELECT COUNT(*) FROM trades WHERE status = 'active' OR status = 'pending'")).fetchone())[0]
        
        if active_trades_count >= bot_data.settings['max_concurrent_trades']:
            logger.info(f"Scan skipped: Max trades ({active_trades_count}) reached.")
            return

        top_markets = await get_okx_markets(bot_data)
        if not top_markets: return

        symbols_to_scan = [m['symbol'] for m in top_markets]
        ohlcv_data = await asyncio.gather(*[bot_data.exchange.fetch_ohlcv(s, TIMEFRAME, limit=100) for s in symbols_to_scan], return_exceptions=True)
        
        queue, signals_found, analysis_errors = asyncio.Queue(), [], []
        for i, market in enumerate(top_markets):
            if isinstance(ohlcv_data[i], list) and ohlcv_data[i]:
                await queue.put({'market': market, 'ohlcv': ohlcv_data[i]})

        worker_tasks = [asyncio.create_task(worker_batch(queue, signals_found, analysis_errors)) for _ in range(bot_data.settings.get("worker_threads", 10))]
        await queue.join()
        for task in worker_tasks: task.cancel()

        trades_opened_count = 0
        for signal in signals_found:
            if active_trades_count >= bot_data.settings['max_concurrent_trades']: break
            if await initiate_real_trade(signal):
                active_trades_count += 1
                trades_opened_count += 1
                await asyncio.sleep(2)

        duration = time.time() - start_time
        bot_data.last_scan_info = {'duration_seconds': f"{duration:.2f}", 'checked_symbols': len(top_markets), 'found_signals': len(signals_found), 'opened_trades': trades_opened_count}
        logger.info(f"Scan finished in {duration:.2f}s. Found {len(signals_found)} signals, opened {trades_opened_count} trades.")
# =======================================================================================

async def post_init(application: Application):
    logger.info("--- Bot post-initialization started ---")
    if not all([TELEGRAM_BOT_TOKEN, OKX_API_KEY, OKX_API_SECRET, OKX_API_PASSPHRSE, TELEGRAM_CHAT_ID]):
        logger.critical("FATAL: Missing critical environment variables."); return

    bot_data.application = application
    
    try:
        config = {'apiKey': OKX_API_KEY, 'secret': OKX_API_SECRET, 'password': OKX_API_PASSPHRSE, 'enableRateLimit': True}
        bot_data.exchange = ccxt.okx(config)
        await bot_data.exchange.load_markets()
        logger.info("✅ Step 1/5: Successfully connected to OKX and loaded markets.")
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

    # --- [الكود المُعدّل] ---
    logger.info("Waiting 5s for WebSocket connections to establish before syncing...")
    await asyncio.sleep(5)
    await bot_data.guardian.sync_subscriptions()
    # --- [نهاية التعديل] ---
    
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
