import logging
import aiosqlite
import asyncio
import json
import pandas as pd
import pandas_ta as ta
import ccxt.async_support as ccxt

logger = logging.getLogger(__name__)

class EvolutionaryEngine:
    def __init__(self, exchange: ccxt.Exchange, db_file: str):
        """
        [النسخة النهائية] يتم الآن تمرير مسار قاعدة البيانات بشكل صريح.
        """
        self.exchange = exchange
        self.db_file = db_file
        logger.info("🧬 Evolutionary Engine Initialized (Final Version).")

    async def _capture_market_snapshot(self, symbol: str) -> dict:
        try:
            ohlcv = await self.exchange.fetch_ohlcv(symbol, '15m', limit=100)
            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            rsi = ta.rsi(df['close'], length=14)
            adx_data = ta.adx(df['high'], df['low'], df['close'])
            last_rsi = rsi.iloc[-1] if rsi is not None and not rsi.empty else None
            last_adx = adx_data['ADX_14'].iloc[-1] if adx_data is not None and not adx_data.empty else None
            snapshot = {"rsi_14": round(last_rsi, 2) if last_rsi is not None else "N/A", "adx_14": round(last_adx, 2) if last_adx is not None else "N/A"}
            return snapshot
        except Exception as e:
            logger.error(f"Smart Engine: Could not capture snapshot for {symbol}: {e}")
            return {}

    async def add_trade_to_journal(self, trade_details: dict):
        trade_id, symbol = trade_details.get('id'), trade_details.get('symbol')
        if not trade_id or not symbol: return
        logger.info(f"🧬 Journaling trade #{trade_id} for {symbol}...")
        try:
            snapshot = await self._capture_market_snapshot(symbol)
            async with aiosqlite.connect(self.db_file) as conn:
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS trade_journal (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        trade_id INTEGER,
                        entry_strategy TEXT,
                        entry_indicators_snapshot TEXT,
                        exit_reason TEXT,
                        FOREIGN KEY (trade_id) REFERENCES trades (id)
                    )
                """)
                await conn.execute("INSERT INTO trade_journal (trade_id, entry_strategy, entry_indicators_snapshot, exit_reason) VALUES (?, ?, ?, ?)",
                                   (trade_id, trade_details.get('reason'), json.dumps(snapshot), trade_details.get('status')))
                await conn.commit()
            logger.info(f"Successfully journaled trade #{trade_id}.")
        except Exception as e:
            logger.error(f"Smart Engine: Failed to journal trade #{trade_id}: {e}", exc_info=True)


