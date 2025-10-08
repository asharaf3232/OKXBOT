# -*- coding: utf-8 -*-
# =======================================================================================
# --- 🧠 Wise Man V2.0 (ML-Powered Guardian & Maestro) 🧠 ---
# =======================================================================================
#
# --- سجل التغييرات للإصدار 2.0 (ترقية الذكاء الاصطناعي) ---
#   ✅ [ميزة ML] **التنبؤ بالنجاح:** إضافة نموذج `LogisticRegression` للتدريب على الصفقات التاريخية والتنبؤ باحتمالية نجاح الصفقات الجديدة.
#   ✅ [ميزة ML] **رفض الصفقات الخطرة:** يتم الآن رفض المرشحين للتداول تلقائيًا إذا كانت احتمالية النجاح المتوقعة أقل من 60%.
#   ✅ [ميزة ديناميكية] **إدارة حجم الصفقة:** تعديل حجم الصفقة ديناميكيًا بناءً على تقلب (ATR)، وتقليل المخاطرة في الأسواق شديدة التقلب.
#   ✅ [ميزة ديناميكية] **تحليل الارتباط:** إضافة فحص الارتباط مع BTC ورفض الصفقات شديدة الارتباط (>0.8) لتجنب المخاطر النظامية.
#   ✅ [ميزة تكاملية] **دمج تحليل المشاعر:** قرارات الخروج أصبحت أكثر حساسية، حيث يتم تشديد وقف الخسارة تلقائيًا عند وجود مشاعر سلبية في السوق.
#   ✅ [ميزة تنبيه] **تنبيهات استباقية:** إضافة نظام تنبيه عبر البريد الإلكتروني لتحذيرات مخاطر المحفظة (التركيز العالي والارتباط الشديد).
#   ✅ [هيكلة] **تحسين الأمان والأداء:** استخدام `asyncio.Semaphore` للتحكم في طلبات API وتجنب الاستيراد الدائري (Circular Imports).
#
# =======================================================================================

import logging
import aiosqlite
import pandas as pd
import pandas_ta as ta
import ccxt.async_support as ccxt
from telegram.ext import Application
from collections import defaultdict, deque
import asyncio
import time
from datetime import datetime, timezone
import os

# --- [تعديل V2.0] إضافة مكتبات جديدة ---
import numpy as np
from smtplib import SMTP
from email.mime.text import MIMEText

try:
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler
    SKLEARN_AVAILABLE = True
except ImportError:
    SKLEARN_AVAILABLE = False
    logging.warning("Scikit-learn not found. ML features will be disabled.")


# --- إعدادات أساسية ---
logger = logging.getLogger(__name__)

# --- قواعد إدارة مخاطر المحفظة ---
PORTFOLIO_RISK_RULES = {
    "max_asset_concentration_pct": 30.0,
    "max_sector_concentration_pct": 50.0,
}
SECTOR_MAP = {
    'RNDR': 'AI', 'FET': 'AI', 'AGIX': 'AI', 'WLD': 'AI', 'OCEAN': 'AI', 'TAO': 'AI',
    'SAND': 'Gaming', 'MANA': 'Gaming', 'GALA': 'Gaming', 'AXS': 'Gaming', 'IMX': 'Gaming', 'APE': 'Gaming',
    'UNI': 'DeFi', 'AAVE': 'DeFi', 'LDO': 'DeFi', 'MKR': 'DeFi', 'CRV': 'DeFi', 'COMP': 'DeFi',
    'SOL': 'Layer 1', 'ETH': 'Layer 1', 'AVAX': 'Layer 1', 'ADA': 'Layer 1', 'NEAR': 'Layer 1', 'SUI': 'Layer 1',
    'MATIC': 'Layer 2', 'ARB': 'Layer 2', 'OP': 'Layer 2', 'STRK': 'Layer 2',
    'ONDO': 'RWA', 'POLYX': 'RWA', 'OM': 'RWA',
    'DOGE': 'Memecoin', 'PEPE': 'Memecoin', 'SHIB': 'Memecoin', 'WIF': 'Memecoin', 'BONK': 'Memecoin',
}

class WiseMan:
    def __init__(self, exchange: ccxt.Exchange, application: Application, bot_data_ref: object, db_file: str):
        self.exchange = exchange
        self.application = application
        self.bot_data = bot_data_ref
        self.db_file = db_file
        self.telegram_chat_id = application.bot_data.get('TELEGRAM_CHAT_ID')
        
        # --- [تعديل V2.0] تهيئة مكونات تعلم الآلة وإدارة المخاطر ---
        self.ml_model = LogisticRegression() if SKLEARN_AVAILABLE else None
        self.scaler = StandardScaler() if SKLEARN_AVAILABLE else None
        self.model_trained = False
        self.historical_features = deque(maxlen=200) # Buffer for potential future live training
        
        self.correlation_cache = {} # Cache for BTC correlation
        self.request_semaphore = asyncio.Semaphore(3) # Rate limiting for Wise Man's own API calls
        self.entry_event = asyncio.Event() # Event for signaling purposes
        
        logger.info("🧠 Wise Man module upgraded to V2.0 'ML Guardian & Maestro' model.")

    # ==============================================================================
    # --- 🧠 محرك تعلم الآلة (يعمل أسبوعيًا) 🧠 ---
    # ==============================================================================
    async def train_ml_model(self, context: object = None):
        """تدريب نموذج تعلم الآلة على بيانات الصفقات التاريخية للتنبؤ بالنجاح."""
        if not SKLEARN_AVAILABLE:
            logger.warning("Wise Man: Cannot train ML model, scikit-learn is not installed.")
            return

        logger.info("🧠 Wise Man: Starting weekly ML model training...")
        features = []
        labels = []
        try:
            async with aiosqlite.connect(self.db_file) as conn:
                conn.row_factory = aiosqlite.Row
                closed_trades = await (await conn.execute("SELECT * FROM trades WHERE status LIKE '%(%' LIMIT 500")).fetchall()

            if len(closed_trades) < 20:
                logger.warning(f"Wise Man: Not enough historical data to train ML model (found {len(closed_trades)} trades).")
                return
            
            # Fetch BTC data for trend analysis
            btc_ohlcv = await self.exchange.fetch_ohlcv('BTC/USDT', '1h', limit=1000)
            btc_df = pd.DataFrame(btc_ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            btc_df['timestamp'] = pd.to_datetime(btc_df['timestamp'], unit='ms', utc=True)
            btc_df.set_index('timestamp', inplace=True)
            btc_df['btc_ema_50'] = ta.ema(btc_df['close'], length=50)

            for trade in closed_trades:
                try:
                    trade_time = datetime.fromisoformat(trade['timestamp']).replace(tzinfo=None)
                    ohlcv = await self.exchange.fetch_ohlcv(trade['symbol'], '15m', since=int((trade_time - timedelta(hours=20)).timestamp() * 1000), limit=80)
                    df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
                    
                    # Find data point closest to trade entry time
                    entry_df = df.iloc[(df['timestamp'] - trade_time).abs().argsort()[:1]]
                    if entry_df.empty: continue

                    adx_data = ta.adx(df['high'], df['low'], df['close'])
                    rsi = ta.rsi(df['close']).iloc[-1]
                    adx = adx_data['ADX_14'].iloc[-1] if adx_data is not None and not adx_data.empty else 25

                    btc_row = btc_df.iloc[btc_df.index.get_loc(pd.to_datetime(trade['timestamp']), method='nearest')]
                    btc_trend = 1 if btc_row['close'] > btc_row['btc_ema_50'] else 0

                    features.append([rsi, adx, btc_trend])
                    is_win = 1 if 'ناجحة' in trade['status'] or 'تأمين' in trade['status'] else 0
                    labels.append(is_win)
                except Exception:
                    continue # Skip trade if data fetching fails
            
            if len(features) < 10:
                logger.warning("Wise Man: Could not generate enough features for ML training.")
                return

            X = np.array(features)
            y = np.array(labels)

            X_scaled = self.scaler.fit_transform(X)
            self.ml_model.fit(X_scaled, y)
            self.model_trained = True
            logger.info(f"🧠 Wise Man: ML model training complete. Trained on {len(X)} data points.")
        except Exception as e:
            logger.error(f"Wise Man: An error occurred during ML model training: {e}", exc_info=True)


    # ==============================================================================
    # --- 🚀 المحرك الرئيسي السريع (يعمل كل 10 ثوانٍ) 🚀 ---
    # ==============================================================================
    async def run_realtime_review(self, context: object = None):
        """المهمة السريعة التي تتخذ قرارات الدخول والخروج اللحظية."""
        await self._review_pending_entries()
        await self._review_pending_exits()

    # ==============================================================================
    # --- 1. منطق "نقطة الدخول الممتازة" (جزء من المحرك السريع) ---
    # ==============================================================================
    async def _review_pending_entries(self):
        """يراجع الفرص المرشحة ويقتنص أفضل لحظة للدخول باستخدام ML وتحليل المخاطر."""
        async with aiosqlite.connect(self.db_file) as conn:
            conn.row_factory = aiosqlite.Row
            candidates = await (await conn.execute("SELECT * FROM trade_candidates WHERE status = 'pending'")).fetchall()
            for cand_data in candidates:
                candidate = dict(cand_data)
                symbol = candidate['symbol']
                
                # Check for existing trade
                trade_exists = await (await conn.execute("SELECT 1 FROM trades WHERE symbol = ? AND status IN ('active', 'pending')", (symbol,))).fetchone()
                if trade_exists:
                    await conn.execute("UPDATE trade_candidates SET status = 'cancelled_duplicate' WHERE id = ?", (candidate['id'],)); await conn.commit()
                    continue

                try:
                    async with self.request_semaphore:
                        ticker = await self.exchange.fetch_ticker(symbol)
                        ohlcv = await self.exchange.fetch_ohlcv(symbol, '15m', limit=50)
                    
                    # 1. Price check
                    current_price = ticker['last']
                    signal_price = candidate['entry_price']
                    if not (0.995 * signal_price <= current_price <= 1.005 * signal_price):
                        if current_price > 1.01 * signal_price:
                            logger.info(f"Wise Man cancels {symbol}: Price moved too far.")
                            await conn.execute("UPDATE trade_candidates SET status = 'cancelled_price_moved' WHERE id = ?", (candidate['id'],))
                        elif time.time() - datetime.fromisoformat(candidate['timestamp']).timestamp() > 180:
                            logger.info(f"Wise Man cancels {symbol}: Candidate expired.")
                            await conn.execute("UPDATE trade_candidates SET status = 'cancelled_expired' WHERE id = ?", (candidate['id'],))
                        await conn.commit()
                        continue

                    # 2. Dynamic Sizing based on Volatility
                    df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                    atr = ta.atr(df['high'], df['low'], df['close'], length=14).iloc[-1]
                    atr_percent = (atr / current_price) * 100
                    if atr_percent > 1.0:
                        original_size = candidate.get('trade_size', self.bot_data.settings['real_trade_size_usdt'])
                        new_size = original_size * 0.75
                        candidate['trade_size'] = new_size
                        logger.info(f"Wise Man: High volatility detected in {symbol} ({atr_percent:.2f}%). Reducing trade size to ${new_size:.2f}.")

                    # 3. Correlation Check
                    correlation = await self._get_correlation(symbol, df)
                    if correlation > 0.8:
                        logger.warning(f"Wise Man rejects {symbol}: High correlation with BTC ({correlation:.2f}).")
                        await conn.execute("UPDATE trade_candidates SET status = 'rejected_correlation' WHERE id = ?", (candidate['id'],)); await conn.commit()
                        continue

                    # 4. ML Win Probability Prediction
                    if self.model_trained:
                        btc_ohlcv = await self.exchange.fetch_ohlcv('BTC/USDT', '1h', limit=51)
                        btc_df = pd.DataFrame(btc_ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                        btc_ema_50 = ta.ema(btc_df['close'], length=50).iloc[-1]
                        btc_trend = 1 if btc_df['close'].iloc[-1] > btc_ema_50 else 0
                        
                        adx_data = ta.adx(df['high'], df['low'], df['close'])
                        rsi = ta.rsi(df['close']).iloc[-1]
                        adx = adx_data['ADX_14'].iloc[-1] if adx_data is not None else 25
                        
                        current_features = np.array([[rsi, adx, btc_trend]])
                        scaled_features = self.scaler.transform(current_features)
                        win_prob = self.ml_model.predict_proba(scaled_features)[0][1]
                        candidate['win_prob'] = win_prob

                        if win_prob < 0.6:
                            logger.warning(f"Wise Man rejects {symbol}: Low ML win probability ({win_prob:.2f}).")
                            await conn.execute("UPDATE trade_candidates SET status = 'rejected_ml_prob' WHERE id = ?", (candidate['id'],)); await conn.commit()
                            continue

                    # 5. Final Confirmation & Execution
                    logger.info(f"Wise Man confirms entry for {symbol}. All checks passed. Initiating trade.")
                    from okx_maestro import initiate_real_trade 
                    if await initiate_real_trade(candidate, self.bot_data.settings, self.exchange, self.application.bot):
                        await conn.execute("UPDATE trade_candidates SET status = 'executed' WHERE id = ?", (candidate['id'],))
                    else:
                        await conn.execute("UPDATE trade_candidates SET status = 'failed_execution' WHERE id = ?", (candidate['id'],))
                    await conn.commit()
                    await asyncio.sleep(1) # Stagger executions
                except Exception as e:
                    logger.error(f"Wise Man: Error reviewing entry candidate for {symbol}: {e}", exc_info=True)
                    await conn.execute("UPDATE trade_candidates SET status = 'error' WHERE id = ?", (candidate['id'],)); await conn.commit()

    # ==============================================================================
    # --- 2. منطق "نقطة الخروج الرائعة" (جزء من المحرك السريع) ---
    # ==============================================================================
    async def _review_pending_exits(self):
        """يراجع طلبات الخروج مع الأخذ في الاعتبار مشاعر السوق."""
        async with aiosqlite.connect(self.db_file) as conn:
            conn.row_factory = aiosqlite.Row
            trades_to_review = await (await conn.execute("SELECT * FROM trades WHERE status = 'pending_exit_confirmation'")).fetchall()
            if not trades_to_review: return

            # --- [تعديل V2.0] جلب مشاعر السوق مرة واحدة لجميع المراجعات
            from okx_maestro import get_fundamental_market_mood
            mood_result = await get_fundamental_market_mood()
            is_negative_mood = mood_result['mood'] in ["NEGATIVE", "DANGEROUS"]

            for trade_data in trades_to_review:
                trade = dict(trade_data)
                symbol = trade['symbol']
                try:
                    async with self.request_semaphore:
                        ohlcv = await self.exchange.fetch_ohlcv(symbol, '1m', limit=20)
                    df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                    df['ema_9'] = ta.ema(df['close'], length=9)
                    current_price = df['close'].iloc[-1]
                    last_ema = df['ema_9'].iloc[-1]
                    
                    # --- [تعديل V2.0] تشديد شرط الخروج إذا كانت المشاعر سلبية
                    # نجعل الخروج أكثر حساسية (يحدث أسرع) عندما يكون المزاج سيئًا
                    exit_threshold = last_ema
                    if is_negative_mood:
                        exit_threshold *= 0.998 # A tighter stop: exit even if price is only slightly below EMA
                        logger.info(f"Wise Man: Negative market mood detected. Tightening SL for {symbol}.")
                    
                    if current_price < exit_threshold:
                        logger.warning(f"Wise Man confirms exit for {symbol}. Momentum is weak. Closing trade #{trade['id']}.")
                        await self.bot_data.trade_guardian._close_trade(trade, "فاشلة (بقرار حكيم)", current_price)
                    else:
                        logger.info(f"Wise Man cancels exit for {symbol}. Price recovered. Resetting status to active for trade #{trade['id']}.")
                        from okx_maestro import safe_send_message
                        message = f"✅ **إلغاء الخروج | #{trade['id']} {symbol}**\nقرر الرجل الحكيم إعطاء الصفقة فرصة أخرى بعد تعافي السعر لحظيًا."
                        await safe_send_message(self.application.bot, message)
                        await conn.execute("UPDATE trades SET status = 'active' WHERE id = ?", (trade['id'],))
                        await conn.commit()
                except Exception as e:
                    logger.error(f"Wise Man: Error making final exit decision for {symbol}: {e}. Forcing closure.", exc_info=True)
                    await self.bot_data.trade_guardian._close_trade(trade, "فاشلة (خطأ في المراجعة)", trade['stop_loss'])

    # ==============================================================================
    # --- 🎼 المايسترو التكتيكي (يعمل كل 15 دقيقة) 🎼 ---
    # ==============================================================================
    async def review_active_trades_with_tactics(self, context: object = None):
        """
        [النسخة المصححة] يراجع الصفقات النشطة لتمديد الأهداف وتأمين الأرباح بشكل متدرج عند اقتراب السعر من الهدف،
        أو يقطع الخسائر استباقيًا للصفقات الضعيفة.
        """
        logger.info("🧠 Wise Man: Running tactical review (Intelligent Trailing & Proactive Exits)...")
        async with self.bot_data.trade_management_lock:
            async with aiosqlite.connect(self.db_file) as conn:
                conn.row_factory = aiosqlite.Row
                active_trades = await (await conn.execute("SELECT * FROM trades WHERE status = 'active'")).fetchall()
                try:
                    # جلب بيانات البيتكوين مرة واحدة لتقليل طلبات API
                    async with self.request_semaphore:
                        btc_ohlcv = await self.exchange.fetch_ohlcv('BTC/USDT', '1h', limit=20)
                    btc_df = pd.DataFrame(btc_ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                    btc_momentum_is_negative = ta.mom(btc_df['close'], length=10).iloc[-1] < 0
                except Exception:
                    btc_momentum_is_negative = False

                for trade_data in active_trades:
                    trade = dict(trade_data)
                    symbol = trade['symbol']
                    try:
                        async with self.request_semaphore:
                            ohlcv = await self.exchange.fetch_ohlcv(symbol, '15m', limit=50)
                        if not ohlcv:
                            continue
                        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                        current_price = df['close'].iloc[-1]

                        # --- المنطق الأول: الخروج الاستباقي من الصفقات الضعيفة والعالقة ---
                        trade_open_time = datetime.fromisoformat(trade['timestamp'])
                        minutes_since_open = (datetime.now(timezone.utc).astimezone(trade_open_time.tzinfo) - trade_open_time).total_seconds() / 60
                        
                        if minutes_since_open > 45:
                            df['ema_slow'] = ta.ema(df['close'], length=30)
                            if current_price < (df['ema_slow'].iloc[-1] * 0.995) and btc_momentum_is_negative and current_price < trade['entry_price']:
                                logger.warning(f"Wise Man proactively detected SUSTAINED weakness in {symbol}. Requesting exit.")
                                await conn.execute("UPDATE trades SET status = 'pending_exit_confirmation' WHERE id = ?", (trade['id'],))
                                await conn.commit()
                                from okx_maestro import safe_send_message
                                await safe_send_message(self.application.bot, f"🧠 **إنذار ضعف! | #{trade['id']} {symbol}**\nرصد الرجل الحكيم ضعفًا مستمرًا، جاري مراجعة الخروج.")
                                continue # ننتقل للصفقة التالية بعد طلب الخروج

                        # --- المنطق الثاني: التمديد والتأمين الذكي المتدرج للصفقات القوية ---
                        settings = self.bot_data.settings
                        if not settings.get('trailing_sl_enabled', True):
                            continue

                        strong_adx_level = settings.get('wise_man_strong_adx_level', 30)
                        
                        # نسبة الاقتراب من الهدف المطلوبة لتفعيل التمديد (يمكن إضافتها للإعدادات)
                        PROXIMITY_PERCENT = 0.98  # يعني عندما يصل السعر إلى 98% من الهدف

                        # الشرط الجديد: هل السعر اقترب من الهدف الحالي؟
                        price_is_near_target = current_price >= (trade['take_profit'] * PROXIMITY_PERCENT)

                        if price_is_near_target:
                            adx_data = ta.adx(df['high'], df['low'], df['close'])
                            current_adx = adx_data['ADX_14'].iloc[-1] if adx_data is not None and not adx_data.empty else 0

                            # شرط الزخم لا يزال مطلوبًا
                            if current_adx > strong_adx_level:
                                # --- المنطق الجديد لتحديد الأهداف والوقف ---
                                previous_tp = trade['take_profit']
                                
                                # 1. الهدف الجديد يكون أعلى من الهدف السابق بنسبة 5% (يمكن تعديلها)
                                new_tp = previous_tp * 1.05
                                
                                # 2. الوقف الجديد هو الهدف السابق (أو تحته بـ 1% للأمان من الانزلاق السعري)
                                new_sl = previous_tp * 0.99

                                # 3. تحديث الهدف والوقف معًا في أمر واحد
                                await conn.execute(
                                    "UPDATE trades SET take_profit = ?, stop_loss = ? WHERE id = ?",
                                    (new_tp, new_sl, trade['id'],)
                                )
                                await conn.commit()
                                
                                logger.info(f"Wise Man extended TP to {new_tp} and TRAILED SL to {new_sl} for trade #{trade['id']}")
                                
                                from okx_maestro import safe_send_message
                                locked_in_profit_pct = (new_sl / trade['entry_price'] - 1) * 100 if trade['entry_price'] > 0 else 0
                                await safe_send_message(
                                    self.application.bot,
                                    f"🧠 **صعود مؤمّن! | #{trade['id']} {symbol}**\n"
                                    f"تم تحقيق الهدف، وبسبب الزخم تم:\n"
                                    f"  - **رفع الهدف إلى:** `${new_tp:.4f}`\n"
                                    f"  - **تأمين الوقف عند:** `${new_sl:.4f}` (ربح مؤمّن: `~{locked_in_profit_pct:+.2f}%`)"
                                )

                        await asyncio.sleep(2) # فاصل بسيط بين معالجة كل صفقة
                    except Exception as e:
                        logger.error(f"Wise Man: Error during tactical review for {symbol}: {e}", exc_info=True)
    # ==============================================================================
    # --- ♟️ المدير الاستراتيجي (يعمل كل ساعة) ♟️ ---
    # ==============================================================================
    async def review_portfolio_risk(self, context: object = None):
        """يراجع مخاطر المحفظة (تركيز الأصول، القطاعات، والارتباط) ويرسل تنبيهات."""
        logger.info("🧠 Wise Man: Starting portfolio risk review...")
        alerts = []
        try:
            async with self.request_semaphore:
                balance = await self.exchange.fetch_balance()
            assets = {a: d['total'] for a, d in balance.items() if isinstance(d, dict) and d.get('total', 0) > 1e-5 and a != 'USDT'}
            if not assets: return
            
            asset_list = [f"{asset}/USDT" for asset in assets.keys()]
            async with self.request_semaphore:
                tickers = await self.exchange.fetch_tickers(asset_list)
            
            total_portfolio_value = balance.get('USDT', {}).get('total', 0.0)
            asset_values = {}
            for asset, amount in assets.items():
                symbol = f"{asset}/USDT"
                if symbol in tickers and tickers[symbol] and tickers[symbol]['last'] is not None:
                    value_usdt = amount * tickers[symbol]['last']
                    if value_usdt > 1.0:
                        asset_values[asset] = value_usdt
                        total_portfolio_value += value_usdt
            if total_portfolio_value < 1.0: return
            
            # 1. Asset Concentration Check
            for asset, value in asset_values.items():
                concentration = (value / total_portfolio_value) * 100
                if concentration > PORTFOLIO_RISK_RULES['max_asset_concentration_pct']:
                    alerts.append(f"High Asset Concentration: `{asset}` is **{concentration:.1f}%** of portfolio.")
            
            # 2. Sector Concentration Check
            sector_values = defaultdict(float)
            for asset, value in asset_values.items():
                sector_values[SECTOR_MAP.get(asset, 'Other')] += value
            for sector, value in sector_values.items():
                concentration = (value / total_portfolio_value) * 100
                if concentration > PORTFOLIO_RISK_RULES['max_sector_concentration_pct']:
                    alerts.append(f"High Sector Concentration: '{sector}' sector is **{concentration:.1f}%** of portfolio.")
            
            # 3. Correlation Check for major holdings
            major_holdings = sorted(asset_values.items(), key=lambda item: item[1], reverse=True)[:3]
            for asset, value in major_holdings:
                correlation = await self._get_correlation(f"{asset}/USDT")
                if correlation > 0.9:
                    alerts.append(f"High Correlation Warning: `{asset}` has a very high correlation of **{correlation:.2f}** with BTC.")
            
            if alerts:
                from okx_maestro import safe_send_message
                message_body = "\n- ".join(alerts)
                message = f"⚠️ **تنبيه من الرجل الحكيم (إدارة المخاطر):**\n- {message_body}"
                await safe_send_message(self.application.bot, message)
                await self._send_email_alert("Wise Man: Portfolio Risk Warning", message.replace('`', '').replace('*', ''))

        except Exception as e:
            logger.error(f"Wise Man: Error during portfolio risk review: {e}", exc_info=True)
            
    # ==============================================================================
    # --- 🛠️ دوال مساعدة V2.0 🛠️ ---
    # ==============================================================================
    async def _get_correlation(self, symbol: str, df_symbol: pd.DataFrame = None) -> float:
        """يحسب الارتباط بين عملة و BTC، مع استخدام ذاكرة تخزين مؤقتة."""
        now = time.time()
        if symbol in self.correlation_cache and (now - self.correlation_cache[symbol]['timestamp'] < 3600):
            return self.correlation_cache[symbol]['value']
        try:
            async with self.request_semaphore:
                if df_symbol is None:
                    ohlcv_symbol = await self.exchange.fetch_ohlcv(symbol, '1h', limit=100)
                    df_symbol = pd.DataFrame(ohlcv_symbol, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                
                ohlcv_btc = await self.exchange.fetch_ohlcv('BTC/USDT', '1h', limit=100)
                df_btc = pd.DataFrame(ohlcv_btc, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            
            correlation = df_symbol['close'].corr(df_btc['close'])
            self.correlation_cache[symbol] = {'timestamp': now, 'value': correlation}
            return correlation
        except Exception as e:
            logger.error(f"Wise Man: Could not calculate correlation for {symbol}: {e}")
            return 0.5 # Return neutral value on error

    async def _send_email_alert(self, subject: str, body: str):
        """يرسل تنبيهًا عبر البريد الإلكتروني."""
        smtp_user = os.getenv('SMTP_USER')
        smtp_pass = os.getenv('SMTP_PASSWORD')
        smtp_server = os.getenv('SMTP_SERVER')
        smtp_port = os.getenv('SMTP_PORT')
        recipient = os.getenv('RECIPIENT_EMAIL')

        if not all([smtp_user, smtp_pass, smtp_server, smtp_port, recipient]):
            logger.warning("Wise Man: Email credentials not fully configured. Skipping email alert.")
            return

        msg = MIMEText(body)
        msg['Subject'] = subject
        msg['From'] = smtp_user
        msg['To'] = recipient

        try:
            with SMTP(smtp_server, int(smtp_port)) as server:
                server.starttls()
                server.login(smtp_user, smtp_pass)
                server.send_message(msg)
            logger.info(f"Wise Man: Successfully sent email alert: '{subject}'")
        except Exception as e:
            logger.error(f"Wise Man: Failed to send email alert: {e}", exc_info=True)
