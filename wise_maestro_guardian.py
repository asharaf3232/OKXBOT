# -*- coding: utf-8 -*-
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

# افتراض أن هذه الملفات موجودة في نفس المجلد
from _settings_config import PORTFOLIO_RISK_RULES, SECTOR_MAP, STRATEGY_NAMES_AR, SCANNERS
from _settings_config import TIMEFRAME
from _strategy_scanners import find_col

logger = logging.getLogger(__name__)

# ملاحظة: سيتم تعيين هذه المتغيرات في الملف الرئيسي لكل منصة
DB_FILE = None 
bot_data = None # سيتم تمرير كائن الحالة العامة للبوت

class TradeGuardian:
    def __init__(self, exchange: ccxt.Exchange, application: Application, bot_state_object: object, db_file: str):
        """
        وحدة الحارس والرقابة المزدوجة (WiseMan + Reviewer).
        """
        global DB_FILE, bot_data
        DB_FILE = db_file
        bot_data = bot_state_object
        self.exchange = exchange
        self.application = application
        self.telegram_chat_id = bot_data.TELEGRAM_CHAT_ID 
        logger.info("🛡️ Wise Maestro Guardian (Shared Logic) initialized.")

    async def safe_send_message(self, text, **kwargs):
        """إرسال آمن للرسائل عبر تيليجرام."""
        if self.telegram_chat_id:
            try:
                await self.application.bot.send_message(self.telegram_chat_id, text, parse_mode='Markdown', **kwargs)
            except Exception as e:
                logger.error(f"Telegram Send Error: {e}")

    # =======================================================================================
    # --- A. منطق الرجل الحكيم (Wise Man - Tactical Review) ---
    # =======================================================================================
    
    async def review_open_trades(self, context: object = None):
        """
        الرجل الحكيم: يراجع الصفقات المفتوحة لاتخاذ قرارات تكتيكية (خروج مبكر/تمديد هدف).
        """
        if not bot_data.settings.get('adaptive_intelligence_enabled', True): return
        logger.info("🧠 Wise Man: Starting periodic review of open trades...")
        
        async with aiosqlite.connect(DB_FILE) as conn:
            conn.row_factory = aiosqlite.Row
            active_trades = await (await conn.execute("SELECT * FROM trades WHERE status = 'active'")).fetchall()
            if not active_trades: return

            try:
                # نحصل على زخم BTC كمرجع عام لضعف السوق
                btc_ohlcv = await self.exchange.fetch_ohlcv('BTC/USDT', '1h', limit=30)
                btc_df = pd.DataFrame(btc_ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                btc_momentum = ta.mom(btc_df['close'], length=10).iloc[-1]
            except Exception as e:
                logger.error(f"Wise Man: Could not fetch BTC data for comparison: {e}")
                btc_momentum = 1 # نعتبره إيجابي إذا فشل الجلب

            for trade_data in active_trades:
                trade = dict(trade_data)
                symbol = trade['symbol']
                
                try:
                    ohlcv = await self.exchange.fetch_ohlcv(symbol, '15m', limit=50)
                    df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                    current_price = df['close'].iloc[-1]
                    
                    # 1. منطق "اقطع خسائرك مبكرًا" (Early Exit / Risk Mitigation)
                    df['ema_fast'] = ta.ema(df['close'], length=10)
                    df['ema_slow'] = ta.ema(df['close'], length=30)
                    # شرط الضعف: السعر تحت كلا المتوسطين
                    is_weak = current_price < df['ema_fast'].iloc[-1] and current_price < df['ema_slow'].iloc[-1]
                    
                    if is_weak and btc_momentum < 0 and current_price < trade['entry_price']:
                        logger.warning(f"Wise Man recommends early exit for {symbol} (Weakness + BTC down).")
                        # تحديث حالة الصفقة للإغلاق الفوري من قبل التيكر هاندلر
                        await self._close_trade(trade, "إغلاق مبكر (Wise Man)", current_price)
                        await self.safe_send_message(f"🧠 **توصية من الرجل الحكيم | #{trade['id']} {symbol}**\nتم رصد ضعف تكتيكي مع هبوط BTC. تم طلب الخروج المبكر لحماية رأس المال.")
                        continue

                    # 2. منطق "دع أرباحك تنمو" (TP Extension)
                    current_profit_pct = (current_price / trade['entry_price'] - 1) * 100
                    df.ta.adx(append=True)
                    current_adx = df[find_col(df.columns, "ADX_14")].iloc[-1]
                    is_strong = current_profit_pct > 3.0 and current_adx > 30

                    if is_strong:
                        new_tp = trade['take_profit'] * 1.05
                        await conn.execute("UPDATE trades SET take_profit = ? WHERE id = ?", (new_tp, trade['id']))
                        await conn.commit() # Commit after each update
                        logger.info(f"Wise Man recommends extending target for {symbol}. New TP: {new_tp:.4f}")
                        await self.safe_send_message(f"🧠 **نصيحة من الرجل الحكيم | #{trade['id']} {symbol}**\nتم رصد زخم قوي. تم تمديد الهدف إلى `${new_tp:.4f}`.")

                except Exception as e:
                    logger.error(f"Wise Man: Failed to analyze trade #{trade['id']} for {symbol}: {e}")
                
                await asyncio.sleep(1)
            
            # The commit outside the loop might be intended, but committing inside ensures changes are saved per trade
            # await conn.commit()

    # =======================================================================================
    # --- B. منطق المراجع الذكي (Intelligent Reviewer - Signal Validity Check) ---
    # =======================================================================================

    async def intelligent_reviewer_job(self, context: object = None):
        """
        المراجع الذكي: يعيد تشغيل تحليل الإشارة الأصلية لضمان أن الصفقة لم تفقد مبررها الفني.
        """
        if not bot_data.settings.get('intelligent_reviewer_enabled', True): return
        logger.info("🧠 Intelligent Reviewer: Reviewing active trades for signal validity...")
        
        async with aiosqlite.connect(DB_FILE) as conn:
            conn.row_factory = aiosqlite.Row
            active_trades = await (await conn.execute("SELECT * FROM trades WHERE status = 'active'")).fetchall()
        
        for trade in active_trades:
            trade_dict = dict(trade)
            symbol = trade_dict['symbol']
            
            # نحصل على الإشارة الأصلية (قد تكون مركبة) ونأخذ العنصر الأول
            reasons_list = trade_dict['reason'].split(' (')[0].split(' + ') 
            primary_reason = reasons_list[0].strip()

            if primary_reason not in SCANNERS: continue # إشارة غير قياسية

            try:
                # جلب بيانات الشموع اللازمة لإعادة التحليل
                ohlcv = await self.exchange.fetch_ohlcv(symbol, TIMEFRAME, limit=220)
                df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
                df = df.set_index('timestamp').sort_index()

                # نحتاج إلى قيم rvol و adx_value لبعض الماسحات
                df.ta.adx(append=True); adx_value = df[find_col(df.columns, "ADX_")].iloc[-2]
                df['volume_sma'] = ta.sma(df['volume'], length=20); rvol = df['volume'].iloc[-2] / df['volume_sma'].iloc[-2]

                # إعادة تشغيل المحلل الأصلي
                analyzer_func = SCANNERS[primary_reason]
                params = bot_data.settings.get(primary_reason, {})
                
                func_args = {'df': df.copy(), 'params': params, 'rvol': rvol, 'adx_value': adx_value}
                if primary_reason in ['support_rebound']:
                    func_args.update({'exchange': self.exchange, 'symbol': symbol})
                
                # تنفيذ الدالة (سواء كانت async أو sync)
                result = await analyzer_func(**func_args) if asyncio.iscoroutinefunction(analyzer_func) else analyzer_func(**{k: v for k, v in func_args.items() if k not in ['exchange', 'symbol']})

                if not result:
                    # الإشارة بطلت، يتم الإغلاق
                    current_price = df['close'].iloc[-1]
                    await self._close_trade(trade_dict, f"إغلاق (المراجع الذكي: {STRATEGY_NAMES_AR.get(primary_reason, primary_reason)})", current_price)
                    logger.info(f"🧠 Intelligent Reviewer: Closed trade #{trade_dict['id']} - Signal invalidated.")
            except Exception as e:
                logger.error(f"Intelligent Reviewer failed for {symbol}: {e}", exc_info=True)
        
        logger.info("🧠 Intelligent Reviewer: Review cycle complete.")


    # =======================================================================================
    # --- C. منطق إدارة الصفقة في الوقت الحقيقي (Ticker Handler) ---
    # =======================================================================================
    
    async def handle_ticker_update(self, standard_ticker: dict):
        """
        [العقل الموحد] يتم استدعاؤها مع كل تحديث للسعر بتنسيق موحد.
        تنسيق موحد متوقع: {'symbol': 'BTC/USDT', 'price': 60000.0}
        """
        # ملاحظة: تم تعديل trade_management_lock ليتم جلبه من كائن الحالة المشترك bot_data
        async with bot_data.trade_management_lock:
            symbol = standard_ticker['symbol']
            current_price = standard_ticker['price']
            
            try:
                async with aiosqlite.connect(DB_FILE) as conn:
                    conn.row_factory = aiosqlite.Row
                    trade = await (await conn.execute("SELECT * FROM trades WHERE symbol = ? AND status = 'active'", (symbol,))).fetchone()
                    
                    if not trade: return
                    trade = dict(trade); settings = bot_data.settings

                    # 1. الأولوية: وقف الخسارة (Hard SL)
                    if current_price <= trade['stop_loss']:
                        reason = "فاشلة (SL)"
                        if trade.get('trailing_sl_active', False):
                            reason = "تم تأمين الربح (TSL)" if current_price > trade['entry_price'] else "فاشلة (TSL)"
                        await self._close_trade(trade, reason, current_price)
                        return

                    # 2. الأولوية: وضع اقتناص الزخم (Momentum Scalp Mode)
                    if settings.get('momentum_scalp_mode_enabled', False):
                        scalp_target = trade['entry_price'] * (1 + settings['momentum_scalp_target_percent'] / 100)
                        if current_price >= scalp_target and current_price > trade['entry_price']:
                            await self._close_trade(trade, "ناجحة (Scalp Mode)", current_price)
                            return

                    # 3. الأولوية: الهدف (TP)
                    if current_price >= trade['take_profit']: 
                        await self._close_trade(trade, "ناجحة (TP)", current_price)
                        return

                    # 4. منطق الوقف المتحرك (TSL)
                    if settings['trailing_sl_enabled']:
                        new_highest_price = max(trade.get('highest_price', 0), current_price)
                        if new_highest_price > trade.get('highest_price', 0):
                            await conn.execute("UPDATE trades SET highest_price = ? WHERE id = ?", (new_highest_price, trade['id']))
                        
                        # تفعيل TSL
                        if not trade.get('trailing_sl_active', False) and current_price >= trade['entry_price'] * (1 + settings['trailing_sl_activation_percent'] / 100):
                            new_sl = trade['entry_price'] * 1.001 # رفع الـ SL إلى نقطة الدخول تقريباً
                            if new_sl > trade['stop_loss']:
                                await conn.execute("UPDATE trades SET trailing_sl_active = 1, stop_loss = ? WHERE id = ?", (new_sl, trade['id']))
                                await self.safe_send_message(f"🚀 **تأمين الأرباح! | #{trade['id']} {symbol}**\nتم رفع وقف الخسارة إلى نقطة الدخول: `${new_sl:.4f}`")
                                trade['trailing_sl_active'] = True # تحديث محلي

                        # رفع TSL
                        if trade.get('trailing_sl_active', False): 
                            current_stop_loss = trade.get('stop_loss', 0)
                            new_sl_candidate = new_highest_price * (1 - settings['trailing_sl_callback_percent'] / 100)
                            if new_sl_candidate > current_stop_loss:
                                await conn.execute("UPDATE trades SET stop_loss = ? WHERE id = ?", (new_sl_candidate, trade['id']))

                    # 5. منطق إشعارات الربح المتزايدة
                    if settings.get('incremental_notifications_enabled', True):
                        last_notified = trade.get('last_profit_notification_price', trade['entry_price'])
                        increment = settings['incremental_notification_percent'] / 100
                        if current_price >= last_notified * (1 + increment):
                            profit_percent = ((current_price / trade['entry_price']) - 1) * 100
                            await self.safe_send_message(f"📈 **ربح متزايد! | #{trade['id']} {symbol}**\n**الربح الحالي:** `{profit_percent:+.2f}%`")
                            await conn.execute("UPDATE trades SET last_profit_notification_price = ? WHERE id = ?", (current_price, trade['id']))

                    await conn.commit()

            except Exception as e: 
                logger.error(f"Guardian Ticker Error for {symbol}: {e}", exc_info=True)
                
    # =======================================================================================
    # --- D. الإغلاق المصّلب (Hardened Closure - The Blackbox Logic) ---
    # =======================================================================================
    
    async def _close_trade(self, trade: dict, reason: str, close_price: float):
        """
        ينفذ الإغلاق القسري المصّلب (Blackbox) للحد من مشكلات الرصيد العالق.
        """
        symbol, trade_id, quantity_in_db = trade['symbol'], trade['id'], trade['quantity']
        max_retries = bot_data.settings.get('close_retries', 3)
        base_currency = symbol.split('/')[0]

        logger.info(f"Guard: Initiating Hardened Closure for #{trade_id} [{symbol}]. Reason: {reason}")
        
        # 1. محاولة الإغلاق والتأمين
        for i in range(max_retries):
            try:
                # 1.1 خطوة الإلغاء
                await self.exchange.cancel_all_orders(symbol)
                logger.info(f"[{symbol}] All open orders cancelled.")
                
                # 1.2 فحص الرصيد والتأكد من تحرير الكمية (Blackbox check)
                is_balance_free = False
                quantity_to_sell = float(self.exchange.amount_to_precision(symbol, quantity_in_db))
                
                for attempt in range(5): # محاولات انتظار للرصيد
                    await asyncio.sleep(1) 
                    balance = await self.exchange.fetch_balance()
                    available_quantity = balance.get(base_currency, {}).get('free', 0.0)
                    
                    if available_quantity >= quantity_to_sell * 0.98: # مع هامش بسيط
                        is_balance_free = True
                        break
                
                if not is_balance_free:
                    raise Exception("Balance not freed after cancellation and waiting.")
                    
                # 1.3 خطوة التنفيذ
                params = {'tdMode': 'cash'} if self.exchange.id == 'okx' else {}
                await self.exchange.create_market_sell_order(symbol, quantity_to_sell, params=params)
                
                # 1.4 حساب الـ PNL وتحديث DB
                pnl = (close_price - trade['entry_price']) * quantity_to_sell
                pnl_percent = (close_price / trade['entry_price'] - 1) * 100 if trade['entry_price'] > 0 else 0
                emoji = "✅" if pnl >= 0 else "🛑"
                
                async with aiosqlite.connect(DB_FILE) as conn:
                    await conn.execute("UPDATE trades SET status = ?, close_price = ?, pnl_usdt = ? WHERE id = ?", (reason, close_price, pnl, trade_id))
                    await conn.commit()
                
                await self.safe_send_message(f"{emoji} **تم إغلاق الصفقة | #{trade_id} {symbol}**\n**السبب:** {reason}\n**الربح/الخسارة:** `${pnl:,.2f}` ({pnl_percent:+.2f}%)")
                
                if hasattr(bot_data, 'websocket_manager') and hasattr(bot_data.websocket_manager, 'sync_subscriptions'):
                    await bot_data.websocket_manager.sync_subscriptions()
                
                if hasattr(bot_data, 'smart_brain') and hasattr(bot_data.smart_brain, 'add_trade_to_journal'):
                    async with aiosqlite.connect(DB_FILE) as conn:
                         conn.row_factory = aiosqlite.Row
                         final_trade_details = await (await conn.execute("SELECT * FROM trades WHERE id = ?", (trade_id,))).fetchone()
                         if final_trade_details:
                             await bot_data.smart_brain.add_trade_to_journal(dict(final_trade_details))
                
                return # تم الإغلاق بنجاح
            
            except Exception as e:
                logger.warning(f"Failed to close trade #{trade_id}. Retrying... ({i + 1}/{max_retries}): {e}")
                await asyncio.sleep(5)
                
        # 2. فشل الإغلاق (النقل إلى الحضانة)
        logger.critical(f"CRITICAL: Hardened closure for #{trade_id} failed after {max_retries} retries. MOVING TO INCUBATOR.")
        async with aiosqlite.connect(DB_FILE) as conn:
            await conn.execute("UPDATE trades SET status = 'incubated' WHERE id = ?", (trade_id,))
            await conn.commit()
        await self.safe_send_message(f"⚠️ **فشل الإغلاق الحرج | #{trade_id} {symbol}**\nفشل الإغلاق بعد عدة محاولات. تم نقل الصفقة إلى *الحضانة* للمراقبة. الرجاء مراجعة رصيدك يدوياً.")
        if hasattr(bot_data, 'websocket_manager') and hasattr(bot_data.websocket_manager, 'sync_subscriptions'):
            await bot_data.websocket_manager.sync_subscriptions()

    # =======================================================================================
    # --- E. منطق المشرف (Supervisor - Recovery & Monitoring) ---
    # =======================================================================================

    async def the_supervisor_job(self, context: object = None):
        """
        المشرف: يعالج الصفقات العالقة ويدير الحضانة ويحاول التعافي.
        """
        logger.info("🕵️ Supervisor: Running audit and recovery checks...")
        
        async with aiosqlite.connect(DB_FILE) as conn:
            conn.row_factory = aiosqlite.Row
            
            # 1. إدارة الصفقات في 'الحضانة' (Incubated Trades)
            incubated_trades = await (await conn.execute("SELECT * FROM trades WHERE status = 'incubated'")).fetchall()

            for trade_data in incubated_trades:
                trade = dict(trade_data)
                try:
                    ticker = await self.exchange.fetch_ticker(trade['symbol'])
                    current_price = ticker.get('last')
                    if not current_price: continue

                    # الشرط الأول: هل تعافت الصفقة؟
                    if current_price > trade['stop_loss']:
                        await conn.execute("UPDATE trades SET status = 'active' WHERE id = ?", (trade['id'],))
                        await conn.commit()
                        await self.safe_send_message(f"✅ **تعافي الصفقة | #{trade['id']} {trade['symbol']}**\nعادت للمراقبة النشطة بسعر حالي: `${current_price:.4f}`")
                        
                    # الشرط الثاني: ما زالت في منطقة الخطر - حاول الإغلاق مجدداً
                    else:
                        logger.info(f"Supervisor: Trade #{trade['id']} still in danger. Retrying Hardened Closure.")
                        await self._close_trade(trade, f"فاشلة (SL-Supervisor)", current_price)
                
                except Exception as e:
                    logger.error(f"🕵️ Supervisor: Error processing incubated trade #{trade['id']}: {e}")
                
                await asyncio.sleep(5)
    
        logger.info("🕵️ Supervisor: Audit and recovery checks complete.")

    # =======================================================================================
    # --- F. مراجعة مخاطر المحفظة (Portfolio Risk Review) ---
    # =======================================================================================
    
    async def review_portfolio_risk(self, context: object = None):
        """
        الرجل الحكيم: يفحص المحفظة ككل ويعطي تنبيهات حول التركيز القطاعي أو الأصول الفردية.
        """
        logger.info("🧠 Wise Man: Starting portfolio risk review...")
        try:
            balance = await self.exchange.fetch_balance()
            
            assets = {
                asset: data['total'] 
                for asset, data in balance.items() 
                if isinstance(data, dict) and data.get('total', 0) > 0.00001 and asset != 'USDT'
            }
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
                    if value_usdt > 1.0: # فقط للأصول ذات القيمة
                        asset_values[asset] = value_usdt
                        total_portfolio_value += value_usdt
            
            if total_portfolio_value < 100.0: return # نتجاهل المحافظ الصغيرة جداً

            sector_values = defaultdict(float)
            
            # تحليل تركيز الأصول الفردية والقطاعات
            for asset, value in asset_values.items():
                # 1. تركيز الأصل الفردي
                concentration_pct = (value / total_portfolio_value) * 100
                if concentration_pct > PORTFOLIO_RISK_RULES['max_asset_concentration_pct']:
                    await self.safe_send_message(f"⚠️ **تنبيه الرجل الحكيم (تركيز الأصل):**\n"
                                               f"عملة `{asset}` تشكل **{concentration_pct:.1f}%** من المحفظة (> {PORTFOLIO_RISK_RULES['max_asset_concentration_pct']}%).\n"
                                               f"الرجاء مراجعة المحفظة.")
                
                # 2. تركيز القطاع
                sector = SECTOR_MAP.get(asset, 'Other')
                sector_values[sector] += value
            
            for sector, value in sector_values.items():
                concentration_pct = (value / total_portfolio_value) * 100
                if concentration_pct > PORTFOLIO_RISK_RULES['max_sector_concentration_pct']:
                     await self.safe_send_message(f"⚠️ **تنبيه الرجل الحكيم (تركيز قطاعي):**\n"
                                                f"أصول قطاع **'{sector}'** تشكل **{concentration_pct:.1f}%** من المحفظة (> {PORTFOLIO_RISK_RULES['max_sector_concentration_pct']}%).\n"
                                                f"الرجاء تنويع الأصول.")

        except Exception as e:
            logger.error(f"Wise Man: Error during portfolio risk review: {e}", exc_info=True)
