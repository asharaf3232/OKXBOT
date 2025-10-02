import logging
import aiosqlite
import pandas as pd
import pandas_ta as ta
import ccxt.async_support as ccxt
from telegram.ext import Application
from collections import defaultdict
import asyncio

logger = logging.getLogger(__name__)

# (القواعد وقاموس القطاعات تبقى كما هي)
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
        """
        [النسخة النهائية] يتم الآن تمرير كل الاعتماديات بشكل صريح.
        """
        self.exchange = exchange
        self.application = application
        self.bot_data = bot_data_ref
        self.db_file = db_file
        self.telegram_chat_id = application.bot_data.get('TELEGRAM_CHAT_ID')
        logger.info("🧠 Wise Man module initialized (Final Version).")

    async def review_portfolio_risk(self, context: object = None):
        """
        تقوم هذه الدالة بفحص المحفظة ككل وإعطاء تنبيهات حول التركيز.
        """
        logger.info("🧠 Wise Man: Starting portfolio risk review...")
        try:
            balance = await self.exchange.fetch_balance()
            
            assets = {
                asset: data['total'] 
                for asset, data in balance.items() 
                if isinstance(data, dict) and data.get('total', 0) > 0.00001 and asset != 'USDT'
            }
            
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

        logger.info("🧠 Wise Man: Portfolio risk review complete.")


