import logging
import aiosqlite
import asyncio
import json
import pandas as pd
import pandas_ta as ta
import ccxt.async_support as ccxt
from telegram.ext import Application # استيراد Application لإرسال الرسائل

logger = logging.getLogger(__name__)
DB_FILE = 'trading_bot_v6.6_binance.db'
ANALYSIS_PERIOD_CANDLES = 24

class EvolutionaryEngine:
    def __init__(self, exchange: ccxt.Exchange, application: Application):
        self.exchange = exchange
        self.application = application # نحفظ application لنتمكن من إرسال الرسائل
        self.telegram_chat_id = application.bot_data.get('TELEGRAM_CHAT_ID')
        logger.info("🧬 Evolutionary Engine Initialized. Ready to build memory.")

    async def _capture_market_snapshot(self, symbol: str) -> dict:
        """يلتقط صورة لحالة المؤشرات الفنية للسوق في لحظة معينة."""
        try:
            ohlcv = await self.exchange.fetch_ohlcv(symbol, '15m', limit=100)
            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            rsi = ta.rsi(df['close'], length=14).iloc[-1]
            adx_data = ta.adx(df['high'], df['low'], df['close'])
            adx = adx_data['ADX_14'].iloc[-1] if adx_data is not None else None
            return {"rsi": round(rsi, 2), "adx": round(adx, 2) if adx is not None else None}
        except Exception as e:
            logger.error(f"Smart Engine: Could not capture market snapshot for {symbol}: {e}")
            return {}

    async def add_trade_to_journal(self, trade_details: dict):
        """الوظيفة الرئيسية: تسجل الصفقة المغلقة في الذاكرة وتبدأ تحليل "ماذا لو؟" """
        trade_id = trade_details.get('id')
        symbol = trade_details.get('symbol')
        logger.info(f"🧬 Journaling trade #{trade_id} for {symbol}...")
        try:
            snapshot = await self._capture_market_snapshot(symbol)
            async with aiosqlite.connect(DB_FILE) as conn:
                await conn.execute("""
                    INSERT INTO trade_journal (trade_id, entry_strategy, entry_indicators_snapshot, exit_reason)
                    VALUES (?, ?, ?, ?)
                """, (
                    trade_id,
                    trade_details.get('reason'),
                    json.dumps(snapshot),
                    trade_details.get('status')
                ))
                await conn.commit()
            asyncio.create_task(self._perform_what_if_analysis(trade_details))
        except Exception as e:
            logger.error(f"Smart Engine: Failed to journal trade #{trade_id}: {e}", exc_info=True)

    async def _perform_what_if_analysis(self, trade_details: dict):
        """تحلل سلوك العملة بعد الخروج منها لتقييم جودة القرار."""
        trade_id = trade_details.get('id')
        symbol = trade_details.get('symbol')
        exit_reason = trade_details.get('status', '')
        original_tp = trade_details.get('take_profit')
        original_sl = trade_details.get('stop_loss')
        # risk_reward_ratio is not directly in trade_details, it's a setting. Defaulting to 2.0
        risk_reward_ratio = bot_data.settings.get('risk_reward_ratio', 2.0)

        await asyncio.sleep(60) 
        logger.info(f"🔬 Smart Engine: Performing 'What-If' analysis for closed trade #{trade_id} ({symbol})...")
        try:
            future_ohlcv = await self.exchange.fetch_ohlcv(symbol, '15m', limit=ANALYSIS_PERIOD_CANDLES)
            df_future = pd.DataFrame(future_ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            highest_price_after = df_future['high'].max()
            lowest_price_after = df_future['low'].min()
            score = 0
            notes = ""
            if 'SL' in exit_reason:
                if highest_price_after >= original_tp:
                    score = -10
                    notes = f"Stop Loss Regret: Price recovered and hit original TP ({original_tp})."
                else:
                    score = 10
                    notes = f"Good Save: Price continued to drop to {lowest_price_after} after SL."
            elif 'TP' in exit_reason:
                missed_profit_pct = ((highest_price_after / original_tp) - 1) * 100 if original_tp > 0 else 0
                if missed_profit_pct > (risk_reward_ratio * 100):
                    score = -5
                    notes = f"Missed Opportunity: Price rallied an additional {missed_profit_pct:.2f}% after TP."
                elif missed_profit_pct > 1.0:
                    score = 5
                    notes = f"Good Exit: Price rallied a little more."
                else:
                    score = 10
                    notes = f"Perfect Exit: Price dropped or stalled after TP."
            post_performance_data = {
                "highest_price_after": highest_price_after,
                "lowest_price_after": lowest_price_after,
                "analysis_period_hours": (ANALYSIS_PERIOD_CANDLES * 15) / 60
            }
            async with aiosqlite.connect(DB_FILE) as conn:
                await conn.execute("""
                    UPDATE trade_journal SET exit_quality_score = ?, post_exit_performance = ?, notes = ? WHERE trade_id = ?
                """, (score, json.dumps(post_performance_data), notes, trade_id))
                await conn.commit()
            logger.info(f"🔬 Analysis complete for trade #{trade_id}. Exit Quality Score: {score}. Notes: {notes}")
        except Exception as e:
            logger.error(f"Smart Engine: 'What-If' analysis failed for trade #{trade_id}: {e}", exc_info=True)

    # --- [الدالة المضافة] ---
    async def run_pattern_discovery(self, context: object = None):
        """
        تقوم بتحليل كل البيانات في السجل لاكتشاف أنماط وتقديم تقرير.
        """
        logger.info("🧬 Evolutionary Engine: Starting pattern discovery analysis...")
        report_lines = ["🧠 **تقرير الذكاء الاستراتيجي اليومي** 🧠\n"]
        try:
            async with aiosqlite.connect(DB_FILE) as conn:
                journal_df = pd.read_sql_query("SELECT * FROM trade_journal WHERE notes IS NOT NULL", conn)
                trades_df = pd.read_sql_query("SELECT id, symbol, pnl_usdt FROM trades", conn)
                
                if journal_df.empty or len(journal_df) < 5: # لا نرسل تقريرًا إذا كانت البيانات قليلة جدًا
                    logger.info("🧬 Pattern Discovery: Not enough journaled trades to create a report.")
                    return

                full_df = pd.merge(journal_df, trades_df, left_on='trade_id', right_on='id')

            # التحليل الأول: أداء الاستراتيجيات بناءً على جودة القرار
            strategy_quality = full_df.groupby('entry_strategy')['exit_quality_score'].mean().sort_values(ascending=False)
            report_lines.append("--- **أداء الاستراتيجيات (حسب جودة الخروج)** ---")
            for strategy, score in strategy_quality.items():
                if strategy:
                    report_lines.append(f"- `{strategy.split(' (')[0]}`: متوسط درجة الجودة **{score:+.2f}**")

            # التحليل الثاني: الأسباب الأكثر شيوعًا للندم أو النجاح
            common_notes = full_df['notes'].value_counts().nlargest(3)
            report_lines.append("\n--- **أهم الملاحظات المتكررة من 'ماذا لو؟'** ---")
            for note, count in common_notes.items():
                if note:
                    report_lines.append(f"- '{note}' (تكررت **{count}** مرات)")

            # التحليل الثالث: هل هناك استراتيجية تخسر باستمرار؟
            losing_strategies = full_df[full_df['pnl_usdt'] < 0]['entry_strategy'].value_counts()
            if not losing_strategies.empty:
                report_lines.append("\n--- **أكثر الاستراتيجيات تسببًا للخسارة** ---")
                for strategy, losses in losing_strategies.items():
                    if strategy:
                        report_lines.append(f"- `{strategy.split(' (')[0]}`: تسببت في **{losses}** صفقة خاسرة")

            # إرسال التقرير النهائي إلى تليجرام
            final_report = "\n".join(report_lines)
            await self.application.bot.send_message(self.telegram_chat_id, final_report)

            logger.info("🧬 Pattern Discovery analysis complete and report sent.")

        except Exception as e:
            logger.error(f"Smart Engine: Pattern discovery failed: {e}", exc_info=True)