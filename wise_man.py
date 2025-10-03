import logging
import aiosqlite
import pandas as pd
import pandas_ta as ta
import ccxt.async_support as ccxt
from telegram.ext import Application
from collections import defaultdict
import asyncio
import time

# --- إعدادات أساسية ---
logger = logging.getLogger(__name__)

# --- قواعد إدارة مخاطر المحفظة ---
PORTFOLIO_RISK_RULES = {
    "max_asset_concentration_pct": 30.0,
    "max_sector_concentration_pct": 50.0,
}
SECTOR_MAP = {
    'RNDR': 'AI', 'FET': 'AI', 'AGIX': 'AI', 'UNI': 'DeFi', 'AAVE': 'DeFi',
    'LDO': 'DeFi', 'SOL': 'Layer 1', 'ETH': 'Layer 1', 'AVAX': 'Layer 1',
    'DOGE': 'Memecoin', 'PEPE': 'Memecoin', 'SHIB': 'Memecoin', 'LINK': 'Oracle',
    'BAND': 'Oracle', 'BTC': 'Layer 1'
}

class WiseMan:
    def __init__(self, exchange: ccxt.Exchange, application: Application, bot_data_ref: object, db_file: str):
        self.exchange = exchange
        self.application = application
        self.bot_data = bot_data_ref
        self.db_file = db_file
        self.telegram_chat_id = application.bot_data.get('TELEGRAM_CHAT_ID')
        logger.info("🧠 Wise Man module upgraded to 'Wise Guardian' model.")

    # ==============================================================================
    # --- 🚀 المحرك الرئيسي الجديد (الجسد الرياضي) 🚀 ---
    # ==============================================================================
    async def run_realtime_review(self, context: object = None):
        """
        هذه هي المهمة السريعة التي تعمل كل بضع ثوانٍ لاتخاذ قرارات الدخول والخروج.
        """
        await self._review_pending_entries()
        await self._review_pending_exits()

    # ==============================================================================
    # --- 1. منطق "نقطة الدخول الممتازة" ---
    # ==============================================================================
    async def _review_pending_entries(self):
        async with aiosqlite.connect(self.db_file) as conn:
            conn.row_factory = aiosqlite.Row
            candidates = await (await conn.execute("SELECT * FROM trade_candidates WHERE status = 'pending'")).fetchall()

            for cand_data in candidates:
                candidate = dict(cand_data)
                symbol = candidate['symbol']
                
                # التحقق من عدم وجود صفقة مفتوحة بالفعل لهذه العملة
                trade_exists = await (await conn.execute("SELECT 1 FROM trades WHERE symbol = ? AND status IN ('active', 'pending')", (symbol,))).fetchone()
                if trade_exists:
                    await conn.execute("UPDATE trade_candidates SET status = 'cancelled_duplicate' WHERE id = ?", (candidate['id'],))
                    await conn.commit()
                    continue

                try:
                    ticker = await self.exchange.fetch_ticker(symbol)
                    current_price = ticker['last']
                    signal_price = candidate['entry_price']

                    # قرار الدخول: هل السعر الحالي فرصة أفضل؟
                    if 0.995 * signal_price <= current_price <= 1.005 * signal_price:
                        logger.info(f"Wise Man confirms entry for {symbol}. Price is optimal. Initiating trade.")
                        # استدعاء دالة فتح الصفقة من الملف الرئيسي
                        from okx_maestro import initiate_real_trade 
                        if await initiate_real_trade(candidate):
                             await conn.execute("UPDATE trade_candidates SET status = 'executed' WHERE id = ?", (candidate['id'],))
                        else:
                             await conn.execute("UPDATE trade_candidates SET status = 'failed_execution' WHERE id = ?", (candidate['id'],))
                    
                    # إذا ارتفع السعر كثيرًا، ألغِ الفرصة
                    elif current_price > 1.01 * signal_price: # ارتفع أكثر من 1%
                        logger.info(f"Wise Man cancels entry for {symbol}. Price moved too far away.")
                        await conn.execute("UPDATE trade_candidates SET status = 'cancelled_price_moved' WHERE id = ?", (candidate['id'],))

                    # إذا مر وقت طويل، ألغِ الفرصة
                    elif time.time() - datetime.fromisoformat(candidate['timestamp']).timestamp() > 180: # 3 دقائق
                         logger.info(f"Wise Man cancels entry for {symbol}. Candidate expired.")
                         await conn.execute("UPDATE trade_candidates SET status = 'cancelled_expired' WHERE id = ?", (candidate['id'],))

                    await conn.commit()
                    await asyncio.sleep(1) # فاصل بسيط بين مراجعة كل مرشح

                except Exception as e:
                    logger.error(f"Wise Man: Error reviewing entry candidate for {symbol}: {e}")
                    await conn.execute("UPDATE trade_candidates SET status = 'error' WHERE id = ?", (candidate['id'],))
                    await conn.commit()

    # ==============================================================================
    # --- 2. منطق "نقطة الخروج الرائعة" ---
    # ==============================================================================
    async def _review_pending_exits(self):
        async with aiosqlite.connect(self.db_file) as conn:
            conn.row_factory = aiosqlite.Row
            trades_to_review = await (await conn.execute("SELECT * FROM trades WHERE status = 'pending_exit_confirmation'")).fetchall()

            for trade_data in trades_to_review:
                trade = dict(trade_data)
                symbol = trade['symbol']
                try:
                    # فحص خاطف للزخم باستخدام بيانات دقيقة واحدة
                    ohlcv = await self.exchange.fetch_ohlcv(symbol, '1m', limit=20)
                    df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                    df['ema_9'] = ta.ema(df['close'], length=9)
                    
                    current_price = df['close'].iloc[-1]
                    last_ema = df['ema_9'].iloc[-1]

                    # القرار الحكيم: هل الهبوط حقيقي أم مجرد تذبذب؟
                    if current_price < last_ema:
                        # الزخم لا يزال سلبيًا، نؤكد الخروج
                        logger.warning(f"Wise Man confirms exit for {symbol}. Momentum is weak. Closing trade #{trade['id']}.")
                        await self.bot_data.trade_guardian._close_trade(trade, "فاشلة (بقرار حكيم)", current_price)
                    else:
                        # السعر ارتد فوق المتوسط، هذا تذبذب. أعطِ الصفقة فرصة أخرى
                        logger.info(f"Wise Man cancels exit for {symbol}. Price recovered. Resetting status to active for trade #{trade['id']}.")
                        await conn.execute("UPDATE trades SET status = 'active' WHERE id = ?", (trade['id'],))
                        await conn.commit()
                
                except Exception as e:
                    logger.error(f"Wise Man: Error making final exit decision for {symbol}: {e}. Forcing closure as a safety measure.")
                    await self.bot_data.trade_guardian._close_trade(trade, "فاشلة (خطأ في المراجعة)", trade['stop_loss'])

    # ==============================================================================
    # --- 3. الوظائف القديمة (لا تزال مفيدة) ---
    # ==============================================================================
    async def review_portfolio_risk(self, context: object = None):
        """
        هذه الدالة تبقى كما هي لمراقبة مخاطر المحفظة ككل.
        """
        logger.info("🧠 Wise Man: Starting portfolio risk review...")
        # ... الكود هنا يبقى كما هو بدون أي تغيير ...
        try:
            balance = await self.exchange.fetch_balance()
            assets = {asset: data['total'] for asset, data in balance.items() if isinstance(data, dict) and data.get('total', 0) > 0.00001 and asset != 'USDT'}
            if not assets: return
            asset_list = [f"{asset}/USDT" for asset in assets.keys() if asset != 'USDT']
            if not asset_list: return
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
            for asset, value in asset_values.items():
                concentration_pct = (value / total_portfolio_value) * 100
                if concentration_pct > PORTFOLIO_RISK_RULES['max_asset_concentration_pct']:
                    message = (f"⚠️ **تنبيه من الرجل الحكيم (إدارة المخاطر):**\n"
                               f"تركيز المخاطر عالٍ! عملة `{asset}` تشكل **{concentration_pct:.1f}%** من قيمة المحفظة، "
                               f"وهو ما يتجاوز الحد المسموح به ({PORTFOLIO_RISK_RULES['max_asset_concentration_pct']}%).")
                    await self.application.bot.send_message(self.telegram_chat_id, message)
            sector_values = defaultdict(float)
            for asset, value in asset_values.items():
                sector = SECTOR_MAP.get(asset, 'Other')
                sector_values[sector] += value
            for sector, value in sector_values.items():
                concentration_pct = (value / total_portfolio_value) * 100
                if concentration_pct > PORTFOLIO_RISK_RULES['max_sector_concentration_pct']:
                     message = (f"⚠️ **تنبيه من الرجل الحكيم (إدارة المخاطر):**\n"
                               f"تركيز قطاعي! أصول قطاع **'{sector}'** تشكل **{concentration_pct:.1f}%** من المحفظة، "
                               f"مما يعرضك لتقلبات هذا القطاع بشكل كبير (الحد المسموح به: {PORTFOLIO_RISK_RULES['max_sector_concentration_pct']}%).")
                     await self.application.bot.send_message(self.telegram_chat_id, message)
        except Exception as e:
            logger.error(f"Wise Man: Error during portfolio risk review: {e}", exc_info=True)
