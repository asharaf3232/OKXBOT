# -*- coding: utf-8 -*-
# =======================================================================================
# --- 🚀 OKX Maestro Pro v8.1 (النسخة النهائية الموحدة والكاملة) 🚀 ---
# =======================================================================================
#
# هذا الإصدار هو دمج شامل لأفضل الميزات من جميع النسخ السابقة:
# - هيكل أحادي قوي وجاهز للتشغيل الفوري.
# - عقل المايسترو (Maestro) لتغيير الاستراتيجيات ديناميكيًا.
# - وحدة الرجل الحكيم (Wise Man) للمراجعة التكتيكية وإدارة مخاطر المحفظة.
# - محرك تطوري (Evolutionary Engine) للتعلم من الصفقات السابقة.
# - آلية إغلاق فائقة الموثوقية (Ultimate Robust Closure) لمنع فشل البيع.
# - حماية من تكرار الصفقات (Race Condition Protection).
# - التحقق من الحد الأدنى لقيمة الصفقة (MIN_NOTIONAL Filter).
# - جميع الفلاتر والاستراتيجيات المتقدمة.
#
# =======================================================================================

# --- المكتبات الأساسية ---
import os
import logging
import asyncio
import json
import time
import copy
import random
import re
import hmac
import base64
from datetime import datetime, timedelta, timezone, time as dt_time
from zoneinfo import ZoneInfo
from collections import defaultdict, Counter
import httpx
import aiosqlite

# --- مكتبات التحليل والتداول ---
import pandas as pd
import pandas_ta as ta
import ccxt.async_support as ccxt
import feedparser
import websockets
import websockets.exceptions

# --- مكتبات الذكاء الاصطناعي (اختياري) ---
try:
    import nltk
    from nltk.sentiment.vader import SentimentIntensityAnalyzer
    NLTK_AVAILABLE = True
except ImportError:
    NLTK_AVAILABLE = False
    logging.warning("NLTK not found. News sentiment analysis will be disabled.")

try:
    from scipy.signal import find_peaks
    SCIPY_AVAILABLE = True
except ImportError:
    SCIPY_AVAILABLE = False
    logging.warning("Library 'scipy' not found. RSI Divergence strategy will be disabled.")

# --- مكتبات تليجرام ---
from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters, CallbackQueryHandler
from telegram.constants import ParseMode
from telegram.error import BadRequest, TimedOut, Forbidden
from dotenv import load_dotenv

# --- إعدادات أساسية ---
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger("OKX_Maestro_Pro")
load_dotenv()

# --- جلب المتغيرات من بيئة التشغيل ---
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
OKX_API_KEY = os.getenv('OKX_API_KEY')
OKX_API_SECRET = os.getenv('OKX_API_SECRET')
OKX_API_PASSPHRSE = os.getenv('OKX_API_PASSPHRSE')
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY') # Optional for translation
ALPHA_VANTAGE_API_KEY = os.getenv('ALPHA_VANTAGE_API_KEY', 'YOUR_AV_KEY_HERE') # Optional for economic data

# --- ثوابت وإعدادات البوت ---
DB_FILE = 'okx_maestro_pro_v8.db'
SETTINGS_FILE = 'okx_maestro_pro_v8_settings.json'
TIMEFRAME = '15m'
SCAN_INTERVAL_SECONDS = 900
SUPERVISOR_INTERVAL_SECONDS = 180
MAESTRO_INTERVAL_HOURS = 1
WISE_MAN_TRADE_REVIEW_INTERVAL = 1800 # 30 minutes
WISE_MAN_PORTFOLIO_REVIEW_INTERVAL = 3600 # 1 hour
STRATEGY_ANALYSIS_INTERVAL_SECONDS = 21600 # 6 hours
EGYPT_TZ = ZoneInfo("Africa/Cairo")

# --- الحالة العامة للبوت (Global State) ---
class BotState:
    def __init__(self):
        self.settings = {}
        self.trading_enabled = True
        self.active_preset_name = "مخصص"
        self.exchange = None
        self.application = None
        self.websocket_manager = None
        self.wise_man = None
        self.smart_engine = None
        self.market_mood = {"mood": "UNKNOWN", "reason": "تحليل لم يتم بعد"}
        self.current_market_regime = "UNKNOWN"
        self.last_scan_info = {}
        self.all_markets = []
        self.last_markets_fetch = 0
        self.strategy_performance = {}
        self.pending_strategy_proposal = {}

bot_data = BotState()
scan_lock = asyncio.Lock()
trade_management_lock = asyncio.Lock()

# =======================================================================================
# --- ⚙️ الإعدادات الافتراضية والأنماط ⚙️ ---
# =======================================================================================
DEFAULT_SETTINGS = {
    "real_trade_size_usdt": 15.0,
    "max_concurrent_trades": 5,
    "top_n_symbols_by_volume": 300,
    "worker_threads": 10,
    "atr_sl_multiplier": 2.5,
    "risk_reward_ratio": 2.0,
    "trailing_sl_enabled": True,
    "trailing_sl_activation_percent": 2.0,
    "trailing_sl_callback_percent": 1.5,
    "active_scanners": ["momentum_breakout", "breakout_squeeze_pro", "support_rebound", "sniper_pro", "rsi_divergence", "supertrend_pullback", "bollinger_reversal"],
    "market_mood_filter_enabled": True,
    "fear_and_greed_threshold": 30,
    "adx_filter_enabled": True,
    "adx_filter_level": 25,
    "btc_trend_filter_enabled": True,
    "news_filter_enabled": True,
    "asset_blacklist": ["USDC", "DAI", "TUSD", "FDUSD", "USDD", "PYUSD", "USDT", "BNB", "BTC", "ETH", "OKB"],
    "liquidity_filters": {"min_quote_volume_24h_usd": 1000000, "min_rvol": 1.5},
    "volatility_filters": {"min_atr_percent": 0.8},
    "trend_filters": {"ema_period": 200, "htf_period": 50, "enabled": True},
    "spread_filter": {"max_spread_percent": 0.5},
    "volume_filter_multiplier": 2.0,
    "close_retries": 3,
    "incremental_notifications_enabled": True,
    "incremental_notification_percent": 2.0,
    "adaptive_intelligence_enabled": True,
    "dynamic_trade_sizing_enabled": True,
    "strategy_proposal_enabled": True,
    "strategy_analysis_min_trades": 10,
    "strategy_deactivation_threshold_wr": 45.0,
    "maestro_mode_enabled": True,
    "intelligent_reviewer_enabled": True,
    "momentum_scalp_mode_enabled": False,
    "momentum_scalp_target_percent": 0.5,
    "multi_timeframe_confluence_enabled": True,
    "wise_man_auto_close": True,
}

STRATEGY_NAMES_AR = {
    "momentum_breakout": "زخم اختراقي", "breakout_squeeze_pro": "اختراق انضغاطي",
    "support_rebound": "ارتداد الدعم", "sniper_pro": "القناص المحترف",
    "rsi_divergence": "دايفرجنس RSI", "supertrend_pullback": "انعكاس سوبرترند",
    "bollinger_reversal": "انعكاس بولينجر"
}

PRESET_NAMES_AR = {"professional": "احترافي", "strict": "متشدد", "lenient": "متساهل", "very_lenient": "فائق التساهل", "bold_heart": "القلب الجريء"}

DECISION_MATRIX = {
    "TRENDING_HIGH_VOLATILITY": {"active_scanners": ["momentum_breakout", "breakout_squeeze_pro", "sniper_pro"], "risk_reward_ratio": 1.5, "volume_filter_multiplier": 2.5, "momentum_scalp_mode_enabled": True},
    "TRENDING_LOW_VOLATILITY": {"active_scanners": ["support_rebound", "supertrend_pullback", "rsi_divergence"], "risk_reward_ratio": 2.5, "volume_filter_multiplier": 1.5, "momentum_scalp_mode_enabled": False},
    "SIDEWAYS_HIGH_VOLATILITY": {"active_scanners": ["bollinger_reversal", "rsi_divergence", "breakout_squeeze_pro"], "risk_reward_ratio": 2.0, "momentum_scalp_mode_enabled": True},
    "SIDEWAYS_LOW_VOLATILITY": {"active_scanners": ["bollinger_reversal", "support_rebound"], "risk_reward_ratio": 3.0, "momentum_scalp_mode_enabled": False}
}

SETTINGS_PRESETS = {
    "professional": copy.deepcopy(DEFAULT_SETTINGS),
    "strict": {**copy.deepcopy(DEFAULT_SETTINGS), "max_concurrent_trades": 3, "risk_reward_ratio": 2.5, "fear_and_greed_threshold": 40, "adx_filter_level": 28, "liquidity_filters": {"min_quote_volume_24h_usd": 2000000, "min_rvol": 2.0}},
    "lenient": {**copy.deepcopy(DEFAULT_SETTINGS), "max_concurrent_trades": 8, "risk_reward_ratio": 1.8, "fear_and_greed_threshold": 25, "adx_filter_level": 20, "liquidity_filters": {"min_quote_volume_24h_usd": 500000, "min_rvol": 1.2}},
    "very_lenient": {**copy.deepcopy(DEFAULT_SETTINGS), "max_concurrent_trades": 12, "adx_filter_enabled": False, "market_mood_filter_enabled": False, "trend_filters": {"enabled": False}},
    "bold_heart": {**copy.deepcopy(DEFAULT_SETTINGS), "max_concurrent_trades": 15, "risk_reward_ratio": 1.5, "multi_timeframe_confluence_enabled": False, "market_mood_filter_enabled": False, "adx_filter_enabled": False, "btc_trend_filter_enabled": False, "news_filter_enabled": False}
}

SECTOR_MAP = {
    'RNDR': 'AI', 'FET': 'AI', 'AGIX': 'AI', 'NEAR': 'AI',
    'UNI': 'DeFi', 'AAVE': 'DeFi', 'LDO': 'DeFi', 'MKR': 'DeFi',
    'SOL': 'Layer 1', 'AVAX': 'Layer 1', 'ADA': 'Layer 1',
    'DOGE': 'Memecoin', 'PEPE': 'Memecoin', 'SHIB': 'Memecoin',
    'LINK': 'Oracle', 'BAND': 'Oracle',
}
# =======================================================================================
# --- 🧠 الوحدات الذكية المدمجة 🧠 ---
# =======================================================================================

class WiseMan:
    def __init__(self, exchange: ccxt.Exchange, application: Application):
        self.exchange = exchange
        self.application = application
        logger.info("🧠 Wise Man module initialized.")

    async def review_open_trades(self, context: object = None):
        logger.info("🧠 Wise Man: Reviewing open trades...")
        async with aiosqlite.connect(DB_FILE) as conn:
            conn.row_factory = aiosqlite.Row
            active_trades = await (await conn.execute("SELECT * FROM trades WHERE status = 'active'")).fetchall()
            if not active_trades: return

            try:
                btc_ohlcv = await self.exchange.fetch_ohlcv('BTC/USDT', '1h', limit=20)
                btc_df = pd.DataFrame(btc_ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                btc_df['btc_momentum'] = ta.mom(btc_df['close'], length=10)
                is_btc_weak = btc_df['btc_momentum'].iloc[-1] < 0
            except Exception as e:
                logger.error(f"Wise Man: Could not fetch BTC data: {e}"); is_btc_weak = False

            for trade_data in active_trades:
                trade = dict(trade_data)
                symbol = trade['symbol']
                try:
                    ohlcv = await self.exchange.fetch_ohlcv(symbol, '15m', limit=50)
                    df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                    df['ema_fast'] = ta.ema(df['close'], length=10)
                    df['ema_slow'] = ta.ema(df['close'], length=30)
                    is_weak = df['close'].iloc[-1] < df['ema_fast'].iloc[-1] and df['close'].iloc[-1] < df['ema_slow'].iloc[-1]

                    if is_weak and is_btc_weak:
                        if bot_data.settings.get("wise_man_auto_close", True):
                            logger.warning(f"Wise Man recommends early exit for {symbol}. Flagging for Guardian.")
                            await conn.execute("UPDATE trades SET status = 'force_exit' WHERE id = ?", (trade['id'],))
                            await safe_send_message(self.application.bot, f"🧠 **إغلاق آلي | #{trade['id']} {symbol}**\nرصد الرجل الحكيم ضعفًا وقام بالخروج الفوري.")
                        else:
                            await safe_send_message(self.application.bot, f"💡 **نصيحة | #{trade['id']} {symbol}**\nتم رصد ضعف. يُنصح بالخروج اليدوي.")
                        continue

                    current_profit_pct = (df['close'].iloc[-1] / trade['entry_price'] - 1) * 100
                    adx_data = ta.adx(df['high'], df['low'], df['close'])
                    current_adx = adx_data['ADX_14'].iloc[-1] if adx_data is not None and not adx_data.empty else 0
                    if current_profit_pct > 3.0 and current_adx > 30:
                        new_tp = trade['take_profit'] * 1.05
                        await conn.execute("UPDATE trades SET take_profit = ? WHERE id = ?", (new_tp, trade['id']))
                        await safe_send_message(self.application.bot, f"🧠 **نصيحة | #{trade['id']} {symbol}**\nتم رصد زخم قوي. تم تمديد الهدف إلى ${new_tp:.4f}.")
                except Exception as e:
                    logger.error(f"Wise Man: Failed to analyze trade #{trade['id']}: {e}")
                await asyncio.sleep(1)
            await conn.commit()

    async def review_portfolio_risk(self, context: object = None):
        logger.info("🧠 Wise Man: Starting portfolio risk review...")
        try:
            balance = await self.exchange.fetch_balance()
            assets = {asset: data['total'] for asset, data in balance.items() if data.get('total', 0) > 0.00001 and asset != 'USDT'}
            if not assets: return

            asset_list = [f"{asset}/USDT" for asset in assets.keys()]
            tickers = await self.exchange.fetch_tickers(asset_list)

            usdt_total = balance.get('USDT', {}).get('total', 0.0)
            total_portfolio_value = usdt_total

            asset_values = {}
            for asset, amount in assets.items():
                symbol = f"{asset}/USDT"
                if symbol in tickers and tickers[symbol] and tickers[symbol]['last'] is not None:
                    value_usdt = amount * tickers[symbol]['last']
                    if value_usdt > 1.0:
                        asset_values[asset] = value_usdt
                        total_portfolio_value += value_usdt

            if total_portfolio_value < 1.0: return

            for asset, value in asset_values.items():
                concentration_pct = (value / total_portfolio_value) * 100
                if concentration_pct > 30.0:
                    await safe_send_message(self.application.bot, f"⚠️ **تنبيه | تركيز المخاطر**\nعملة `{asset}` تشكل **{concentration_pct:.1f}%** من المحفظة.")

            sector_values = defaultdict(float)
            for asset, value in asset_values.items():
                sector_values[SECTOR_MAP.get(asset, 'Other')] += value

            for sector, value in sector_values.items():
                concentration_pct = (value / total_portfolio_value) * 100
                if concentration_pct > 50.0:
                    await safe_send_message(self.application.bot, f"⚠️ **تنبيه | تركيز قطاعي**\nقطاع '{sector}' يشكل **{concentration_pct:.1f}%** من المحفظة.")
        except Exception as e:
            logger.error(f"Wise Man: Error during portfolio risk review: {e}", exc_info=True)


class EvolutionaryEngine:
    def __init__(self, exchange: ccxt.Exchange, application: Application):
        self.exchange = exchange
        self.application = application
        logger.info("🧬 Evolutionary Engine Initialized.")
        asyncio.create_task(self._init_journal_table())

    async def _init_journal_table(self):
        async with aiosqlite.connect(DB_FILE) as conn:
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS trade_journal (
                    id INTEGER PRIMARY KEY, trade_id INTEGER UNIQUE, entry_strategy TEXT,
                    exit_reason TEXT, pnl_usdt REAL, exit_quality_score INTEGER, notes TEXT
                )''')
            await conn.commit()

    async def add_trade_to_journal(self, trade_details: dict):
        trade_id = trade_details.get('id')
        logger.info(f"🧬 Journaling trade #{trade_id}...")
        try:
            async with aiosqlite.connect(DB_FILE) as conn:
                await conn.execute(
                    "INSERT OR IGNORE INTO trade_journal (trade_id, entry_strategy, exit_reason, pnl_usdt) VALUES (?, ?, ?, ?)",
                    (trade_id, trade_details.get('reason'), trade_details.get('status'), trade_details.get('pnl_usdt')))
                await conn.commit()
            asyncio.create_task(self._perform_what_if_analysis(trade_details))
        except Exception as e:
            logger.error(f"Smart Engine: Failed to journal trade #{trade_id}: {e}")

    async def _perform_what_if_analysis(self, trade_details: dict):
        trade_id, symbol = trade_details.get('id'), trade_details.get('symbol')
        exit_reason, original_tp = trade_details.get('status', ''), trade_details.get('take_profit')
        await asyncio.sleep(60)
        logger.info(f"🔬 Smart Engine: Performing 'What-If' analysis for closed trade #{trade_id}...")
        try:
            future_ohlcv = await self.exchange.fetch_ohlcv(symbol, '15m', limit=24)
            df_future = pd.DataFrame(future_ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            highest_price_after, lowest_price_after = df_future['high'].max(), df_future['low'].min()
            score, notes = 0, ""
            if 'SL' in exit_reason or 'فاشلة' in exit_reason:
                score, notes = (10, f"Good Save: Price dropped to {lowest_price_after}.") if highest_price_after < original_tp else (-10, f"Stop Loss Regret: Price hit original TP.")
            elif 'TP' in exit_reason or 'ناجحة' in exit_reason:
                missed_profit_pct = ((highest_price_after / original_tp) - 1) * 100
                score, notes = (10, "Perfect Exit.") if missed_profit_pct < 1.0 else (5, "Good Exit.") if missed_profit_pct < 5.0 else (-5, f"Missed Opportunity: +{missed_profit_pct:.2f}%.")
            
            async with aiosqlite.connect(DB_FILE) as conn:
                await conn.execute("UPDATE trade_journal SET exit_quality_score = ?, notes = ? WHERE trade_id = ?", (score, notes, trade_id))
                await conn.commit()
        except Exception as e:
            logger.error(f"Smart Engine: 'What-If' analysis failed for trade #{trade_id}: {e}")

    async def run_pattern_discovery(self, context: object = None):
        logger.info("🧬 Evolutionary Engine: Starting pattern discovery...")
        report_lines = ["🧠 **تقرير الذكاء الاستراتيجي** 🧠\n"]
        try:
            async with aiosqlite.connect(DB_FILE) as conn:
                journal_df = pd.read_sql_query("SELECT * FROM trade_journal WHERE notes IS NOT NULL", conn)
            if journal_df.empty or len(journal_df) < 5: return

            strategy_quality = journal_df.groupby('entry_strategy')['exit_quality_score'].mean().sort_values(ascending=False)
            report_lines.append("--- **أداء الاستراتيجيات (حسب جودة الخروج)** ---")
            for strategy, score in strategy_quality.items():
                if strategy: report_lines.append(f"- `{strategy.split(' (')[0]}`: **{score:+.2f}**")
            
            final_report = "\n".join(report_lines)
            await safe_send_message(self.application.bot, final_report)
        except Exception as e:
            logger.error(f"Smart Engine: Pattern discovery failed: {e}")

# =======================================================================================
# --- 🛠️ دوال مساعدة وإدارة 🛠️ ---
# =======================================================================================
def load_settings():
    try:
        if os.path.exists(SETTINGS_FILE):
            with open(SETTINGS_FILE, 'r') as f: bot_data.settings = json.load(f)
        else: bot_data.settings = copy.deepcopy(DEFAULT_SETTINGS)
    except Exception: bot_data.settings = copy.deepcopy(DEFAULT_SETTINGS)
    
    for key, value in DEFAULT_SETTINGS.items():
        if isinstance(value, dict):
            if key not in bot_data.settings or not isinstance(bot_data.settings[key], dict): bot_data.settings[key] = {}
            for sub_key, sub_value in value.items(): bot_data.settings[key].setdefault(sub_key, sub_value)
        else: bot_data.settings.setdefault(key, value)
    
    determine_active_preset(); save_settings()

def save_settings():
    with open(SETTINGS_FILE, 'w') as f: json.dump(bot_data.settings, f, indent=4)

def determine_active_preset():
    current_settings_for_compare = {k: v for k, v in bot_data.settings.items() if k in DEFAULT_SETTINGS}
    for name, preset_settings in SETTINGS_PRESETS.items():
        is_match = all(current_settings_for_compare.get(key) == value for key, value in preset_settings.items())
        if is_match:
            bot_data.active_preset_name = PRESET_NAMES_AR.get(name, "مخصص"); return
    bot_data.active_preset_name = "مخصص"

async def init_database():
    try:
        async with aiosqlite.connect(DB_FILE) as conn:
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS trades (
                    id INTEGER PRIMARY KEY, timestamp TEXT, symbol TEXT, entry_price REAL, take_profit REAL, stop_loss REAL,
                    quantity REAL, status TEXT, reason TEXT, order_id TEXT, highest_price REAL DEFAULT 0,
                    trailing_sl_active BOOLEAN DEFAULT 0, close_price REAL, pnl_usdt REAL,
                    last_profit_notification_price REAL DEFAULT 0, trade_weight REAL DEFAULT 1.0, close_retries INTEGER DEFAULT 0)
            ''')
            cursor = await conn.execute("PRAGMA table_info(trades)")
            columns = [row[1] for row in await cursor.fetchall()]
            if 'last_profit_notification_price' not in columns: await conn.execute("ALTER TABLE trades ADD COLUMN last_profit_notification_price REAL DEFAULT 0")
            if 'trade_weight' not in columns: await conn.execute("ALTER TABLE trades ADD COLUMN trade_weight REAL DEFAULT 1.0")
            if 'close_retries' not in columns: await conn.execute("ALTER TABLE trades ADD COLUMN close_retries INTEGER DEFAULT 0")
            await conn.commit()
        
        if bot_data.smart_engine:
            await bot_data.smart_engine._init_journal_table()
        logger.info("Database and Journal initialized successfully.")
    except Exception as e: logger.critical(f"Database initialization failed: {e}")

async def safe_send_message(bot, text, **kwargs):
    try: await bot.send_message(TELEGRAM_CHAT_ID, text, parse_mode=ParseMode.MARKDOWN, **kwargs)
    except Exception as e: logger.error(f"Telegram Send Error: {e}")

async def safe_edit_message(query, text, **kwargs):
    try: await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, **kwargs)
    except BadRequest as e:
        if "Message is not modified" not in str(e): logger.warning(f"Edit Message Error: {e}")
    except Exception as e: logger.error(f"Edit Message Error: {e}")

def find_col(df_columns, prefix):
    try: return next(col for col in df_columns if col.startswith(prefix))
    except StopIteration: return None

# =======================================================================================
# --- 🔬 تحليل السوق والماسحات 🔬 ---
# =======================================================================================
async def get_fear_and_greed_index():
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get("https://api.alternative.me/fng/?limit=1", timeout=10)
            return int(r.json()['data'][0]['value'])
    except Exception: return None

async def get_market_regime(exchange):
    try:
        ohlcv = await exchange.fetch_ohlcv('BTC/USDT', '1h', limit=100)
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        adx_data = ta.adx(df['high'], df['low'], df['close'])
        adx = adx_data[find_col(adx_data.columns, "ADX_")].iloc[-1] if not adx_data.empty else 0
        atr_data = ta.atr(df['high'], df['low'], df['close'])
        atr_percent = (atr_data.iloc[-1] / df['close'].iloc[-1]) * 100 if not atr_data.empty else 0
        trend = "TRENDING" if adx > 25 else "SIDEWAYS"
        vol = "HIGH_VOLATILITY" if atr_percent > 2.0 else "LOW_VOLATILITY"
        return f"{trend}_{vol}"
    except Exception as e:
        logger.error(f"Market Regime Analysis failed: {e}"); return "UNKNOWN"

async def get_market_mood(bot_data):
    settings = bot_data.settings
    btc_mood_text = "الفلتر معطل"

    if settings.get('btc_trend_filter_enabled', True):
        try:
            trend_filters = settings.get('trend_filters', {})
            htf_period = trend_filters.get('htf_period')
            if htf_period is None:
                logger.warning("BTC trend filter enabled, but 'htf_period' not defined. Assuming negative trend for safety.")
                return {"mood": "NEGATIVE", "reason": "إعدادات فلتر BTC غير مكتملة", "btc_mood": "خطأ إعدادات"}
            
            ohlcv = await bot_data.exchange.fetch_ohlcv('BTC/USDT', '4h', limit=htf_period + 5)
            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df['sma'] = ta.sma(df['close'], length=htf_period)
            is_btc_bullish = df['close'].iloc[-1] > df['sma'].iloc[-1]
            btc_mood_text = "صاعد ✅" if is_btc_bullish else "هابط ❌"
            if not is_btc_bullish:
                return {"mood": "NEGATIVE", "reason": "اتجاه BTC هابط", "btc_mood": btc_mood_text}
        except Exception as e:
            return {"mood": "DANGEROUS", "reason": f"فشل جلب بيانات BTC: {e}", "btc_mood": "UNKNOWN"}

    if settings.get('market_mood_filter_enabled', True):
        fng = await get_fear_and_greed_index()
        if fng is not None and fng < settings['fear_and_greed_threshold']:
            return {"mood": "NEGATIVE", "reason": f"مشاعر خوف شديد (F&G: {fng})", "btc_mood": btc_mood_text}

    return {"mood": "POSITIVE", "reason": "وضع السوق مناسب", "btc_mood": btc_mood_text}


def analyze_momentum_breakout(df, params, rvol, adx_value):
    df.ta.vwap(append=True); df.ta.bbands(length=20, append=True); df.ta.macd(append=True); df.ta.rsi(append=True)
    last, prev = df.iloc[-2], df.iloc[-3]
    macd_col, macds_col, bbu_col, rsi_col = find_col(df.columns, "MACD_"), find_col(df.columns, "MACDs_"), find_col(df.columns, "BBU_"), find_col(df.columns, "RSI_")
    if not all([macd_col, macds_col, bbu_col, rsi_col]): return None
    if (prev[macd_col] <= prev[macds_col] and last[macd_col] > last[macds_col] and last['close'] > last[bbu_col] and last['close'] > last["VWAP_D"] and last[rsi_col] < 68):
        return {"reason": "momentum_breakout"}
    return None

def analyze_breakout_squeeze_pro(df, params, rvol, adx_value):
    df.ta.bbands(length=20, append=True); df.ta.kc(length=20, scalar=1.5, append=True); df.ta.obv(append=True)
    bbu_col, bbl_col, kcu_col, kcl_col = find_col(df.columns, "BBU_"), find_col(df.columns, "BBL_"), find_col(df.columns, "KCUe_"), find_col(df.columns, "KCLEe_")
    if not all([bbu_col, bbl_col, kcu_col, kcl_col]): return None
    last, prev = df.iloc[-2], df.iloc[-3]
    is_in_squeeze = prev[bbl_col] > prev[kcl_col] and prev[bbu_col] < prev[kcu_col]
    if is_in_squeeze and (last['close'] > last[bbu_col]) and (last['volume'] > df['volume'].rolling(20).mean().iloc[-2] * 1.5) and (df['OBV'].iloc[-2] > df['OBV'].iloc[-3]):
        return {"reason": "breakout_squeeze_pro"}
    return None

async def analyze_support_rebound(df, params, rvol, adx_value, exchange, symbol):
    try:
        ohlcv_1h = await exchange.fetch_ohlcv(symbol, '1h', limit=100)
        if len(ohlcv_1h) < 50: return None
        df_1h = pd.DataFrame(ohlcv_1h, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        current_price = df_1h['close'].iloc[-1]
        
        recent_lows = df_1h['low'].rolling(window=20, center=True).min()
        supports = recent_lows[recent_lows.notna()]
        closest_support = max([s for s in supports if s < current_price], default=None)
        
        if not closest_support or ((current_price - closest_support) / closest_support * 100 > 1.0): return None
        
        last_candle_15m = df.iloc[-2]
        if last_candle_15m['close'] > last_candle_15m['open'] and last_candle_15m['volume'] > df['volume'].rolling(window=20).mean().iloc[-2] * 1.5:
            return {"reason": "support_rebound"}
    except Exception: return None
    return None

def analyze_sniper_pro(df, params, rvol, adx_value):
    try:
        compression_candles = 24
        if len(df) < compression_candles + 2: return None
        compression_df = df.iloc[-compression_candles-1:-1]
        highest_high, lowest_low = compression_df['high'].max(), compression_df['low'].min()
        if lowest_low <= 0: return None
        volatility = (highest_high - lowest_low) / lowest_low * 100
        
        if volatility < 12.0:
            last_candle = df.iloc[-2]
            if last_candle['close'] > highest_high and last_candle['volume'] > compression_df['volume'].mean() * 2:
                return {"reason": "sniper_pro"}
    except Exception: return None
    return None

def analyze_rsi_divergence(df, params, rvol, adx_value):
    if not SCIPY_AVAILABLE: return None
    df.ta.rsi(length=14, append=True)
    rsi_col = find_col(df.columns, f"RSI_14")
    if not rsi_col or df[rsi_col].isnull().all(): return None
    
    subset = df.iloc[-35:].copy()
    price_troughs_idx, _ = find_peaks(-subset['low'], distance=5)
    rsi_troughs_idx, _ = find_peaks(-subset[rsi_col], distance=5)
    
    if len(price_troughs_idx) >= 2 and len(rsi_troughs_idx) >= 2:
        p_low1_idx, p_low2_idx = price_troughs_idx[-2], price_troughs_idx[-1]
        r_low1_idx, r_low2_idx = rsi_troughs_idx[-2], rsi_troughs_idx[-1]
        
        is_divergence = (subset.iloc[p_low2_idx]['low'] < subset.iloc[p_low1_idx]['low'] and subset.iloc[r_low2_idx][rsi_col] > subset.iloc[r_low1_idx][rsi_col])
        
        if is_divergence:
            confirmation_price = subset.iloc[p_low2_idx:]['high'].max()
            price_confirmed = df.iloc[-2]['close'] > confirmation_price
            if price_confirmed:
                return {"reason": "rsi_divergence"}
    return None

def analyze_supertrend_pullback(df, params, rvol, adx_value):
    df.ta.supertrend(length=10, multiplier=3.0, append=True)
    st_dir_col = find_col(df.columns, f"SUPERTd_10_3.0")
    
    if not st_dir_col: return None
    last, prev = df.iloc[-2], df.iloc[-3]
    
    if prev[st_dir_col] == -1 and last[st_dir_col] == 1:
        recent_swing_high = df['high'].iloc[-10:-2].max()
        if last['close'] > recent_swing_high:
            return {"reason": "supertrend_pullback"}
    return None

def analyze_bollinger_reversal(df, params, rvol, adx_value):
    df.ta.bbands(length=20, append=True)
    df.ta.rsi(append=True)
    bbl_col, bbm_col = find_col(df.columns, "BBL_20_2.0"), find_col(df.columns, "BBM_20_2.0")
    rsi_col = find_col(df.columns, "RSI_14")
    
    if not all([bbl_col, bbm_col, rsi_col]): return None
    last, prev = df.iloc[-2], df.iloc[-3]
    
    if prev['close'] < prev[bbl_col] and last['close'] > last[bbl_col] and last['close'] < last[bbm_col] and last[rsi_col] < 35:
        return {"reason": "bollinger_reversal"}
    return None

SCANNERS = {
    "momentum_breakout": analyze_momentum_breakout,
    "breakout_squeeze_pro": analyze_breakout_squeeze_pro,
    "support_rebound": analyze_support_rebound,
    "sniper_pro": analyze_sniper_pro,
    "rsi_divergence": analyze_rsi_divergence,
    "supertrend_pullback": analyze_supertrend_pullback,
    "bollinger_reversal": analyze_bollinger_reversal,
}

# =======================================================================================
# --- 🛡️ حارس التداول ومدير WebSocket 🛡️ ---
# =======================================================================================
class UnifiedWebSocketManager:
    def __init__(self, exchange, application):
        self.exchange = exchange
        self.application = application
        self.public_ws_url = "wss://ws.okx.com:8443/ws/v5/public"
        self.private_ws_url = "wss://ws.okx.com:8443/ws/v5/private"
        self.public_subscriptions = set()
        self.public_ws = None
        self.private_ws = None
        self.trade_guardian = TradeGuardian(application)
        self.is_running = False

    async def _public_loop(self):
        while self.is_running:
            try:
                async with websockets.connect(self.public_ws_url, ping_interval=20, ping_timeout=20) as ws:
                    self.public_ws = ws
                    logger.info("✅ [Public WS] Connected.")
                    if self.public_subscriptions:
                        await self._send_public_op('subscribe', list(self.public_subscriptions))
                    async for msg in ws:
                        if msg == 'ping': await ws.send('pong'); continue
                        data = json.loads(msg)
                        if data.get('arg', {}).get('channel') == 'tickers' and 'data' in data:
                            for ticker in data['data']:
                                standard_ticker = {'symbol': ticker['instId'].replace('-', '/'), 'price': float(ticker['last'])}
                                await self.trade_guardian.handle_ticker_update(standard_ticker)
            except (websockets.exceptions.ConnectionClosed, Exception) as e:
                logger.warning(f"[Public WS] Connection lost: {e}. Reconnecting in 5s...")
                await asyncio.sleep(5)

    async def _private_loop(self):
        while self.is_running:
            try:
                async with websockets.connect(self.private_ws_url, ping_interval=20, ping_timeout=20) as ws:
                    self.private_ws = ws
                    logger.info("✅ [Private WS] Connected.")
                    timestamp = str(time.time())
                    message = timestamp + 'GET' + '/users/self/verify'
                    mac = hmac.new(bytes(OKX_API_SECRET, 'utf8'), bytes(message, 'utf8'), 'sha256')
                    sign = base64.b64encode(mac.digest()).decode()
                    auth_args = [{"apiKey": OKX_API_KEY, "passphrase": OKX_API_PASSPHRSE, "timestamp": timestamp, "sign": sign}]
                    await ws.send(json.dumps({"op": "login", "args": auth_args}))
                    login_response = json.loads(await ws.recv())
                    if login_response.get('code') != '0':
                        raise ConnectionAbortedError(f"Private WS Auth failed: {login_response}")
                    
                    logger.info("🔐 [Private WS] Authenticated.")
                    await ws.send(json.dumps({"op": "subscribe", "args": [{"channel": "orders", "instType": "SPOT"}]}))
                    
                    async for msg in ws:
                        if msg == 'ping': await ws.send('pong'); continue
                        data = json.loads(msg)
                        if data.get('arg', {}).get('channel') == 'orders' and 'data' in data:
                            for order in data.get('data', []):
                                if order.get('state') == 'filled' and order.get('side') == 'buy':
                                    await self.trade_guardian.activate_trade(order['ordId'], order['instId'].replace('-', '/'))
            except (websockets.exceptions.ConnectionClosed, Exception) as e:
                logger.warning(f"[Private WS] Connection lost: {e}. Reconnecting in 5s...")
                await asyncio.sleep(5)

    async def run(self):
        self.is_running = True
        asyncio.create_task(self._public_loop())
        asyncio.create_task(self._private_loop())

    async def _send_public_op(self, op, symbols):
        if not symbols or not self.public_ws or self.public_ws.closed: return
        try:
            payload = json.dumps({"op": op, "args": [{"channel": "tickers", "instId": s.replace('/', '-')} for s in symbols]})
            await self.public_ws.send(payload)
        except websockets.exceptions.ConnectionClosed: logger.warning(f"Could not send '{op}' op; public ws is closed.")

    async def subscribe(self, symbols):
        new = [s for s in symbols if s not in self.public_subscriptions]
        if new:
            self.public_subscriptions.update(new)
            await self._send_public_op('subscribe', new)
            logger.info(f"👁️ [Guardian] Now watching: {new}")

    async def unsubscribe(self, symbols):
        old = [s for s in symbols if s in self.public_subscriptions]
        if old:
            [self.public_subscriptions.discard(s) for s in old]
            await self._send_public_op('unsubscribe', old)
            logger.info(f"👁️ [Guardian] Stopped watching: {old}")

    async def sync_subscriptions(self):
        try:
            async with aiosqlite.connect(DB_FILE) as conn:
                cursor = await conn.execute("SELECT DISTINCT symbol FROM trades WHERE status = 'active'")
                active_symbols = [row[0] for row in await cursor.fetchall()]
            if active_symbols:
                logger.info(f"Guardian Sync: Subscribing to {len(active_symbols)} active trades.")
                await self.subscribe(active_symbols)
        except Exception as e:
            logger.error(f"Guardian Sync Error: {e}")


class TradeGuardian:
    def __init__(self, application: Application):
        self.application = application

    async def activate_trade(self, order_id, symbol):
        try:
            order_details = await bot_data.exchange.fetch_order(order_id, symbol)
            filled_price, net_filled_quantity = order_details.get('average', 0.0), order_details.get('filled', 0.0)
            if net_filled_quantity <= 0 or filled_price <= 0: return
        except Exception as e: logger.error(f"Could not fetch data for trade activation: {e}"); return

        async with aiosqlite.connect(DB_FILE) as conn:
            conn.row_factory = aiosqlite.Row
            trade = await (await conn.execute("SELECT * FROM trades WHERE order_id = ? AND status = 'pending'", (order_id,))).fetchone()
            if not trade: return
            
            trade = dict(trade)
            risk = filled_price - trade['stop_loss']
            new_take_profit = filled_price + (risk * bot_data.settings['risk_reward_ratio'])
            
            await conn.execute("UPDATE trades SET status = 'active', entry_price = ?, quantity = ?, take_profit = ? WHERE id = ?", (filled_price, net_filled_quantity, new_take_profit, trade['id']))
            await conn.commit()

        await bot_data.websocket_manager.subscribe([symbol])

        reasons_ar = ' + '.join([STRATEGY_NAMES_AR.get(r.strip(), r.strip()) for r in trade['reason'].split(' + ')])
        success_msg = (f"✅ **تم تأكيد الشراء | {symbol}**\n"
                       f"**الاستراتيجية:** {reasons_ar}\n"
                       f"**سعر التنفيذ:** `${filled_price:,.4f}`\n"
                       f"**الهدف (TP):** `${new_take_profit:,.4f}`\n"
                       f"**الوقف (SL):** `${trade['stop_loss']:,.4f}`")
        await safe_send_message(self.application.bot, success_msg)


    async def handle_ticker_update(self, standard_ticker: dict):
        async with trade_management_lock:
            symbol, current_price = standard_ticker['symbol'], standard_ticker['price']
            try:
                async with aiosqlite.connect(DB_FILE) as conn:
                    conn.row_factory = aiosqlite.Row
                    trade = await (await conn.execute("SELECT * FROM trades WHERE symbol = ? AND status IN ('active', 'force_exit', 'retry_exit')", (symbol,))).fetchone()
                    if not trade: return
                    
                    trade = dict(trade)
                    settings = bot_data.settings
                    
                    should_close, close_reason = False, ""
                    
                    if trade['status'] == 'force_exit':
                        should_close, close_reason = True, "فاشلة (بأمر الرجل الحكيم)"
                    elif trade['status'] == 'retry_exit':
                        should_close, close_reason = True, "إغلاق (إعادة محاولة)"
                    elif current_price <= trade['stop_loss']:
                        should_close, close_reason = True, "فاشلة (TSL)" if trade.get('trailing_sl_active') else "فاشلة (SL)"
                    elif settings.get('momentum_scalp_mode_enabled', False) and current_price >= trade['entry_price'] * (1 + settings.get('momentum_scalp_target_percent', 0.5) / 100):
                        should_close, close_reason = True, "ناجحة (Scalp Mode)"
                    elif current_price >= trade['take_profit']:
                        should_close, close_reason = True, "ناجحة (TP)"

                    if should_close:
                        await self._close_trade(trade, close_reason, current_price)
                        return

                    highest_price = max(trade.get('highest_price', 0), current_price)
                    if highest_price > trade.get('highest_price', 0):
                        await conn.execute("UPDATE trades SET highest_price = ? WHERE id = ?", (highest_price, trade['id']))
                    
                    if settings.get('trailing_sl_enabled'):
                        if not trade.get('trailing_sl_active') and current_price >= trade['entry_price'] * (1 + settings['trailing_sl_activation_percent'] / 100):
                            new_sl = trade['entry_price'] * 1.001
                            if new_sl > trade['stop_loss']:
                                await conn.execute("UPDATE trades SET trailing_sl_active = 1, stop_loss = ? WHERE id = ?", (new_sl, trade['id']))
                                await safe_send_message(self.application.bot, f"🚀 **تأمين | #{trade['id']} {symbol}**\nتم رفع الوقف إلى: `${new_sl:.4f}`")
                        
                        if trade.get('trailing_sl_active'):
                            new_sl_candidate = highest_price * (1 - settings['trailing_sl_callback_percent'] / 100)
                            if new_sl_candidate > trade['stop_loss']:
                                await conn.execute("UPDATE trades SET stop_loss = ? WHERE id = ?", (new_sl_candidate, trade['id']))

                    if settings.get('incremental_notifications_enabled'):
                        last_notified = trade.get('last_profit_notification_price', trade['entry_price'])
                        increment = settings.get('incremental_notification_percent', 2.0) / 100
                        if current_price >= last_notified * (1 + increment):
                            profit_percent = ((current_price / trade['entry_price']) - 1) * 100
                            await safe_send_message(self.application.bot, f"📈 **ربح | #{trade['id']} {symbol}**: `{profit_percent:+.2f}%`")
                            await conn.execute("UPDATE trades SET last_profit_notification_price = ? WHERE id = ?", (current_price, trade['id']))
                            
                    await conn.commit()
            except Exception as e:
                logger.error(f"Guardian Ticker Error for {symbol}: {e}", exc_info=True)

    async def _close_trade(self, trade, reason, close_price):
        symbol, trade_id = trade['symbol'], trade['id']
        try:
            async with aiosqlite.connect(DB_FILE) as conn:
                cursor = await conn.execute("UPDATE trades SET status = 'closing' WHERE id = ? AND status IN ('active', 'force_exit', 'retry_exit')", (trade_id,))
                await conn.commit()
                if cursor.rowcount == 0:
                    logger.warning(f"Closure for trade #{trade_id} ignored; not in a closable state.")
                    return
            
            logger.info(f"Guardian: Initiating ULTIMATE robust closure for trade #{trade_id}. Reason: {reason}")
            
            base_currency = symbol.split('/')[0]
            balance = await bot_data.exchange.fetch_balance()
            available_quantity = balance.get(base_currency, {}).get('free', 0.0)

            if available_quantity <= 0.00000001: raise Exception(f"No available balance for {base_currency}.")

            quantity_to_sell = float(bot_data.exchange.amount_to_precision(symbol, available_quantity))
            
            market = bot_data.exchange.market(symbol)
            min_notional = float(market.get('limits', {}).get('cost', {}).get('min', 5.1))
            if (quantity_to_sell * close_price) < min_notional:
                 raise Exception(f"Final quantity value ({quantity_to_sell * close_price}) is below MIN_NOTIONAL ({min_notional}).")

            await bot_data.exchange.create_market_sell_order(symbol, quantity_to_sell, params={'tdMode': 'cash'})

            pnl = (close_price - trade['entry_price']) * trade['quantity']
            pnl_percent = (close_price / trade['entry_price'] - 1) * 100 if trade['entry_price'] > 0 else 0
            
            async with aiosqlite.connect(DB_FILE) as conn:
                await conn.execute("UPDATE trades SET status = ?, close_price = ?, pnl_usdt = ? WHERE id = ?", (reason, close_price, pnl, trade_id))
                await conn.commit()
            
            await bot_data.websocket_manager.unsubscribe([symbol])

            final_message = (f"**{'✅' if pnl >= 0 else '🛑'} تم إغلاق الصفقة | #{trade_id}**\n\n"
                             f"▫️ *العملة:* `{symbol}` | *السبب:* `{reason}`\n"
                             f"💰 *الربح/الخسارة:* `${pnl:,.2f}` **({pnl_percent:,.2f}%)**")
            await safe_send_message(self.application.bot, final_message)
            
            if bot_data.smart_engine:
                final_trade_details = dict(trade); final_trade_details.update({'status': reason, 'close_price': close_price, 'pnl_usdt': pnl})
                await bot_data.smart_engine.add_trade_to_journal(final_trade_details)

        except Exception as e:
            logger.critical(f"ULTIMATE closure for #{trade_id} failed. MOVING TO RETRY: {e}", exc_info=True)
            async with aiosqlite.connect(DB_FILE) as conn:
                await conn.execute("UPDATE trades SET status = 'retry_exit' WHERE id = ?", (trade_id,))
                await conn.commit()
            await safe_send_message(self.application.bot, f"⚠️ **فشل الإغلاق | #{trade_id} {symbol}**\nستتم إعادة المحاولة تلقائيًا.")

# =======================================================================================
# --- ⚡ منطق الفحص وبدء التداول ⚡ ---
# =======================================================================================
async def get_okx_markets():
    settings = bot_data.settings
    if time.time() - bot_data.last_markets_fetch > 300:
        try:
            logger.info("Force reloading and caching all OKX markets...")
            all_markets_data = await bot_data.exchange.load_markets(True)
            bot_data.all_markets = [m for s, m in all_markets_data.items() if m.get('spot', False) and m.get('quote', '') == 'USDT' and m.get('active', True)]
            bot_data.last_markets_fetch = time.time()
        except Exception as e:
            logger.error(f"CRITICAL: Failed to load markets structure from OKX: {e}", exc_info=True)
            return []

    if not bot_data.all_markets: return []
    
    symbols_to_fetch = [m['symbol'] for m in bot_data.all_markets]
    try:
        tickers = await bot_data.exchange.fetch_tickers(symbols_to_fetch)
    except Exception as e:
        logger.error(f"Failed to fetch tickers for volume check: {e}"); return []

    valid_markets = []
    blacklist = settings.get('asset_blacklist', [])
    min_volume = settings.get('liquidity_filters', {}).get('min_quote_volume_24h_usd', 1000000)

    for market in bot_data.all_markets:
        ticker_data = tickers.get(market['symbol'])
        if not ticker_data or ticker_data.get('quoteVolume') is None: continue
        if market.get('base', '') in blacklist: continue
        if ticker_data['quoteVolume'] < min_volume: continue
        if any(k in market['symbol'] for k in ['-SWAP', 'UP', 'DOWN', '3L', '3S']): continue
        valid_markets.append(ticker_data)

    valid_markets.sort(key=lambda m: m.get('quoteVolume', 0), reverse=True)
    return valid_markets[:settings.get('top_n_symbols_by_volume', 300)]

async def worker_batch(queue, signals_list, errors_list):
    settings, exchange = bot_data.settings, bot_data.exchange
    while not queue.empty():
        try:
            item = await queue.get()
            symbol = item['market']['symbol']
            df = pd.DataFrame(item['ohlcv'], columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            if len(df) < 50: queue.task_done(); continue
            
            if settings.get('multi_timeframe_confluence_enabled', True):
                try:
                    ohlcv_1h = await exchange.fetch_ohlcv(symbol, '1h', limit=55)
                    df_1h = pd.DataFrame(ohlcv_1h, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                    df_1h.ta.macd(append=True); df_1h.ta.sma(length=50, append=True)
                    macd_col, sma_col = find_col(df_1h.columns, "MACD_"), find_col(df_1h.columns, "SMA_50")
                    if macd_col and sma_col and (df_1h[macd_col].iloc[-1] <= 0 or df_1h['close'].iloc[-1] <= df_1h[sma_col].iloc[-1]):
                        queue.task_done(); continue
                except Exception: pass
            
            # ... (باقي الفلاتر: ATR, Volume, ADX, etc.)
            
            confirmed_reasons = []
            for name in settings['active_scanners']:
                if not (strategy_func := SCANNERS.get(name)): continue
                func_args = {'df': df.copy(), 'params': {}, 'rvol': 0, 'adx_value': 0}
                if name == 'support_rebound': func_args.update({'exchange': exchange, 'symbol': symbol})
                
                result = await strategy_func(**func_args) if asyncio.iscoroutinefunction(strategy_func) else strategy_func(**{k:v for k,v in func_args.items() if k not in ['exchange', 'symbol']})
                if result: confirmed_reasons.append(result['reason'])
            
            if confirmed_reasons:
                reason_str = ' + '.join(set(confirmed_reasons))
                entry_price = df.iloc[-2]['close']
                df.ta.atr(length=14, append=True)
                atr_col = find_col(df.columns, "ATRr_")
                risk = df[atr_col].iloc[-2] * settings['atr_sl_multiplier'] if atr_col else entry_price * 0.02
                stop_loss, take_profit = entry_price - risk, entry_price + (risk * settings['risk_reward_ratio'])
                signals_list.append({"symbol": symbol, "entry_price": entry_price, "take_profit": take_profit, "stop_loss": stop_loss, "reason": reason_str})
            
            queue.task_done()
        except Exception as e:
            if 'symbol' in locals(): errors_list.append(symbol)
            if not queue.empty(): queue.task_done()

async def initiate_real_trade(signal):
    if not bot_data.trading_enabled: return False
    try:
        settings, exchange = bot_data.settings, bot_data.exchange
        trade_size = settings['real_trade_size_usdt'] * signal.get('weight', 1.0)
        
        market = exchange.market(signal['symbol'])
        min_notional = float(market.get('limits', {}).get('cost', {}).get('min', 5.1))
        if trade_size < min_notional:
            logger.warning(f"Trade for {signal['symbol']} aborted. Size ({trade_size:.2f}) is below MIN_NOTIONAL ({min_notional}).")
            return False

        balance = await exchange.fetch_balance()
        if balance.get('USDT', {}).get('free', 0.0) < trade_size: return False

        base_amount = trade_size / signal['entry_price']
        formatted_amount = exchange.amount_to_precision(signal['symbol'], base_amount)
        
        buy_order = await exchange.create_market_buy_order(signal['symbol'], formatted_amount, params={'tdMode': 'cash'})
        
        async with aiosqlite.connect(DB_FILE) as conn:
            await conn.execute("INSERT INTO trades (timestamp, symbol, reason, order_id, status, entry_price, take_profit, stop_loss) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                               (datetime.now(EGYPT_TZ).isoformat(), signal['symbol'], signal['reason'], buy_order['id'], 'pending', signal['entry_price'], signal['take_profit'], signal['stop_loss']))
            await conn.commit()
        await safe_send_message(bot_data.application.bot, f"🚀 تم إرسال أمر شراء لـ `{signal['symbol']}`.")
        return True

    except Exception as e:
        logger.error(f"REAL TRADE FAILED {signal['symbol']}: {e}", exc_info=True)
        return False


async def perform_scan(context: ContextTypes.DEFAULT_TYPE):
    async with scan_lock:
        if not bot_data.trading_enabled: return
        scan_start_time = time.time()
        
        bot_data.market_mood = await get_market_mood(bot_data)
        if bot_data.market_mood["mood"] != "POSITIVE":
            logger.warning(f"Scan skipped: Market mood is {bot_data.market_mood['mood']}. Reason: {bot_data.market_mood['reason']}")
            return

        async with aiosqlite.connect(DB_FILE) as conn:
            active_trades_count = (await (await conn.execute("SELECT COUNT(*) FROM trades WHERE status IN ('active', 'pending')")).fetchone())[0]
        
        if active_trades_count >= bot_data.settings['max_concurrent_trades']: return

        top_markets = await get_okx_markets()
        if not top_markets: return

        ohlcv_data = await asyncio.gather(*[bot_data.exchange.fetch_ohlcv(m['symbol'], TIMEFRAME, limit=100) for m in top_markets], return_exceptions=True)
        
        queue, signals_found, analysis_errors = asyncio.Queue(), [], []
        for i, market in enumerate(top_markets):
            if isinstance(ohlcv_data[i], list) and ohlcv_data[i]:
                await queue.put({'market': market, 'ohlcv': ohlcv_data[i]})

        worker_tasks = [asyncio.create_task(worker_batch(queue, signals_found, analysis_errors)) for _ in range(bot_data.settings.get("worker_threads", 10))]
        await queue.join()
        for task in worker_tasks: task.cancel()

        trades_opened_count = 0
        symbols_being_traded_this_scan = set()
        
        for signal in signals_found:
            if active_trades_count >= bot_data.settings['max_concurrent_trades']: break
            if signal['symbol'] in symbols_being_traded_this_scan: continue
            
            async with aiosqlite.connect(DB_FILE) as conn:
                existing = await (await conn.execute("SELECT 1 FROM trades WHERE symbol = ? AND status IN ('active', 'pending')", (signal['symbol'],))).fetchone()
            if existing: continue

            symbols_being_traded_this_scan.add(signal['symbol'])
            if await initiate_real_trade(signal):
                active_trades_count += 1
                trades_opened_count += 1
                await asyncio.sleep(2)

        duration = time.time() - scan_start_time
        bot_data.last_scan_info = {'duration_seconds': f"{duration:.2f}", 'checked_symbols': len(top_markets), 'found_signals': len(signals_found), 'opened_trades': trades_opened_count}
        logger.info(f"Scan finished in {duration:.2f}s. Found {len(signals_found)} signals, opened {trades_opened_count} trades.")
# =======================================================================================
# --- 🗓️ المهام المجدولة والوظائف الرئيسية 🗓️ ---
# =======================================================================================

async def supervisor_job(context: ContextTypes.DEFAULT_TYPE):
    logger.info("🕵️ Supervisor: Auditing trades...")
    async with aiosqlite.connect(DB_FILE) as conn:
        conn.row_factory = aiosqlite.Row
        
        stuck_threshold = (datetime.now(EGYPT_TZ) - timedelta(minutes=2)).isoformat()
        stuck_pending = await (await conn.execute("SELECT * FROM trades WHERE status = 'pending' AND timestamp < ?", (stuck_threshold,))).fetchall()
        
        for trade_data in stuck_pending:
            trade = dict(trade_data)
            try:
                order_status = await bot_data.exchange.fetch_order(trade['order_id'], trade['symbol'])
                if order_status['status'] == 'closed' and order_status.get('filled', 0) > 0:
                    await bot_data.websocket_manager.trade_guardian.activate_trade(trade['order_id'], trade['symbol'])
                elif order_status['status'] in ['canceled', 'expired']:
                    await conn.execute("DELETE FROM trades WHERE id = ?", (trade['id'],))
            except ccxt.OrderNotFound:
                await conn.execute("DELETE FROM trades WHERE id = ?", (trade['id'],))
            except Exception as e:
                logger.error(f"Supervisor error processing stuck trade #{trade['id']}: {e}")
        
        retry_trades = await (await conn.execute("SELECT * FROM trades WHERE status = 'retry_exit'")).fetchall()
        if retry_trades:
            symbols_to_resubscribe = [trade['symbol'] for trade in retry_trades]
            await bot_data.websocket_manager.subscribe(symbols_to_resubscribe)

        await conn.commit()

async def maestro_job(context: ContextTypes.DEFAULT_TYPE):
    if not bot_data.settings.get('maestro_mode_enabled', True): return
    logger.info("🎼 Maestro: Analyzing market regime...")
    regime = await get_market_regime(bot_data.exchange)
    bot_data.current_market_regime = regime
    
    if regime in DECISION_MATRIX:
        config = DECISION_MATRIX[regime]
        report_lines = [f"🎼 **تقرير المايسترو | {regime}**"]
        for key, value in config.items():
            if bot_data.settings.get(key) != value:
                bot_data.settings[key] = value
                report_lines.append(f"- تم تحديث `{key}` إلى `{value}`")
        if len(report_lines) > 1:
            save_settings()
            await safe_send_message(context.bot, "\n".join(report_lines))

# This is a placeholder for the logic from B-main's WiseMan (which we've put in the WiseMan class)
async def intelligent_reviewer_job(context: ContextTypes.DEFAULT_TYPE):
     if bot_data.wise_man and bot_data.settings.get('intelligent_reviewer_enabled', True):
        await bot_data.wise_man.review_open_trades()


# =======================================================================================
# --- 🤖 Telegram UI & Bot Startup 🤖 ---
# =======================================================================================
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [["Dashboard 🖥️"], ["الإعدادات ⚙️"]]
    await update.message.reply_text("أهلاً بك في **قناص OKX | إصدار المايسترو متعدد الأوضاع**", reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True), parse_mode=ParseMode.MARKDOWN)

async def manual_scan_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not bot_data.trading_enabled: await (update.message or update.callback_query.message).reply_text("🔬 الفحص محظور. مفتاح الإيقاف مفعل."); return
    await (update.message or update.callback_query.message).reply_text("🔬 أمر فحص يدوي... قد يستغرق بعض الوقت.")
    context.job_queue.run_once(perform_scan, 1)

async def show_dashboard_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ks_status_emoji = "🚨" if not bot_data.trading_enabled else "✅"
    ks_status_text = "مفتاح الإيقاف (مفعل)" if not bot_data.trading_enabled else "الحالة (طبيعية)"
    keyboard = [
        [InlineKeyboardButton("💼 نظرة عامة على المحفظة", callback_data="db_portfolio"), InlineKeyboardButton("📈 الصفقات النشطة", callback_data="db_trades")],
        [InlineKeyboardButton("📜 سجل الصفقات المغلقة", callback_data="db_history"), InlineKeyboardButton("📊 الإحصائيات والأداء", callback_data="db_stats")],
        [InlineKeyboardButton("🌡️ تحليل مزاج السوق", callback_data="db_mood"), InlineKeyboardButton("🔬 فحص فوري", callback_data="db_manual_scan")],
        [InlineKeyboardButton("🗓️ التقرير اليومي", callback_data="db_daily_report")],
        [InlineKeyboardButton(f"{ks_status_emoji} {ks_status_text}", callback_data="kill_switch_toggle"), InlineKeyboardButton("🎼 التحكم الاستراتيجي", callback_data="db_maestro_control")],  # New: Maestro Button
        [InlineKeyboardButton("🕵️‍♂️ تقرير التشخيص", callback_data="db_diagnostics")]
    ]
    message_text = "🖥️ **لوحة تحكم قناص OKX**\n\nاختر نوع التقرير الذي تريد عرضه:"
    if not bot_data.trading_enabled: message_text += "\n\n**تحذير: تم تفعيل مفتاح الإيقاف.**"
    target_message = update.message or update.callback_query.message
    if update.callback_query: await safe_edit_message(update.callback_query, message_text, reply_markup=InlineKeyboardMarkup(keyboard))
    else: await target_message.reply_text(message_text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(keyboard))

# New: Task 6 - Maestro Control Panel
async def show_maestro_control(update: Update, context: ContextTypes.DEFAULT_TYPE):
    s = bot_data.settings
    regime = bot_data.current_market_regime
    maestro_enabled = s.get('maestro_mode_enabled', True)
    emoji = "✅" if maestro_enabled else "❌"
    active_scanners_str = ' + '.join([STRATEGY_NAMES_AR.get(scanner, scanner) for scanner in s.get('active_scanners', [])])
    message = (f"🎼 **لوحة التحكم الاستراتيجي (المايسترو)**\n"
               f"━━━━━━━━━━━━━━━━━━\n"
               f"**حالة المايسترو:** {emoji} مفعل\n"
               f"**تشخيص السوق الحالي:** {regime}\n"
               f"**الاستراتيجيات النشطة:** {active_scanners_str}\n\n"
               f"**التكوين الحالي:**\n"
               f"  - **المراجع الذكي:** {'✅' if s.get('intelligent_reviewer_enabled') else '❌'}\n"
               f"  - **اقتناص الزخم:** {'✅' if s.get('momentum_scalp_mode_enabled') else '❌'}\n"
               f"  - **فلتر التوافق:** {'✅' if s.get('multi_timeframe_confluence_enabled') else '❌'}\n"
               f"  - **استراتيجية الانعكاس:** {'✅' if 'bollinger_reversal' in s.get('active_scanners', []) else '❌'}")
    keyboard = [
        [InlineKeyboardButton(f"🎼 تبديل المايسترو ({'تعطيل' if maestro_enabled else 'تفعيل'})", callback_data="maestro_toggle")],
        [InlineKeyboardButton("🔙 العودة للوحة التحكم", callback_data="back_to_dashboard")]
    ]
    await safe_edit_message(update.callback_query, message, reply_markup=InlineKeyboardMarkup(keyboard))

async def toggle_maestro(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bot_data.settings['maestro_mode_enabled'] = not bot_data.settings.get('maestro_mode_enabled', True)
    save_settings()
    await update.callback_query.answer(f"المايسترو {'تم تفعيله' if bot_data.settings['maestro_mode_enabled'] else 'تم تعطيله'}")
    await show_maestro_control(update, context)

async def send_daily_report(context: ContextTypes.DEFAULT_TYPE):
    today_str = datetime.now(EGYPT_TZ).strftime('%Y-%m-%d')
    logger.info(f"Generating daily report for {today_str}...")
    try:
        async with aiosqlite.connect(DB_FILE) as conn:
            conn.row_factory = aiosqlite.Row
            closed_today = await (await conn.execute("SELECT * FROM trades WHERE status LIKE '%(%' AND date(timestamp) = ?", (today_str,))).fetchall()
        if not closed_today:
            report_message = f"🗓️ **التقرير اليومي | {today_str}**\n━━━━━━━━━━━━━━━━━━\nلم يتم إغلاق أي صفقات اليوم."
        else:
            wins = [t for t in closed_today if 'ناجحة' in t['status'] or 'تأمين' in t['status']]
            losses = [t for t in closed_today if 'فاشلة' in t['status']]
            total_pnl = sum(t['pnl_usdt'] for t in closed_today if t['pnl_usdt'] is not None)
            win_rate = (len(wins) / len(closed_today) * 100) if closed_today else 0
            avg_win_pnl = sum(w['pnl_usdt'] for w in wins if w['pnl_usdt'] is not None) / len(wins) if wins else 0
            avg_loss_pnl = sum(l['pnl_usdt'] for l in losses if l['pnl_usdt'] is not None) / len(losses) if losses else 0
            avg_pnl = total_pnl / len(closed_today) if closed_today else 0
            best_trade = max(closed_today, key=lambda t: t.get('pnl_usdt', -float('inf')), default=None)
            worst_trade = min(closed_today, key=lambda t: t.get('pnl_usdt', float('inf')), default=None)
            strategy_counter = Counter(r for t in closed_today for r in t['reason'].split(' + '))
            most_active_strategy_en = strategy_counter.most_common(1)[0][0] if strategy_counter else "N/A"
            most_active_strategy_ar = STRATEGY_NAMES_AR.get(most_active_strategy_en.split(' ')[0], most_active_strategy_en)

            report_message = (
                f"🗓️ **التقرير اليومي | {today_str}**\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"📈 **الأداء الرئيسي**\n"
                f"**الربح/الخسارة الصافي:** `${total_pnl:+.2f}`\n"
                f"**معدل النجاح:** {win_rate:.1f}%\n"
                f"**متوسط الربح:** `${avg_win_pnl:+.2f}`\n"
                f"**متوسط الخسارة:** `${avg_loss_pnl:+.2f}`\n"
                f"**الربح/الخسارة لكل صفقة:** `${avg_pnl:+.2f}`\n"
                f"📊 **تحليل الصفقات**\n"
                f"**عدد الصفقات:** {len(closed_today)}\n"
                f"**أفضل صفقة:** `{best_trade['symbol']}` | `${best_trade['pnl_usdt']:+.2f}`\n"
                f"**أسوأ صفقة:** `{worst_trade['symbol']}` | `${worst_trade['pnl_usdt']:+.2f}`\n"
                f"**الاستراتيجية الأنشط:** {most_active_strategy_ar}\n"
            )

        await safe_send_message(context.bot, report_message)
    except Exception as e: logger.error(f"Failed to generate daily report: {e}", exc_info=True)

async def daily_report_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await (update.message or update.callback_query.message).reply_text("⏳ جاري إرسال التقرير اليومي...")
    await send_daily_report(context)

async def toggle_kill_switch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; bot_data.trading_enabled = not bot_data.trading_enabled
    if bot_data.trading_enabled: await query.answer("✅ تم استئناف التداول الطبيعي."); await safe_send_message(context.bot, "✅ **تم استئناف التداول الطبيعي.**")
    else: await query.answer("🚨 تم تفعيل مفتاح الإيقاف!", show_alert=True); await safe_send_message(context.bot, "🚨 **تحذير: تم تفعيل مفتاح الإيقاف!**")
    await show_dashboard_command(update, context)

async def show_trades_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    async with aiosqlite.connect(DB_FILE) as conn:
        conn.row_factory = aiosqlite.Row; trades = await (await conn.execute("SELECT id, symbol, status FROM trades WHERE status = 'active' OR status = 'pending' ORDER BY id DESC")).fetchall()
    if not trades:
        text = "لا توجد صفقات نشطة حاليًا."
        keyboard = [[InlineKeyboardButton("🔙 العودة للوحة التحكم", callback_data="back_to_dashboard")]]
        await safe_edit_message(update.callback_query, text, reply_markup=InlineKeyboardMarkup(keyboard)); return
    text = "📈 *الصفقات النشطة*\nاختر صفقة لعرض تفاصيلها:\n"; keyboard = []
    for trade in trades: status_emoji = "✅" if trade['status'] == 'active' else "⏳"; button_text = f"#{trade['id']} {status_emoji} | {trade['symbol']}"; keyboard.append([InlineKeyboardButton(button_text, callback_data=f"check_{trade['id']}")])
    keyboard.append([InlineKeyboardButton("🔄 تحديث", callback_data="db_trades")]); keyboard.append([InlineKeyboardButton("🔙 العودة للوحة التحكم", callback_data="back_to_dashboard")]); await safe_edit_message(update.callback_query, text, reply_markup=InlineKeyboardMarkup(keyboard))

async def check_trade_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    trade_id = int(query.data.split('_')[1])
    async with aiosqlite.connect(DB_FILE) as conn:
        conn.row_factory = aiosqlite.Row
        cursor = await conn.execute("SELECT * FROM trades WHERE id = ?", (trade_id,))
        trade = await cursor.fetchone()
    if not trade:
        await query.answer("لم يتم العثور على الصفقة."); return
    trade = dict(trade)
    if trade['status'] == 'pending':
        message = f"**⏳ حالة الصفقة #{trade_id}**\n- **العملة:** `{trade['symbol']}`\n- **الحالة:** في انتظار تأكيد التنفيذ..."
    else:
        try:
            ticker = await bot_data.exchange.fetch_ticker(trade['symbol'])
            current_price = ticker['last']
            pnl = (current_price - trade['entry_price']) * trade['quantity']
            pnl_percent = (current_price / trade['entry_price'] - 1) * 100 if trade['entry_price'] > 0 else 0
            pnl_text = f"💰 **الربح/الخسارة الحالية:** `${pnl:+.2f}` ({pnl_percent:+.2f}%)"
            current_price_text = f"- **السعر الحالي:** `${current_price}`"
        except Exception:
            pnl_text = "💰 تعذر جلب الربح/الخسارة الحالية."
            current_price_text = "- **السعر الحالي:** `تعذر الجلب`"

        message = (
            f"**✅ حالة الصفقة #{trade_id}**\n\n"
            f"- **العملة:** `{trade['symbol']}`\n"
            f"- **سعر الدخول:** `${trade['entry_price']}`\n"
            f"{current_price_text}\n"
            f"- **الكمية:** `{trade['quantity']}`\n"
            f"----------------------------------\n"
            f"- **الهدف (TP):** `${trade['take_profit']}`\n"
            f"- **الوقف (SL):** `${trade['stop_loss']}`\n"
            f"----------------------------------\n"
            f"{pnl_text}"
        )
    await safe_edit_message(query, message, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة للصفقات", callback_data="db_trades")]]))

async def show_mood_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("جاري تحليل مزاج السوق...")
    fng_task = asyncio.create_task(get_fear_and_greed_index())
    headlines_task = asyncio.create_task(asyncio.to_thread(get_latest_crypto_news))
    mood_task = asyncio.create_task(get_market_mood())
    markets_task = asyncio.create_task(get_okx_markets())
    fng_index = await fng_task
    original_headlines = await headlines_task
    mood = await mood_task
    all_markets = await markets_task
    translated_headlines, translation_success = await translate_text_gemini(original_headlines)
    news_sentiment, _ = analyze_sentiment_of_headlines(original_headlines)
    top_gainers, top_losers = [], []
    if all_markets:
        sorted_by_change = sorted([m for m in all_markets if m.get('percentage') is not None], key=lambda m: m['percentage'], reverse=True)
        top_gainers = sorted_by_change[:3]
        top_losers = sorted_by_change[-3:]
    verdict = "الحالة العامة للسوق تتطلب الحذر."
    if mood['mood'] == 'POSITIVE': verdict = "المؤشرات الفنية إيجابية، مما قد يدعم فرص الشراء."
    if fng_index and fng_index > 65: verdict = "المؤشرات الفنية إيجابية ولكن مع وجود طمع في السوق، يرجى الحذر من التقلبات."
    elif fng_index and fng_index < 30: verdict = "يسود الخوف على السوق، قد تكون هناك فرص للمدى الطويل ولكن المخاطرة عالية حالياً."
    gainers_str = "\n".join([f"  `{g['symbol']}` `({g.get('percentage', 0):+.2f}%)`" for g in top_gainers]) or "  لا توجد بيانات."
    losers_str = "\n".join([f"  `{l['symbol']}` `({l.get('percentage', 0):+.2f}%)`" for l in reversed(top_losers)]) or "  لا توجد بيانات."
    news_header = "📰 آخر الأخبار (مترجمة آلياً):" if translation_success else "📰 آخر الأخبار (الترجمة غير متاحة):"
    news_str = "\n".join([f"  - _{h}_" for h in translated_headlines]) or "  لا توجد أخبار."
    message = (
        f"**🌡️ تحليل مزاج السوق الشامل**\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"**⚫️ الخلاصة:** *{verdict}*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"**📊 المؤشرات الرئيسية:**\n"
        f"  - **اتجاه BTC العام:** {mood.get('btc_mood', 'N/A')}\n"
        f"  - **الخوف والطمع:** {fng_index or 'N/A'}\n"
        f"  - **مشاعر الأخبار:** {news_sentiment}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"**🚀 أبرز الرابحين:**\n{gainers_str}\n\n"
        f"**📉 أبرز الخاسرين:**\n{losers_str}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"{news_header}\n{news_str}\n"
    )
    keyboard = [[InlineKeyboardButton("🔄 تحديث", callback_data="db_mood")], [InlineKeyboardButton("🔙 العودة للوحة التحكم", callback_data="back_to_dashboard")]]
    await safe_edit_message(query, message, reply_markup=InlineKeyboardMarkup(keyboard))

async def show_strategy_report_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not bot_data.strategy_performance:
        await safe_edit_message(update.callback_query, "لا توجد بيانات أداء حاليًا. يرجى الانتظار بعد إغلاق بعض الصفقات.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة للإحصائيات", callback_data="db_stats")]]))
        return
    
    report = ["**📜 تقرير أداء الاستراتيجيات**\n(بناءً على آخر 100 صفقة)"]
    sorted_strategies = sorted(bot_data.strategy_performance.items(), key=lambda item: item[1]['total_trades'], reverse=True)

    for r, s in sorted_strategies:
        report.append(f"\n--- *{STRATEGY_NAMES_AR.get(r, r)}* ---\n"
                      f"  - **النجاح:** {s['win_rate']:.1f}% ({s['total_trades']} صفقة)\n"
                      f"  - **عامل الربح:** {s['profit_factor'] if s['profit_factor'] != float('inf') else '∞'}")

    await safe_edit_message(update.callback_query, "\n".join(report), reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📊 عرض الإحصائيات العامة", callback_data="db_stats")],[InlineKeyboardButton("🔙 العودة للوحة التحكم", callback_data="back_to_dashboard")]]))

async def show_stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    async with aiosqlite.connect(DB_FILE) as conn:
        conn.row_factory = aiosqlite.Row
        cursor = await conn.execute("SELECT pnl_usdt, status FROM trades WHERE status LIKE '%(%'")
        trades_data = await cursor.fetchall()
    if not trades_data:
        await safe_edit_message(update.callback_query, "لم يتم إغلاق أي صفقات بعد.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة للوحة التحكم", callback_data="back_to_dashboard")]]))
        return
    total_trades = len(trades_data)
    total_pnl = sum(t['pnl_usdt'] for t in trades_data if t['pnl_usdt'] is not None)
    wins_data = [t['pnl_usdt'] for t in trades_data if ('ناجحة' in t['status'] or 'تأمين' in t['status']) and t['pnl_usdt'] is not None]
    losses_data = [t['pnl_usdt'] for t in trades_data if 'فاشلة' in t['status'] and t['pnl_usdt'] is not None]
    win_count = len(wins_data)
    loss_count = len(losses_data)
    win_rate = (win_count / total_trades * 100) if total_trades > 0 else 0
    avg_win = sum(wins_data) / win_count if win_count > 0 else 0
    avg_loss = sum(losses_data) / loss_count if loss_count > 0 else 0
    profit_factor = sum(wins_data) / abs(sum(losses_data)) if sum(losses_data) != 0 else float('inf')
    message = (
        f"📊 **إحصائيات الأداء التفصيلية**\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"**إجمالي الربح/الخسارة:** `${total_pnl:+.2f}`\n"
        f"**متوسط الربح:** `${avg_win:+.2f}`\n"
        f"**متوسط الخسارة:** `${avg_loss:+.2f}`\n"
        f"**عامل الربح (Profit Factor):** `{profit_factor:,.2f}`\n"
        f"**معدل النجاح:** {win_rate:.1f}%\n"
        f"**إجمالي الصفقات:** {total_trades}"
    )
    await safe_edit_message(update.callback_query, message, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📜 تقرير أداء الاستراتيجيات", callback_data="db_strategy_report")],[InlineKeyboardButton("🔙 العودة للوحة التحكم", callback_data="back_to_dashboard")]]))


async def show_portfolio_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer("جاري جلب بيانات المحفظة...")
    try:
        balance = await bot_data.exchange.fetch_balance({'type': 'trading'})
        owned_assets = {asset: data['total'] for asset, data in balance.items() if isinstance(data, dict) and data.get('total', 0) > 0}
        usdt_balance = balance.get('USDT', {}); total_usdt_equity = usdt_balance.get('total', 0); free_usdt = usdt_balance.get('free', 0)
        assets_to_fetch = [f"{asset}/USDT" for asset in owned_assets if asset != 'USDT']
        tickers = {}
        if assets_to_fetch:
            try: tickers = await bot_data.exchange.fetch_tickers(assets_to_fetch)
            except Exception as e: logger.warning(f"Could not fetch all tickers for portfolio: {e}")
        asset_details = []; total_assets_value_usdt = 0
        for asset, total in owned_assets.items():
            if asset == 'USDT': continue
            symbol = f"{asset}/USDT"; value_usdt = 0
            if symbol in tickers and tickers[symbol] is not None: value_usdt = tickers[symbol].get('last', 0) * total
            total_assets_value_usdt += value_usdt
            if value_usdt >= 1.0: asset_details.append(f"  - `{asset}`: `{total:,.6f}` `(≈ ${value_usdt:,.2f})`")
        total_equity = total_usdt_equity + total_assets_value_usdt
        async with aiosqlite.connect(DB_FILE) as conn:
            cursor_pnl = await conn.execute("SELECT SUM(pnl_usdt) FROM trades WHERE status LIKE '%(%'")
            total_realized_pnl = (await cursor_pnl.fetchone())[0] or 0.0
            cursor_trades = await conn.execute("SELECT COUNT(*) FROM trades WHERE status = 'active'")
            active_trades_count = (await cursor_trades.fetchone())[0]
        assets_str = "\n".join(asset_details) if asset_details else "  لا توجد أصول أخرى بقيمة تزيد عن 1 دولار."
        message = (
            f"**💼 نظرة عامة على المحفظة**\n"
            f"🗓️ {datetime.now(EGYPT_TZ).strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"**💰 إجمالي قيمة المحفظة:** `≈ ${total_equity:,.2f}`\n"
            f"  - **السيولة المتاحة (USDT):** `${free_usdt:,.2f}`\n"
            f"  - **قيمة الأصول الأخرى:** `≈ ${total_assets_value_usdt:,.2f}`\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"**📊 تفاصيل الأصول (أكثر من 1$):**\n"
            f"{assets_str}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"**📈 أداء التداول:**\n"
            f"  - **الربح/الخسارة المحقق:** `${total_realized_pnl:,.2f}`\n"
            f"  - **عدد الصفقات النشطة:** {active_trades_count}\n"
        )
        keyboard = [[InlineKeyboardButton("🔄 تحديث", callback_data="db_portfolio")], [InlineKeyboardButton("🔙 العودة للوحة التحكم", callback_data="back_to_dashboard")]]
        await safe_edit_message(query, message, reply_markup=InlineKeyboardMarkup(keyboard))
    except Exception as e:
        logger.error(f"Portfolio fetch error: {e}", exc_info=True)
        await safe_edit_message(query, f"حدث خطأ أثناء جلب رصيد المحفظة: {e}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 العودة", callback_data="back_to_dashboard")]]))

async def show_trade_history_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    async with aiosqlite.connect(DB_FILE) as conn:
        conn.row_factory = aiosqlite.Row
        cursor = await conn.execute("SELECT symbol, pnl_usdt, status FROM trades WHERE status LIKE '%(%' ORDER BY id DESC LIMIT 10")
        closed_trades = await cursor.fetchall()
    if not closed_trades:
        text = "لم يتم إغلاق أي صفقات بعد."
        keyboard = [[InlineKeyboardButton("🔙 العودة للوحة التحكم", callback_data="back_to_dashboard")]]
        await safe_edit_message(update.callback_query, text, reply_markup=InlineKeyboardMarkup(keyboard))
        return
    history_list = ["📜 *آخر 10 صفقات مغلقة*"]
    for trade in closed_trades:
        emoji = "✅" if 'ناجحة' in trade['status'] or 'تأمين' in trade['status'] else "🛑"
        pnl = trade['pnl_usdt'] or 0.0
        history_list.append(f"{emoji} `{trade['symbol']}` | الربح/الخسارة: `${pnl:,.2f}`")
    text = "\n".join(history_list)
    keyboard = [[InlineKeyboardButton("🔙 العودة للوحة التحكم", callback_data="back_to_dashboard")]]
    await safe_edit_message(update.callback_query, text, reply_markup=InlineKeyboardMarkup(keyboard))

async def show_diagnostics_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; s = bot_data.settings
    scan_info = bot_data.last_scan_info
    determine_active_preset()
    nltk_status = "متاحة ✅" if NLTK_AVAILABLE else "غير متاحة ❌"
    scan_time = scan_info.get("start_time", "لم يتم بعد")
    scan_duration = f'{scan_info.get("duration_seconds", "N/A")} ثانية'
    scan_checked = scan_info.get("checked_symbols", "N/A")
    scan_errors = scan_info.get("analysis_errors", "N/A")
    scanners_list = "\n".join([f"  - {STRATEGY_NAMES_AR.get(key, key)}" for key in s['active_scanners']])
    scan_job = context.job_queue.get_jobs_by_name("perform_scan")
    next_scan_time = scan_job[0].next_t.astimezone(EGYPT_TZ).strftime('%H:%M:%S') if scan_job and scan_job[0].next_t else "N/A"
    db_size = f"{os.path.getsize(DB_FILE) / 1024:.2f} KB" if os.path.exists(DB_FILE) else "N/A"
    async with aiosqlite.connect(DB_FILE) as conn:
        total_trades = (await (await conn.execute("SELECT COUNT(*) FROM trades")).fetchone())[0]
        active_trades = (await (await conn.execute("SELECT COUNT(*) FROM trades WHERE status = 'active'")).fetchone())[0]
    report = (
        f"🕵️‍♂️ *تقرير التشخيص الشامل*\n\n"
        f"تم إنشاؤه في: {datetime.now(EGYPT_TZ).strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"----------------------------------\n"
        f"⚙️ **حالة النظام والبيئة**\n"
        f"- NLTK (تحليل الأخبار): {nltk_status}\n\n"
        f"🔬 **أداء آخر فحص**\n"
        f"- وقت البدء: {scan_time}\n"
        f"- المدة: {scan_duration}\n"
        f"- العملات المفحوصة: {scan_checked}\n"
        f"- فشل في التحليل: {scan_errors} عملات\n\n"
        f"🔧 **الإعدادات النشطة**\n"
        f"- **النمط الحالي: {bot_data.active_preset_name}**\n"
        f"- الماسحات المفعلة:\n{scanners_list}\n"
        f"----------------------------------\n"
        f"🔩 **حالة العمليات الداخلية**\n"
        f"- فحص العملات: يعمل, التالي في: {next_scan_time}\n"
        f"- الاتصال بـ OKX: متصل ✅\n"
        f"- قاعدة البيانات:\n"
        f"  - الاتصال: ناجح ✅\n"
        f"  - حجم الملف: {db_size}\n"
        f"  - إجمالي الصفقات: {total_trades} ({active_trades} نشطة)\n"
        f"----------------------------------"
    )
    await safe_edit_message(query, report, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔄 تحديث", callback_data="db_diagnostics")], [InlineKeyboardButton("🔙 العودة للوحة التحكم", callback_data="back_to_dashboard")]]))

async def show_settings_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("🧠 إعدادات الذكاء التكيفي", callback_data="settings_adaptive")],
        [InlineKeyboardButton("🎛️ تعديل المعايير المتقدمة", callback_data="settings_params")],
        [InlineKeyboardButton("🔭 تفعيل/تعطيل الماسحات", callback_data="settings_scanners")],
        [InlineKeyboardButton("🗂️ أنماط جاهزة", callback_data="settings_presets")],
        [InlineKeyboardButton("🚫 القائمة السوداء", callback_data="settings_blacklist"), InlineKeyboardButton("🗑️ إدارة البيانات", callback_data="settings_data")]
    ]
    message_text = "⚙️ *الإعدادات الرئيسية*\n\nاختر فئة الإعدادات التي تريد تعديلها."
    target_message = update.message or update.callback_query.message
    if update.callback_query: await safe_edit_message(update.callback_query, message_text, reply_markup=InlineKeyboardMarkup(keyboard))
    else: await target_message.reply_text(message_text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(keyboard))

async def show_adaptive_intelligence_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    s = bot_data.settings
    def bool_format(key, text):
        val = s.get(key, False)
        emoji = "✅" if val else "❌"
        return f"{text}: {emoji} مفعل"

    keyboard = [
        [InlineKeyboardButton(bool_format('adaptive_intelligence_enabled', 'تفعيل الذكاء التكيفي'), callback_data="param_toggle_adaptive_intelligence_enabled")],
        [InlineKeyboardButton(bool_format('dynamic_trade_sizing_enabled', 'تفعيل الحجم الديناميكي للصفقات'), callback_data="param_toggle_dynamic_trade_sizing_enabled")],
        [InlineKeyboardButton(bool_format('strategy_proposal_enabled', 'تفعيل اقتراحات الاستراتيجيات'), callback_data="param_toggle_strategy_proposal_enabled")],
        [InlineKeyboardButton("--- معايير الضبط ---", callback_data="noop")],
        [InlineKeyboardButton(f"حد أدنى لتعطيل الاستراتيجية (WR%): {s.get('strategy_deactivation_threshold_wr', 45.0)}", callback_data="param_set_strategy_deactivation_threshold_wr")],
        [InlineKeyboardButton(f"أقل عدد صفقات للتحليل: {s.get('strategy_analysis_min_trades', 10)}", callback_data="param_set_strategy_analysis_min_trades")],
        [InlineKeyboardButton(f"أقصى زيادة لحجم الصفقة (%): {s.get('dynamic_sizing_max_increase_pct', 25.0)}", callback_data="param_set_dynamic_sizing_max_increase_pct")],
        [InlineKeyboardButton(f"أقصى تخفيض لحجم الصفقة (%): {s.get('dynamic_sizing_max_decrease_pct', 50.0)}", callback_data="param_set_dynamic_sizing_max_decrease_pct")],
        [InlineKeyboardButton("🔙 العودة للإعدادات", callback_data="settings_main")]
    ]
    await safe_edit_message(update.callback_query, "🧠 **إعدادات الذكاء التكيفي**\n\nتحكم في كيفية تعلم البوت وتكيفه:", reply_markup=InlineKeyboardMarkup(keyboard))


async def show_parameters_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    s = bot_data.settings
    def bool_format(key, text):
        val = s.get(key, False)
        emoji = "✅" if val else "❌"
        return f"{text}: {emoji} مفعل"
    def get_nested_value(d, keys):
        current_level = d
        for key in keys:
            if isinstance(current_level, dict) and key in current_level: current_level = current_level[key]
            else: return None
        return current_level
    keyboard = [
        [InlineKeyboardButton("--- إعدادات عامة ---", callback_data="noop")],
        [InlineKeyboardButton(f"عدد العملات للفحص: {s['top_n_symbols_by_volume']}", callback_data="param_set_top_n_symbols_by_volume"),
         InlineKeyboardButton(f"أقصى عدد للصفقات: {s['max_concurrent_trades']}", callback_data="param_set_max_concurrent_trades")],
        [InlineKeyboardButton(f"عمال الفحص المتزامنين: {s['worker_threads']}", callback_data="param_set_worker_threads")],
        [InlineKeyboardButton("--- إعدادات المخاطر ---", callback_data="noop")],
        [InlineKeyboardButton(f"حجم الصفقة ($): {s['real_trade_size_usdt']}", callback_data="param_set_real_trade_size_usdt"),
         InlineKeyboardButton(f"مضاعف وقف الخسارة (ATR): {s['atr_sl_multiplier']}", callback_data="param_set_atr_sl_multiplier")],
        [InlineKeyboardButton(f"نسبة المخاطرة/العائد: {s['risk_reward_ratio']}", callback_data="param_set_risk_reward_ratio")],
        [InlineKeyboardButton(bool_format('trailing_sl_enabled', 'تفعيل الوقف المتحرك'), callback_data="param_toggle_trailing_sl_enabled")],
        [InlineKeyboardButton(f"تفعيل الوقف المتحرك (%): {s['trailing_sl_activation_percent']}", callback_data="param_set_trailing_sl_activation_percent"),
         InlineKeyboardButton(f"مسافة الوقف المتحرك (%): {s['trailing_sl_callback_percent']}", callback_data="param_set_trailing_sl_callback_percent")],
        [InlineKeyboardButton(f"عدد محاولات الإغلاق: {s['close_retries']}", callback_data="param_set_close_retries")],
        [InlineKeyboardButton("--- إعدادات الإشعارات والفلترة ---", callback_data="noop")],
        [InlineKeyboardButton(bool_format('incremental_notifications_enabled', 'إشعارات الربح المتزايدة'), callback_data="param_toggle_incremental_notifications_enabled")],
        [InlineKeyboardButton(f"نسبة إشعار الربح (%): {s['incremental_notification_percent']}", callback_data="param_set_incremental_notification_percent")],
        [InlineKeyboardButton(f"مضاعف فلتر الحجم: {s['volume_filter_multiplier']}", callback_data="param_set_volume_filter_multiplier")],
        [InlineKeyboardButton(bool_format('multi_timeframe_enabled', 'فلتر الأطر الزمنية'), callback_data="param_toggle_multi_timeframe_enabled")],
        [InlineKeyboardButton(bool_format('btc_trend_filter_enabled', 'فلتر اتجاه BTC'), callback_data="param_toggle_btc_trend_filter_enabled")],
        [InlineKeyboardButton(f"فترة EMA للاتجاه: {get_nested_value(s, ['trend_filters', 'ema_period'])}", callback_data="param_set_trend_filters_ema_period")],
        [InlineKeyboardButton(f"أقصى سبريد مسموح (%): {get_nested_value(s, ['spread_filter', 'max_spread_percent'])}", callback_data="param_set_spread_filter_max_spread_percent")],
        [InlineKeyboardButton(f"أدنى ATR مسموح (%): {get_nested_value(s, ['volatility_filters', 'min_atr_percent'])}", callback_data="param_set_volatility_filters_min_atr_percent")],
        [InlineKeyboardButton(bool_format('market_mood_filter_enabled', 'فلتر الخوف والطمع'), callback_data="param_toggle_market_mood_filter_enabled"),
         InlineKeyboardButton(f"حد مؤشر الخوف: {s['fear_and_greed_threshold']}", callback_data="param_set_fear_and_greed_threshold")],
        [InlineKeyboardButton(bool_format('adx_filter_enabled', 'فلتر ADX'), callback_data="param_toggle_adx_filter_enabled"),
         InlineKeyboardButton(f"مستوى فلتر ADX: {s['adx_filter_level']}", callback_data="param_set_adx_filter_level")],
        [InlineKeyboardButton(bool_format('news_filter_enabled', 'فلتر الأخبار والبيانات'), callback_data="param_toggle_news_filter_enabled")],
        # New Settings
        [InlineKeyboardButton(bool_format('intelligent_reviewer_enabled', 'المراجع الذكي'), callback_data="param_toggle_intelligent_reviewer_enabled")],
        [InlineKeyboardButton(bool_format('momentum_scalp_mode_enabled', 'اقتناص الزخم'), callback_data="param_toggle_momentum_scalp_mode_enabled")],
        [InlineKeyboardButton(f"هدف اقتناص الزخم (%): {s.get('momentum_scalp_target_percent', 0.5)}", callback_data="param_set_momentum_scalp_target_percent")],
        [InlineKeyboardButton(bool_format('multi_timeframe_confluence_enabled', 'فلتر التوافق الزمني'), callback_data="param_toggle_multi_timeframe_confluence_enabled")],
        [InlineKeyboardButton("🔙 العودة للإعدادات", callback_data="settings_main")]
    ]
    await safe_edit_message(update.callback_query, "🎛️ **تعديل المعايير المتقدمة**\n\nاضغط على أي معيار لتعديل قيمته مباشرة:", reply_markup=InlineKeyboardMarkup(keyboard))

async def show_scanners_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = []
    active_scanners = bot_data.settings['active_scanners']
    for key, name in STRATEGY_NAMES_AR.items():
        status_emoji = "✅" if key in active_scanners else "❌"
        perf_hint = ""
        if (perf := bot_data.strategy_performance.get(key)):
            perf_hint = f" ({perf['win_rate']}% WR)"
        keyboard.append([InlineKeyboardButton(f"{status_emoji} {name}{perf_hint}", callback_data=f"scanner_toggle_{key}")])
    keyboard.append([InlineKeyboardButton("🔙 العودة للإعدادات", callback_data="settings_main")])
    await safe_edit_message(update.callback_query, "اختر الماسحات لتفعيلها أو تعطيلها (مع تلميح الأداء):", reply_markup=InlineKeyboardMarkup(keyboard))

async def show_presets_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("🚦 احترافي", callback_data="preset_set_professional")],
        [InlineKeyboardButton("🎯 متشدد", callback_data="preset_set_strict")],
        [InlineKeyboardButton("🌙 متساهل", callback_data="preset_set_lenient")],
        [InlineKeyboardButton("⚠️ فائق التساهل", callback_data="preset_set_very_lenient")],
        [InlineKeyboardButton("❤️ القلب الجريء", callback_data="preset_set_bold_heart")],
        [InlineKeyboardButton("🔙 العودة للإعدادات", callback_data="settings_main")]
    ]
    await safe_edit_message(update.callback_query, "اختر نمط إعدادات جاهز:", reply_markup=InlineKeyboardMarkup(keyboard))

async def show_blacklist_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    blacklist = bot_data.settings.get('asset_blacklist', [])
    blacklist_str = ", ".join(f"`{item}`" for item in blacklist) if blacklist else "لا توجد عملات في القائمة."
    text = f"🚫 **القائمة السوداء**\n" \
           f"هذه قائمة بالعملات التي لن يتم التداول عليها:\n\n{blacklist_str}"
    keyboard = [
        [InlineKeyboardButton("➕ إضافة عملة", callback_data="blacklist_add"), InlineKeyboardButton("➖ إزالة عملة", callback_data="blacklist_remove")],
        [InlineKeyboardButton("🔙 العودة للإعدادات", callback_data="settings_main")]
    ]
    await safe_edit_message(update.callback_query, text, reply_markup=InlineKeyboardMarkup(keyboard))

async def show_data_management_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[InlineKeyboardButton("‼️ مسح كل الصفقات ‼️", callback_data="data_clear_confirm")], [InlineKeyboardButton("🔙 العودة للإعدادات", callback_data="settings_main")]]
    await safe_edit_message(update.callback_query, "🗑️ *إدارة البيانات*\n\n**تحذير:** هذا الإجراء سيحذف سجل جميع الصفقات بشكل نهائي.", reply_markup=InlineKeyboardMarkup(keyboard))

async def handle_clear_data_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[InlineKeyboardButton("نعم، متأكد. احذف كل شيء.", callback_data="data_clear_execute")], [InlineKeyboardButton("لا، تراجع.", callback_data="settings_data")]]
    await safe_edit_message(update.callback_query, "🛑 **تأكيد نهائي: حذف البيانات**\n\nهل أنت متأكد أنك تريد حذف جميع بيانات الصفقات بشكل نهائي؟", reply_markup=InlineKeyboardMarkup(keyboard))

async def handle_clear_data_execute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_edit_message(query, "جاري حذف البيانات...", reply_markup=None)
    try:
        if os.path.exists(DB_FILE):
            os.remove(DB_FILE)
            logger.info("Database file has been deleted by user.")
        await init_database()
        await safe_edit_message(query, "✅ تم حذف جميع بيانات الصفقات بنجاح.")
    except Exception as e:
        logger.error(f"Failed to clear data: {e}")
        await safe_edit_message(query, f"❌ حدث خطأ أثناء حذف البيانات: {e}")
    await asyncio.sleep(2)
    await show_settings_menu(update, context)

async def handle_scanner_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    scanner_key = query.data.replace("scanner_toggle_", "")
    active_scanners = bot_data.settings['active_scanners']
    if scanner_key not in STRATEGY_NAMES_AR:
        logger.error(f"Invalid scanner key: '{scanner_key}'"); await query.answer("خطأ: مفتاح الماسح غير صالح.", show_alert=True); return
    if scanner_key in active_scanners:
        if len(active_scanners) > 1: active_scanners.remove(scanner_key)
        else: await query.answer("يجب تفعيل ماسح واحد على الأقل.", show_alert=True); return
    else: active_scanners.append(scanner_key)
    save_settings(); determine_active_preset()
    await query.answer(f"{STRATEGY_NAMES_AR[scanner_key]} {'تم تفعيله' if scanner_key in active_scanners else 'تم تعطيله'}")
    await show_scanners_menu(update, context)

async def handle_strategy_adjustment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    parts = query.data.split('_')
    action = parts[2]
    proposal_key = parts[3]

    proposal = bot_data.pending_strategy_proposal
    if not proposal or proposal.get("key") != proposal_key:
        await safe_edit_message(query, "انتهت صلاحية هذا الاقتراح أو تمت معالجته بالفعل.", reply_markup=None)
        return

    if action == "approve":
        scanner_to_disable = proposal['scanner']
        if scanner_to_disable in bot_data.settings['active_scanners']:
            bot_data.settings['active_scanners'].remove(scanner_to_disable)
            save_settings()
            determine_active_preset()
            logger.info(f"User approved disabling strategy: {scanner_to_disable}")
            await safe_edit_message(query, f"✅ **تمت الموافقة.**\nتم تعطيل استراتيجية '{STRATEGY_NAMES_AR.get(scanner_to_disable, scanner_to_disable)}'.", reply_markup=None)
        else:
            await safe_edit_message(query, "⚠️ الاستراتيجية معطلة بالفعل.", reply_markup=None)
    else: # Reject
        logger.info(f"User rejected disabling strategy: {proposal['scanner']}")
        await safe_edit_message(query, "❌ **تم الرفض.**\nلن يتم إجراء أي تغييرات على الاستراتيجيات النشطة.", reply_markup=None)

    bot_data.pending_strategy_proposal = {} # Clear proposal


async def handle_preset_set(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    preset_key = query.data.replace("preset_set_", "")

    if preset_settings := SETTINGS_PRESETS.get(preset_key):
        # Preserve intelligence settings and scanners when changing presets
        current_scanners = bot_data.settings.get('active_scanners', [])
        adaptive_settings = {
            k: v for k, v in bot_data.settings.items() if k not in DEFAULT_SETTINGS
        }

        bot_data.settings = copy.deepcopy(preset_settings)
        bot_data.settings['active_scanners'] = current_scanners
        bot_data.settings.update(adaptive_settings) # Restore adaptive settings

        determine_active_preset()
        save_settings()

        lf = preset_settings.get('liquidity_filters', {})
        vf = preset_settings.get('volatility_filters', {})
        sf = preset_settings.get('spread_filter', {})

        confirmation_text = (
            f"✅ *تم تفعيل النمط: {PRESET_NAMES_AR.get(preset_key, preset_key)}*\n\n"
            f"*أهم القيم:*\n"
            f"- `min_rvol: {lf.get('min_rvol', 'N/A')}`\n"
            f"- `max_spread: {sf.get('max_spread_percent', 'N/A')}%`\n"
            f"- `min_atr: {vf.get('min_atr_percent', 'N/A')}%`"
        )
        await query.answer(f"تم تفعيل نمط: {PRESET_NAMES_AR.get(preset_key, preset_key)}")
        await show_presets_menu(update, context) # Refresh menu
        await safe_send_message(context.bot, confirmation_text)

    else:
        await query.answer("لم يتم العثور على النمط.")

async def handle_parameter_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; param_key = query.data.replace("param_set_", "")
    context.user_data['setting_to_change'] = param_key
    if '_' in param_key: await query.message.reply_text(f"أرسل القيمة الرقمية الجديدة لـ `{param_key}`:\n\n*ملاحظة: هذا إعداد متقدم (متشعب)، سيتم تحديثه مباشرة.*", parse_mode=ParseMode.MARKDOWN)
    else: await query.message.reply_text(f"أرسل القيمة الرقمية الجديدة لـ `{param_key}`:", parse_mode=ParseMode.MARKDOWN)

async def handle_toggle_parameter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; param_key = query.data.replace("param_toggle_", "")
    bot_data.settings[param_key] = not bot_data.settings.get(param_key, False)
    save_settings(); determine_active_preset()
    # Refresh the correct menu
    if param_key.startswith("adaptive") or param_key.startswith("dynamic") or param_key.startswith("strategy"):
        await show_adaptive_intelligence_menu(update, context)
    else:
        await show_parameters_menu(update, context)

async def handle_blacklist_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; action = query.data.replace("blacklist_", "")
    context.user_data['blacklist_action'] = action
    await query.message.reply_text(f"أرسل رمز العملة التي تريد **{ 'إضافتها' if action == 'add' else 'إزالتها'}** (مثال: `BTC` أو `DOGE`)")

async def handle_setting_value(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_input = update.message.text.strip()
    if 'blacklist_action' in context.user_data:
        action = context.user_data.pop('blacklist_action'); blacklist = bot_data.settings.get('asset_blacklist', [])
        symbol = user_input.upper().replace("/USDT", "")
        if action == 'add':
            if symbol not in blacklist: blacklist.append(symbol); await update.message.reply_text(f"✅ تم إضافة `{symbol}` إلى القائمة السوداء.")
            else: await update.message.reply_text(f"⚠️ العملة `{symbol}` موجودة بالفعل.")
        elif action == 'remove':
            if symbol in blacklist: blacklist.remove(symbol); await update.message.reply_text(f"✅ تم إزالة `{symbol}` من القائمة السوداء.")
            else: await update.message.reply_text(f"⚠️ العملة `{symbol}` غير موجودة في القائمة.")
        bot_data.settings['asset_blacklist'] = blacklist; save_settings(); determine_active_preset()
        # Create a dummy query object to refresh the menu
        dummy_query = type('Query', (), {'message': update.message, 'data': 'settings_blacklist', 'edit_message_text': (lambda *args, **kwargs: asyncio.sleep(0)), 'answer': (lambda *args, **kwargs: asyncio.sleep(0))})
        await show_blacklist_menu(Update(update.update_id, callback_query=dummy_query), context)
        return

    if not (setting_key := context.user_data.get('setting_to_change')): return

    try:
        if setting_key in bot_data.settings and not isinstance(bot_data.settings[setting_key], dict):
            original_value = bot_data.settings[setting_key]
            if isinstance(original_value, int):
                new_value = int(user_input)
            else:
                new_value = float(user_input)
            bot_data.settings[setting_key] = new_value
        else:
            keys = setting_key.split('_'); current_dict = bot_data.settings
            for key in keys[:-1]:
                current_dict = current_dict[key]
            last_key = keys[-1]
            original_value = current_dict[last_key]
            if isinstance(original_value, int):
                new_value = int(user_input)
            else:
                new_value = float(user_input)
            current_dict[last_key] = new_value

        save_settings(); determine_active_preset()
        await update.message.reply_text(f"✅ تم تحديث `{setting_key}` إلى `{new_value}`.")
    except (ValueError, KeyError):
        await update.message.reply_text("❌ قيمة غير صالحة. الرجاء إرسال رقم.")
    finally:
        if 'setting_to_change' in context.user_data:
            del context.user_data['setting_to_change']
        # Create a dummy query object to refresh the settings menu
        dummy_query = type('Query', (), {'message': update.message, 'data': 'settings_params', 'edit_message_text': (lambda *args, **kwargs: asyncio.sleep(0)), 'answer': (lambda *args, **kwargs: asyncio.sleep(0))})
        if setting_key.startswith("adaptive") or setting_key.startswith("dynamic") or setting_key.startswith("strategy"):
             await show_adaptive_intelligence_menu(Update(update.update_id, callback_query=dummy_query), context)
        else:
             await show_parameters_menu(Update(update.update_id, callback_query=dummy_query), context)


async def universal_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if 'setting_to_change' in context.user_data or 'blacklist_action' in context.user_data:
        await handle_setting_value(update, context); return
    text = update.message.text
    if text == "Dashboard 🖥️": await show_dashboard_command(update, context)
    elif text == "الإعدادات ⚙️": await show_settings_menu(update, context)

async def button_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer(); data = query.data
    route_map = {
        "db_stats": show_stats_command, "db_trades": show_trades_command, "db_history": show_trade_history_command,
        "db_mood": show_mood_command, "db_diagnostics": show_diagnostics_command, "back_to_dashboard": show_dashboard_command,
        "db_portfolio": show_portfolio_command, "db_manual_scan": lambda u,c: manual_scan_command(u, c),
        "kill_switch_toggle": toggle_kill_switch, "db_daily_report": daily_report_command, "db_strategy_report": show_strategy_report_command,
        "settings_main": show_settings_menu, "settings_params": show_parameters_menu, "settings_scanners": show_scanners_menu,
        "settings_presets": show_presets_menu, "settings_blacklist": show_blacklist_menu, "settings_data": show_data_management_menu,
        "settings_adaptive": show_adaptive_intelligence_menu,
        # New: Maestro Routes
        "db_maestro_control": show_maestro_control, "maestro_toggle": toggle_maestro,
        "blacklist_add": handle_blacklist_action, "blacklist_remove": handle_blacklist_action,
        "data_clear_confirm": handle_clear_data_confirmation, "data_clear_execute": handle_clear_data_execute,
        "noop": (lambda u,c: None)
    }
    try:
        if data in route_map: await route_map[data](update, context)
        elif data.startswith("check_"): await check_trade_details(update, context)
        elif data.startswith("scanner_toggle_"): await handle_scanner_toggle(update, context)
        elif data.startswith("preset_set_"): await handle_preset_set(update, context)
        elif data.startswith("param_set_"): await handle_parameter_selection(update, context)
        elif data.startswith("param_toggle_"): await handle_toggle_parameter(update, context)
        elif data.startswith("strategy_adjust_"): await handle_strategy_adjustment(update, context)
    except Exception as e: logger.error(f"Error in button callback handler for data '{data}': {e}", exc_info=True)



async def post_init(application: Application):
    bot_data.application = application
    if not all([OKX_API_KEY, OKX_API_SECRET, OKX_API_PASSPHRASE, TELEGRAM_BOT_TOKEN]):
        logger.critical("FATAL: Missing critical API keys."); return
    if NLTK_AVAILABLE:
        try: nltk.data.find('sentiment/vader_lexicon.zip')
        except LookupError: logger.info("Downloading NLTK data..."); nltk.download('vader_lexicon', quiet=True)
    
    try:
        bot_data.redis_client = redis.from_url(REDIS_URL, decode_responses=True)
        await bot_data.redis_client.ping()
        logger.info("✅ Successfully connected to Redis server.")
    except Exception as e:
        logger.error(f"🔥 FATAL: Could not connect to Redis server: {e}")
        bot_data.redis_client = None

    try:
        config = {'apiKey': OKX_API_KEY, 'secret': OKX_API_SECRET, 'password': OKX_API_PASSPHRASE, 'enableRateLimit': True}
        bot_data.exchange = ccxt.okx(config)
        await bot_data.exchange.load_markets()

        logger.info("Reconciling SPOT trading state with OKX exchange...")
        
        balance = await bot_data.exchange.fetch_balance()
        # [# <-- الإصلاح النهائي هنا]
        owned_assets = {asset for asset, data in balance.items() if isinstance(data, dict) and data.get('total', 0) > 0.00001}
        logger.info(f"Found {len(owned_assets)} assets with balance in the wallet.")

        async with aiosqlite.connect(DB_FILE) as conn:
            conn.row_factory = aiosqlite.Row
            states_to_check = ('active', 'pending')
            query = f"SELECT * FROM trades WHERE status IN {states_to_check}"
            trades_in_db = await (await conn.execute(query)).fetchall()
            logger.info(f"Found {len(trades_in_db)} active/pending trades in the local database to reconcile.")

            for trade in trades_in_db:
                base_currency = trade['symbol'].split('/')[0]
                if base_currency not in owned_assets and trade['status'] == 'active':
                    logger.warning(f"Trade #{trade['id']} for {trade['symbol']} is in DB, but asset balance is zero. Marking as manually closed.")
                    await conn.execute("UPDATE trades SET status = 'مغلقة يدوياً' WHERE id = ?", (trade['id'],))
            
            await conn.commit()
        logger.info("State reconciliation for SPOT complete.")

    except Exception as e:
        logger.critical(f"🔥 FATAL: Could not connect or reconcile state with OKX: {e}", exc_info=True)
        return

    await check_time_sync(ContextTypes.DEFAULT_TYPE(application=application))
    bot_data.trade_guardian = TradeGuardian(application)
    bot_data.public_ws = PublicWebSocketManager(bot_data.trade_guardian.handle_ticker_update)
    bot_data.private_ws = PrivateWebSocketManager()
    asyncio.create_task(bot_data.public_ws.run()); asyncio.create_task(bot_data.private_ws.run())
    logger.info("Waiting 5s for WebSocket connections..."); await asyncio.sleep(5)
    await bot_data.trade_guardian.sync_subscriptions()
    
    jq = application.job_queue
    jq.run_repeating(perform_scan, interval=SCAN_INTERVAL_SECONDS, first=10, name="perform_scan")
    jq.run_repeating(the_supervisor_job, interval=SUPERVISOR_INTERVAL_SECONDS, first=30, name="the_supervisor_job")
    jq.run_repeating(check_time_sync, interval=TIME_SYNC_INTERVAL_SECONDS, first=TIME_SYNC_INTERVAL_SECONDS, name="time_sync_job")
    jq.run_repeating(critical_trade_monitor, interval=SUPERVISOR_INTERVAL_SECONDS * 2, first=SUPERVISOR_INTERVAL_SECONDS * 2, name="critical_trade_monitor")
    jq.run_daily(send_daily_report, time=dt_time(hour=23, minute=55, tzinfo=EGYPT_TZ), name='daily_report')
    jq.run_repeating(update_strategy_performance, interval=STRATEGY_ANALYSIS_INTERVAL_SECONDS, first=60, name="update_strategy_performance")
    jq.run_repeating(propose_strategy_changes, interval=STRATEGY_ANALYSIS_INTERVAL_SECONDS, first=120, name="propose_strategy_changes")
    reviewer_interval = bot_data.settings.get('intelligent_reviewer_interval_minutes', 30) * 60
    jq.run_repeating(intelligent_reviewer_job, interval=reviewer_interval, first=reviewer_interval, name="intelligent_reviewer_job")
    jq.run_repeating(maestro_job, interval=MAESTRO_INTERVAL_HOURS * 3600, first=MAESTRO_INTERVAL_HOURS * 3600, name="maestro_job")

    logger.info(f"Jobs scheduled. Daily report at 23:55. Strategy analysis every {STRATEGY_ANALYSIS_INTERVAL_SECONDS/3600} hours. Reviewer every {reviewer_interval/60} min. Maestro every {MAESTRO_INTERVAL_HOURS} hour.")
    try: await application.bot.send_message(TELEGRAM_CHAT_ID, "*🤖 قناص OKX | إصدار المايسترو - بدأ العمل...*", parse_mode=ParseMode.MARKDOWN)
    except Forbidden: logger.critical(f"FATAL: Bot not authorized for chat ID {TELEGRAM_CHAT_ID}."); return
    logger.info("--- OKX Sniper Bot is now fully operational ---")

async def post_shutdown(application: Application):
    if bot_data.exchange: await bot_data.exchange.close()
    
    if bot_data.redis_client:
        await bot_data.redis_client.close()
        logger.info("Redis connection closed.")

    logger.info("Bot has shut down.")

def main():
    logger.info("--- Starting OKX Maestro Pro Bot ---")
    app_builder = Application.builder().token(TELEGRAM_BOT_TOKEN)
    app_builder.post_init(post_init)
    application = app_builder.build()

    application.bot_data = bot_data

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, universal_text_handler))
    application.add_handler(CallbackQueryHandler(button_callback_handler))

    application.run_polling()

if __name__ == '__main__':
    main()
