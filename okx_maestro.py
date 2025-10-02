# -*- coding: utf-8 -*-
# =======================================================================================
# --- 🚀 OKX Maestro Bot V8.0 (Final & Stable) 🚀 ---
# =======================================================================================
#
# --- سجل التغييرات للإصدار 8.0 ---
#   ✅ [نهائي] **الملف الكامل:** تم دمج جميع الإصلاحات السابقة في ملف واحد ومستقر.
#   ✅ [إصلاح] **واجهة المستخدم:** إعادة إضافة جميع دوال واجهة تليجرام (show_settings_menu, etc.) التي حُذفت بالخطأ.
#   ✅ [إصلاح] **تقرير التشخيص:** استخدام الطريقة الصحيحة (.open) لفحص اتصال WebSocket.
#   ✅ [إصلاح] **تعريف الوحدات:** تمرير الاعتماديات الصحيحة عند إنشاء WiseMan و SmartEngine.
#   ✅ [إصلاح] **بدء التشغيل:** منطق بدء تشغيل قوي يوقف البوت عند فشل الاتصال بالمنصة.
#
# --- سجل التغييرات للإصدار 6.6 (تدقيق كامل وتصليب) ---
#   ✅ [إصلاح حاسم] **منع تكرار الصفقات (Race Condition):** تم إضافة ذاكرة مؤقتة لدورة الفحص
#     لضمان عدم فتح أكثر من صفقة لنفس العملة في نفس الدورة.
#   ✅ [إصلاح حاسم] **فلتر الحد الأدنى لقيمة الصفقة (MIN_NOTIONAL):** يقوم البوت الآن بالتحقق
#     من أن حجم الصفقة يفي بالحد الأدنى لمنصة OKX قبل إرسال الأمر.
#   ✅ [هيكلة] **دمج وتوحيد اتصال WebSocket:** تم دمج `UserDataStreamManager` و `TradeGuardian`
#     في فئة واحدة (`OKXWebSocketManager`) أكثر قوة وموثوقية مع آلية إعادة اتصال تلقائي.
#   ✅ [تحسين] **تحسين منطق الفحص (Scanner):** تم إعادة هيكلة دالة `worker_batch` لتكون أكثر
#     نظافة وكفاءة عبر فصل منطق الفلاتر في دالة مساعدة.
#   ✅ [تحسين] **تحسين آلية إغلاق الصفقات:** معالجة أفضل للأخطاء المتعلقة بقواعد المنصة
#     مثل `LOT_SIZE` و `MIN_NOTIONAL` عند محاولة إغلاق صفقة.
#
# --- سجل التغييرات للتحويل إلى OKX ---
#   ✅ [التعديل السهل] تغيير الاتصال الأساسي إلى OKX عبر CCXT.
#   ✅ [التعديل السهل] تحديث فلاتر السوق لـ MIN_NOTIONAL (استخدام 'cost' limits في OKX).
#   ✅ [التعديل الصعب] إعادة كتابة OKXWebSocketManager كاملاً مع مصادقة واشتراكات مخصصة.
#
# --- سجل الإصلاحات الجديدة ---
#   ✅ [إصلاح DB] تحسين init_database مع logging وإعادة إنشاء الجدول إذا فشل.
#   ✅ [إصلاح Diagnostics] إضافة try-except في show_diagnostics_command لتجنب الانهيار.
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
from datetime import datetime, timedelta, timezone, time as dt_time
from zoneinfo import ZoneInfo
from collections import defaultdict, Counter
import httpx
import re
import aiosqlite
import hmac
import hashlib
import base64
import sqlite3

# --- مكتبات التحليل والتداول ---
import pandas as pd
import pandas_ta as ta
import ccxt.async_support as ccxt
import feedparser
import websockets
import websockets.exceptions

# --- [ترقية] مكتبات جديدة للعقل المطور ---
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

# --- الوحدات المخصصة ---
from wise_man import WiseMan
from smart_engine import EvolutionaryEngine

# --- إعدادات أساسية ---
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# --- جلب المتغيرات من بيئة التشغيل ---
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
OKX_API_KEY = os.getenv('OKX_API_KEY')
OKX_API_SECRET = os.getenv('OKX_API_SECRET')
OKX_API_PASSWORD = os.getenv('OKX_API_PASSWORD')
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
ALPHA_VANTAGE_API_KEY = os.getenv('ALPHA_VANTAGE_API_KEY', 'YOUR_AV_KEY_HERE')

# --- إعدادات البوت ---
DB_FILE = 'trading_bot_v8.0_okx.db'
SETTINGS_FILE = 'trading_bot_v8.0_okx_settings.json'
TIMEFRAME = '15m'
SCAN_INTERVAL_SECONDS = 900
SUPERVISOR_INTERVAL_SECONDS = 180
TIME_SYNC_INTERVAL_SECONDS = 3600
STRATEGY_ANALYSIS_INTERVAL_SECONDS = 21600 # 6 hours
EGYPT_TZ = ZoneInfo("Africa/Cairo")

# (بقية الإعدادات الافتراضية تبقى كما هي)
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
    "active_scanners": ["momentum_breakout", "breakout_squeeze_pro", "support_rebound", "sniper_pro", "whale_radar", "rsi_divergence", "supertrend_pullback"],
    "market_mood_filter_enabled": True,
    "fear_and_greed_threshold": 30,
    "adx_filter_enabled": True,
    "adx_filter_level": 25,
    "btc_trend_filter_enabled": True,
    "news_filter_enabled": True,
    "asset_blacklist": ["USDC", "DAI", "TUSD", "FDUSD", "USDD", "PYUSD", "USDT", "BTC", "ETH"],
    "liquidity_filters": {"min_quote_volume_24h_usd": 1000000, "min_rvol": 1.5},
    "volatility_filters": {"atr_period_for_filter": 14, "min_atr_percent": 0.8},
    "trend_filters": {"ema_period": 200, "htf_period": 50, "enabled": True},
    "spread_filter": {"max_spread_percent": 0.5},
    "rsi_divergence": {"rsi_period": 14, "lookback_period": 35, "peak_trough_lookback": 5, "confirm_with_rsi_exit": True},
    "supertrend_pullback": {"atr_period": 10, "atr_multiplier": 3.0, "swing_high_lookback": 10},
    "multi_timeframe_enabled": True,
    "multi_timeframe_htf": '4h',
    "volume_filter_multiplier": 2.0,
    "close_retries": 3,
    "incremental_notifications_enabled": True,
    "incremental_notification_percent": 2.0,
    "adaptive_intelligence_enabled": True,
    "dynamic_trade_sizing_enabled": True,
    "strategy_proposal_enabled": True,
    "strategy_analysis_min_trades": 10,
    "strategy_deactivation_threshold_wr": 45.0,
    "dynamic_sizing_max_increase_pct": 25.0,
    "dynamic_sizing_max_decrease_pct": 50.0,
    "wise_man_auto_close": True, 
    "wise_man_strong_profit_pct": 3.0, 
    "wise_man_strong_adx_level": 30,  
    # --- [إضافة جديدة] ---
    "wise_guardian_enabled": True,
    "wise_guardian_trigger_pct": -1.5,
    "wise_guardian_cooldown_minutes": 15,
}

STRATEGY_NAMES_AR = {
    "momentum_breakout": "زخم اختراقي", "breakout_squeeze_pro": "اختراق انضغاطي",
    "support_rebound": "ارتداد الدعم", "sniper_pro": "القناص المحترف", "whale_radar": "رادار الحيتان",
    "rsi_divergence": "دايفرجنس RSI", "supertrend_pullback": "انعكاس سوبرترند"
}

PRESET_NAMES_AR = {"professional": "احترافي", "strict": "متشدد", "lenient": "متساهل", "very_lenient": "فائق التساهل", "bold_heart": "القلب الجريء"}

SETTINGS_PRESETS = {
    "professional": copy.deepcopy({k: v for k, v in DEFAULT_SETTINGS.items() if "adaptive" not in k and "dynamic" not in k and "strategy" not in k}),
    "strict": {**copy.deepcopy({k: v for k, v in DEFAULT_SETTINGS.items() if "adaptive" not in k and "dynamic" not in k and "strategy" not in k}), "max_concurrent_trades": 3, "risk_reward_ratio": 2.5, "fear_and_greed_threshold": 40, "adx_filter_level": 28, "liquidity_filters": {"min_quote_volume_24h_usd": 2000000, "min_rvol": 2.0}},
    "lenient": {**copy.deepcopy({k: v for k, v in DEFAULT_SETTINGS.items() if "adaptive" not in k and "dynamic" not in k and "strategy" not in k}), "max_concurrent_trades": 8, "risk_reward_ratio": 1.8, "fear_and_greed_threshold": 25, "adx_filter_level": 20, "liquidity_filters": {"min_quote_volume_24h_usd": 500000, "min_rvol": 1.2}},
    "very_lenient": {
        **copy.deepcopy({k: v for k, v in DEFAULT_SETTINGS.items() if "adaptive" not in k and "dynamic" not in k and "strategy" not in k}),
        "max_concurrent_trades": 12, "adx_filter_enabled": False, "market_mood_filter_enabled": False,
        "trend_filters": {"ema_period": 200, "htf_period": 50, "enabled": False},
        "liquidity_filters": {"min_quote_volume_24h_usd": 250000, "min_rvol": 1.0},
        "volatility_filters": {"atr_period_for_filter": 14, "min_atr_percent": 0.4}, "spread_filter": {"max_spread_percent": 1.5}
    },
    "bold_heart": {
        **copy.deepcopy({k: v for k, v in DEFAULT_SETTINGS.items() if "adaptive" not in k and "dynamic" not in k and "strategy" not in k}),
        "max_concurrent_trades": 15, "risk_reward_ratio": 1.5, "multi_timeframe_enabled": False, "market_mood_filter_enabled": False,
        "adx_filter_enabled": False, "btc_trend_filter_enabled": False, "news_filter_enabled": False,
        "volume_filter_multiplier": 1.0, "liquidity_filters": {"min_quote_volume_24h_usd": 100000, "min_rvol": 1.0},
        "volatility_filters": {"atr_period_for_filter": 14, "min_atr_percent": 0.2}, "spread_filter": {"max_spread_percent": 2.0}
    }
}
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
        self.websocket_manager = None
        self.strategy_performance = {}
        self.pending_strategy_proposal = {}
        # --- [إضافة جديدة] ---
        self.last_deep_analysis_time = defaultdict(float)

bot_data = BotState()
wise_man = None
smart_brain = None
scan_lock = asyncio.Lock()
trade_management_lock = asyncio.Lock()

# --- وظائف مساعدة وقاعدة البيانات ---
def load_settings():
    try:
        if os.path.exists(SETTINGS_FILE):
            with open(SETTINGS_FILE, 'r') as f: bot_data.settings = json.load(f)
        else: bot_data.settings = copy.deepcopy(DEFAULT_SETTINGS)
    except Exception: bot_data.settings = copy.deepcopy(DEFAULT_SETTINGS)
    default_copy = copy.deepcopy(DEFAULT_SETTINGS)
    for key, value in default_copy.items():
        if isinstance(value, dict):
            if key not in bot_data.settings or not isinstance(bot_data.settings[key], dict): bot_data.settings[key] = {}
            for sub_key, sub_value in value.items(): bot_data.settings[key].setdefault(sub_key, sub_value)
        else: bot_data.settings.setdefault(key, value)
    determine_active_preset(); save_settings()
    logger.info(f"Settings loaded. Active preset: {bot_data.active_preset_name}")

def determine_active_preset():
    current_settings_for_compare = {k: v for k, v in bot_data.settings.items() if k in SETTINGS_PRESETS['professional']}
    for name, preset_settings in SETTINGS_PRESETS.items():
        is_match = True
        for key, value in preset_settings.items():
            if key in current_settings_for_compare and current_settings_for_compare[key] != value:
                is_match = False; break
        if is_match:
            bot_data.active_preset_name = PRESET_NAMES_AR.get(name, "مخصص"); return
    bot_data.active_preset_name = "مخصص"

def save_settings():
    with open(SETTINGS_FILE, 'w') as f: json.dump(bot_data.settings, f, indent=4)

async def init_database():
    try:
        logger.info("Starting DB init...")
        async with aiosqlite.connect(DB_FILE) as conn:
            await conn.execute('CREATE TABLE IF NOT EXISTS trades (id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT, symbol TEXT, entry_price REAL, take_profit REAL, stop_loss REAL, quantity REAL, status TEXT, reason TEXT, order_id TEXT, highest_price REAL DEFAULT 0, trailing_sl_active BOOLEAN DEFAULT 0, close_price REAL, pnl_usdt REAL, signal_strength INTEGER DEFAULT 1, close_retries INTEGER DEFAULT 0, last_profit_notification_price REAL DEFAULT 0, trade_weight REAL DEFAULT 1.0)')
            await conn.commit()
            cursor = await conn.execute("PRAGMA table_info(trades)")
            columns = [row[1] for row in await cursor.fetchall()]
            # إضافة الأعمدة المفقودة (مع logging)
            added_columns = []
            if 'signal_strength' not in columns:
                await conn.execute("ALTER TABLE trades ADD COLUMN signal_strength INTEGER DEFAULT 1")
                added_columns.append('signal_strength')
            if 'close_retries' not in columns:
                await conn.execute("ALTER TABLE trades ADD COLUMN close_retries INTEGER DEFAULT 0")
                added_columns.append('close_retries')
            if 'last_profit_notification_price' not in columns:
                await conn.execute("ALTER TABLE trades ADD COLUMN last_profit_notification_price REAL DEFAULT 0")
                added_columns.append('last_profit_notification_price')
            if 'trade_weight' not in columns:
                await conn.execute("ALTER TABLE trades ADD COLUMN trade_weight REAL DEFAULT 1.0")
                added_columns.append('trade_weight')
            if 'trailing_sl_active' not in columns:
                await conn.execute("ALTER TABLE trades ADD COLUMN trailing_sl_active BOOLEAN DEFAULT 0")
                added_columns.append('trailing_sl_active')
            if 'highest_price' not in columns:
                await conn.execute("ALTER TABLE trades ADD COLUMN highest_price REAL DEFAULT 0")
                added_columns.append('highest_price')
            await conn.commit()
            if added_columns:
                logger.info(f"Added missing columns to trades table: {', '.join(added_columns)}")
        logger.info("✅ Adaptive database initialized successfully.")
    except Exception as e:
        logger.critical(f"❌ Database initialization failed: {e}", exc_info=True)
        raise  # لإيقاف التشغيل إذا فشل الإنشاء الأساسي

async def log_pending_trade_to_db(signal, buy_order):
    try:
        async with aiosqlite.connect(DB_FILE) as conn:
            await conn.execute("""
                INSERT INTO trades (timestamp, symbol, reason, order_id, status, entry_price, take_profit, stop_loss, signal_strength, trade_weight)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (datetime.now(EGYPT_TZ).isoformat(), signal['symbol'], signal['reason'], buy_order['id'], 'pending',
                  signal['entry_price'], signal['take_profit'], signal['stop_loss'], signal.get('strength', 1), signal.get('weight', 1.0)))
            await conn.commit()
            logger.info(f"Logged pending trade for {signal['symbol']} with order ID {buy_order['id']}.")
            return True
    except Exception as e:
        logger.error(f"DB Log Pending Error for {signal['symbol']}: {e}")
        return False

async def safe_send_message(bot, text, **kwargs):
    for i in range(3):
        try:
            await bot.send_message(TELEGRAM_CHAT_ID, text, parse_mode=ParseMode.MARKDOWN, **kwargs)
            return
        except (TimedOut, Forbidden) as e:
            logger.error(f"Telegram Send Error: {e}. Attempt {i+1}/3.")
            if isinstance(e, Forbidden) or i == 2:
                logger.critical("Critical Telegram error. Cannot send messages.")
                return
            await asyncio.sleep(2)
        except Exception as e:
            logger.error(f"Unknown Telegram Send Error: {e}. Attempt {i+1}/3.")
            await asyncio.sleep(2)

async def safe_edit_message(query, text, **kwargs):
    try: await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, **kwargs)
    except BadRequest as e:
        if "Message is not modified" not in str(e): logger.warning(f"Edit Message Error: {e}")
    except Exception as e: logger.error(f"Edit Message Error: {e}")

# --- [NEW] ADAPTIVE INTELLIGENCE MODULE ---
async def update_strategy_performance(context: ContextTypes.DEFAULT_TYPE):
    logger.info("🧠 Adaptive Mind: Analyzing strategy performance...")
    try:
        async with aiosqlite.connect(DB_FILE) as conn:
            cursor = await conn.execute("SELECT reason, status, pnl_usdt FROM trades WHERE status LIKE '%(%' ORDER BY id DESC LIMIT 100")
            trades = await cursor.fetchall()

        if not trades:
            logger.info("🧠 Adaptive Mind: No closed trades found to analyze.")
            return

        stats = defaultdict(lambda: {'wins': 0, 'losses': 0, 'total_pnl': 0.0, 'win_pnl': 0.0, 'loss_pnl': 0.0})
        for reason_str, status, pnl in trades:
            if not reason_str or pnl is None: continue
            clean_reason = reason_str.split(' (')[0]
            reasons = clean_reason.split(' + ')
            for r in set(reasons):
                is_win = 'ناجحة' in status or 'تأمين' in status
                if is_win:
                    stats[r]['wins'] += 1
                    stats[r]['win_pnl'] += pnl
                else:
                    stats[r]['losses'] += 1
                    stats[r]['loss_pnl'] += pnl
                stats[r]['total_pnl'] += pnl

        performance_data = {}
        for r, s in stats.items():
            total = s['wins'] + s['losses']
            win_rate = (s['wins'] / total * 100) if total > 0 else 0
            profit_factor = s['win_pnl'] / abs(s['loss_pnl']) if s['loss_pnl'] != 0 else float('inf')
            performance_data[r] = {
                "win_rate": round(win_rate, 2),
                "profit_factor": round(profit_factor, 2),
                "total_trades": total
            }
        bot_data.strategy_performance = performance_data
        logger.info(f"🧠 Adaptive Mind: Analysis complete for {len(performance_data)} strategies.")

    except Exception as e:
        logger.error(f"🧠 Adaptive Mind: Failed to analyze strategy performance: {e}", exc_info=True)


async def propose_strategy_changes(context: ContextTypes.DEFAULT_TYPE):
    settings = bot_data.settings
    if not settings.get('adaptive_intelligence_enabled') or not settings.get('strategy_proposal_enabled'):
        return

    logger.info("🧠 Adaptive Mind: Checking for underperforming strategies...")
    active_scanners = settings.get('active_scanners', [])
    min_trades = settings.get('strategy_analysis_min_trades', 10)
    deactivation_wr = settings.get('strategy_deactivation_threshold_wr', 45.0)

    for scanner in active_scanners:
        perf = bot_data.strategy_performance.get(scanner)
        if perf and perf['total_trades'] >= min_trades and perf['win_rate'] < deactivation_wr:
            if bot_data.pending_strategy_proposal.get('scanner') == scanner:
                continue

            proposal_key = f"prop_{int(time.time())}"
            bot_data.pending_strategy_proposal = {
                "key": proposal_key, "action": "disable", "scanner": scanner,
                "reason": f"أظهرت أداءً ضعيفًا بمعدل نجاح `{perf['win_rate']}%` في آخر `{perf['total_trades']}` صفقة."
            }
            logger.warning(f"🧠 Adaptive Mind: Proposing to disable '{scanner}'.")

            message = (f"💡 **اقتراح تحسين الأداء** 💡\n\n"
                       f"مرحباً، لاحظت أن استراتيجية **'{STRATEGY_NAMES_AR.get(scanner, scanner)}'** "
                       f"{bot_data.pending_strategy_proposal['reason']}\n\n"
                       f"أقترح تعطيلها مؤقتًا. هل توافق؟")

            keyboard = [[
                InlineKeyboardButton("✅ موافقة", callback_data=f"strategy_adjust_approve_{proposal_key}"),
                InlineKeyboardButton("❌ رفض", callback_data=f"strategy_adjust_reject_{proposal_key}")
            ]]
            await safe_send_message(context.bot, message, reply_markup=InlineKeyboardMarkup(keyboard))
            return

# --- العقل والماسحات ---
def find_col(df_columns, prefix):
    try: return next(col for col in df_columns if col.startswith(prefix))
    except StopIteration: return None

async def translate_text_gemini(text_list):
    if not GEMINI_API_KEY:
        logger.warning("GEMINI_API_KEY not found. Skipping translation.")
        return text_list, False
    if not text_list: return [], True
    prompt = "Translate the following English headlines to Arabic. Return only the translated text, with each headline on a new line:\n\n" + "\n".join(text_list)
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-pro:generateContent?key={GEMINI_API_KEY}"
    payload = {"contents": [{"parts": [{"text": prompt}]}]}
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post(url, json=payload, headers={"Content-Type": "application/json"})
            response.raise_for_status()
            result = response.json()
            translated_text = result['candidates'][0]['content']['parts'][0]['text']
            return translated_text.strip().split('\n'), True
    except Exception as e:
        logger.error(f"Gemini translation failed: {e}")
        return text_list, False

def get_alpha_vantage_economic_events():
    if not ALPHA_VANTAGE_API_KEY or ALPHA_VANTAGE_API_KEY == 'YOUR_AV_KEY_HERE': return []
    today_str = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    params = {'function': 'ECONOMIC_CALENDAR', 'horizon': '3month', 'apikey': ALPHA_VANTAGE_API_KEY}
    try:
        response = httpx.get('https://www.alphavantage.co/query', params=params, timeout=20)
        response.raise_for_status(); data_str = response.text
        if "premium" in data_str.lower(): return []
        lines = data_str.strip().split('\r\n')
        if len(lines) < 2: return []
        header = [h.strip() for h in lines[0].split(',')]
        events = [dict(zip(header, [v.strip() for v in line.split(',')])) for line in lines[1:]]
        high_impact_events = [e.get('event', 'Unknown Event') for e in events if e.get('releaseDate', '') == today_str and e.get('impact', '').lower() == 'high' and e.get('country', '') in ['USD', 'EUR']]
        if high_impact_events: logger.warning(f"High-impact events today: {high_impact_events}")
        return high_impact_events
    except httpx.RequestError as e: logger.error(f"Failed to fetch economic calendar: {e}"); return None

def get_latest_crypto_news(limit=15):
    urls = ["https://cointelegraph.com/rss", "https://www.coindesk.com/arc/outboundfeeds/rss/"]
    headlines = [entry.title for url in urls for entry in feedparser.parse(url).entries[:7]]
    return list(set(headlines))[:limit]

def analyze_sentiment_of_headlines(headlines):
    if not headlines or not NLTK_AVAILABLE: return "N/A", 0.0
    sia = SentimentIntensityAnalyzer()
    score = sum(sia.polarity_scores(h)['compound'] for h in headlines) / len(headlines)
    if score > 0.15: mood = "إيجابية"
    elif score < -0.15: mood = "سلبية"
    else: mood = "محايدة"
    return mood, score

async def get_fundamental_market_mood():
    settings = bot_data.settings
    if not settings.get('news_filter_enabled', True): return {"mood": "POSITIVE", "reason": "فلتر الأخبار معطل"}
    high_impact_events = await asyncio.to_thread(get_alpha_vantage_economic_events)
    if high_impact_events is None: return {"mood": "DANGEROUS", "reason": "فشل جلب البيانات الاقتصادية"}
    if high_impact_events: return {"mood": "DANGEROUS", "reason": f"أحداث هامة اليوم: {', '.join(high_impact_events)}"}
    latest_headlines = await asyncio.to_thread(get_latest_crypto_news)
    sentiment, score = analyze_sentiment_of_headlines(latest_headlines)
    logger.info(f"Market sentiment score: {score:.2f} ({sentiment})")
    if score > 0.25: return {"mood": "POSITIVE", "reason": f"مشاعر إيجابية (الدرجة: {score:.2f})"}
    elif score < -0.25: return {"mood": "NEGATIVE", "reason": f"مشاعر سلبية (الدرجة: {score:.2f})"}
    else: return {"mood": "NEUTRAL", "reason": f"مشاعر محايدة (الدرجة: {score:.2f})"}

async def get_fear_and_greed_index():
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get("https://api.alternative.me/fng/?limit=1", timeout=10)
            return int(r.json()['data'][0]['value'])
    except Exception: return None

async def get_market_mood():
    settings = bot_data.settings
    if settings.get('btc_trend_filter_enabled', True):
        try:
            htf_period = settings['trend_filters']['htf_period']
            ohlcv = await bot_data.exchange.fetch_ohlcv('BTC/USDT', '4h', limit=htf_period + 5)
            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df['sma'] = ta.sma(df['close'], length=htf_period)
            is_btc_bullish = df['close'].iloc[-1] > df['sma'].iloc[-1]
            btc_mood_text = "صاعد ✅" if is_btc_bullish else "هابط ❌"
            if not is_btc_bullish: return {"mood": "NEGATIVE", "reason": "اتجاه BTC هابط", "btc_mood": btc_mood_text}
        except Exception as e: return {"mood": "DANGEROUS", "reason": f"فشل جلب بيانات BTC: {e}", "btc_mood": "UNKNOWN"}
    else: btc_mood_text = "الفلتر معطل"
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
        recent_lows = df_1h['low'].rolling(window=10, center=True).min()
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

async def analyze_whale_radar(df, params, rvol, adx_value, exchange, symbol):
    try:
        ob = await exchange.fetch_order_book(symbol, limit=20)
        if not ob or not ob.get('bids'): return None
        if sum(float(price) * float(qty) for price, qty in ob['bids'][:10]) > 30000:
            return {"reason": "whale_radar"}
    except Exception: return None
    return None

def analyze_rsi_divergence(df, params, rvol, adx_value):
    if not SCIPY_AVAILABLE: return None
    df.ta.rsi(length=params.get('rsi_period', 14), append=True)
    rsi_col = find_col(df.columns, f"RSI_{params.get('rsi_period', 14)}")
    if not rsi_col or df[rsi_col].isnull().all(): return None
    subset = df.iloc[-params.get('lookback_period', 35):].copy()
    price_troughs_idx, _ = find_peaks(-subset['low'], distance=params.get('peak_trough_lookback', 5))
    rsi_troughs_idx, _ = find_peaks(-subset[rsi_col], distance=params.get('peak_trough_lookback', 5))
    if len(price_troughs_idx) >= 2 and len(rsi_troughs_idx) >= 2:
        p_low1_idx, p_low2_idx = price_troughs_idx[-2], price_troughs_idx[-1]
        r_low1_idx, r_low2_idx = rsi_troughs_idx[-2], rsi_troughs_idx[-1]
        is_divergence = (subset.iloc[p_low2_idx]['low'] < subset.iloc[p_low1_idx]['low'] and subset.iloc[r_low2_idx][rsi_col] > subset.iloc[r_low1_idx][rsi_col])
        if is_divergence:
            rsi_exits_oversold = (subset.iloc[r_low1_idx][rsi_col] < 35 and subset.iloc[-2][rsi_col] > 40)
            confirmation_price = subset.iloc[p_low2_idx:]['high'].max()
            price_confirmed = df.iloc[-2]['close'] > confirmation_price
            if (not params.get('confirm_with_rsi_exit', True) or rsi_exits_oversold) and price_confirmed:
                return {"reason": "rsi_divergence"}
    return None

def analyze_supertrend_pullback(df, params, rvol, adx_value):
    df.ta.supertrend(length=params.get('atr_period', 10), multiplier=params.get('atr_multiplier', 3.0), append=True)
    st_dir_col = find_col(df.columns, f"SUPERTd_{params.get('atr_period', 10)}_")
    if not st_dir_col: return None
    last, prev = df.iloc[-2], df.iloc[-3]
    if prev[st_dir_col] == -1 and last[st_dir_col] == 1:
        recent_swing_high = df['high'].iloc[-params.get('swing_high_lookback', 10):-2].max()
        if last['close'] > recent_swing_high:
            return {"reason": "supertrend_pullback"}
    return None

SCANNERS = {
    "momentum_breakout": analyze_momentum_breakout, "breakout_squeeze_pro": analyze_breakout_squeeze_pro,
    "support_rebound": analyze_support_rebound, "sniper_pro": analyze_sniper_pro, "whale_radar": analyze_whale_radar,
    "rsi_divergence": analyze_rsi_divergence, "supertrend_pullback": analyze_supertrend_pullback
}

# --- محرك التداول ---
async def get_okx_markets():
    settings = bot_data.settings
    if time.time() - bot_data.last_markets_fetch > 300:
        try:
            logger.info("Fetching and caching all OKX markets..."); all_tickers = await bot_data.exchange.fetch_tickers()
            bot_data.all_markets = list(all_tickers.values()); bot_data.last_markets_fetch = time.time()
        except Exception as e: logger.error(f"Failed to fetch all markets: {e}"); return []
    blacklist = settings.get('asset_blacklist', [])
    valid_markets = [t for t in bot_data.all_markets if 'USDT' in t['symbol'] and t.get('quoteVolume', 0) > settings['liquidity_filters']['min_quote_volume_24h_usd'] and t['symbol'].split('/')[0] not in blacklist and t.get('active', True) and not any(k in t['symbol'] for k in ['-SWAP', 'UP', 'DOWN', '3L', '3S'])]
    valid_markets.sort(key=lambda m: m.get('quoteVolume', 0), reverse=True)
    return valid_markets[:settings['top_n_symbols_by_volume']]

async def fetch_ohlcv_batch(exchange, symbols, timeframe, limit):
    tasks = [exchange.fetch_ohlcv(s, timeframe, limit=limit) for s in symbols]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    return {symbols[i]: results[i] for i in range(len(symbols)) if not isinstance(results[i], Exception)}

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

            orderbook = await exchange.fetch_order_book(symbol, limit=1)
            if not orderbook['bids'] or not orderbook['asks']:
                queue.task_done(); continue

            best_bid, best_ask = orderbook['bids'][0][0], orderbook['asks'][0][0]
            if best_bid <= 0:
                queue.task_done(); continue
            spread_percent = ((best_ask - best_bid) / best_bid) * 100

            if 'whale_radar' in settings['active_scanners']:
                whale_radar_signal = await analyze_whale_radar(df.copy(), {}, 0, 0, exchange, symbol)
                if whale_radar_signal and spread_percent <= settings['spread_filter']['max_spread_percent'] * 2:
                    reason_str, strength = whale_radar_signal['reason'], 5
                    entry_price = df.iloc[-2]['close']
                    df.ta.atr(length=14, append=True)
                    atr = df.iloc[-2].get(find_col(df.columns, "ATRr_14"), 0)
                    risk = atr * settings['atr_sl_multiplier']
                    stop_loss, take_profit = entry_price - risk, entry_price + (risk * settings['risk_reward_ratio'])
                    signals_list.append({"symbol": symbol, "entry_price": entry_price, "take_profit": take_profit, "stop_loss": stop_loss, "reason": reason_str, "strength": strength, "weight": 1.0})
                    queue.task_done();

            if spread_percent > settings['spread_filter']['max_spread_percent']:
                queue.task_done(); continue

            is_htf_bullish = True
            if settings.get('multi_timeframe_enabled', True):
                ohlcv_htf = await exchange.fetch_ohlcv(symbol, settings.get('multi_timeframe_htf'), limit=220)
                df_htf = pd.DataFrame(ohlcv_htf, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                if len(df_htf) > 200:
                    df_htf.ta.ema(length=200, append=True)
                    ema_col_name_htf = find_col(df_htf.columns, "EMA_200")
                    if ema_col_name_htf and pd.notna(df_htf[ema_col_name_htf].iloc[-2]):
                        is_htf_bullish = df_htf['close'].iloc[-2] > df_htf[ema_col_name_htf].iloc[-2]

            if settings.get('trend_filters', {}).get('enabled', True):
                ema_period = settings.get('trend_filters', {}).get('ema_period', 200)
                if len(df) < ema_period + 1:
                    queue.task_done(); continue
                df.ta.ema(length=ema_period, append=True)
                ema_col_name = find_col(df.columns, f"EMA_{ema_period}")
                if not ema_col_name or pd.isna(df[ema_col_name].iloc[-2]):
                    queue.task_done(); continue
                if df['close'].iloc[-2] < df[ema_col_name].iloc[-2]:
                    queue.task_done(); continue

            vol_filters = settings.get('volatility_filters', {})
            atr_period, min_atr_percent = vol_filters.get('atr_period_for_filter', 14), vol_filters.get('min_atr_percent', 0.8)
            df.ta.atr(length=atr_period, append=True)
            atr_col_name = find_col(df.columns, f"ATRr_{atr_period}")
            if not atr_col_name or pd.isna(df[atr_col_name].iloc[-2]):
                queue.task_done(); continue
            last_close = df['close'].iloc[-2]
            atr_percent = (df[atr_col_name].iloc[-2] / last_close) * 100 if last_close > 0 else 0
            if atr_percent < min_atr_percent:
                queue.task_done(); continue

            df['volume_sma'] = ta.sma(df['volume'], length=20)
            if pd.isna(df['volume_sma'].iloc[-2]) or df['volume_sma'].iloc[-2] == 0:
                queue.task_done(); continue
            rvol = df['volume'].iloc[-2] / df['volume_sma'].iloc[-2]
            if rvol < settings.get('volume_filter_multiplier', 2.0):
                queue.task_done(); continue

            adx_value = 0
            if settings.get('adx_filter_enabled', False):
                df.ta.adx(append=True); adx_col = find_col(df.columns, "ADX_")
                adx_value = df[adx_col].iloc[-2] if adx_col and pd.notna(df[adx_col].iloc[-2]) else 0
                if adx_value < settings.get('adx_filter_level', 25):
                    queue.task_done(); continue

            confirmed_reasons = []
            for name in settings['active_scanners']:
                if name == 'whale_radar': continue
                if not (strategy_func := SCANNERS.get(name)): continue
                params = settings.get(name, {})
                func_args = {'df': df.copy(), 'params': params, 'rvol': rvol, 'adx_value': adx_value}
                if name in ['support_rebound', 'whale_radar']:
                    func_args.update({'exchange': exchange, 'symbol': symbol})
                result = await strategy_func(**func_args) if asyncio.iscoroutinefunction(strategy_func) else strategy_func(**{k: v for k, v in func_args.items() if k not in ['exchange', 'symbol']})
                if result: confirmed_reasons.append(result['reason'])

            if confirmed_reasons:
                reason_str, strength = ' + '.join(set(confirmed_reasons)), len(set(confirmed_reasons))

                trade_weight = 1.0
                if settings.get('adaptive_intelligence_enabled', True):
                    primary_reason = confirmed_reasons[0]
                    perf = bot_data.strategy_performance.get(primary_reason)
                    if perf:
                        if perf['win_rate'] < 50 and perf['total_trades'] > 5:
                            trade_weight = 1 - (settings['dynamic_sizing_max_decrease_pct'] / 100.0)
                        elif perf['win_rate'] > 70 and perf['profit_factor'] > 1.5:
                            trade_weight = 1 + (settings['dynamic_sizing_max_increase_pct'] / 100.0)

                        if perf['win_rate'] < settings['strategy_deactivation_threshold_wr'] and perf['total_trades'] > settings['strategy_analysis_min_trades']:
                           logger.warning(f"Signal for {symbol} from weak strategy '{primary_reason}' ignored.")
                           queue.task_done(); continue

                if not is_htf_bullish:
                    strength = max(1, int(strength / 2))
                    reason_str += " (اتجاه كبير ضعيف)"
                    trade_weight *= 0.8

                entry_price = df.iloc[-2]['close']
                df.ta.atr(length=14, append=True)
                atr = df.iloc[-2].get(find_col(df.columns, "ATRr_14"), 0)
                risk = atr * settings['atr_sl_multiplier']
                stop_loss, take_profit = entry_price - risk, entry_price + (risk * settings['risk_reward_ratio'])
                signals_list.append({"symbol": symbol, "entry_price": entry_price, "take_profit": take_profit, "stop_loss": stop_loss, "reason": reason_str, "strength": strength, "weight": trade_weight})

            queue.task_done()
        except Exception as e:
            if 'symbol' in locals():
                logger.error(f"Error processing symbol {symbol}: {e}", exc_info=True)
                errors_list.append(symbol)
            else:
                logger.error(f"Worker error with no symbol context: {e}", exc_info=True)
            if not queue.empty():
                queue.task_done()


async def handle_order_update(order_data):
    """يتم استدعاؤها عند ورود تحديث لأمر من مراسل البيانات."""
    # تكييف مع تنسيق OKX: order_data من channel 'orders', state 'filled', side 'buy'
    if order_data.get('state') == 'filled' and order_data.get('side') == 'buy':
        logger.info(f"Fast Reporter: Received fill for order {order_data['ordId']}. Activating trade...")
        await activate_trade(order_data['ordId'], order_data['instId'])

async def activate_trade(order_id, symbol):
    """
    الدالة المحورية لتفعيل الصفقة بعد التأكد من تنفيذها.
    تقوم بتحديث قاعدة البيانات وإرسال الإشعار التفصيلي.
    """
    bot = bot_data.application.bot
    try:
        order_details = await bot_data.exchange.fetch_order(order_id, symbol)
        filled_price = float(order_details.get('average', 0.0))
        net_filled_quantity = float(order_details.get('filled', 0.0))

        if net_filled_quantity <= 0 or filled_price <= 0:
            logger.error(f"Order {order_id} invalid fill data. Cancelling activation.")
            return

    except Exception as e:
        logger.error(f"Could not fetch order details for activation of {order_id}: {e}", exc_info=True)
        return

    async with aiosqlite.connect(DB_FILE) as conn:
        conn.row_factory = aiosqlite.Row
        trade = await (await conn.execute("SELECT * FROM trades WHERE order_id = ? AND status = 'pending'", (order_id,))).fetchone()

        if not trade:
            logger.info(f"Activation ignored for {order_id}: Trade not found or not pending.")
            return

        trade = dict(trade)
        logger.info(f"Activating trade #{trade['id']} for {symbol}...")

        risk = filled_price - trade['stop_loss']
        new_take_profit = filled_price + (risk * bot_data.settings['risk_reward_ratio'])

        await conn.execute(
            "UPDATE trades SET status = 'active', entry_price = ?, quantity = ?, take_profit = ?, last_profit_notification_price = ? WHERE id = ?",
            (filled_price, net_filled_quantity, new_take_profit, filled_price, trade['id'])
        )
        active_trades_count = (await (await conn.execute("SELECT COUNT(*) FROM trades WHERE status = 'active'")).fetchone())[0]
        await conn.commit()

    await bot_data.websocket_manager.sync_subscriptions()

    balance_after = await bot_data.exchange.fetch_balance()
    usdt_remaining = balance_after.get('USDT', {}).get('free', 0)
    trade_cost = filled_price * net_filled_quantity
    tp_percent = (new_take_profit / filled_price - 1) * 100
    sl_percent = (1 - trade['stop_loss'] / filled_price) * 100
    reasons_ar = ' + '.join([STRATEGY_NAMES_AR.get(r.strip(), r.strip()) for r in trade['reason'].split(' + ')])
    strength_stars = '⭐' * trade.get('signal_strength', 1)

    success_msg = (
        f"✅ **تم تأكيد الشراء | {symbol}**\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"**الاستراتيجية:** {reasons_ar} {strength_stars}\n"
        f"**تفاصيل الصفقة:**\n"
        f"  - **رقم:** `#{trade['id']}`\n"
        f"  - **سعر التنفيذ:** `${filled_price:,.4f}`\n"
        f"  - **الكمية:** `{net_filled_quantity:,.4f}`\n"
        f"  - **التكلفة الإجمالية:** `${trade_cost:,.2f}`\n"
        f"**الأهداف:**\n"
        f"  - **الهدف (TP):** `${new_take_profit:,.4f}` `({tp_percent:+.2f}%)`\n"
        f"  - **الوقف (SL):** `${trade['stop_loss']:,.4f}` `({sl_percent:.2f}%)`\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"💰 **السيولة المتبقية:** `${usdt_remaining:,.2f}`\n"
        f"🔄 **الصفقات النشطة:** `{active_trades_count}`"
    )
    await safe_send_message(bot, success_msg)

async def has_active_trade_for_symbol(symbol: str) -> bool:
    """Checks the database for an existing 'active' or 'pending' trade for the given symbol."""
    try:
        async with aiosqlite.connect(DB_FILE) as conn:
            cursor = await conn.execute(
                "SELECT 1 FROM trades WHERE symbol = ? AND status IN ('active', 'pending') LIMIT 1",
                (symbol,)
            )
            result = await cursor.fetchone()
            return result is not None
    except Exception as e:
        logger.error(f"Database check for active trade failed for {symbol}: {e}")
        return True

async def initiate_real_trade(signal):
    if not bot_data.trading_enabled:
        logger.warning(f"Trade for {signal['symbol']} blocked: Kill Switch active."); return False

    try:
        settings, exchange = bot_data.settings, bot_data.exchange
        base_trade_size = settings['real_trade_size_usdt']
        trade_weight = signal.get('weight', 1.0)
        trade_size = base_trade_size * trade_weight if settings.get('dynamic_trade_sizing_enabled', True) else base_trade_size

        # --- [الإصلاح الحاسم] التحقق من الحد الأدنى لقيمة الصفقة (تكييف مع OKX: استخدام 'cost' limits) ---
        try:
            market = exchange.market(signal['symbol'])
            # في OKX عبر CCXT، 'notional' قد يكون تحت 'cost'
            min_notional_str = market.get('limits', {}).get('notional', {}).get('min') or market.get('limits', {}).get('cost', {}).get('min')

            if min_notional_str is not None:
                min_notional_value = float(min_notional_str)
                required_size = min_notional_value * 1.05 

                if trade_size < required_size:
                    logger.warning(f"Trade for {signal['symbol']} aborted. Trade size ({trade_size:.2f} USDT) is below the required minimum notional value with safety margin ({required_size:.2f} USDT).")
                    return False
        except Exception as e:
            logger.error(f"Could not fetch market rules for {signal['symbol']}: {e}. Skipping trade to be safe.")
            return False
        # --- [نهاية الإصلاح] ---

        balance = await exchange.fetch_balance()
        usdt_balance = balance.get('USDT', {}).get('free', 0.0)

        if usdt_balance < trade_size:
            logger.error(f"Insufficient USDT for {signal['symbol']}. Have: {usdt_balance:,.2f}, Need: {trade_size:,.2f}"); return False

        base_amount = trade_size / signal['entry_price']
        formatted_amount = exchange.amount_to_precision(signal['symbol'], base_amount)

        buy_order = await exchange.create_market_buy_order(signal['symbol'], formatted_amount)

        if await log_pending_trade_to_db(signal, buy_order):
            await safe_send_message(bot_data.application.bot, f"🚀 تم إرسال أمر شراء لـ `{signal['symbol']}`. في انتظار تأكيد التنفيذ...")
            return True
        else:
            logger.critical(f"CRITICAL: Failed to log pending trade for {signal['symbol']}. Cancelling order {buy_order['id']}.")
            await exchange.cancel_order(buy_order['id'], signal['symbol'])
            return False

    except ccxt.InsufficientFunds as e:
        logger.error(f"REAL TRADE FAILED {signal['symbol']}: {e}", exc_info=True)
        return False
    except Exception as e:
        logger.error(f"REAL TRADE FAILED {signal['symbol']}: {e}", exc_info=True)
        return False

async def perform_scan(context: ContextTypes.DEFAULT_TYPE):
    async with scan_lock:
        if not bot_data.trading_enabled:
            logger.warning("Scan skipped: Trading is disabled by circuit breaker or manually.")
            return

        scan_start_time = time.time()
        logger.info("--- Starting new Intelligent Engine scan... ---")
        settings, bot = bot_data.settings, context.bot

        try:
            balance = await bot_data.exchange.fetch_balance()
            usdt_balance = balance.get('USDT', {}).get('free', 0.0)
            trade_size_min_check = settings['real_trade_size_usdt'] * 0.98
            if usdt_balance < trade_size_min_check:
                logger.error(f"Scan skipped: Insufficient USDT balance ({usdt_balance:,.2f} < {trade_size_min_check:,.2f}) to open a trade.")
                return
        except Exception as e:
            logger.error(f"Failed to fetch balance for scan check: {e}"); return

        if settings.get('news_filter_enabled', True):
            mood_result_fundamental = await get_fundamental_market_mood()
            if mood_result_fundamental['mood'] in ["NEGATIVE", "DANGEROUS"]:
                bot_data.market_mood = mood_result_fundamental; return

        mood_result = await get_market_mood()
        bot_data.market_mood = mood_result
        if mood_result['mood'] in ["NEGATIVE", "DANGEROUS"]: return

        async with aiosqlite.connect(DB_FILE) as conn:
            active_trades_count = (await (await conn.execute("SELECT COUNT(*) FROM trades WHERE status = 'active' OR status = 'pending'")).fetchone())[0]

        if active_trades_count >= settings['max_concurrent_trades']:
            logger.info(f"Scan skipped: Max trades ({active_trades_count}) reached."); return

        top_markets = await get_okx_markets()
        if not top_markets:
             logger.warning("Scan could not retrieve any markets to check.")
             return

        symbols_to_scan = [m['symbol'] for m in top_markets]
        ohlcv_data = await fetch_ohlcv_batch(bot_data.exchange, symbols_to_scan, TIMEFRAME, 220)

        queue, signals_found, analysis_errors = asyncio.Queue(), [], []
        for market in top_markets:
            if market['symbol'] in ohlcv_data:
                await queue.put({'market': market, 'ohlcv': ohlcv_data[market['symbol']]})

        worker_tasks = [asyncio.create_task(worker_batch(queue, signals_found, analysis_errors)) for _ in range(settings.get("worker_threads", 10))]
        await queue.join()
        for task in worker_tasks: task.cancel()

        trades_opened_count = 0
        signals_found.sort(key=lambda s: s.get('strength', 0), reverse=True)

        # --- [الحل النهائي لمشكلة سباق الشراء V6.7] ---
        balance_lock = asyncio.Lock()
        available_slots = settings['max_concurrent_trades'] - active_trades_count
        symbols_being_traded_in_this_scan = set()

        for signal in signals_found:
            if available_slots <= 0:
                logger.info("Stopping trade initiation, max concurrent trade slots filled for this cycle.")
                break

            symbol_to_trade = signal['symbol']

            if symbol_to_trade in symbols_being_traded_in_this_scan:
                logger.warning(f"Signal for {symbol_to_trade} ignored: A trade for this symbol is already being processed in THIS scan cycle.")
                continue

            if await has_active_trade_for_symbol(symbol_to_trade):
                logger.info(f"Signal for {symbol_to_trade} ignored: An active trade for this symbol already exists in the database.")
                continue

            if time.time() - bot_data.last_signal_time.get(symbol_to_trade, 0) > (SCAN_INTERVAL_SECONDS * 0.9):
                async with balance_lock:
                    try:
                        # التحقق من الرصيد الفعلي مباشرة قبل إرسال الأمر
                        balance = await bot_data.exchange.fetch_balance()
                        usdt_balance = balance.get('USDT', {}).get('free', 0.0)
                        required_size = settings['real_trade_size_usdt']

                        if usdt_balance >= required_size:
                            logger.info(f"Balance OK ({usdt_balance:.2f} USDT). Proceeding with trade for {symbol_to_trade}.")
                            bot_data.last_signal_time[symbol_to_trade] = time.time()
                            symbols_being_traded_in_this_scan.add(symbol_to_trade)

                            if await initiate_real_trade(signal):
                                trades_opened_count += 1
                                available_slots -= 1 # تقليل عدد الصفقات المتاحة لهذه الدورة
                            else:
                                symbols_being_traded_in_this_scan.remove(symbol_to_trade)

                            await asyncio.sleep(2) # إعطاء فرصة للمنصة لتحديث الرصيد
                        else:
                            logger.warning(f"Stopping trade search: Insufficient final balance for {symbol_to_trade} ({usdt_balance:.2f} USDT).")
                            # نوقف البحث عن صفقات جديدة إذا لم يعد هناك رصيد
                            break 
                    except Exception as e:
                        logger.error(f"Error during balance check for {symbol_to_trade}: {e}")
        # --- [نهاية الحل] ---

        scan_duration = time.time() - scan_start_time
        bot_data.last_scan_info = {"start_time": datetime.fromtimestamp(scan_start_time, EGYPT_TZ).strftime('%Y-%m-%d %H:%M:%S'), "duration_seconds": int(scan_duration), "checked_symbols": len(top_markets), "analysis_errors": len(analysis_errors)}
        await safe_send_message(bot, f"✅ **فحص السوق اكتمل بنجاح**\n"
                                   f"━━━━━━━━━━━━━━━━━━\n"
                                   f"**المدة:** {int(scan_duration)} ثانية | **العملات المفحوصة:** {len(top_markets)}\n"
                                   f"**النتائج:**\n"
                                   f"  - **إشارات جديدة:** {len(signals_found)}\n"
                                   f"  - **صفقات تم فتحها:** {trades_opened_count} صفقة\n"
                                   f"  - **مشكلات تحليل:** {len(analysis_errors)} عملة")

# =======================================================================================
# --- [FINAL VERSION] Unified OKX WebSocket Manager (SPOT-CORRECTED) ---
# =======================================================================================
class OKXWebSocketManager:
    """
    فئة موحدة لإدارة اتصالات WebSocket مع OKX (بيانات عامة وخاصة).
    تدعم اتصالين منفصلين: public للتيكرز، private لأوامر المستخدم مع مصادقة.
    """
    def __init__(self, exchange, application):
        self.exchange = exchange
        self.application = application
        self.public_subscriptions = set()
        self.public_ws = None
        self.private_ws = None
        self.is_running = False
        self.conn_id = None

    def _generate_signature(self, timestamp, method, request_path, secret):
        message = timestamp + method + request_path
        signature = hmac.new(secret.encode('utf-8'), message.encode('utf-8'), hashlib.sha256).digest()
        return base64.b64encode(signature).decode('utf-8')

    async def _login_private(self):
        try:
            timestamp = str(int(time.time()))
            method = 'GET'
            request_path = '/users/self/verify'
            sign = self._generate_signature(timestamp, method, request_path, OKX_API_SECRET)
            login_payload = {
                "op": "login",
                "args": [{
                    "apiKey": OKX_API_KEY,
                    "passphrase": OKX_API_PASSWORD,
                    "timestamp": timestamp,
                    "sign": sign
                }]
            }
            await self.private_ws.send(json.dumps(login_payload))
            response = json.loads(await asyncio.wait_for(self.private_ws.recv(), timeout=10.0))
            if response.get('event') == 'login' and response.get('code') == '0':
                self.conn_id = response.get('connId')
                logger.info("OKX WebSocket Manager: Private login successful.")
                return True
            else:
                logger.error(f"OKX WebSocket Manager: Private login failed: {response}")
                return False
        except Exception as e:
            logger.error(f"OKX WebSocket Manager: Login error: {e}")
            return False

    # --- [الإضافة الجديدة] دالة تنسيق مدة الصفقة ---
    def _format_duration(self, duration_delta: timedelta) -> str:
        """
        Formats a timedelta object into a readable Arabic string (days, hours, minutes).
        """
        seconds = duration_delta.total_seconds()

        if seconds < 60:
            return "أقل من دقيقة"

        days, remainder = divmod(seconds, 86400)
        hours, remainder = divmod(remainder, 3600)
        minutes, _ = divmod(remainder, 60)

        parts = []
        if days > 0:
            parts.append(f"{int(days)} يوم")
        if hours > 0:
            parts.append(f"{int(hours)} ساعة")
        if minutes > 0:
            parts.append(f"{int(minutes)} دقيقة")

        return " و ".join(parts)

    async def run(self):
        self.is_running = True

        # تشغيل اتصال public و private بشكل متوازي
        public_task = asyncio.create_task(self._run_public_ws())
        private_task = asyncio.create_task(self._run_private_ws())

        await asyncio.gather(public_task, private_task, return_exceptions=True)

    async def _run_public_ws(self):
        while self.is_running:
            uri = "wss://ws.okx.com:8443/ws/v5/public"  # Production
            try:
                async with websockets.connect(uri, ping_interval=20, ping_timeout=10) as ws:
                    self.public_ws = ws
                    logger.info("OKX WebSocket Manager: Public WS connected.")
                    await self._subscribe_public(ws)
                    async for message in ws:
                        await self._handle_public_message(message)
            except Exception as e:
                if self.is_running:
                    logger.warning(f"OKX Public WS: Connection lost: {e}. Reconnecting in 5s...")
                    await asyncio.sleep(5)

    async def _run_private_ws(self):
        while self.is_running:
            uri = "wss://ws.okx.com:8443/ws/v5/private"  # Production
            try:
                async with websockets.connect(uri, ping_interval=20, ping_timeout=10) as ws:
                    self.private_ws = ws
                    logger.info("OKX WebSocket Manager: Private WS connected.")
                    if await self._login_private():
                        await self._subscribe_private(ws)
                        async for message in ws:
                            await self._handle_private_message(message)
                    else:
                        await asyncio.sleep(60)
            except Exception as e:
                if self.is_running:
                    logger.warning(f"OKX Private WS: Connection lost: {e}. Reconnecting in 5s...")
                    await asyncio.sleep(5)

    async def _subscribe_public(self, ws):
        if not self.public_subscriptions:
            return
        args = [{"channel": "tickers", "instType": "SPOT", "instId": sym.replace('/', '-')} for sym in self.public_subscriptions]
        subscribe_payload = {"op": "subscribe", "args": args}
        await ws.send(json.dumps(subscribe_payload))
        logger.info(f"OKX Public WS: Subscribed to {len(args)} tickers.")

    async def _subscribe_private(self, ws):
        subscribe_payload = {"op": "subscribe", "args": [{"channel": "orders", "instType": "SPOT"}]}
        await ws.send(json.dumps(subscribe_payload))
        logger.info("OKX Private WS: Subscribed to orders channel.")

    async def _handle_public_message(self, message):
        try:
            data = json.loads(message)
            if data.get('arg', {}).get('channel') == 'tickers':
                ticker_data = data['data'][0] if data['data'] else {}
                await self._handle_ticker_update(ticker_data)
        except Exception as e:
            logger.error(f"Error handling public message: {e}")

    async def _handle_private_message(self, message):
        try:
            data = json.loads(message)
            if data.get('arg', {}).get('channel') == 'orders':
                order_data = data['data'][0] if data['data'] else {}
                await handle_order_update(order_data)
        except Exception as e:
            logger.error(f"Error handling private message: {e}")

    async def _handle_ticker_update(self, ticker_data):
        symbol = ticker_data.get('instId', '').replace('-', '/')
        current_price = float(ticker_data.get('last', 0))

        async with trade_management_lock:
            try:
                async with aiosqlite.connect(DB_FILE) as conn:
                    conn.row_factory = aiosqlite.Row
                    trade = await (await conn.execute("SELECT * FROM trades WHERE symbol = ? AND status IN ('active', 'force_exit', 'retry_exit')", (symbol,))).fetchone()

                    if not trade:
                        return

                    trade = dict(trade)
                    settings = bot_data.settings

                    # --- [منطق الإغلاق الموحد] ---
                    should_close = False
                    close_reason = ""

                    # 1. التحقق من توصيات المستشارين
                    if trade['status'] == 'force_exit':
                        should_close = True
                        close_reason = "فاشلة (بأمر الرجل الحكيم)"
                    elif trade['status'] == 'retry_exit':
                        should_close = True
                        close_reason = "فاشلة (SL-Incubator)"

                    # 2. التحقق من الأهداف السعرية (فقط إذا كانت الصفقة نشطة)
                    if not should_close and trade['status'] == 'active':
                        if current_price >= trade['take_profit']: 
                            should_close = True
                            close_reason = "ناجحة (TP)"
                        elif current_price <= trade['stop_loss']:
                            should_close = True
                            reason = "فاشلة (SL)"
                            if trade.get('trailing_sl_active', False):
                                reason = "تم تأمين الربح (TSL)" if current_price > trade['entry_price'] else "فاشلة (TSL)"
                            close_reason = reason

                    # --- [التنفيذ] ---
                    if should_close:
                        await self._close_trade(conn, trade, close_reason, current_price)
                        return

                    # --- [منطق إدارة الصفقات النشطة (يعمل فقط إذا لم يكن هناك قرار إغلاق)] ---
                    if trade['status'] == 'active':
                        highest_price = max(trade.get('highest_price', 0), current_price)
                        if highest_price > trade.get('highest_price', 0):
                            await conn.execute("UPDATE trades SET highest_price = ? WHERE id = ?", (highest_price, trade['id']))

                        # منطق الوقف المتحرك (كامل كما هو في ملفك)
                        if settings['trailing_sl_enabled']:
                            if not trade.get('trailing_sl_active', False) and current_price >= trade['entry_price'] * (1 + settings['trailing_sl_activation_percent'] / 100):
                                new_sl = trade['entry_price'] * 1.001
                                if new_sl > trade['stop_loss']:
                                    await conn.execute("UPDATE trades SET trailing_sl_active = 1, stop_loss = ? WHERE id = ?", (new_sl, trade['id']))
                                    await safe_send_message(self.application.bot, f"🚀 **تأمين الأرباح! | #{trade['id']} {trade['symbol']}**\nتم رفع وقف الخسارة إلى نقطة الدخول: `${new_sl:.4f}`")

                            if trade.get('trailing_sl_active', False):
                                current_sl_res = await (await conn.execute("SELECT stop_loss FROM trades WHERE id = ?", (trade['id'],))).fetchone()
                                if current_sl_res:
                                    current_sl = current_sl_res[0]
                                    new_sl_candidate = highest_price * (1 - settings['trailing_sl_callback_percent'] / 100)
                                    if new_sl_candidate > current_sl:
                                        await conn.execute("UPDATE trades SET stop_loss = ? WHERE id = ?", (new_sl_candidate, trade['id']))

                        # منطق إشعارات الربح (مع إضافة منطق "حلب العملة")
                        if settings.get('incremental_notifications_enabled', True):
                            last_notified = trade.get('last_profit_notification_price', trade['entry_price'])
                            increment = settings.get('incremental_notification_percent', 2.0) / 100
                            if current_price >= last_notified * (1 + increment):
                                profit_percent = ((current_price / trade['entry_price']) - 1) * 100
                                await safe_send_message(self.application.bot, f"📈 **ربح متزايد! | #{trade['id']} {trade['symbol']}**\n**الربح الحالي:** `{profit_percent:+.2f}%`")
                                await conn.execute("UPDATE trades SET last_profit_notification_price = ? WHERE id = ?", (current_price, trade['id']))

                                # --- [إضافة منطق حلب العملة هنا] ---
                                cooldown_minutes = settings.get('wise_guardian_cooldown_minutes', 15)
                                last_analysis_time = bot_data.last_deep_analysis_time.get(trade['id'], 0)
                                if (time.time() - last_analysis_time) > (cooldown_minutes * 60):
                                    bot_data.last_deep_analysis_time[trade['id']] = time.time()
                                    updated_trade = dict(trade)
                                    updated_trade['last_profit_notification_price'] = current_price
                                    asyncio.create_task(wise_man.check_for_strong_momentum(updated_trade))
                                # --- [نهاية الإضافة] ---

                        # منطق الحارس الحكيم (قطع الخسائر)
                        if settings.get('wise_guardian_enabled', True) and trade.get('highest_price', 0) > 0:
                            drawdown_pct = ((current_price / trade['highest_price']) - 1) * 100
                            trigger_pct = settings.get('wise_guardian_trigger_pct', -1.5)

                            if drawdown_pct < trigger_pct:
                                cooldown_minutes = settings.get('wise_guardian_cooldown_minutes', 15)
                                last_analysis_time = bot_data.last_deep_analysis_time.get(trade['id'], 0)

                                if (time.time() - last_analysis_time) > (cooldown_minutes * 60):
                                    bot_data.last_deep_analysis_time[trade['id']] = time.time()
                                    asyncio.create_task(wise_man.perform_deep_analysis(trade))

                        await conn.commit()

            except Exception as e:
                logger.error(f"Guardian Ticker Error for {symbol}: {e}", exc_info=True)

    # --- [الدالة المُرقاة] ---
    async def _close_trade(self, conn, trade, reason, close_price):
        symbol, trade_id = trade['symbol'], trade['id']
        bot = self.application.bot

        try:
            # نستخدم IN ('active', ...) لضمان أننا نلتقط الصفقات التي أمر الرجل الحكيم أو المشرف بإغلاقها
            cursor = await conn.execute("UPDATE trades SET status = 'closing' WHERE id = ? AND status IN ('active', 'retry_exit', 'force_exit')", (trade_id,))
            await conn.commit()
            if cursor.rowcount == 0:
                logger.warning(f"Closure for trade #{trade_id} ignored; another process is already closing it.")
                return
        except Exception as e:
            logger.error(f"CRITICAL DB ACTION FAILED for trade #{trade_id}: {e}")
            return

        logger.info(f"Guardian: Attempting ULTIMATE robust closure for trade #{trade_id} [{symbol}]. Reason: {reason}")

        try:
            base_currency = symbol.split('/')[0]
            logger.info(f"[{symbol}] Fetching true current balance from exchange...")
            balance = await bot_data.exchange.fetch_balance()
            available_quantity = balance.get(base_currency, {}).get('free', 0.0)

            if available_quantity <= 0:
                logger.warning(f"[{symbol}] No available balance found. Cleaning up trade #{trade_id} as if closed.")
                await conn.execute("UPDATE trades SET status = ?, close_price = ?, pnl_usdt = ? WHERE id = ?", (f"{reason} (No Balance)", close_price, 0.0, trade_id))
                await conn.commit()
                await self.sync_subscriptions()
                return

            import math
            market = bot_data.exchange.market(symbol)

            step_size_str = market.get('limits', {}).get('amount', {}).get('step')
            if step_size_str and float(step_size_str) > 0:
                step_size_float = float(step_size_str)
                quantity_to_sell = math.floor(available_quantity / step_size_float) * step_size_float
            else:
                quantity_to_sell = float(bot_data.exchange.amount_to_precision(symbol, available_quantity))

            logger.info(f"[{symbol}] Final formatted quantity to sell: {quantity_to_sell}")

            # فحص الحد الأدنى للكمية
            min_qty_str = market.get('limits', {}).get('amount', {}).get('min')
            if min_qty_str and quantity_to_sell < float(min_qty_str):
                 raise ccxt.InvalidOrder(f"Final quantity {quantity_to_sell} is below the exchange's minimum amount of {min_qty_str}.")

            # --- [الإضافة الحاسمة هنا] ---
            # فحص الحد الأدنى لقيمة الصفقة (تكييف مع OKX)
            min_notional_str = market.get('limits', {}).get('notional', {}).get('min') or market.get('limits', {}).get('cost', {}).get('min')
            if min_notional_str and (quantity_to_sell * close_price) < float(min_notional_str):
                raise ccxt.InvalidOrder(f"Total trade value is below minimum notional. Value: {quantity_to_sell * close_price}, Min Required: {min_notional_str}")
            # --- [نهاية الإضافة] ---

            await bot_data.exchange.create_market_sell_order(symbol, quantity_to_sell)

            # --- 1. حساب النتائج المالية النهائية ---
            pnl = (close_price - trade['entry_price']) * quantity_to_sell
            pnl_percent = (close_price / trade['entry_price'] - 1) * 100 if trade['entry_price'] > 0 else 0
            is_profit = pnl >= 0

            # --- 2. تحديث قاعدة البيانات ---
            await conn.execute("UPDATE trades SET status = ?, close_price = ?, pnl_usdt = ? WHERE id = ?", (reason, close_price, pnl, trade_id))
            await conn.commit()

            # --- 3. مزامنة الاشتراكات ---
            await self.sync_subscriptions()

            # --- 4. حساب المقاييس الجديدة للرسالة التحليلية ---
            try:
                # حساب مدة الصفقة
                trade_entry_time = datetime.fromisoformat(trade['timestamp'])
                duration_delta = datetime.now(EGYPT_TZ) - trade_entry_time
                trade_duration = self._format_duration(duration_delta)

                # حساب كفاءة الخروج (فقط للصفقات الرابحة)
                exit_efficiency_str = ""
                if is_profit and trade.get('highest_price', 0) > trade['entry_price']:
                    peak_gain = trade['highest_price'] - trade['entry_price']
                    actual_gain = close_price - trade['entry_price']
                    if peak_gain > 0:
                        efficiency = min((actual_gain / peak_gain) * 100, 100.0)
                        exit_efficiency_str = f"🧠 *كفاءة الخروج:* {efficiency:.2f}%\n"
            except Exception as e:
                logger.error(f"Error calculating metrics for report on trade #{trade_id}: {e}")
                trade_duration = "غير معروف"
                exit_efficiency_str = ""

            # --- 5. صياغة وإرسال الرسالة الجديدة المفصلة ---
            title = "✅ ملف المهمة المكتملة" if is_profit else "🛑 ملف المهمة المغلقة"
            profit_emoji = "💰" if is_profit else "💸"
            reasons_ar = ' + '.join([STRATEGY_NAMES_AR.get(r.strip(), r.strip()) for r in trade['reason'].split(' + ')])

            message_body = (
                f"▫️ *العملة:* `{trade['symbol']}`\n"
                f"▫️ *رقم الصفقة:* `{trade['id']}`\n"
                f"▫️ *الاستراتيجية:* `{reasons_ar}`\n"
                f"▫️ *سبب الإغلاق:* `{reason}`\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"{profit_emoji} *صافي الربح/الخسارة:* `${pnl:,.2f}` **({pnl_percent:,.2f}%)**\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"⏳ *مدة الصفقة:* {trade_duration}\n"
                f"📉 *متوسط سعر الدخول:* `${trade['entry_price']:,.4f}`\n"
                f"📈 *متوسط سعر الخروج:* `${close_price:,.4f}`\n"
                f"🔝 *أعلى سعر وصلت إليه:* `${trade.get('highest_price', 0):,.4f}`\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"{exit_efficiency_str}"
            )
            final_message = f"**{title}**\n\n{message_body}"
            await safe_send_message(bot, final_message)

        except (ccxt.InvalidOrder, ccxt.InsufficientFunds) as e:
             logger.warning(f"Closure for #{trade_id} failed with an expected trade rule error (e.g., dust), moving to incubator: {e}")
             await conn.execute("UPDATE trades SET status = 'incubated' WHERE id = ?", (trade_id,))
             await conn.commit()
             await self.sync_subscriptions()
        except Exception as e:
            logger.critical(f"CRITICAL: ULTIMATE closure for #{trade_id} failed unexpectedly. MOVING TO INCUBATOR: {e}", exc_info=True)
            await conn.execute("UPDATE trades SET status = 'incubated' WHERE id = ?", (trade_id,))
            await conn.commit()
            await safe_send_message(bot, f"⚠️ **فشل الإغلاق | #{trade_id} {symbol}**\nسيتم نقل الصفقة إلى الحضانة للمراقبة.")
            await self.sync_subscriptions()

    async def sync_subscriptions(self):
    """
    [تم الإصلاح النهائي] يضمن إعادة الاتصال عند تغيير الصفقات النشطة.
    """
    async with aiosqlite.connect(DB_FILE) as conn:
        active_symbols_tuples = await (await conn.execute("SELECT DISTINCT symbol FROM trades WHERE status = 'active'")).fetchall()
        active_symbols = {row[0] for row in active_symbols_tuples}

    if active_symbols != self.public_subscriptions:
        logger.info(f"OKX WebSocket Manager: Syncing subscriptions. Old: {len(self.public_subscriptions)}, New: {len(active_symbols)}")
        self.public_subscriptions = active_symbols
        
        # --- [الإصلاح النهائي هنا] ---
        # استخدام .open لإغلاق الاتصال القديم قبل إعادة الاتصال باشتراكات جديدة
        if self.public_ws and self.public_ws.open:
            try: await self.public_ws.close(code=1000, reason='Subscription change')
            except Exception: pass
        
        # لا نحتاج لإعادة تشغيل الاتصال الخاص لأنه لا يعتمد على الرموز
        # سيتم إعادة الاتصال تلقائياً بواسطة حلقة التشغيل الرئيسية


# =======================================================================================

async def the_supervisor_job(context: ContextTypes.DEFAULT_TYPE):
    """
    المشرف: يعالج الصفقات العالقة ويطلب من الحارس إعادة محاولة إغلاق صفقات الحضانة.
    """
    logger.info("🕵️ Supervisor: Running audit and recovery checks...")

    async with aiosqlite.connect(DB_FILE) as conn:
        conn.row_factory = aiosqlite.Row

        # --- شبكة الأمان للصفقات العالقة في حالة Pending ---
        total_pending_cursor = await conn.execute("SELECT COUNT(*) FROM trades WHERE status = 'pending'")
        total_pending_count = (await total_pending_cursor.fetchone())[0]
        if total_pending_count > 0:
            logger.info(f"Supervisor Diagnostics: Found {total_pending_count} total trades in 'pending' status.")

        stuck_threshold_time = (datetime.now(EGYPT_TZ) - timedelta(minutes=2)).isoformat()
        stuck_pending_trades = await (await conn.execute("SELECT * FROM trades WHERE status = 'pending' AND timestamp < ?", (stuck_threshold_time,))).fetchall()

        if stuck_pending_trades:
            logger.warning(f"🕵️ Supervisor: Found {len(stuck_pending_trades)} STUCK pending trades. Verifying status...")
            for trade_data in stuck_pending_trades:
                trade = dict(trade_data)
                try:
                    order_status = await bot_data.exchange.fetch_order(trade['order_id'], trade['symbol'])
                    if order_status['status'] == 'closed' or order_status.get('filled', 0) > 0:
                        await activate_trade(trade['order_id'], trade['symbol'])
                    elif order_status['status'] in ['canceled', 'expired']:
                        await conn.execute("DELETE FROM trades WHERE id = ?", (trade['id'],))
                    await asyncio.sleep(2)
                except ccxt.OrderNotFound:
                    await conn.execute("DELETE FROM trades WHERE id = ?", (trade['id'],))
                except Exception as e:
                    logger.error(f"🕵️ Supervisor: Error processing stuck pending trade #{trade['id']}: {e}")

        # --- إدارة الصفقات في الحضانة ---
        incubated_trades = await (await conn.execute("SELECT * FROM trades WHERE status = 'incubated'")).fetchall()
        if incubated_trades:
            logger.warning(f"🕵️ Supervisor: Found {len(incubated_trades)} trades in incubator...")
            for trade_data in incubated_trades:
                trade = dict(trade_data)
                try:
                    await conn.execute("UPDATE trades SET status = 'retry_exit' WHERE id = ?", (trade['id'],))
                except Exception as e:
                    logger.error(f"🕵️ Supervisor: Error processing incubated trade #{trade['id']}: {e}")

        await conn.commit()

    logger.info("🕵️ Supervisor: Audit and recovery checks complete.")

# --- [هنا يبدأ الجزء الخاص بواجهة تليجرام الذي تم حذفه بالخطأ] ---
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [["Dashboard 🖥️"], ["الإعدادات ⚙️"]]
    await update.message.reply_text("أهلاً بك في **بوت OKX V8.0 (النسخة النهائية)**", reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True), parse_mode=ParseMode.MARKDOWN)

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
        [InlineKeyboardButton(f"{ks_status_emoji} {ks_status_text}", callback_data="kill_switch_toggle"), InlineKeyboardButton("🕵️‍♂️ تقرير التشخيص", callback_data="db_diagnostics")]
    ]
    message_text = "🖥️ **لوحة تحكم بوت OKX**\n\nاختر نوع التقرير الذي تريد عرضه:"
    if not bot_data.trading_enabled: message_text += "\n\n**تحذير: تم تفعيل مفتاح الإيقاف.**"
    target_message = update.message or update.callback_query.message
    if update.callback_query: await safe_edit_message(update.callback_query, message_text, reply_markup=InlineKeyboardMarkup(keyboard))
    else: await target_message.reply_text(message_text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(keyboard))

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

async def universal_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # This check prevents handling text input when waiting for a setting value
    if 'setting_to_change' in context.user_data or 'blacklist_action' in context.user_data:
        await handle_setting_value(update, context)
        return
        
    text = update.message.text
    if text == "Dashboard 🖥️":
        await show_dashboard_command(update, context)
    elif text == "الإعدادات ⚙️":
        await show_settings_menu(update, context)

async def show_diagnostics_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    s = bot_data.settings
    scan_info = bot_data.last_scan_info
    determine_active_preset()
    nltk_status = "متاحة ✅" if NLTK_AVAILABLE else "غير متاحة ❌"
    scan_time = scan_info.get("start_time", "لم يتم بعد")
    scan_duration = f'{scan_info.get("duration_seconds", "N/A")} ثانية'
    scan_checked = scan_info.get("checked_symbols", "N/A")
    scan_errors = scan_info.get("analysis_errors", "N/A")
    scanners_list = "\n".join([f"  - {STRATEGY_NAMES_AR.get(key, key)}" for key in s.get('active_scanners', [])])
    scan_job = context.job_queue.get_jobs_by_name("perform_scan")
    next_scan_time = scan_job[0].next_t.astimezone(EGYPT_TZ).strftime('%H:%M:%S') if scan_job and scan_job[0].next_t else "N/A"
    db_size = f"{os.path.getsize(DB_FILE) / 1024:.2f} KB" if os.path.exists(DB_FILE) else "N/A"
    
    total_trades = 0
    active_trades = 0
    try:
        async with aiosqlite.connect(DB_FILE) as conn:
            total_trades = (await (await conn.execute("SELECT COUNT(*) FROM trades")).fetchone())[0]
            active_trades = (await (await conn.execute("SELECT COUNT(*) FROM trades WHERE status = 'active'")).fetchone())[0]
    except sqlite3.OperationalError as e:
        if "no such table: trades" in str(e):
            logger.warning("DB table 'trades' missing in diagnostics. Re-initializing...")
            await init_database()
        else:
            logger.error(f"Diagnostics DB Error: {e}")

    ws_status = "غير متصل ❌"
    if bot_data.websocket_manager:
        public_ws_open = bot_data.websocket_manager.public_ws and not bot_data.websocket_manager.public_ws.closed
        private_ws_open = bot_data.websocket_manager.private_ws and not bot_data.websocket_manager.private_ws.closed
        if public_ws_open and private_ws_open:
            ws_status = "متصل ✅ (عام وخاص)"
        elif public_ws_open:
            ws_status = "متصل ✅ (عام فقط)"
        elif private_ws_open:
            ws_status = "متصل ✅ (خاص فقط)"
    
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
        f"- اتصال OKX WebSocket: {ws_status}\n"
        f"- قاعدة البيانات:\n"
        f"  - الاتصال: ناجح ✅\n"
        f"  - حجم الملف: {db_size}\n"
        f"  - إجمالي الصفقات: {total_trades} ({active_trades} نشطة)\n"
        f"----------------------------------"
    )
    await safe_edit_message(query, report, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔄 تحديث", callback_data="db_diagnostics")], [InlineKeyboardButton("🔙 العودة للوحة التحكم", callback_data="back_to_dashboard")]]))

# --- (بقية دوال الواجهة مثل show_trades_command, show_parameters_menu, etc.) ---
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
    if bot_data.trading_enabled: 
        await query.answer("✅ تم استئناف التداول الطبيعي."); 
        await safe_send_message(context.bot, "✅ **تم استئناف التداول الطبيعي.**")
    else: 
        await query.answer("🚨 تم تفعيل مفتاح الإيقاف!", show_alert=True); 
        await safe_send_message(context.bot, "🚨 **تحذير: تم تفعيل مفتاح الإيقاف!**")
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

    keyboard = [
        [InlineKeyboardButton("🚨 بيع فوري (بسعر السوق)", callback_data=f"manual_sell_confirm_{trade_id}")],
        [InlineKeyboardButton("🔙 العودة للصفقات", callback_data="db_trades")]
    ]

    if trade['status'] == 'pending':
        message = f"**⏳ حالة الصفقة #{trade_id}**\n- **العملة:** `{trade['symbol']}`\n- **الحالة:** في انتظار تأكيد التنفيذ..."
        # For pending trades, we don't need the keyboard with the sell button
        keyboard = [[InlineKeyboardButton("🔙 العودة للصفقات", callback_data="db_trades")]]
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
    await safe_edit_message(query, message, reply_markup=InlineKeyboardMarkup(keyboard))

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
    await safe_edit_message(update.callback_query, message, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📜 عرض تقرير الاستراتيجيات", callback_data="db_strategy_report")],[InlineKeyboardButton("🔙 العودة للوحة التحكم", callback_data="back_to_dashboard")]]))

async def show_portfolio_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer("جاري جلب بيانات المحفظة...")
    try:
        balance = await bot_data.exchange.fetch_balance()
        owned_assets = {asset: data['total'] for asset, data in balance.items() if isinstance(data, dict) and data.get('total', 0) > 0 and 'USDT' not in asset}
        usdt_balance = balance.get('USDT', {}); total_usdt_equity = usdt_balance.get('total', 0); free_usdt = usdt_balance.get('free', 0)
        assets_to_fetch = [f"{asset}/USDT" for asset in owned_assets if asset != 'USDT']
        tickers = {}
        if assets_to_fetch:
            try: tickers = await bot_data.exchange.fetch_tickers(assets_to_fetch)
            except Exception as e: logger.warning(f"Could not fetch all tickers for portfolio: {e}")
        asset_details = []; total_assets_value_usdt = 0
        for asset, total in owned_assets.items():
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

async def show_adaptive_intelligence_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    s = bot_data.settings
    def bool_format(key, text):
        val = s.get(key, False)
        emoji = "✅" if val else "❌"
        return f"{text}: {emoji} مفعل"

    keyboard = [
        [InlineKeyboardButton(bool_format('adaptive_intelligence_enabled', 'تفعيل الذكاء التكيفي'), callback_data="param_toggle_adaptive_intelligence_enabled")],
        # --- [الزر الجديد هنا] ---
        [InlineKeyboardButton(bool_format('wise_man_auto_close', 'الإغلاق الآلي للرجل الحكيم'), callback_data="param_toggle_wise_man_auto_close")],
        # --- [نهاية الإضافة] ---
        [InlineKeyboardButton(bool_format('dynamic_trade_sizing_enabled', 'الحجم الديناميكي للصفقات'), callback_data="param_toggle_dynamic_trade_sizing_enabled")],
        [InlineKeyboardButton(bool_format('strategy_proposal_enabled', 'اقتراحات الاستراتيجيات'), callback_data="param_toggle_strategy_proposal_enabled")],
        [InlineKeyboardButton("--- معايير الضبط ---", callback_data="noop")],
        [InlineKeyboardButton(f"حد أدنى للتعطيل (WR%): {s.get('strategy_deactivation_threshold_wr', 45.0)}", callback_data="param_set_strategy_deactivation_threshold_wr")],
        [InlineKeyboardButton(f"أقل عدد صفقات للتحليل: {s.get('strategy_analysis_min_trades', 10)}", callback_data="param_set_strategy_analysis_min_trades")],
        [InlineKeyboardButton(f"أقصى زيادة للحجم (%): {s.get('dynamic_sizing_max_increase_pct', 25.0)}", callback_data="param_set_dynamic_sizing_max_increase_pct")],
        [InlineKeyboardButton(f"أقصى تخفيض للحجم (%): {s.get('dynamic_sizing_max_decrease_pct', 50.0)}", callback_data="param_set_dynamic_sizing_max_decrease_pct")],
        [InlineKeyboardButton("🔙 العودة للإعدادات", callback_data="settings_main")]
    ]
    # نحتاج أيضًا إلى تعديل معالج الضغط على الزر
    # ابحث عن دالة handle_toggle_parameter وأضف 'wise_man_auto_close' إلى قائمة الشروط
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
        [InlineKeyboardButton("--- إعدادات الرجل الحكيم (حساسية الزخم) ---", callback_data="noop")],
        [InlineKeyboardButton(f"نسبة الربح للزخم القوي (%): {s.get('wise_man_strong_profit_pct', 3.0)}", callback_data="param_set_wise_man_strong_profit_pct")],
        [InlineKeyboardButton(f"مستوى ADX للزخم القوي: {s.get('wise_man_strong_adx_level', 30)}", callback_data="param_set_wise_man_strong_adx_level")],
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

async def handle_preset_set(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    preset_key = query.data.replace("preset_set_", "")
    if preset_settings := SETTINGS_PRESETS.get(preset_key):
        current_scanners = bot_data.settings.get('active_scanners', [])
        adaptive_settings = {k: v for k, v in bot_data.settings.items() if k not in preset_settings}
        bot_data.settings = copy.deepcopy(preset_settings)
        bot_data.settings['active_scanners'] = current_scanners 
        bot_data.settings.update(adaptive_settings)
        determine_active_preset(); save_settings()
        await query.answer(f"✅ تم تفعيل النمط: {PRESET_NAMES_AR.get(preset_key, preset_key)}", show_alert=True)
    else:
        await query.answer("لم يتم العثور على النمط.")
    await show_presets_menu(update, context)

async def handle_strategy_adjustment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    parts = query.data.split('_')
    action, proposal_key = parts[2], parts[3]
    proposal = bot_data.pending_strategy_proposal
    if not proposal or proposal.get("key") != proposal_key:
        await safe_edit_message(query, "انتهت صلاحية هذا الاقتراح.", reply_markup=None); return

    if action == "approve":
        scanner_to_disable = proposal['scanner']
        if scanner_to_disable in bot_data.settings['active_scanners']:
            bot_data.settings['active_scanners'].remove(scanner_to_disable); save_settings(); determine_active_preset()
            await safe_edit_message(query, f"✅ **تمت الموافقة.** تم تعطيل استراتيجية '{STRATEGY_NAMES_AR.get(scanner_to_disable, scanner_to_disable)}'.", reply_markup=None)
    else:
        await safe_edit_message(query, "❌ **تم الرفض.** لن يتم إجراء أي تغييرات.", reply_markup=None)

    bot_data.pending_strategy_proposal = {}

async def handle_parameter_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; param_key = query.data.replace("param_set_", "")
    context.user_data['setting_to_change'] = param_key
    if '_' in param_key: await query.message.reply_text(f"أرسل القيمة الرقمية الجديدة لـ `{param_key}`:\n\n*ملاحظة: هذا إعداد متقدم (متشعب)، سيتم تحديثه مباشرة.*", parse_mode=ParseMode.MARKDOWN)
    else: await query.message.reply_text(f"أرسل القيمة الرقمية الجديدة لـ `{param_key}`:", parse_mode=ParseMode.MARKDOWN)

async def handle_toggle_parameter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    param_key = query.data.replace("param_toggle_", "")
    bot_data.settings[param_key] = not bot_data.settings.get(param_key, False)
    save_settings()
    determine_active_preset()
    # --- [التعديل هنا] ---
    if "adaptive" in param_key or "strategy" in param_key or "dynamic" in param_key or "wise_man" in param_key:
        await show_adaptive_intelligence_menu(update, context)
    # --- [نهاية التعديل] ---
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
        fake_query = type('Query', (), {'message': update.message, 'data': 'settings_blacklist', 'edit_message_text': (lambda *args, **kwargs: asyncio.sleep(0)), 'answer': (lambda *args, **kwargs: asyncio.sleep(0))})
        await show_blacklist_menu(Update(update.update_id, callback_query=fake_query), context); return

    if not (setting_key := context.user_data.get('setting_to_change')): return

    try:
        if setting_key in bot_data.settings and not isinstance(bot_data.settings[setting_key], dict):
            original_value = bot_data.settings[setting_key]
            if isinstance(original_value, int): new_value = int(user_input)
            else: new_value = float(user_input)
            bot_data.settings[setting_key] = new_value
        else:
            keys = setting_key.split('_'); current_dict = bot_data.settings
            for key in keys[:-1]: current_dict = current_dict[key]
            last_key = keys[-1]; original_value = current_dict[last_key]
            if isinstance(original_value, int): new_value = int(user_input)
            else: new_value = float(user_input)
            current_dict[last_key] = new_value

        save_settings(); determine_active_preset()
        await update.message.reply_text(f"✅ تم تحديث `{setting_key}` إلى `{new_value}`.")
    except (ValueError, KeyError):
        await update.message.reply_text("❌ قيمة غير صالحة. الرجاء إرسال رقم.")
    finally:
        if 'setting_to_change' in context.user_data: del context.user_data['setting_to_change']
        parent_menu_data = "settings_adaptive" if any(k in setting_key for k in ["adaptive", "strategy", "dynamic"]) else "settings_params"
        fake_query = type('Query', (), {'message': update.message, 'data': parent_menu_data, 'edit_message_text': (lambda *args, **kwargs: asyncio.sleep(0)), 'answer': (lambda *args, **kwargs: asyncio.sleep(0))})
        if parent_menu_data == "settings_adaptive": await show_adaptive_intelligence_menu(Update(update.update_id, callback_query=fake_query), context)
        else: await show_parameters_menu(Update(update.update_id, callback_query=fake_query), context)

async def handle_manual_sell_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """يعرض رسالة تأكيد قبل البيع اليدوي."""
    query = update.callback_query
    # [تم الإصلاح] الحصول على الرقم من آخر جزء في النص
    trade_id = int(query.data.split('_')[-1])

    async with aiosqlite.connect(DB_FILE) as conn:
        cursor = await conn.execute("SELECT symbol FROM trades WHERE id = ?", (trade_id,))
        trade_data = await cursor.fetchone()

    if not trade_data:
        await query.answer("لم يتم العثور على الصفقة.", show_alert=True); return

    symbol = trade_data[0]
    message = f"🛑 **تأكيد البيع الفوري** 🛑\n\nهل أنت متأكد أنك تريد بيع صفقة `{symbol}` رقم `#{trade_id}` بسعر السوق الحالي؟"

    keyboard = [
        [InlineKeyboardButton("✅ نعم، قم بالبيع الآن", callback_data=f"manual_sell_execute_{trade_id}")],
        [InlineKeyboardButton("❌ لا، تراجع", callback_data=f"check_{trade_id}")]
    ]
    await safe_edit_message(query, message, reply_markup=InlineKeyboardMarkup(keyboard))

async def handle_manual_sell_execute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ينفذ البيع اليدوي ويغلق الصفقة."""
    query = update.callback_query
    trade_id = int(query.data.split('_')[-1])

    await safe_edit_message(query, "⏳ جاري إرسال أمر البيع...", reply_markup=None)

    try:
        # **[الإصلاح]** يجب فتح اتصال بقاعدة البيانات هنا
        async with aiosqlite.connect(DB_FILE) as conn:
            conn.row_factory = aiosqlite.Row
            trade = await (await conn.execute("SELECT * FROM trades WHERE id = ? AND status = 'active'", (trade_id,))).fetchone()

            if not trade:
                await query.answer("لم يتم العثور على الصفقة أو أنها ليست نشطة.", show_alert=True)
                # ... (منطق العودة يبقى كما هو) ...
                return

            trade = dict(trade)
            ticker = await bot_data.exchange.fetch_ticker(trade['symbol'])
            current_price = ticker['last']

            # **[الإصلاح]** تمرير اتصال قاعدة البيانات 'conn' إلى دالة الإغلاق
            await bot_data.websocket_manager._close_trade(conn, trade, "إغلاق يدوي", current_price)
            await query.answer("✅ تم إرسال أمر البيع بنجاح!")

    except Exception as e:
        logger.error(f"Manual sell execution failed for trade #{trade_id}: {e}", exc_info=True)
        await safe_send_message(context.bot, f"🚨 فشل البيع اليدوي للصفقة #{trade_id}. السبب: {e}")
        await query.answer("🚨 فشل أمر البيع. راجع السجلات.", show_alert=True)

# ==============================================================================
# --- دالة موجه الأزرار الرئيسية ---
# ==============================================================================
async def button_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer(); data = query.data
    route_map = {
        "db_stats": show_stats_command, "db_trades": show_trades_command, "db_history": show_trade_history_command,
        "db_mood": show_mood_command, "db_diagnostics": show_diagnostics_command, "back_to_dashboard": show_dashboard_command,
        "db_portfolio": show_portfolio_command, "db_manual_scan": manual_scan_command,
        "kill_switch_toggle": toggle_kill_switch, "db_daily_report": daily_report_command, "db_strategy_report": show_strategy_report_command,
        "settings_main": show_settings_menu, "settings_params": show_parameters_menu, "settings_scanners": show_scanners_menu,
        "settings_presets": show_presets_menu, "settings_blacklist": show_blacklist_menu, "settings_data": show_data_management_menu,
        "blacklist_add": handle_blacklist_action, "blacklist_remove": handle_blacklist_action,
        "data_clear_confirm": handle_clear_data_confirmation, "data_clear_execute": handle_clear_data_execute,
        "settings_adaptive": show_adaptive_intelligence_menu,
        "noop": (lambda u,c: None)
    }
    try:
        if data in route_map: await route_map[data](update, context)
        elif data.startswith("check_"): await check_trade_details(update, context)
        elif data.startswith("manual_sell_confirm_"): await handle_manual_sell_confirmation(update, context)
        elif data.startswith("manual_sell_execute_"): await handle_manual_sell_execute(update, context)
        elif data.startswith("scanner_toggle_"): await handle_scanner_toggle(update, context)
        elif data.startswith("preset_set_"): await handle_preset_set(update, context)
        elif data.startswith("param_set_"): await handle_parameter_selection(update, context)
        elif data.startswith("param_toggle_"): await handle_toggle_parameter(update, context)
        elif data.startswith("strategy_adjust_"): await handle_strategy_adjustment(update, context)
    except Exception as e: logger.error(f"Error in button callback handler for data '{data}': {e}", exc_info=True)

async def post_init(application: Application):
    logger.info("Performing post-initialization setup for OKX Bot V8.0...")

    required_vars = ['TELEGRAM_BOT_TOKEN', 'TELEGRAM_CHAT_ID', 'OKX_API_KEY', 'OKX_API_SECRET', 'OKX_API_PASSWORD']
    missing_vars = [var for var in required_vars if not os.getenv(var)]
    if missing_vars:
        logger.critical(f"FATAL: Missing required environment variables: {', '.join(missing_vars)}")
        raise RuntimeError("Bot cannot start due to missing environment variables.")

    application.bot_data['TELEGRAM_CHAT_ID'] = TELEGRAM_CHAT_ID

    try:
        await init_database()
    except Exception as e:
        logger.critical(f"FATAL: Database could not be initialized: {e}", exc_info=True)
        raise RuntimeError("Bot cannot start due to database failure.")

    try:
        logger.info("Attempting to connect to OKX...")
        bot_data.exchange = ccxt.okx({
            'apiKey': OKX_API_KEY,
            'secret': OKX_API_SECRET,
            'password': OKX_API_PASSWORD,
            'enableRateLimit': True,
            'options': {'defaultType': 'spot', 'timeout': 30000}
        })
        await bot_data.exchange.load_markets()
        await bot_data.exchange.fetch_balance()
        logger.info("✅ Successfully connected to OKX Spot.")
    except Exception as e:
        logger.critical(f"🔥 FATAL: Could not connect to OKX. PLEASE CHECK YOUR API KEYS AND PASSPHRASE.", exc_info=True)
        await application.bot.send_message(
            TELEGRAM_CHAT_ID,
            "🚨 **فشل تشغيل البوت** 🚨\n\nلم يتمكن البوت من الاتصال بمنصة OKX. "
            "يرجى التحقق من مفاتيح الـ API وكلمة المرور الخاصة بها."
        )
        raise RuntimeError("Failed to connect to OKX exchange.")

    bot_data.application = application

    if NLTK_AVAILABLE:
        try: nltk.data.find('sentiment/vader_lexicon.zip')
        except LookupError: logger.info("Downloading NLTK data..."); nltk.download('vader_lexicon', quiet=True)
    
    load_settings()

    global wise_man, smart_brain
    wise_man = WiseMan(exchange=bot_data.exchange, application=application, bot_data_ref=bot_data, db_file=DB_FILE)
    smart_brain = EvolutionaryEngine(exchange=bot_data.exchange, db_file=DB_FILE)

    bot_data.websocket_manager = OKXWebSocketManager(bot_data.exchange, application)
    asyncio.create_task(bot_data.websocket_manager.run())

    logger.info("WebSocket Manager: Performing initial sync..."); await asyncio.sleep(5) 
    await bot_data.websocket_manager.sync_subscriptions()
    logger.info("WebSocket Manager: Initial sync complete.")

    jq = application.job_queue
    jq.run_repeating(perform_scan, interval=SCAN_INTERVAL_SECONDS, first=10, name="perform_scan")
    jq.run_repeating(the_supervisor_job, interval=SUPERVISOR_INTERVAL_SECONDS, first=30, name="the_supervisor_job")
    jq.run_daily(send_daily_report, time=dt_time(hour=23, minute=55, tzinfo=EGYPT_TZ), name='daily_report')
    jq.run_repeating(update_strategy_performance, interval=STRATEGY_ANALYSIS_INTERVAL_SECONDS, first=60, name="update_strategy_performance")
    jq.run_repeating(propose_strategy_changes, interval=STRATEGY_ANALYSIS_INTERVAL_SECONDS, first=120, name="propose_strategy_changes")
    jq.run_repeating(wise_man.review_portfolio_risk, interval=3600, first=90, name="wise_man_portfolio_review")

    logger.info(f"All jobs scheduled. OKX Bot is fully operational.")
    await application.bot.send_message(TELEGRAM_CHAT_ID, "*🤖 بوت OKX V8.0 (مستقر) - بدأ العمل...*", parse_mode=ParseMode.MARKDOWN)

async def post_shutdown(application: Application):
    if bot_data.exchange: await bot_data.exchange.close()
    if bot_data.websocket_manager: await bot_data.websocket_manager.stop()
    logger.info("Bot has shut down gracefully.")

def main():
    logger.info("Starting OKX Maestro Bot V8.0...")
    app_builder = Application.builder().token(TELEGRAM_BOT_TOKEN)
    app_builder.post_init(post_init).post_shutdown(post_shutdown)
    application = app_builder.build()

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("scan", manual_scan_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, universal_text_handler))
    application.add_handler(CallbackQueryHandler(button_callback_handler))

    application.run_polling()
    
if __name__ == '__main__':
    main()
