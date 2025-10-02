# -*- coding: utf-8 -*-
# =======================================================================================
# --- 🛡️ Wise Maestro Guardian - v4.2 (Supervisor Logic Complete & Final) 🛡️ ---
# =======================================================================================
import logging
import asyncio
import aiosqlite
import pandas as pd
import pandas_ta as ta
import ccxt.async_support as ccxt
from telegram.ext import Application
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import json
import random
import hmac
import base64
import time
import websockets
import websockets.exceptions

from settings_config import STRATEGY_NAMES_AR, TIMEFRAME
from strategy_scanners import find_col

logger = logging.getLogger(__name__)

DB_FILE = None
bot_data_ref = None 
EGYPT_TZ = ZoneInfo("Africa/Cairo")

# =======================================================================================
# --- WebSocket Managers ---
# =======================================================================================
async def exponential_backoff_with_jitter(run_coro, *args, **kwargs):
    retries = 0; base_delay, max_delay = 2, 120
    while True:
        try: await run_coro(*args, **kwargs)
        except Exception as e:
            retries += 1; backoff_delay = min(max_delay, base_delay * (2 ** retries)); jitter = random.uniform(0, backoff_delay * 0.5); total_delay = backoff_delay + jitter
            logger.error(f"Coroutine {run_coro.__name__} failed: {e}. Retrying in {total_delay:.2f} seconds...")
            await asyncio.sleep(total_delay)

class PublicWebSocketManager:
    def __init__(self, handler_coro):
        self.ws_url = "wss://ws.okx.com:8443/ws/v5/public"
        self.handler = handler_coro
        self.subscriptions = set()
        self.websocket = None

    async def _send_op(self, op, symbols):
        if not symbols or not self.websocket or not self.websocket.open: return
        try:
            payload = json.dumps({"op": op, "args": [{"channel": "tickers", "instId": s.replace('/', '-')} for s in symbols]})
            await self.websocket.send(payload)
        except websockets.exceptions.ConnectionClosed: logger.warning(f"Could not send '{op}' op; ws is closed.")

    async def subscribe(self, symbols):
        new = [s for s in symbols if s not in self.subscriptions]
        if new: await self._send_op('subscribe', new); self.subscriptions.update(new); logger.info(f"👁️ [Guardian] Now watching: {new}")

    async def unsubscribe(self, symbols):
        old = [s for s in symbols if s in self.subscriptions]
        if old: await self._send_op('unsubscribe', old); [self.subscriptions.discard(s) for s in old]; logger.info(f"👁️ [Guardian] Stopped watching: {old}")

    async def _run_loop(self):
        async with websockets.connect(self.ws_url, ping_interval=20, ping_timeout=20) as ws:
            self.websocket = ws; logger.info("✅ [Guardian's Eyes] Public WebSocket Connected.")
            if self.subscriptions: await self.subscribe(list(self.subscriptions))
            async for msg in ws:
                if msg == 'ping': await ws.send('pong'); continue
                data = json.loads(msg)
                if data.get('arg', {}).get('channel') == 'tickers' and 'data' in data:
                    for ticker in data['data']:
                        standard_ticker = {'symbol': ticker['instId'].replace('-', '/'), 'price': float(ticker['last'])}
                        await self.handler(standard_ticker)
    async def run(self): await exponential_backoff_with_jitter(self._run_loop)

class PrivateWebSocketManager:
    def __init__(self, api_key, api_secret, passphrase):
        self.ws_url = "wss://ws.okx.com:8443/ws/v5/private"
        self.api_key = api_key; self.api_secret = api_secret; self.passphrase = passphrase; self.websocket = None

    def _get_auth_args(self):
        timestamp = str(time.time()); message = timestamp + 'GET' + '/users/self/verify'
        mac = hmac.new(bytes(self.api_secret, 'utf8'), bytes(message, 'utf8'), 'sha256')
        sign = base64.b64encode(mac.digest()).decode()
        return [{"apiKey": self.api_key, "passphrase": self.passphrase, "timestamp": timestamp, "sign": sign}]

    async def _message_handler(self, msg):
        if msg == 'ping': await self.websocket.send('pong'); return
        data = json.loads(msg)
        if data.get('arg', {}).get('channel') == 'orders' and 'data' in data:
             for order in data.get('data', []):
                if order.get('state') == 'filled' and order.get('side') == 'buy':
                    logger.info(f"Private WS: Detected filled buy order {order['ordId']}")
                    if hasattr(bot_data_ref.guardian, 'activate_trade'):
                        await bot_data_ref.guardian.activate_trade(order['ordId'], order['instId'].replace('-', '/'))

    async def _run_loop(self):
        async with websockets.connect(self.ws_url, ping_interval=20, ping_timeout=20) as ws:
            self.websocket = ws; logger.info("✅ [Private WS] Connected.")
            await ws.send(json.dumps({"op": "login", "args": self._get_auth_args()}))
            login_response = json.loads(await ws.recv())
            if login_response.get('code') == '0':
                logger.info("🔐 [Private WS] Authenticated.")
                await ws.send(json.dumps({"op": "subscribe", "args": [{"channel": "orders", "instType": "SPOT"}]}))
                async for msg in ws: await self._message_handler(msg)
            else: raise ConnectionAbortedError(f"Private WS Authentication failed: {login_response}")
    async def run(self): await exponential_backoff_with_jitter(self._run_loop)

# =======================================================================================
# --- TradeGuardian Class ---
# =======================================================================================
class TradeGuardian:
    def __init__(self, exchange_obj: ccxt.Exchange, application_obj: Application, bot_state: object, db_path: str):
        global DB_FILE, bot_data_ref
        DB_FILE = db_path; bot_data_ref = bot_state
        self.exchange = exchange_obj; self.application = application_obj; self.telegram_chat_id = bot_state.TELEGRAM_CHAT_ID
        logger.info("🛡️ Wise Maestro Guardian Initialized (Complete).")

    async def safe_send_message(self, text, **kwargs):
        if self.telegram_chat_id:
            try: await self.application.bot.send_message(self.telegram_chat_id, text, parse_mode='Markdown', **kwargs)
            except Exception as e: logger.error(f"Telegram Send Error: {e}")

    async def log_pending_trade_to_db(self, signal, buy_order):
        try:
            async with aiosqlite.connect(DB_FILE) as conn:
                await conn.execute("INSERT INTO trades (timestamp, symbol, reason, order_id, status, entry_price, take_profit, stop_loss) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                                   (datetime.now(EGYPT_TZ).isoformat(), signal['symbol'], signal['reason'], buy_order['id'], 'pending', signal['entry_price'], signal['take_profit'], signal['stop_loss']))
                await conn.commit()
                return True
        except Exception as e: logger.error(f"DB Log Pending Error: {e}"); return False

    async def activate_trade(self, order_id, symbol):
        try:
            order_details = await self.exchange.fetch_order(order_id, symbol)
            filled_price, net_filled_quantity = order_details.get('average', 0.0), order_details.get('filled', 0.0)
            if net_filled_quantity <= 0 or filled_price <= 0: return
        except Exception as e: logger.error(f"Could not fetch data for trade activation: {e}"); return

        async with aiosqlite.connect(DB_FILE) as conn:
            conn.row_factory = aiosqlite.Row
            trade = await (await conn.execute("SELECT * FROM trades WHERE order_id = ? AND status = 'pending'", (order_id,))).fetchone()
            if not trade: return
            
            trade = dict(trade)
            risk = filled_price - trade['stop_loss']
            new_take_profit = filled_price + (risk * bot_data_ref.settings['risk_reward_ratio'])
            
            await conn.execute("UPDATE trades SET status = 'active', entry_price = ?, quantity = ?, take_profit = ? WHERE id = ?", (filled_price, net_filled_quantity, new_take_profit, trade['id']))
            await conn.commit()

        if hasattr(bot_data_ref, 'public_ws'):
            await bot_data_ref.public_ws.subscribe([symbol])

        reasons_ar = ' + '.join([STRATEGY_NAMES_AR.get(r.strip(), r.strip()) for r in trade['reason'].split(' + ')])
        success_msg = (f"✅ **تم تأكيد الشراء | {symbol}**\n"
                       f"**الاستراتيجية:** {reasons_ar}\n"
                       f"**سعر التنفيذ:** `${filled_price:,.4f}`\n"
                       f"**الهدف (TP):** `${new_take_profit:,.4f}`\n"
                       f"**الوقف (SL):** `${trade['stop_loss']:,.4f}`")
        await self.safe_send_message(success_msg)

    async def sync_subscriptions(self):
        try:
            async with aiosqlite.connect(DB_FILE) as conn:
                cursor = await conn.execute("SELECT DISTINCT symbol FROM trades WHERE status = 'active'")
                active_symbols = [row[0] for row in await cursor.fetchall()]
            if active_symbols:
                logger.info(f"Guardian Sync: Subscribing to {len(active_symbols)} active trades.")
                if hasattr(bot_data_ref, 'public_ws'):
                    await bot_data_ref.public_ws.subscribe(active_symbols)
        except Exception as e: logger.error(f"Guardian Sync Error: {e}")

    def _format_duration(self, duration_delta: timedelta) -> str:
        seconds = duration_delta.total_seconds()
        if seconds < 60: return "أقل من دقيقة"
        days, remainder = divmod(seconds, 86400); hours, remainder = divmod(remainder, 3600); minutes, _ = divmod(remainder, 60)
        parts = []
        if days > 0: parts.append(f"{int(days)} يوم")
        if hours > 0: parts.append(f"{int(hours)} ساعة")
        if minutes > 0: parts.append(f"{int(minutes)} دقيقة")
        return " و ".join(parts)

    async def _close_trade(self, trade: dict, reason: str, close_price: float):
        symbol, trade_id = trade['symbol'], trade['id']
        try:
            async with aiosqlite.connect(DB_FILE) as conn:
                cursor = await conn.execute("UPDATE trades SET status = 'closing' WHERE id = ? AND status IN ('active', 'retry_exit', 'force_exit')", (trade_id,))
                await conn.commit()
                if cursor.rowcount == 0: return
        except Exception as e: logger.error(f"CRITICAL DB ACTION FAILED for trade #{trade_id}: {e}"); return
        
        logger.info(f"🛡️ Initiating closure for trade #{trade_id} [{symbol}]. Reason: {reason}")
        try:
            base_currency = symbol.split('/')[0]
            balance = await self.exchange.fetch_balance()
            available_quantity = balance.get(base_currency, {}).get('free', 0.0)
            
            if available_quantity <= 0.00000001:
                pnl = (close_price - trade['entry_price']) * trade['quantity']
                async with aiosqlite.connect(DB_FILE) as conn:
                    await conn.execute("UPDATE trades SET status = ?, close_price = ?, pnl_usdt = ? WHERE id = ?", (f"{reason} (No Balance)", close_price, pnl, trade_id))
                    await conn.commit()
                if hasattr(bot_data_ref, 'public_ws'): await bot_data_ref.public_ws.unsubscribe([symbol])
                return

            quantity_to_sell = float(self.exchange.amount_to_precision(symbol, available_quantity))
            params = {'tdMode': 'cash'}
            await self.exchange.create_market_sell_order(symbol, quantity_to_sell, params=params)
            
            pnl = (close_price - trade['entry_price']) * trade['quantity']
            pnl_percent = (close_price / trade['entry_price'] - 1) * 100 if trade['entry_price'] > 0 else 0
            
            async with aiosqlite.connect(DB_FILE) as conn:
                await conn.execute("UPDATE trades SET status = ?, close_price = ?, pnl_usdt = ? WHERE id = ?", (reason, close_price, pnl, trade_id))
                await conn.commit()

            trade_duration = self._format_duration(datetime.now(EGYPT_TZ) - datetime.fromisoformat(trade['timestamp']))
            title = "✅ مهمة مكتملة" if pnl >= 0 else "🛑 مهمة مغلقة"
            profit_emoji = "💰" if pnl >= 0 else "💸"
            reasons_ar = ' + '.join([STRATEGY_NAMES_AR.get(r.strip().split(' (')[0], r.strip().split(' (')[0]) for r in trade['reason'].split(' + ')])
            
            final_message = (f"**{title}**\n\n"
                           f"▫️ *العملة:* `{symbol}` | *السبب:* `{reason}`\n"
                           f"▫️ *الاستراتيجية:* `{reasons_ar}`\n"
                           f"━━━━━━━━━━━━━━━━━━\n"
                           f"{profit_emoji} *الربح/الخسارة:* `${pnl:,.2f}` **({pnl_percent:,.2f}%)**\n"
                           f"━━━━━━━━━━━━━━━━━━\n"
                           f"⏳ *مدة الصفقة:* {trade_duration}\n")
            await self.safe_send_message(final_message)
            
            if hasattr(bot_data_ref, 'smart_brain'):
                final_trade_details = dict(trade); final_trade_details.update({'status': reason, 'close_price': close_price, 'pnl_usdt': pnl})
                await bot_data_ref.smart_brain.add_trade_to_journal(final_trade_details)

        except (ccxt.InvalidOrder, ccxt.InsufficientFunds) as e:
             logger.warning(f"Closure for #{trade_id} failed, will retry: {e}")
             async with aiosqlite.connect(DB_FILE) as conn: await conn.execute("UPDATE trades SET status = 'retry_exit' WHERE id = ?", (trade_id,)); await conn.commit()
        except Exception as e:
            logger.critical(f"CRITICAL: Closure for #{trade_id} failed. MOVING TO RETRY: {e}", exc_info=True)
            async with aiosqlite.connect(DB_FILE) as conn: await conn.execute("UPDATE trades SET status = 'retry_exit' WHERE id = ?", (trade_id,)); await conn.commit()
        finally:
            if hasattr(bot_data_ref, 'public_ws'): await bot_data_ref.public_ws.unsubscribe([symbol])

    async def handle_ticker_update(self, standard_ticker: dict):
        async with bot_data_ref.trade_management_lock:
            symbol, current_price = standard_ticker['symbol'], standard_ticker['price']
            try:
                async with aiosqlite.connect(DB_FILE) as conn:
                    conn.row_factory = aiosqlite.Row
                    trade = await (await conn.execute("SELECT * FROM trades WHERE symbol = ? AND status IN ('active', 'retry_exit')", (symbol,))).fetchone()
                    if not trade: return
                    
                    trade = dict(trade)
                    settings = bot_data_ref.settings
                    
                    if trade['status'] == 'retry_exit':
                        await self._close_trade(trade, "إغلاق (إعادة محاولة)", current_price)
                        return
                    
                    should_close, close_reason = False, ""
                    if current_price <= trade['stop_loss']:
                        should_close = True
                        reason = "فاشلة (SL)"
                        if trade.get('trailing_sl_active'):
                            reason = "ربح مؤمن (TSL)" if current_price > trade['entry_price'] else "فاشلة (TSL)"
                        close_reason = reason
                    elif current_price >= trade['take_profit']: 
                        should_close, close_reason = True, "ناجحة (TP)"

                    if should_close:
                        await self._close_trade(trade, close_reason, current_price)
                        return

                    highest_price = max(trade.get('highest_price', 0), current_price)
                    if highest_price > trade.get('highest_price', 0):
                        await conn.execute("UPDATE trades SET highest_price = ? WHERE id = ?", (highest_price, trade['id']))
                    
                    if settings.get('trailing_sl_enabled'):
                        if not trade.get('trailing_sl_active') and current_price >= trade['entry_price'] * (1 + settings['trailing_sl_activation_percent'] / 100):
                            new_sl = trade['entry_price'] * 1.001
                            if new_sl > trade['stop_loss']:
                                await conn.execute("UPDATE trades SET trailing_sl_active = 1, stop_loss = ? WHERE id = ?", (new_sl, trade['id']))
                                await self.safe_send_message(f"🚀 **تأمين | #{trade['id']} {symbol}**\nتم رفع الوقف إلى: `${new_sl:.4f}`")
                        
                        if trade.get('trailing_sl_active'):
                            new_sl_candidate = highest_price * (1 - settings['trailing_sl_callback_percent'] / 100)
                            if new_sl_candidate > trade['stop_loss']:
                                await conn.execute("UPDATE trades SET stop_loss = ? WHERE id = ?", (new_sl_candidate, trade['id']))

                    if settings.get('incremental_notifications_enabled'):
                        last_notified = trade.get('last_profit_notification_price', trade['entry_price'])
                        increment = settings.get('incremental_notification_percent', 2.0) / 100
                        if current_price >= last_notified * (1 + increment):
                            profit_percent = ((current_price / trade['entry_price']) - 1) * 100
                            await self.safe_send_message(f"📈 **ربح | #{trade['id']} {symbol}**: `{profit_percent:+.2f}%`")
                            await conn.execute("UPDATE trades SET last_profit_notification_price = ? WHERE id = ?", (current_price, trade['id']))
                            
                    await conn.commit()
            except Exception as e:
                logger.error(f"Guardian Ticker Error for {symbol}: {e}", exc_info=True)

    # --- [الكود الكامل والصحيح لوظيفة المشرف] ---
    async def the_supervisor_job(self, context: object = None):
        logger.info("🕵️ Supervisor: Running audit and recovery checks...")
        async with aiosqlite.connect(DB_FILE) as conn:
            conn.row_factory = aiosqlite.Row
            
            # 1. التحقق من الصفقات العالقة في حالة "pending"
            stuck_threshold = (datetime.now(EGYPT_TZ) - timedelta(minutes=2)).isoformat()
            stuck_pending = await (await conn.execute("SELECT * FROM trades WHERE status = 'pending' AND timestamp < ?", (stuck_threshold,))).fetchall()
            
            for trade_data in stuck_pending:
                trade = dict(trade_data)
                logger.warning(f"Supervisor: Found stuck pending trade #{trade['id']}. Investigating...")
                try:
                    order_status = await self.exchange.fetch_order(trade['order_id'], trade['symbol'])
                    if order_status['status'] == 'closed' and order_status.get('filled', 0) > 0:
                        logger.info(f"Supervisor: API confirms order {trade['order_id']} was filled. Activating.")
                        await self.activate_trade(trade['order_id'], trade['symbol'])
                    elif order_status['status'] in ['canceled', 'expired']:
                        logger.warning(f"Supervisor: Order {trade['order_id']} was canceled/expired. Deleting trade record.")
                        await conn.execute("DELETE FROM trades WHERE id = ?", (trade['id'],))
                except ccxt.OrderNotFound:
                    logger.warning(f"Supervisor: Order {trade['order_id']} not found on exchange. Deleting trade record.")
                    await conn.execute("DELETE FROM trades WHERE id = ?", (trade['id'],))
                except Exception as e:
                    logger.error(f"Supervisor: Error processing stuck pending trade #{trade['id']}: {e}")
            
            # 2. التحقق من الصفقات التي تحتاج إلى إعادة محاولة الإغلاق
            retry_trades = await (await conn.execute("SELECT * FROM trades WHERE status = 'retry_exit'")).fetchall()
            if retry_trades:
                logger.info(f"Supervisor: Found {len(retry_trades)} trades to retry closing. Re-subscribing to their tickers.")
                symbols_to_resubscribe = [trade['symbol'] for trade in retry_trades]
                if hasattr(bot_data_ref, 'public_ws'):
                    await bot_data_ref.public_ws.subscribe(symbols_to_resubscribe)

            await conn.commit()
        logger.info("🕵️ Supervisor: Audit and recovery checks complete.")
