# -*- coding: utf-8 -*-
import logging
import asyncio
import json
import time 
import httpx
import pandas as pd
import pandas_ta as ta
import feedparser
from collections import defaultdict
from zoneinfo import ZoneInfo
from datetime import datetime, timezone, timedelta, time as dt_time

# --- افتراض توافر المكتبات ---
try:
    import nltk
    from nltk.sentiment.vader import SentimentIntensityAnalyzer
    NLTK_AVAILABLE = True
except ImportError:
    NLTK_AVAILABLE = False

# --- الثوابت ---
EGYPT_TZ = ZoneInfo("Africa/Cairo")
logger = logging.getLogger(__name__)

# =======================================================================================
# --- A. وظائف تحليل مزاج السوق العام (Fundamental & Sentiment) ---
# =======================================================================================

def analyze_sentiment_of_headlines(headlines):
    """يحلل مشاعر العناوين الإخبارية."""
    if not headlines or not NLTK_AVAILABLE: return "N/A", 0.0
    try:
        sia = SentimentIntensityAnalyzer()
        score = sum(sia.polarity_scores(h)['compound'] for h in headlines) / len(headlines)
        if score > 0.15: mood = "إيجابية"
        elif score < -0.15: mood = "سلبية"
        else: mood = "محايدة"
        return mood, score
    except Exception as e:
        logger.warning(f"Sentiment analysis failed: {e}. NLTK Vader corpus might be missing. Run: python -m nltk.downloader vader_lexicon")
        return "N/A", 0.0

def get_latest_crypto_news(limit=15):
    """يجلب آخر عناوين أخبار العملات المشفرة."""
    urls = ["https://cointelegraph.com/rss", "https://www.coindesk.com/arc/outboundfeeds/rss/"]
    headlines = []
    for url in urls:
        try:
            feed = feedparser.parse(url)
            headlines.extend(entry.title for entry in feed.entries[:7])
        except Exception as e:
            logger.warning(f"Could not fetch news from {url}: {e}")
    return list(set(headlines))[:limit]


async def get_fear_and_greed_index():
    """يجلب مؤشر الخوف والطمع."""
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get("https://api.alternative.me/fng/?limit=1", timeout=10)
            return int(r.json()['data'][0]['value'])
    except Exception: return None

# =======================================================================================
# --- B. وظيفة المايسترو: تحليل نمط السوق (Market Regime Analysis) ---
# =======================================================================================

def find_col(df_columns, prefix):
    """يجد اسم العمود الذي يبدأ ببادئة معينة (لمشاكل Pandas-TA)."""
    try: return next(col for col in df_columns if col.startswith(prefix))
    except StopIteration: return None


async def get_market_regime(exchange):
    """
    يحلل نمط السوق الحالي لـ BTC بناءً على الاتجاه والتقلب.
    """
    try:
        ohlcv = await exchange.fetch_ohlcv('BTC/USDT', '1h', limit=100)
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        
        df.ta.adx(append=True)
        adx_col = find_col(df.columns, "ADX_14")
        adx = df[adx_col].iloc[-1] if adx_col and pd.notna(df[adx_col].iloc[-1]) else 0
        
        trend = "TRENDING" if adx > 25 else "SIDEWAYS"
            
        df.ta.atr(append=True)
        atr_col = find_col(df.columns, "ATRr_14")
        current_close = df['close'].iloc[-1]
        
        atr_percent = (df[atr_col].iloc[-1] / current_close) * 100 if atr_col and current_close > 0 else 0.0

        vol = "HIGH_VOLATILITY" if atr_percent > 1.5 else "LOW_VOLATILITY"
            
        regime = f"{trend}_{vol}"
        logger.info(f"Maestro Regime Analysis: {regime} (ADX: {adx:.1f}, ATR%: {atr_percent:.2f}%)")
        return regime
        
    except Exception as e:
        logger.error(f"Market Regime Analysis failed: {e}")
        return "UNKNOWN"

async def get_market_mood(bot_data):
    settings = bot_data.settings
    btc_mood_text = "الفلتر معطل"

    if settings.get('btc_trend_filter_enabled', True):
        try:
            htf_period = settings['trend_filters']['htf_period']
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

async def get_okx_markets(bot_data):
    settings = bot_data.settings
    # --- [الإصلاح] --- تحديث قائمة الأسواق كل 5 دقائق لضمان بيانات حديثة
    if time.time() - bot_data.last_markets_fetch > 300:
        try:
            logger.info("Fetching and caching all OKX SPOT markets...")
            all_markets_raw = await bot_data.exchange.fetch_markets()
            # فلترة أولية للحصول على أزواج SPOT مقابل USDT فقط
            bot_data.all_markets = [
                m for m in all_markets_raw if m.get('spot', False) and m.get('quote', '') == 'USDT'
            ]
            bot_data.last_markets_fetch = time.time()
            logger.info(f"Successfully cached {len(bot_data.all_markets)} SPOT USDT markets.")
        except Exception as e:
            logger.error(f"Failed to fetch and cache markets: {e}")
            return []

    if not bot_data.all_markets:
        return []
        
    blacklist = settings.get('asset_blacklist', [])
    min_volume = settings.get('liquidity_filters', {}).get('min_quote_volume_24h_usd', 1000000)

    # جلب Tickers للأسواق المفلترة للحصول على حجم التداول
    symbols_to_fetch = [m['symbol'] for m in bot_data.all_markets]
    try:
        tickers = await bot_data.exchange.fetch_tickers(symbols_to_fetch)
    except Exception as e:
        logger.error(f"Failed to fetch tickers for volume check: {e}")
        return []

    valid_markets = []
    for market in bot_data.all_markets:
        symbol = market['symbol']
        base_currency = market.get('base', '')
        
        if base_currency in blacklist:
            continue
            
        ticker = tickers.get(symbol)
        if not ticker:
            continue

        # التحقق من حجم التداول
        quote_volume = ticker.get('quoteVolume', 0)
        if quote_volume < min_volume:
            continue

        # التحقق من عدم وجود كلمات غير مرغوب فيها
        if any(k in symbol for k in ['-SWAP', 'UP', 'DOWN', '3L', '3S', '2L', '2S', '4L', '4S', '5L', '5S']):
            continue
            
        # إضافة السوق إلى القائمة الصالحة مع بيانات التيكر
        valid_markets.append(ticker)

    # ترتيب حسب حجم التداول واختيار الأعلى
    valid_markets.sort(key=lambda m: m.get('quoteVolume', 0), reverse=True)
    
    final_list = valid_markets[:settings.get('top_n_symbols_by_volume', 300)]
    logger.info(f"Found {len(final_list)} markets matching liquidity and blacklist criteria.")
    return final_list
