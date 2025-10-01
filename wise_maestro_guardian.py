# -*- coding: utf-8 -*-
# =======================================================================================
# --- 🛡️ Wise Maestro Guardian - v2.2 (Final Corrected) 🛡️ ---
# =======================================================================================
import logging
import asyncio
import aiosqlite
import pandas as pd
import pandas_ta as ta
import ccxt.async_support as ccxt
from telegram.ext import Application
from collections import defaultdict
from datetime import datetime, timedelta
import json
from zoneinfo import ZoneInfo # <<< تم إضافة هذا السطر

# --- هذه الاستيرادات ضرورية للمنطق الداخلي ---
from settings_config import PORTFOLIO_RISK_RULES, SECTOR_MAP, STRATEGY_NAMES_AR, TIMEFRAME
from strategy_scanners import find_col, SCANNERS

logger = logging.getLogger(__name__)

# سيتم تعيين هذه المتغيرات في الملف الرئيسي
DB_FILE = None 
bot_data = None 
EGYPT_TZ = ZoneInfo("Africa/Cairo") # <<< تم إضافة هذا السطر

class TradeGuardian:
    def __init__(self, exchange: ccxt.Exchange, application: Application, bot_state_object: object, db_file: str):
        global DB_FILE, bot_data
        DB_FILE = db_file
        bot_data = bot_state_object
        self.exchange = exchange
        self.application = application
        self.telegram_chat_id = bot_data.TELEGRAM_CHAT_ID 
        logger.info("🛡️ Wise Maestro Guardian (Hardened Edition) initialized.")

    async def safe_send_message(self, text, **kwargs):
        if self.telegram_chat_id:
            try:
                await self.application.bot.send_message(self.telegram_chat_id, text, parse_mode='Markdown', **kwargs)
            except Exception as e:
                logger.error(f"Telegram Send Error: {e}")

    def _safe_get_indicator(self, df: pd.DataFrame, indicator_prefix: str, default_value=0.0, index=-1):
        try:
            col_name = find_col(df.columns, indicator_prefix)
            if col_name and not df[col_name].dropna().empty:
                return df[col_name].iloc[index]
            return default_value
        except (IndexError, KeyError) as e:
            logger.error(f"Safe get: Error accessing indicator '{indicator_prefix}': {e}")
            return default_value

    def _format_duration(self, duration_delta: timedelta) -> str:
        seconds = duration_delta.total_seconds()
        if seconds < 60: return "أقل من دقيقة"
        
        days, remainder = divmod(seconds, 86400)
        hours, remainder = divmod(remainder, 3600)
        minutes, _ = divmod(remainder, 60)
        
        parts = []
        if days > 0: parts.append(f"{int(days)} يوم")
        if hours > 0: parts.append(f"{int(hours)} ساعة")
        if minutes > 0: parts.append(f"{int(minutes)} دقيقة")
        return " و ".join(parts)

    async def review_open_trades(self, context: object = None):
        if not bot_data.settings.get('adaptive_intelligence_enabled', True): return
        logger.info("🧠 Wise Man: Starting periodic review of open trades...")
        
        async with aiosqlite.connect(DB_FILE) as conn:
            conn.row_factory = aiosqlite.Row
            active_trades = await (await conn.execute("SELECT * FROM trades WHERE status = 'active'")).fetchall()
            if not active_trades: return

            try:
                btc_ohlcv = await self.exchange.fetch_ohlcv('BTC/USDT', '1h', limit=30)
                btc_df = pd.DataFrame(btc_ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                btc_momentum = ta.mom(btc_df['close'], length=10).iloc[-1] if not btc_df.empty else 0
            except Exception as e:
                logger.error(f"Wise Man: Could not fetch BTC data for comparison: {e}")
                btc_momentum = 0

            for trade_data in active_trades:
                trade = dict(trade_data)
                symbol = trade['symbol']
                
                try:
                    ohlcv = await self.exchange.fetch_ohlcv(symbol, '15m', limit=50)
                    if not ohlcv: continue
                    df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                    current_price = df['close'].iloc[-1]
                    
                    df['ema_fast'] = ta.ema(df['close'], length=10)
                    df['ema_slow'] = ta.ema(df['close'], length=30)
                    
                    try:
                        is_weak = current_price < df['ema_fast'].iloc[-1] and current_price < df['ema_slow'].iloc[-1]
                    except IndexError:
                        is_weak = False

                    if is_weak and btc_momentum < 0 and current_price < trade['entry_price']:
                        logger.warning(f"Wise Man recommends early exit for {symbol} (Weakness + BTC down).")
                        await self._close_trade(trade, "إغلاق مبكر (Wise Man)", current_price)
                        await self.safe_send_message(f"🧠 **توصية من الرجل الحكيم | #{trade['id']} {symbol}**\nتم رصد ضعف تكتيكي مع هبوط BTC. تم طلب الخروج المبكر لحماية رأس المال.")
                        continue

                    current_profit_pct = (current_price / trade['entry_price'] - 1) * 100
                    df.ta.adx(append=True)
                    current_adx = self._safe_get_indicator(df, "ADX_14", default_value=20)
                    is_strong = current_profit_pct > 3.0 and current_adx > 30

                    if is_strong:
                        new_tp = trade['take_profit'] * 1.05
                        await conn.execute("UPDATE trades SET take_profit = ? WHERE id = ?", (new_tp, trade['id']))
                        await conn.commit()
                        logger.info(f"Wise Man recommends extending target for {symbol}. New TP: {new_tp:.4f}")
                        await self.safe_send_message(f"🧠 **نصيحة من الرجل الحكيم | #{trade['id']} {symbol}**\nتم رصد زخم قوي. تم تمديد الهدف إلى `${new_tp:.4f}`.")

                except Exception as e:
                    logger.error(f"Wise Man: Failed to analyze trade #{trade['id']} for {symbol}: {e}")
                
                await asyncio.sleep(1)

    async def intelligent_reviewer_job(self, context: object = None):
        if not bot_data.settings.get('intelligent_reviewer_enabled', True): return
        logger.info("🧠 Intelligent Reviewer: Reviewing active trades for signal validity...")
        
        async with aiosqlite.connect(DB_FILE) as conn:
            conn.row_factory = aiosqlite.Row
            active_trades = await (await conn.execute("SELECT * FROM trades WHERE status = 'active'")).fetchall()
        
        for trade in active_trades:
            trade_dict = dict(trade)
            symbol = trade_dict['symbol']
            reasons_list = trade_dict['reason'].split(' (')[0].split(' + ') 
            primary_reason = reasons_list[0].strip()

            if primary_reason not in SCANNERS: continue

            try:
                ohlcv = await self.exchange.fetch_ohlcv(symbol, TIMEFRAME, limit=220)
                if not ohlcv or len(ohlcv) < 50: continue
                
                df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                
                analyzer_func = SCANNERS[primary_reason]
                params = bot_data.settings.get(primary_reason, {})
                
                # We pass dummy values for rvol and adx_value as this function doesn't use them
                func_args = {'df': df.copy(), 'params': params, 'rvol': 1.0, 'adx_value': 25}
                if primary_reason in ['support_rebound']:
                    func_args.update({'exchange': self.exchange, 'symbol': symbol})
                
                result = await analyzer_func(**func_args) if asyncio.iscoroutinefunction(analyzer_func) else analyzer_func(**{k: v for k, v in func_args.items() if k not in ['exchange', 'symbol']})

                if not result:
                    current_price = df['close'].iloc[-1]
                    await self._close_trade(trade_dict, f"إغلاق (المراجع الذكي: {STRATEGY_NAMES_AR.get(primary_reason, primary_reason)})", current_price)
                    logger.info(f"🧠 Intelligent Reviewer: Closed trade #{trade_dict['id']} - Signal invalidated.")
            except Exception as e:
                logger.error(f"Intelligent Reviewer failed for {symbol}: {e}", exc_info=True)
        
        logger.info("🧠 Intelligent Reviewer: Review cycle complete.")

    async def handle_ticker_update(self, standard_ticker: dict):
        async with bot_data.trade_management_lock:
            symbol = standard_ticker['symbol']
            current_price = standard_ticker['price']
            
            try:
                async with aiosqlite.connect(DB_FILE) as conn:
                    conn.row_factory = aiosqlite.Row
                    trade = await (await conn.execute("SELECT * FROM trades WHERE symbol = ? AND status IN ('active', 'retry_exit', 'force_exit')", (symbol,))).fetchone()
                    
                    if not trade: return
                    trade = dict(trade); settings = bot_data.settings

                    should_close, close_reason = False, ""
                    if trade['status'] == 'force_exit':
                        should_close, close_reason = True, "فاشلة (بأمر الرجل الحكيم)"
                    elif trade['status'] == 'retry_exit':
                        should_close, close_reason = True, "فاشلة (SL-Supervisor)"
                    elif trade['status'] == 'active':
                        if current_price <= trade['stop_loss']:
                            should_close = True
                            reason = "فاشلة (SL)"
                            if trade.get('trailing_sl_active', False):
                                reason = "تم تأمين الربح (TSL)" if current_price > trade['entry_price'] else "فاشلة (TSL)"
                            close_reason = reason
                        elif settings.get('momentum_scalp_mode_enabled', False) and current_price >= trade['entry_price'] * (1 + settings.get('momentum_scalp_target_percent', 0.5) / 100):
                            should_close, close_reason = True, "ناجحة (Scalp Mode)"
                        elif current_price >= trade['take_profit']: 
                            should_close, close_reason = True, "ناجحة (TP)"
                    
                    if should_close:
                        await self._close_trade(trade, close_reason, current_price)
                        return

                    if trade['status'] == 'active':
                        new_highest_price = max(trade.get('highest_price', 0), current_price)
                        if new_highest_price > trade.get('highest_price', 0):
                            await conn.execute("UPDATE trades SET highest_price = ? WHERE id = ?", (new_highest_price, trade['id']))
                        
                        if settings.get('trailing_sl_enabled', True):
                            if not trade.get('trailing_sl_active', False) and current_price >= trade['entry_price'] * (1 + settings['trailing_sl_activation_percent'] / 100):
                                new_sl = trade['entry_price'] * 1.001
                                if new_sl > trade['stop_loss']:
                                    await conn.execute("UPDATE trades SET trailing_sl_active = 1, stop_loss = ? WHERE id = ?", (new_sl, trade['id']))
                                    await self.safe_send_message(f"🚀 **تأمين الأرباح! | #{trade['id']} {symbol}**\nتم رفع وقف الخسارة إلى نقطة الدخول: `${new_sl:.4f}`")
                            
                            if trade.get('trailing_sl_active', False):
                                new_sl_candidate = new_highest_price * (1 - settings['trailing_sl_callback_percent'] / 100)
                                if new_sl_candidate > trade['stop_loss']:
                                    await conn.execute("UPDATE trades SET stop_loss = ? WHERE id = ?", (new_sl_candidate, trade['id']))

                        if settings.get('incremental_notifications_enabled', True):
                            last_notified = trade.get('last_profit_notification_price', trade['entry_price'])
                            increment = settings.get('incremental_notification_percent', 2.0) / 100
                            if current_price >= last_notified * (1 + increment):
                                profit_percent = ((current_price / trade['entry_price']) - 1) * 100
                                await self.safe_send_message(f"📈 **ربح متزايد! | #{trade['id']} {symbol}**\n**الربح الحالي:** `{profit_percent:+.2f}%`")
                                await conn.execute("UPDATE trades SET last_profit_notification_price = ? WHERE id = ?", (current_price, trade['id']))
                        
                        await conn.commit()
            except Exception as e: 
                logger.error(f"Guardian Ticker Error for {symbol}: {e}", exc_info=True)
                
    async def _close_trade(self, trade: dict, reason: str, close_price: float):
        symbol, trade_id = trade['symbol'], trade['id']

        try:
            async with aiosqlite.connect(DB_FILE) as conn:
                cursor = await conn.execute("UPDATE trades SET status = 'closing' WHERE id = ? AND status IN ('active', 'retry_exit', 'force_exit')", (trade_id,))
                await conn.commit()
                if cursor.rowcount == 0:
                    logger.warning(f"Closure for trade #{trade_id} ignored; not in a closable state.")
                    return
        except Exception as e:
            logger.error(f"CRITICAL DB ACTION FAILED for trade #{trade_id}: {e}")
            return

        logger.info(f"🛡️ Initiating ULTIMATE Hardened Closure for trade #{trade_id} [{symbol}]. Reason: {reason}")
        
        try:
            base_currency = symbol.split('/')[0]
            balance = await bot_data.exchange.fetch_balance()
            available_quantity = balance.get(base_currency, {}).get('free', 0.0)
            
            if available_quantity <= 0.00000001:
                logger.warning(f"[{symbol}] No available balance. Cleaning up trade #{trade_id}.")
                async with aiosqlite.connect(DB_FILE) as conn:
                    await conn.execute("UPDATE trades SET status = ?, close_price = ?, pnl_usdt = ? WHERE id = ?", (f"{reason} (No Balance)", close_price, 0.0, trade_id))
                    await conn.commit()
                if hasattr(bot_data, 'public_ws'): await bot_data.public_ws.unsubscribe([symbol])
                return

            market = bot_data.exchange.market(symbol)
            quantity_to_sell = float(bot_data.exchange.amount_to_precision(symbol, available_quantity))
            
            min_qty = float(market.get('limits', {}).get('amount', {}).get('min', '0'))
            if min_qty > 0 and quantity_to_sell < min_qty:
                raise ccxt.InvalidOrder(f"Qty {quantity_to_sell} < min {min_qty}.")

            params = {'tdMode': 'cash'} if self.exchange.id == 'okx' else {}
            await bot_data.exchange.create_market_sell_order(symbol, quantity_to_sell, params=params)
            
            pnl = (close_price - trade['entry_price']) * quantity_to_sell
            pnl_percent = (close_price / trade['entry_price'] - 1) * 100 if trade['entry_price'] > 0 else 0
            is_profit = pnl >= 0

            async with aiosqlite.connect(DB_FILE) as conn:
                await conn.execute("UPDATE trades SET status = ?, close_price = ?, pnl_usdt = ? WHERE id = ?", (reason, close_price, pnl, trade_id))
                await conn.commit()
            
            trade_duration = self._format_duration(datetime.now(EGYPT_TZ) - datetime.fromisoformat(trade['timestamp']))
            
            exit_efficiency_str = ""
            if is_profit and trade.get('highest_price', 0) > trade['entry_price']:
                peak_gain = trade['highest_price'] - trade['entry_price']
                actual_gain = close_price - trade['entry_price']
                if peak_gain > 0:
                    efficiency = min((actual_gain / peak_gain) * 100, 100.0)
                    exit_efficiency_str = f"🧠 *كفاءة الخروج:* {efficiency:.2f}%\n"

            title = "✅ ملف المهمة المكتملة" if is_profit else "🛑 ملف المهمة المغلقة"
            profit_emoji = "💰" if is_profit else "💸"
            reasons_ar = ' + '.join([STRATEGY_NAMES_AR.get(r.strip().split(' (')[0], r.strip().split(' (')[0]) for r in trade['reason'].split(' + ')])

            message_body = (
                f"▫️ *العملة:* `{trade['symbol']}` | *السبب:* `{reason}`\n"
                f"▫️ *الاستراتيجية:* `{reasons_ar}`\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"{profit_emoji} *الربح/الخسارة:* `${pnl:,.2f}` **({pnl_percent:,.2f}%)**\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"⏳ *مدة الصفقة:* {trade_duration}\n"
                f"📉 *سعر الدخول:* `${trade['entry_price']:,.4f}`\n"
                f"📈 *سعر الخروج:* `${close_price:,.4f}`\n"
                f"🔝 *أعلى سعر:* `${trade.get('highest_price', 0):,.4f}`\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"{exit_efficiency_str}"
            )
            final_message = f"**{title}**\n\n{message_body}"
            await self.safe_send_message(final_message)

            if hasattr(bot_data, 'smart_brain'):
                final_trade_details = dict(trade)
                final_trade_details.update({'status': reason, 'close_price': close_price, 'pnl_usdt': pnl})
                await bot_data.smart_brain.add_trade_to_journal(final_trade_details)

        except (ccxt.InvalidOrder, ccxt.InsufficientFunds) as e:
             logger.warning(f"Closure for #{trade_id} failed with trade rule error, moving to incubator: {e}")
             async with aiosqlite.connect(DB_FILE) as conn:
                await conn.execute("UPDATE trades SET status = 'incubated' WHERE id = ?", (trade_id,))
                await conn.commit()
        except Exception as e:
            logger.critical(f"CRITICAL: ULTIMATE closure for #{trade_id} failed. MOVING TO INCUBATOR: {e}", exc_info=True)
            async with aiosqlite.connect(DB_FILE) as conn:
                await conn.execute("UPDATE trades SET status = 'incubated' WHERE id = ?", (trade_id,))
                await conn.commit()
            await self.safe_send_message(f"⚠️ **فشل الإغلاق | #{trade_id} {symbol}**\nسيتم نقل الصفقة إلى الحضانة للمراقبة.")
        finally:
            if hasattr(bot_data, 'public_ws'): await bot_data.public_ws.unsubscribe([symbol])

    async def the_supervisor_job(self, context: object = None):
        logger.info("🕵️ Supervisor (Smart Edition): Running audit and recovery checks...")
        
        async with aiosqlite.connect(DB_FILE) as conn:
            conn.row_factory = aiosqlite.Row
            
            stuck_threshold = (datetime.now(EGYPT_TZ) - timedelta(minutes=2)).isoformat()
            stuck_pending = await (await conn.execute("SELECT * FROM trades WHERE status = 'pending' AND timestamp < ?", (stuck_threshold,))).fetchall()

            if stuck_pending:
                logger.warning(f"🕵️ Supervisor: Found {len(stuck_pending)} STUCK pending trades. Verifying status...")
                for trade_data in stuck_pending:
                    trade = dict(trade_data)
                    try:
                        order_status = await self.exchange.fetch_order(trade['order_id'], trade['symbol'])
                        if order_status['status'] == 'closed' and order_status.get('filled', 0) > 0:
                            # The main bot file should have activate_trade
                            if hasattr(bot_data.application.bot, 'activate_trade'):
                                await bot_data.application.bot.activate_trade(trade['order_id'], trade['symbol'])
                        elif order_status['status'] in ['canceled', 'expired']:
                            await conn.execute("DELETE FROM trades WHERE id = ?", (trade['id'],))
                        await asyncio.sleep(1)
                    except ccxt.OrderNotFound:
                        await conn.execute("DELETE FROM trades WHERE id = ?", (trade['id'],))
                    except Exception as e:
                        logger.error(f"🕵️ Supervisor: Error processing stuck pending trade #{trade['id']}: {e}")
            
            incubated_trades = await (await conn.execute("SELECT * FROM trades WHERE status = 'incubated'")).fetchall()
            if incubated_trades:
                logger.warning(f"🕵️ Supervisor: Found {len(incubated_trades)} trades in incubator. Flagging for retry.")
                for trade_data in incubated_trades:
                    await conn.execute("UPDATE trades SET status = 'retry_exit' WHERE id = ?", (trade_data['id'],))
            
            await conn.commit()
        
        logger.info("🕵️ Supervisor: Audit and recovery checks complete.")

    async def review_portfolio_risk(self, context: object = None):
        logger.info("🧠 Wise Man: Starting portfolio risk review...")
        try:
            balance = await self.exchange.fetch_balance()
            
            assets = { asset: data['total'] for asset, data in balance.items() if isinstance(data, dict) and data.get('total', 0) > 0.00001 and asset != 'USDT' }
            if not assets: return

            asset_list = [f"{asset}/USDT" for asset in assets.keys() if asset != 'USDT']
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
            
            if total_portfolio_value < 100.0: return

            sector_values = defaultdict(float)
            
            for asset, value in asset_values.items():
                concentration_pct = (value / total_portfolio_value) * 100
                if concentration_pct > PORTFOLIO_RISK_RULES['max_asset_concentration_pct']:
                    await self.safe_send_message(f"⚠️ **تنبيه الرجل الحكيم (تركيز الأصل):**\n`{asset}` تشكل **{concentration_pct:.1f}%** من المحفظة.")
                
                sector = SECTOR_MAP.get(asset, 'Other')
                sector_values[sector] += value
            
            for sector, value in sector_values.items():
                concentration_pct = (value / total_portfolio_value) * 100
                if concentration_pct > PORTFOLIO_RISK_RULES['max_sector_concentration_pct']:
                     await self.safe_send_message(f"⚠️ **تنبيه الرجل الحكيم (تركيز قطاعي):**\nقطاع **'{sector}'** يشكل **{concentration_pct:.1f}%** من المحفظة.")

        except Exception as e:
            logger.error(f"Wise Man: Error during portfolio risk review: {e}", exc_info=True)
