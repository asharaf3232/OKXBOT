# -*- coding: utf-8 -*-
# =======================================================================================
# --- 🚀 Wise Maestro Bot - Final Fusion v8.1 (OKX Edition) 🚀 ---
# =======================================================================================
import os
import logging
import asyncio
import json
import time
import copy
from datetime import datetime, time as dt_time
from zoneinfo import ZoneInfo
from collections import defaultdict
import aiosqlite
import pandas as pd
import pandas_ta as ta
import ccxt.async_support as ccxt
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters, CallbackQueryHandler
from telegram.constants import ParseMode
from dotenv import load_dotenv
import websockets
import websockets.exceptions
import hmac
import base64

# --- استيراد الوحدات المنفصلة ---
from settings_config import *
from strategy_scanners import SCANNERS
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
        # لإ кэширования рынков
        self.all_markets = []
        self.last_markets_fetch = 0
        self.strategy_performance = {}

bot_data = BotState()
scan_lock = asyncio.Lock()

# --- OKX Specific WebSocket ---
class PublicWebSocketManager:
    def __init__(self, handler_coro): 
        self.ws_url = "wss://ws.okx.com:8443/ws/v5/public"
        self.handler = handler_coro
        self.subscriptions = set()
        self.websocket = None

    async def _send_op(self, op, symbols):
        if not symbols or not self.websocket or not self.websocket.open: return
        try: await self.websocket.send(json.dumps({"op": op, "args": [{"channel": "tickers", "instId": s.replace('/', '-')} for s in symbols]}))
        except websockets.exceptions.ConnectionClosed: pass

    async def subscribe(self, symbols):
        new_symbols = [s for s in symbols if s not in self.subscriptions]
        if new_symbols:
            logger.info(f"[Public WS] Subscribing to: {new_symbols}")
            await self._send_op('subscribe', new_symbols)
            self.subscriptions.update(new_symbols)

    async def unsubscribe(self, symbols):
        old_symbols = [s for s in symbols if s in self.subscriptions]
        if old_symbols:
            logger.info(f"[Public WS] Unsubscribing from: {old_symbols}")
            await self._send_op('unsubscribe', old_symbols)
            for s in old_symbols: self.subscriptions.discard(s)

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
                                standard_ticker = {
                                    'symbol': ticker['instId'].replace('-', '/'),
                                    'price': float(ticker['last'])
                                }
                                await self.handler(standard_ticker)
            except Exception as e:
                logger.error(f"OKX Public WS failed: {e}. Retrying in 10s...")
                self.websocket = None
                await asyncio.sleep(10)

class PrivateWebSocketManager:
    def __init__(self): 
        self.ws_url = "wss://ws.okx.com:8443/ws/v5/private"
        self.websocket = None
        
    def _get_auth_args(self):
        timestamp = str(time.time()); message = timestamp + 'GET' + '/users/self/verify'
        mac = hmac.new(bytes(OKX_API_SECRET, 'utf8'), bytes(message, 'utf8'), 'sha256')
        sign = base64.b64encode(mac.digest()).decode()
        return [{"apiKey": OKX_API_KEY, "passphrase": OKX_API_PASSPHRASE, "timestamp": timestamp, "sign": sign}]

    async def _message_handler(self, msg):
        if msg == 'ping': await self.websocket.send('pong'); return
        data = json.loads(msg)
        if data.get('event') == 'error':
             logger.error(f"[Private WS] Error: {data.get('msg')}")
             return
        if data.get('arg', {}).get('channel') == 'orders' and 'data' in data:
            for order_data in data.get('data', []):
                if order_data.get('state') == 'filled' and order_data.get('side') == 'buy': 
                    if hasattr(bot_data, 'activate_trade'): # Ensure function exists
                        await bot_data.activate_trade(order_data['ordId'], order_data['instId'].replace('-', '/'))

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
                self.websocket = None
                await asyncio.sleep(10)

def load_settings():
    try:
        if os.path.exists(SETTINGS_FILE):
            with open(SETTINGS_FILE, 'r') as f: 
                user_settings = json.load(f)
                bot_data.settings = copy.deepcopy(DEFAULT_SETTINGS)
                bot_data.settings.update(user_settings) # Merge to keep new defaults
        else: bot_data.settings = copy.deepcopy(DEFAULT_SETTINGS)
    except Exception: bot_data.settings = copy.deepcopy(DEFAULT_SETTINGS)
    with open(SETTINGS_FILE, 'w') as f: json.dump(bot_data.settings, f, indent=4); logger.info("Settings loaded successfully.")

async def init_database():
    try:
        async with aiosqlite.connect(DB_FILE) as conn:
            await conn.execute('CREATE TABLE IF NOT EXISTS trades (id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT, symbol TEXT, entry_price REAL, take_profit REAL, stop_loss REAL, quantity REAL, status TEXT, reason TEXT, order_id TEXT, highest_price REAL DEFAULT 0, trailing_sl_active BOOLEAN DEFAULT 0, close_price REAL, pnl_usdt REAL, last_profit_notification_price REAL DEFAULT 0, trade_weight REAL DEFAULT 1.0)')
            await conn.commit(); logger.info("Database initialized successfully.")
    except Exception as e: logger.critical(f"Database initialization failed: {e}")

async def perform_scan(context: ContextTypes.DEFAULT_TYPE, manual_run=False):
    if scan_lock.locked():
        logger.info("Scan is already in progress. Skipping this run.")
        if manual_run:
            await context.bot.send_message(TELEGRAM_CHAT_ID, "⚠️ **يوجد فحص آخر قيد التنفيذ. يرجى الانتظار.**")
        return

    async with scan_lock:
        if not bot_data.trading_enabled:
            logger.warning("Trading is disabled via kill switch. Scan aborted.")
            if manual_run:
                await context.bot.send_message(TELEGRAM_CHAT_ID, "🚨 **الفحص اليدوي ملغي. مفتاح الإيقاف مفعل.**")
            return

        logger.info("🚀 Starting new market scan...")
        if manual_run:
            await context.bot.send_message(TELEGRAM_CHAT_ID, "🔬 **بدء فحص يدوي للسوق...**", parse_mode=ParseMode.MARKDOWN)
        
        start_time = time.time()
        found_opportunities = []
        scanned_symbols_count = 0

        try:
            all_markets = await get_okx_markets(bot_data)
            if not all_markets:
                if manual_run: await context.bot.send_message(TELEGRAM_CHAT_ID, "⚠️ تعذر جلب بيانات الأسواق من OKX.")
                return

            market_mood = await get_market_mood(bot_data)
            if market_mood["mood"] != "POSITIVE":
                reason = market_mood['reason']
                logger.info(f"Scan paused due to market mood: {reason}")
                if manual_run: await context.bot.send_message(TELEGRAM_CHAT_ID, f"⏸️ **إيقاف البحث:** {reason}")
                return

            symbols_to_scan = [m['symbol'] for m in all_markets]
            scanned_symbols_count = len(symbols_to_scan)
            
            # This is a simplified sequential scan. For higher performance, this should be parallelized.
            for symbol in symbols_to_scan:
                try:
                    ohlcv = await bot_data.exchange.fetch_ohlcv(symbol, TIMEFRAME, limit=220)
                    if not ohlcv or len(ohlcv) < 50: continue
                    df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                    
                    for scanner_name in bot_data.settings.get('active_scanners', []):
                        if not (scanner_func := SCANNERS.get(scanner_name)): continue

                        # Simple placeholder for rvol and adx for now
                        df.ta.adx(append=True)
                        adx_value = df[next((c for c in df.columns if c.startswith('ADX_')), 'ADX_14')].iloc[-1]
                        
                        args = {'df': df.copy(), 'params': {}, 'rvol': 1.0, 'adx_value': adx_value}
                        if scanner_name == 'support_rebound':
                            args.update({'exchange': bot_data.exchange, 'symbol': symbol})
                        
                        result = await scanner_func(**args) if asyncio.iscoroutinefunction(scanner_func) else scanner_func(**{k: v for k, v in args.items() if k not in ['exchange', 'symbol']})

                        if result:
                            reason_text = result.get('reason', scanner_name)
                            found_opportunities.append({'symbol': symbol, 'reason': reason_text})
                            logger.info(f"✅ Opportunity found for {symbol} by {reason_text}")
                            # Here you would typically trigger the trade opening logic
                            # For now, we'll just report it.
                except Exception:
                    continue
        
        finally:
            duration = time.time() - start_time
            bot_data.last_scan_info = {'duration_seconds': f"{duration:.2f}", 'checked_symbols': scanned_symbols_count}
            
            if manual_run:
                report = f"✅ **اكتمل الفحص اليدوي!**\n\n"
                report += f"⏱️ **المدة:** {duration:.2f} ثانية\n"
                report += f"📊 **العملات المفحوصة:** {scanned_symbols_count}\n\n"
                
                if found_opportunities:
                    report += "🎯 **الفرص التي تم العثور عليها:**\n"
                    for opp in found_opportunities[:10]: # Limit to 10 to avoid message size limit
                        reason_ar = STRATEGY_NAMES_AR.get(opp['reason'], opp['reason'])
                        report += f"- `{opp['symbol']}` (السبب: {reason_ar})\n"
                else:
                    report += "⭕ لم يتم العثور على أي فرص مطابقة للشروط الحالية."
                await context.bot.send_message(TELEGRAM_CHAT_ID, report, parse_mode=ParseMode.MARKDOWN)

async def maestro_job(context: ContextTypes.DEFAULT_TYPE):
    logger.info("🧠 Maestro: Running market regime analysis...")
    if not bot_data.settings.get('maestro_mode_enabled', True):
        logger.info("Maestro mode is disabled.")
        return
        
    try:
        regime = await get_market_regime(bot_data.exchange)
        if regime in DECISION_MATRIX:
            adjustments = DECISION_MATRIX[regime]
            current_settings = bot_data.settings
            
            # Apply adjustments
            for key, value in adjustments.items():
                current_settings[key] = value
            
            # Save the new adaptive settings
            with open(SETTINGS_FILE, 'w') as f:
                json.dump(current_settings, f, indent=4)
            
            bot_data.active_preset_name = f"المايسترو ({regime})"
            
            active_scanners_ar = [STRATEGY_NAMES_AR.get(s, s) for s in adjustments.get('active_scanners', [])]
            
            message = (f"**🧠 المايسترو:** تم تكييف الإعدادات مع حالة السوق!\n"
                       f"**الحالة الحالية:** `{regime}`\n"
                       f"**الماسحات النشطة:** {', '.join(active_scanners_ar)}\n"
                       f"**نسبة المخاطرة/العائد:** `{adjustments.get('risk_reward_ratio', 'N/A')}`")
            await context.bot.send_message(TELEGRAM_CHAT_ID, message, parse_mode=ParseMode.MARKDOWN)
        else:
            logger.warning(f"Maestro: Unknown market regime '{regime}'. No adjustments made.")
    except Exception as e:
        logger.error(f"Maestro job failed: {e}", exc_info=True)


# --- Bot Startup ---
async def post_init(application: Application):
    logger.info("Performing post-initialization for Fused Maestro Bot [OKX Edition]...")
    if not all([TELEGRAM_BOT_TOKEN, OKX_API_KEY, OKX_API_SECRET, OKX_API_PASSPHRASE, TELEGRAM_CHAT_ID]):
        logger.critical("FATAL: Missing critical OKX or Telegram environment variables."); return
    bot_data.application = application
    bot_data.exchange = ccxt.okx({'apiKey': OKX_API_KEY, 'secret': OKX_API_SECRET, 'password': OKX_API_PASSPHRASE, 'enableRateLimit': True})
    try: await bot_data.exchange.load_markets()
    except Exception as e: logger.critical(f"🔥 FATAL: Could not connect to OKX: {e}"); return
    load_settings(); await init_database()
    bot_data.guardian = MaestroGuardian(bot_data.exchange, application, bot_data, DB_FILE)
    bot_data.smart_brain = EvolutionaryEngine(bot_data.exchange, application, DB_FILE)
    bot_data.public_ws = PublicWebSocketManager(bot_data.guardian.handle_ticker_update)
    bot_data.private_ws = PrivateWebSocketManager()
    asyncio.create_task(bot_data.public_ws.run()); asyncio.create_task(bot_data.private_ws.run())
    jq = application.job_queue
    jq.run_repeating(perform_scan, interval=SCAN_INTERVAL_SECONDS, first=10, name="perform_scan")
    jq.run_repeating(bot_data.guardian.the_supervisor_job, interval=SUPERVISOR_INTERVAL_SECONDS, first=30, name="supervisor_job")
    jq.run_repeating(bot_data.guardian.intelligent_reviewer_job, interval=3600, first=60, name="intelligent_reviewer")
    jq.run_repeating(bot_data.guardian.review_open_trades, interval=14400, first=120, name="wise_man_review")
    jq.run_repeating(bot_data.guardian.review_portfolio_risk, interval=86400, first=180, name="portfolio_risk_review")
    jq.run_repeating(maestro_job, interval=MAESTRO_INTERVAL_HOURS * 3600, first=5, name="maestro_job")
    jq.run_daily(bot_data.smart_brain.run_pattern_discovery, time=dt_time(hour=22, tzinfo=ZoneInfo("Africa/Cairo")), name='pattern_discovery_job')
    logger.info(f"All Fused jobs scheduled for OKX Bot.")
    await application.bot.send_message(TELEGRAM_CHAT_ID, "*🤖 Wise Maestro Bot (OKX Fused Edition) - بدأ العمل...*", parse_mode=ParseMode.MARKDOWN)
    logger.info("--- Fused Maestro Bot (OKX Edition) is now fully operational ---")

async def post_shutdown(application: Application):
    if bot_data.exchange: await bot_data.exchange.close()
    logger.info("OKX Bot has shut down gracefully.")

def main():
    logger.info("Starting Fused Maestro Bot - OKX Edition...")
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
