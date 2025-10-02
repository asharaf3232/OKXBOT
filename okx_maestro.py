# -*- coding: utf-8 -*-
# =======================================================================================
# --- 🚀 Wise Maestro Bot - Final Fusion v7.0 (OKX Edition) 🚀 ---
# =======================================================================================
# --- سجل التغييرات للإصدار 7.0 (الدمج النهائي) ---
#   ✅ [تحديث] حذف TradeGuardian المحلي والاعتماد الكامل على الحارس الموحد.
#   ✅ [تحديث] تعديل PublicWebSocketManager لتحويل بيانات OKX إلى التنسيق الموحد.
#   ✅ [تحديث] تعديل post_init لتهيئة وربط الحارس الموحد بشكل صحيح.
#   ✅ [الحفاظ] الإبقاء على كامل بنية المايسترو والعقل التطوري والواجهة.
# =======================================================================================

import os
import logging
import asyncio
import json
import time
import copy
from datetime import datetime, time as dt_time, timedelta
from zoneinfo import ZoneInfo
from collections import defaultdict
import aiosqlite
import pandas as pd
import ccxt.async_support as ccxt
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters, CallbackQueryHandler
from dotenv import load_dotenv
import websockets
import websockets.exceptions
import redis.asyncio as redis
import hmac
import base64

# --- استيراد الوحدات المنفصلة ---
from settings_config import *
from strategy_scanners import SCANNERS, find_col, filter_whale_radar
from ai_market_brain import get_market_regime, get_market_mood, get_okx_markets
from smart_engine import EvolutionaryEngine
import ui_handlers 
from wise_maestro_guardian import TradeGuardian as MaestroGuardian

load_dotenv()

# --- جلب المتغيرات ---
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
OKX_API_KEY = os.getenv('OKX_API_KEY')
OKX_API_SECRET = os.getenv('OKX_API_SECRET')
OKX_API_PASSPHRASE = os.getenv('OKX_API_PASSPHRASE')
REDIS_URL = os.getenv('REDIS_URL', 'redis://localhost:6379')

# --- إعدادات أساسية ---
EGYPT_TZ = ZoneInfo("Africa/Cairo")
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
        self.last_signal_time = defaultdict(float)
        self.exchange = None
        self.application = None
        self.market_mood = {"mood": "UNKNOWN", "reason": "تحليل لم يتم بعد"}
        self.last_scan_info = {}
        self.all_markets = []
        self.last_markets_fetch = 0
        self.public_ws = None
        self.private_ws = None
        self.guardian = None
        self.smart_brain = None
        self.TELEGRAM_CHAT_ID = TELEGRAM_CHAT_ID
        self.current_market_regime = "UNKNOWN"
        self.redis_client = None
        self.trade_management_lock = asyncio.Lock()

bot_data = BotState()
scan_lock = asyncio.Lock()

# --- OKX Specific WebSocket ---
class PublicWebSocketManager:
    def __init__(self, handler_coro): 
        self.ws_url = "wss://ws.okx.com:8443/ws/v5/public"
        self.handler = handler_coro
        self.subscriptions = set()

    async def _send_op(self, op, symbols):
        if not symbols or not hasattr(self, 'websocket') or not self.websocket.open: return
        try: await self.websocket.send(json.dumps({"op": op, "args": [{"channel": "tickers", "instId": s.replace('/', '-')} for s in symbols]}))
        except websockets.exceptions.ConnectionClosed: pass

    async def subscribe(self, symbols):
        new = [s for s in symbols if s not in self.subscriptions]
        if new:
            await self._send_op('subscribe', new)
            self.subscriptions.update(new)

    async def unsubscribe(self, symbols):
        old = [s for s in symbols if s in self.subscriptions]
        if old:
            await self._send_op('unsubscribe', old)
            [self.subscriptions.discard(s) for s in old]

    async def run(self):
        while True:
            try:
                async with websockets.connect(self.ws_url, ping_interval=20, ping_timeout=20) as ws:
                    self.websocket = ws
                    logger.info("✅ [OKX Public WS] Connected.")
                    if self.subscriptions: await self.subscribe(list(self.subscriptions))
                    async for msg in ws:
                        if msg == 'ping': await ws.send('pong'); continue
                        data = json.loads(msg)
                        if data.get('arg', {}).get('channel') == 'tickers' and 'data' in data:
                            for ticker in data['data']:
                                # --- [الترقية] تحويل بيانات OKX إلى التنسيق الموحد للحارس ---
                                standard_ticker = {
                                    'symbol': ticker['instId'].replace('-', '/'),
                                    'price': float(ticker['last'])
                                }
                                await self.handler(standard_ticker)
            except Exception as e:
                logger.error(f"OKX Public WS failed: {e}. Retrying in 10s...")
                await asyncio.sleep(10)

class PrivateWebSocketManager:
    def __init__(self): self.ws_url = "wss://ws.okx.com:8443/ws/v5/private"
    def _get_auth_args(self):
        timestamp = str(time.time()); message = timestamp + 'GET' + '/users/self/verify'
        mac = hmac.new(bytes(OKX_API_SECRET, 'utf8'), bytes(message, 'utf8'), 'sha256')
        sign = base64.b64encode(mac.digest()).decode()
        return [{"apiKey": OKX_API_KEY, "passphrase": OKX_API_PASSPHRASE, "timestamp": timestamp, "sign": sign}]
    async def _message_handler(self, msg):
        if msg == 'ping': await self.websocket.send('pong'); return
        data = json.loads(msg)
        if data.get('arg', {}).get('channel') == 'orders':
            for order in data.get('data', []):
                if order.get('state') == 'filled' and order.get('side') == 'buy': await handle_filled_buy_order(order)
    async def run(self):
        while True:
            try:
                async with websockets.connect(self.ws_url, ping_interval=20, ping_timeout=20) as ws:
                    self.websocket = ws; logger.info("✅ [OKX Private WS] Connected.")
                    await ws.send(json.dumps({"op": "login", "args": self._get_auth_args()}))
                    login_response = json.loads(await ws.recv())
                    if login_response.get('code') == '0':
                        logger.info("🔐 [OKX Private WS] Authenticated.")
                        await ws.send(json.dumps({"op": "subscribe", "args": [{"channel": "orders", "instType": "SPOT"}]}))
                        async for msg in ws: await self._message_handler(msg)
                    else: raise ConnectionAbortedError(f"Auth failed: {login_response}")
            except Exception as e:
                logger.error(f"OKX Private WS failed: {e}. Retrying in 10s...")
                await asyncio.sleep(10)

# --- Helper, Settings & DB Management ---
def load_settings():
    try:
        if os.path.exists(SETTINGS_FILE):
            with open(SETTINGS_FILE, 'r') as f: bot_data.settings = json.load(f)
        else: bot_data.settings = copy.deepcopy(DEFAULT_SETTINGS)
    except Exception: bot_data.settings = copy.deepcopy(DEFAULT_SETTINGS)
    for key, value in DEFAULT_SETTINGS.items():
        bot_data.settings.setdefault(key, value)
    save_settings()
    logger.info("Settings loaded successfully.")

def save_settings():
    with open(SETTINGS_FILE, 'w') as f: json.dump(bot_data.settings, f, indent=4)

async def init_database():
    try:
        async with aiosqlite.connect(DB_FILE) as conn:
            await conn.execute('CREATE TABLE IF NOT EXISTS trades (id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT, symbol TEXT, entry_price REAL, take_profit REAL, stop_loss REAL, quantity REAL, status TEXT, reason TEXT, order_id TEXT, highest_price REAL DEFAULT 0, trailing_sl_active BOOLEAN DEFAULT 0, close_price REAL, pnl_usdt REAL, last_profit_notification_price REAL DEFAULT 0, trade_weight REAL DEFAULT 1.0)')
            await conn.commit()
        logger.info("Database initialized successfully.")
    except Exception as e: logger.critical(f"Database initialization failed: {e}")

async def safe_send_message(bot, text, **kwargs):
    try:
        await bot.send_message(TELEGRAM_CHAT_ID, text, parse_mode=ParseMode.MARKDOWN, **kwargs)
    except Exception as e:
        logger.error(f"Telegram Send Error: {e}.")

# --- Core Trading Logic ---
async def log_pending_trade_to_db(signal, buy_order):
    try:
        async with aiosqlite.connect(DB_FILE) as conn:
            await conn.execute("INSERT INTO trades (timestamp, symbol, reason, order_id, status, entry_price, take_profit, stop_loss, trade_weight) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", (datetime.now(EGYPT_TZ).isoformat(), signal['symbol'], signal['reason'], buy_order['id'], 'pending', signal['entry_price'], signal['take_profit'], signal['stop_loss'], signal.get('weight', 1.0)))
            await conn.commit()
            return True
    except Exception as e:
        logger.error(f"DB Log Pending Error for {signal['symbol']}: {e}")
        return False

async def activate_trade(order_id, symbol):
    bot = bot_data.application.bot
    try:
        order_details = await bot_data.exchange.fetch_order(order_id, symbol)
        filled_price = float(order_details.get('average', 0.0))
        net_filled_quantity = float(order_details.get('filled', 0.0))
        if net_filled_quantity <= 0 or filled_price <= 0: return
    except Exception as e:
        logger.error(f"Could not fetch order details for activation of {order_id}: {e}"); return

    async with aiosqlite.connect(DB_FILE) as conn:
        conn.row_factory = aiosqlite.Row
        trade = await (await conn.execute("SELECT * FROM trades WHERE order_id = ? AND status = 'pending'", (order_id,))).fetchone()
        if not trade: return
        trade = dict(trade)
        risk = filled_price - trade['stop_loss']
        new_take_profit = filled_price + (risk * bot_data.settings['risk_reward_ratio'])
        await conn.execute("UPDATE trades SET status = 'active', entry_price = ?, quantity = ?, take_profit = ?, last_profit_notification_price = ? WHERE id = ?", (filled_price, net_filled_quantity, new_take_profit, filled_price, trade['id']))
        active_trades_count = (await (await conn.execute("SELECT COUNT(*) FROM trades WHERE status = 'active'")).fetchone())[0]
        await conn.commit()

    await bot_data.public_ws.subscribe([symbol])
    tp_percent = (new_take_profit / filled_price - 1) * 100
    sl_percent = (1 - trade['stop_loss'] / filled_price) * 100
    reasons_ar = ' + '.join([STRATEGY_NAMES_AR.get(r.strip(), r.strip()) for r in trade['reason'].split(' + ')])
    msg = (f"✅ **تم تأكيد شراء OKX | {symbol}**\n"
           f"**الاستراتيجية:** {reasons_ar}\n"
           f"**رقم:** `#{trade['id']}` | **سعر:** `${filled_price:,.4f}`\n"
           f"**الهدف:** `${new_take_profit:,.4f}` `({tp_percent:+.2f}%)`\n"
           f"**الوقف:** `${trade['stop_loss']:,.4f}` `({sl_percent:.2f}%)`\n"
           f"**الصفقات النشطة:** `{active_trades_count}`")
    await safe_send_message(bot, msg)

async def handle_filled_buy_order(order_data):
    symbol, order_id = order_data['instId'].replace('-', '/'), order_data['ordId']
    if float(order_data.get('avgPx', 0)) > 0:
        await activate_trade(order_id, symbol)

async def has_active_trade_for_symbol(symbol: str) -> bool:
    async with aiosqlite.connect(DB_FILE) as conn:
        return (await (await conn.execute("SELECT 1 FROM trades WHERE symbol = ? AND status IN ('active', 'pending') LIMIT 1", (symbol,))).fetchone()) is not None

async def initiate_real_trade(signal):
    if not bot_data.trading_enabled: return False
    try:
        settings, exchange = bot_data.settings, bot_data.exchange
        trade_size = settings['real_trade_size_usdt']
        balance = await exchange.fetch_balance({'type': 'trading'})
        if balance.get('USDT', {}).get('free', 0.0) < trade_size: return False
        base_amount = trade_size / signal['entry_price']
        formatted_amount = exchange.amount_to_precision(signal['symbol'], base_amount)
        buy_order = await exchange.create_market_buy_order(signal['symbol'], formatted_amount)
        if await log_pending_trade_to_db(signal, buy_order):
            await safe_send_message(bot_data.application.bot, f"🚀 تم إرسال أمر شراء لـ `{signal['symbol']}`...")
            return True
        else:
            await exchange.cancel_order(buy_order['id'], signal['symbol']); return False
    except Exception as e:
        logger.error(f"REAL TRADE FAILED {signal['symbol']}: {e}", exc_info=True); return False

# --- Scanner Worker and Main Scan Function ---
async def worker_batch(queue, signals_list, errors_list):
    settings, exchange = bot_data.settings, bot_data.exchange
    while not queue.empty():
        symbol = ""
        try:
            market = await queue.get()
            symbol = market['symbol']
            ohlcv = await exchange.fetch_ohlcv(symbol, TIMEFRAME, limit=220)
            if len(ohlcv) < 50: queue.task_done(); continue
            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            
            if settings.get('multi_timeframe_confluence_enabled', True):
                try:
                    ohlcv_1h, ohlcv_4h = await asyncio.gather(
                        exchange.fetch_ohlcv(symbol, '1h', limit=100),
                        exchange.fetch_ohlcv(symbol, '4h', limit=201)
                    )
                    df_1h = pd.DataFrame(ohlcv_1h, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                    df_1h.ta.macd(append=True); df_1h.ta.sma(length=50, append=True)
                    is_1h_bullish = (df_1h[find_col(df_1h.columns, "MACD_")].iloc[-1] > df_1h[find_col(df_1h.columns, "MACDs_")].iloc[-1]) and \
                                    (df_1h['close'].iloc[-1] > df_1h[find_col(df_1h.columns, "SMA_50")].iloc[-1])
                    
                    df_4h = pd.DataFrame(ohlcv_4h, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                    df_4h.ta.ema(length=200, append=True)
                    is_4h_bullish = df_4h['close'].iloc[-1] > df_4h[find_col(df_4h.columns, "EMA_200")].iloc[-1]
                    
                    if not (is_1h_bullish and is_4h_bullish):
                        queue.task_done(); continue
                except Exception: pass
            
            confirmed_reasons = []
            if 'whale_radar' in settings['active_scanners']:
                if await filter_whale_radar(exchange, symbol, settings):
                    confirmed_reasons.append("whale_radar")

            for name in settings['active_scanners']:
                if name == 'whale_radar': continue
                if not (strategy_func := SCANNERS.get(name)): continue
                params = settings.get(name, {})
                func_args = {'df': df.copy(), 'params': params}
                if name in ['support_rebound']: func_args.update({'exchange': exchange, 'symbol': symbol})
                
                result = await strategy_func(**func_args) if asyncio.iscoroutinefunction(strategy_func) else strategy_func(**func_args)
                if result: confirmed_reasons.append(result['reason'])

            if confirmed_reasons:
                reason_str = ' + '.join(set(confirmed_reasons))
                entry_price = df.iloc[-1]['close']
                df.ta.atr(length=14, append=True)
                atr_col = find_col(df.columns, "ATRr_14")
                atr = df[atr_col].iloc[-1] if atr_col and pd.notna(df[atr_col].iloc[-1]) else (df['high'].iloc[-1] - df['low'].iloc[-1])
                risk = atr * settings['atr_sl_multiplier']
                signals_list.append({"symbol": symbol, "entry_price": entry_price, "take_profit": entry_price + (risk * settings['risk_reward_ratio']), "stop_loss": entry_price - risk, "reason": reason_str})
            queue.task_done()
        except Exception as e:
            errors_list.append(symbol if symbol else 'Unknown')
            if not queue.empty(): queue.task_done()

async def perform_scan(context: ContextTypes.DEFAULT_TYPE):
    async with scan_lock:
        if not bot_data.trading_enabled: return
        scan_start_time = time.time(); logger.info("--- Starting new Fused Maestro scan (OKX)... ---")
        settings = bot_data.settings

        mood_result = await get_market_mood(bot_data)
        if mood_result['mood'] in ["NEGATIVE", "DANGEROUS"]:
            logger.warning(f"Scan skipped due to market mood: {mood_result['reason']}")
            return

        async with aiosqlite.connect(DB_FILE) as conn:
            active_trades_count = (await (await conn.execute("SELECT COUNT(*) FROM trades WHERE status IN ('active', 'pending')")).fetchone())[0]
        if active_trades_count >= settings['max_concurrent_trades']:
            logger.info(f"Scan skipped: Max concurrent trades ({active_trades_count}) reached.")
            return
        
        top_markets = await get_okx_markets(bot_data)
        if not top_markets: 
            logger.warning("Scan could not retrieve any markets.")
            return

        queue, signals_found, analysis_errors = asyncio.Queue(), [], []
        for market in top_markets:
            await queue.put(market)
        
        worker_tasks = [asyncio.create_task(worker_batch(queue, signals_found, analysis_errors)) for _ in range(settings.get("worker_threads", 10))]
        await queue.join()
        for task in worker_tasks: task.cancel()
        
        trades_opened_count = 0
        for signal in signals_found:
            if active_trades_count >= settings['max_concurrent_trades']: break
            if not await has_active_trade_for_symbol(signal['symbol']):
                if await initiate_real_trade(signal):
                    trades_opened_count += 1
                    active_trades_count += 1
                    await asyncio.sleep(2)
        
        scan_duration = time.time() - scan_start_time
        bot_data.last_scan_info = {"duration_seconds": int(scan_duration), "checked_symbols": len(top_markets)}
        logger.info(f"OKX Scan complete in {int(scan_duration)}s. Found {len(signals_found)} signals, opened {trades_opened_count} trades.")

# --- Scheduled Jobs ---
async def maestro_job(context: ContextTypes.DEFAULT_TYPE):
    if not bot_data.settings.get('maestro_mode_enabled', True): return
    logger.info("🎼 Maestro (OKX): Analyzing market regime...")
    regime = await get_market_regime(bot_data.exchange)
    if regime != "UNKNOWN" and regime != bot_data.current_market_regime:
        bot_data.current_market_regime = regime
        config = DECISION_MATRIX.get(regime, {})
        if not config: return
        changes_report = []
        for key, value in config.items():
            if key in bot_data.settings and bot_data.settings[key] != value:
                changes_report.append(f"- `{key}` changed to `{value}`")
                bot_data.settings[key] = value
        save_settings()
        if changes_report:
            report = f"🎼 **Maestro Report (OKX) | {regime}**\n" + "\n".join(changes_report)
            await safe_send_message(context.bot, report)

# --- Bot Startup ---
async def post_init(application: Application):
    logger.info("Performing post-initialization for Fused Maestro Bot [OKX Edition]...")
    if not all([TELEGRAM_BOT_TOKEN, OKX_API_KEY, OKX_API_SECRET, OKX_API_PASSPHRASE, TELEGRAM_CHAT_ID]):
        logger.critical("FATAL: Missing critical OKX or Telegram environment variables."); return

    bot_data.application = application
    bot_data.exchange = ccxt.okx({'apiKey': OKX_API_KEY, 'secret': OKX_API_SECRET, 'password': OKX_API_PASSPHRASE, 'enableRateLimit': True})
    try:
        await bot_data.exchange.load_markets()
    except Exception as e:
        logger.critical(f"🔥 FATAL: Could not connect to OKX: {e}"); return
    
    load_settings()
    await init_database()

    # --- [الترقية النهائية] تهيئة وربط الحارس الموحد ---
    bot_data.guardian = MaestroGuardian(bot_data.exchange, application, bot_data, DB_FILE)
    bot_data.smart_brain = EvolutionaryEngine(bot_data.exchange, application, DB_FILE)

    # تمرير دالة المعالج الموحد من الحارس إلى مدير WebSocket
    bot_data.public_ws = PublicWebSocketManager(bot_data.guardian.handle_ticker_update)
    bot_data.private_ws = PrivateWebSocketManager()
    
    asyncio.create_task(bot_data.public_ws.run())
    asyncio.create_task(bot_data.private_ws.run())
    
    # جدولة المهام
    jq = application.job_queue
    jq.run_repeating(perform_scan, interval=SCAN_INTERVAL_SECONDS, first=10, name="perform_scan")
    jq.run_repeating(bot_data.guardian.the_supervisor_job, interval=SUPERVISOR_INTERVAL_SECONDS, first=30, name="supervisor_job")
    jq.run_repeating(bot_data.guardian.intelligent_reviewer_job, interval=3600, first=60, name="intelligent_reviewer")
    jq.run_repeating(bot_data.guardian.review_open_trades, interval=14400, first=120, name="wise_man_review")
    jq.run_repeating(bot_data.guardian.review_portfolio_risk, interval=86400, first=180, name="portfolio_risk_review")
    jq.run_repeating(maestro_job, interval=MAESTRO_INTERVAL_HOURS * 3600, first=5, name="maestro_job")
    jq.run_daily(bot_data.smart_brain.run_pattern_discovery, time=dt_time(hour=22, minute=0, tzinfo=EGYPT_TZ), name='pattern_discovery_job')
    
    logger.info(f"All Fused jobs scheduled for OKX Bot.")
    await safe_send_message(application.bot, "*🤖 Wise Maestro Bot (OKX Fused Edition) - بدأ العمل...*")
    logger.info("--- Fused Maestro Bot (OKX Edition) is now fully operational ---")

async def post_shutdown(application: Application):
    if bot_data.exchange: await bot_data.exchange.close()
    if bot_data.redis_client: await bot_data.redis_client.close()
    logger.info("OKX Bot has shut down gracefully.")

def main():
    logger.info("Starting Fused Maestro Bot - OKX Edition...")
    app_builder = Application.builder().token(TELEGRAM_BOT_TOKEN)
    app_builder.post_init(post_init).post_shutdown(post_shutdown)
    application = app_builder.build()

    application.bot_data = bot_data

    # --- تأكد من وجود هذه الأسطر الثلاثة كاملة وغير معطلة ---
    application.add_handler(CommandHandler("start", ui_handlers.start_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, ui_handlers.universal_text_handler))
    application.add_handler(CallbackQueryHandler(ui_handlers.button_callback_handler)) # <-- هذا هو السطر الحاسم

    application.run_polling()
