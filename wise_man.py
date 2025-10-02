import logging
import aiosqlite
import pandas as pd
import pandas_ta as ta
import ccxt.async_support as ccxt
from telegram.ext import Application
import asyncio
from collections import defaultdict

logger = logging.getLogger(__name__)
DB_FILE = 'trading_bot_v6.6_binance.db' 
PORTFOLIO_RISK_RULES = {
    "max_asset_concentration_pct": 30.0,
    "max_sector_concentration_pct": 50.0,
}
SECTOR_MAP = {
    'RNDR': 'AI', 'FET': 'AI', 'AGIX': 'AI',
    'UNI': 'DeFi', 'AAVE': 'DeFi', 'LDO': 'DeFi',
    'SOL': 'Layer 1', 'ETH': 'Layer 1', 'AVAX': 'Layer 1',
    'DOGE': 'Memecoin', 'PEPE': 'Memecoin', 'SHIB': 'Memecoin',
    'LINK': 'Oracle', 'BAND': 'Oracle',
    'BTC': 'Layer 1'
}

class WiseMan:
    def __init__(self, exchange: ccxt.Exchange, application: Application, bot_data: object):
        self.exchange = exchange
        self.application = application
        self.bot_data = bot_data
        self.telegram_chat_id = application.bot_data.get('TELEGRAM_CHAT_ID')
        logger.info("🧠 Wise Man module initialized as an On-Demand Tactical Advisor.")

    async def send_telegram_message(self, text):
        try:
            if self.application and self.application.bot:
                await self.application.bot.send_message(self.telegram_chat_id, text, parse_mode='Markdown')
        except Exception as e:
            logger.error(f"Wise Man failed to send Telegram message: {e}")

    async def perform_deep_analysis(self, trade: dict):
        """
        [لقطع الخسائر] يتم استدعاء هذه الدالة لتحليل صفقة واحدة بشكل عميق وفوري.
        """
        symbol = trade['symbol']
        trade_id = trade['id']
        logger.info(f"🧠 Wise Man summoned for deep analysis of trade #{trade_id} [{symbol}]...")

        try:
            async with aiosqlite.connect(DB_FILE) as conn:
                ohlcv_task = self.exchange.fetch_ohlcv(symbol, '15m', limit=100)
                btc_ohlcv_task = self.exchange.fetch_ohlcv('BTC/USDT', '1h', limit=100)
                ohlcv, btc_ohlcv = await asyncio.gather(ohlcv_task, btc_ohlcv_task)

                if not ohlcv:
                    logger.warning(f"Wise Man Analysis Canceled: Could not fetch OHLCV for {symbol}.")
                    return

                df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                df['ema_fast'] = ta.ema(df['close'], length=10)
                df['ema_slow'] = ta.ema(df['close'], length=30)
                is_weak = df['close'].iloc[-1] < df['ema_fast'].iloc[-1] and df['close'].iloc[-1] < df['ema_slow'].iloc[-1]

                btc_is_bearish = False
                if btc_ohlcv:
                    btc_df = pd.DataFrame(btc_ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                    btc_df['btc_momentum'] = ta.mom(btc_df['close'], length=10)
                    if not btc_df.empty:
                        btc_is_bearish = btc_df['btc_momentum'].iloc[-1] < 0
                
                logger.info(f"Analysis for {symbol}: is_weak={is_weak}, btc_is_bearish={btc_is_bearish}")

                if is_weak and btc_is_bearish:
                    settings = self.bot_data.settings
                    if settings.get("wise_man_auto_close", True):
                        await conn.execute("UPDATE trades SET status = 'force_exit' WHERE id = ?", (trade_id,))
                        await self.send_telegram_message(f"🧠 **إغلاق آلي فوري** | `#{trade_id} {symbol}`\nأظهر التحليل العميق ضعفاً حاداً.")
                    else:
                        await self.send_telegram_message(f"💡 **تحذير تكتيكي** | `#{trade_id} {symbol}`\nرصد ضعف حاد. يُنصح بالخروج اليدوي.")
                    await conn.commit()
                else:
                    logger.info(f"Wise Man Deep Analysis Concluded: No critical weakness found for {symbol}.")

        except Exception as e:
            logger.error(f"Wise Man: Deep analysis failed for trade #{trade_id}: {e}", exc_info=True)

    async def check_for_strong_momentum(self, trade: dict):
        """
        [لتمديد الأرباح] يتم استدعاؤها عند تحقيق ربح متزايد للتحقق من الزخم وتمديد الهدف.
        """
        symbol = trade['symbol']
        trade_id = trade['id']
        logger.info(f"🧠 Wise Man summoned to check strong momentum for trade #{trade_id} [{symbol}]...")

        try:
            ohlcv = await self.exchange.fetch_ohlcv(symbol, '15m', limit=50)
            if not ohlcv: return

            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            adx_data = df.ta.adx()

            if adx_data is None or adx_data.empty: return
            current_adx = adx_data.iloc[-1]['ADX_14']
            
            settings = self.bot_data.settings
            strong_adx_level = settings.get('wise_man_strong_adx_level', 30)

            if current_adx > strong_adx_level:
                async with aiosqlite.connect(DB_FILE) as conn:
                    current_price = df['close'].iloc[-1]
                    df.ta.atr(append=True, length=14)
                    atr_col = next((col for col in df.columns if col.startswith('ATRr_')), None)
                    if not atr_col: return
                    
                    atr = df.iloc[-1].get(atr_col, 0)
                    new_tp = current_price + (atr * settings.get('risk_reward_ratio', 2.0))
                    
                    if new_tp > trade['take_profit']:
                        await conn.execute("UPDATE trades SET take_profit = ? WHERE id = ?", (new_tp, trade_id))
                        await conn.commit()
                        await self.send_telegram_message(f"🧠 **تمديد الهدف!** | `#{trade_id} {symbol}`\nتم رصد زخم قوي، تم رفع الهدف إلى `${new_tp:.4f}`")
                        logger.info(f"Wise Man extended TP for trade #{trade_id} to {new_tp} due to strong momentum (ADX: {current_adx}).")

        except Exception as e:
            logger.error(f"Wise Man: Strong momentum check failed for trade #{trade_id}: {e}", exc_info=True)

    async def review_portfolio_risk(self, context: object = None):
        """
        تقوم هذه الدالة بفحص المحفظة ككل وإعطاء تنبيهات حول التركيز.
        """
        logger.info("🧠 Wise Man: Starting periodic portfolio risk review...")
        try:
            balance = await self.exchange.fetch_balance()
            
            assets = { asset: data['total'] for asset, data in balance.items() if isinstance(data, dict) and data.get('total', 0) > 0.00001 and asset != 'USDT' }
            
            if not assets:
                logger.info("🧠 Wise Man: Portfolio is empty (only USDT). No risks to analyze.")
                return

            asset_list = [f"{asset}/USDT" for asset in assets.keys() if asset != 'USDT']
            if not asset_list: return

            tickers = await self.exchange.fetch_tickers(asset_list)
            
            usdt_total = balance.get('USDT', {}).get('total', 0.0)
            if not isinstance(usdt_total, float): usdt_total = 0.0
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
                if concentration_pct > PORTFOLIO_RISK_RULES['max_asset_concentration_pct']:
                    message = (f"⚠️ **تنبيه من الرجل الحكيم (إدارة المخاطر):**\n"
                               f"تركيز المخاطر عالٍ! عملة `{asset}` تشكل **{concentration_pct:.1f}%** من قيمة المحفظة، "
                               f"وهو ما يتجاوز الحد المسموح به ({PORTFOLIO_RISK_RULES['max_asset_concentration_pct']}%).")
                    await self.send_telegram_message(message)

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
                    await self.send_telegram_message(message)

        except Exception as e:
            logger.error(f"Wise Man: Error during portfolio risk review: {e}", exc_info=True)

        logger.info("🧠 Wise Man: Portfolio risk review complete.")