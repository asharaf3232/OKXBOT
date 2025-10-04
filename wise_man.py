import logging
import aiosqlite
import pandas as pd
import pandas_ta as ta
import ccxt.async_support as ccxt
from telegram.ext import Application
from collections import defaultdict
import asyncio
import time
from datetime import datetime, timezone

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
        logger.info("🧠 Wise Man module upgraded to final 'Wise Guardian & Maestro' model.")

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
        """يراجع الفرص المرشحة ويقتنص أفضل لحظة للدخول."""
        async with aiosqlite.connect(self.db_file) as conn:
            conn.row_factory = aiosqlite.Row
            candidates = await (await conn.execute("SELECT * FROM trade_candidates WHERE status = 'pending'")).fetchall()
            for cand_data in candidates:
                candidate = dict(cand_data)
                symbol = candidate['symbol']
                trade_exists = await (await conn.execute("SELECT 1 FROM trades WHERE symbol = ? AND status IN ('active', 'pending')", (symbol,))).fetchone()
                if trade_exists:
                    await conn.execute("UPDATE trade_candidates SET status = 'cancelled_duplicate' WHERE id = ?", (candidate['id'],))
                    await conn.commit()
                    continue
                try:
                    ticker = await self.exchange.fetch_ticker(symbol)
                    current_price = ticker['last']
                    signal_price = candidate['entry_price']
                    if 0.995 * signal_price <= current_price <= 1.005 * signal_price:
                        logger.info(f"Wise Man confirms entry for {symbol}. Price is optimal. Initiating trade.")
                        from okx_maestro import initiate_real_trade 
                        if await initiate_real_trade(candidate, self.bot_data.settings, self.exchange, self.application.bot):
                            await conn.execute("UPDATE trade_candidates SET status = 'executed' WHERE id = ?", (candidate['id'],))
                        else:
                            await conn.execute("UPDATE trade_candidates SET status = 'failed_execution' WHERE id = ?", (candidate['id'],))
                    elif current_price > 1.01 * signal_price:
                        logger.info(f"Wise Man cancels entry for {symbol}. Price moved too far away.")
                        await conn.execute("UPDATE trade_candidates SET status = 'cancelled_price_moved' WHERE id = ?", (candidate['id'],))
                    elif time.time() - datetime.fromisoformat(candidate['timestamp']).timestamp() > 180:
                        logger.info(f"Wise Man cancels entry for {symbol}. Candidate expired.")
                        await conn.execute("UPDATE trade_candidates SET status = 'cancelled_expired' WHERE id = ?", (candidate['id'],))
                    await conn.commit()
                    await asyncio.sleep(1)
                except Exception as e:
                    logger.error(f"Wise Man: Error reviewing entry candidate for {symbol}: {e}")
                    await conn.execute("UPDATE trade_candidates SET status = 'error' WHERE id = ?", (candidate['id'],))
                    await conn.commit()

    # ==============================================================================
    # --- 2. منطق "نقطة الخروج الرائعة" (جزء من المحرك السريع) ---
    # ==============================================================================
    async def _review_pending_exits(self):
        """يراجع طلبات الخروج ويمنع الإغلاق المتسرع."""
        async with aiosqlite.connect(self.db_file) as conn:
            conn.row_factory = aiosqlite.Row
            trades_to_review = await (await conn.execute("SELECT * FROM trades WHERE status = 'pending_exit_confirmation'")).fetchall()
            for trade_data in trades_to_review:
                trade = dict(trade_data)
                symbol = trade['symbol']
                try:
                    ohlcv = await self.exchange.fetch_ohlcv(symbol, '1m', limit=20)
                    df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                    df['ema_9'] = ta.ema(df['close'], length=9)
                    current_price = df['close'].iloc[-1]
                    last_ema = df['ema_9'].iloc[-1]
                    if current_price < last_ema:
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
                    logger.error(f"Wise Man: Error making final exit decision for {symbol}: {e}. Forcing closure as a safety measure.")
                    await self.bot_data.trade_guardian._close_trade(trade, "فاشلة (خطأ في المراجعة)", trade['stop_loss'])

    # ==============================================================================
    # --- 🎼 المايسترو التكتيكي (يعمل كل 15 دقيقة) 🎼 ---
    # ==============================================================================
    async def review_active_trades_with_tactics(self, context: object = None):
        """يراجع الصفقات النشطة لتمديد الأهداف أو قطع الخسائر استباقيًا."""
        logger.info("🧠 Wise Man: Running tactical review (Exits & Extensions)...")
        async with aiosqlite.connect(self.db_file) as conn:
            conn.row_factory = aiosqlite.Row
            active_trades = await (await conn.execute("SELECT * FROM trades WHERE status = 'active'")).fetchall()
            try:
                btc_ohlcv = await self.exchange.fetch_ohlcv('BTC/USDT', '1h', limit=20)
                btc_df = pd.DataFrame(btc_ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                btc_momentum_is_negative = ta.mom(btc_df['close'], length=10).iloc[-1] < 0
            except Exception:
                btc_momentum_is_negative = False
            for trade_data in active_trades:
                trade = dict(trade_data)
                symbol = trade['symbol']
                try:
                    ohlcv = await self.exchange.fetch_ohlcv(symbol, '15m', limit=50)
                    df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                    current_price = df['close'].iloc[-1]
                    
                    trade_open_time = datetime.fromisoformat(trade['timestamp'])
                    minutes_since_open = (datetime.now(timezone.utc).astimezone(trade_open_time.tzinfo) - trade_open_time).total_seconds() / 60
                    if minutes_since_open > 45:
                        df['ema_slow'] = ta.ema(df['close'], length=30)
                        is_truly_weak = current_price < (df['ema_slow'].iloc[-1] * 0.995)
                        if is_truly_weak and btc_momentum_is_negative and current_price < trade['entry_price']:
                            logger.warning(f"Wise Man proactively detected SUSTAINED weakness in trade #{trade['id']} for {symbol}. Requesting exit confirmation.")
                            await conn.execute("UPDATE trades SET status = 'pending_exit_confirmation' WHERE id = ?", (trade['id'],))
                            await conn.commit()
                            from okx_maestro import safe_send_message
                            await safe_send_message(self.application.bot, f"🧠 **إنذار ضعف! | #{trade['id']} {symbol}**\nرصد الرجل الحكيم ضعفًا مستمرًا، جاري مراجعة الخروج.")
                            continue
                    
                    strong_profit_pct = self.bot_data.settings.get('wise_man_strong_profit_pct', 3.0)
                    strong_adx_level = self.bot_data.settings.get('wise_man_strong_adx_level', 30)
                    current_profit_pct = (current_price / trade['entry_price'] - 1) * 100
                    if current_profit_pct > strong_profit_pct:
                        adx_data = ta.adx(df['high'], df['low'], df['close'])
                        current_adx = adx_data['ADX_14'].iloc[-1] if adx_data is not None and not adx_data.empty else 0
                        is_strong = current_adx > strong_adx_level
                        if is_strong:
                            new_tp = trade['take_profit'] * 1.05
                            await conn.execute("UPDATE trades SET take_profit = ? WHERE id = ?", (new_tp, trade['id'],))
                            await conn.commit()
                            logger.info(f"Wise Man is extending TP for trade #{trade['id']} on {symbol} to {new_tp}")
                            from okx_maestro import safe_send_message
                            message = f"🧠 **تمديد الهدف! | #{trade['id']} {symbol}**\nتم رصد زخم قوي، تم رفع الهدف إلى `${new_tp:.4f}`"
                            await safe_send_message(self.application.bot, message)
                    await asyncio.sleep(2)
                except Exception as e:
                    logger.error(f"Wise Man: Error during tactical review for {symbol}: {e}")

    # ==============================================================================
    # --- ♟️ المدير الاستراتيجي (يعمل كل ساعة) ♟️ ---
    # ==============================================================================
    async def review_portfolio_risk(self, context: object = None):
        """يراجع مخاطر المحفظة ككل (تركيز الأصول والقطاعات)."""
        logger.info("🧠 Wise Man: Starting portfolio risk review...")
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
                    from okx_maestro import safe_send_message
                    await safe_send_message(self.application.bot, message)
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
                     from okx_maestro import safe_send_message
                     await safe_send_message(self.application.bot, message)
        except Exception as e:
            logger.error(f"Wise Man: Error during portfolio risk review: {e}", exc_info=True)
