# -*- coding: utf-8 -*-
# =======================================================================================
# --- 🎨 ملف واجهة المستخدم v8.0 (الإصلاح الشامل والنهائي) 🎨 ---
# =======================================================================================
# - قائمة إعدادات كاملة 100% (بما في ذلك الرجل الحكيم).
# - دالة حفظ ذكية للتعامل مع كل المتغيرات.
# - ترتيب صحيح لكل الدوال.

import os
import aiosqlite
import asyncio
import copy
from datetime import datetime
from collections import Counter
from zoneinfo import ZoneInfo

from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CommandHandler, MessageHandler, CallbackQueryHandler, filters
from telegram.constants import ParseMode
from telegram.error import BadRequest

# --- استيراد الوحدات المخصصة ---
from settings_config import STRATEGY_NAMES_AR, SETTINGS_PRESETS, DEFAULT_SETTINGS
from strategy_scanners import SCANNERS
from ai_market_brain import get_fear_and_greed_index, get_latest_crypto_news, get_market_mood, get_okx_markets, analyze_sentiment_of_headlines

# --- ثوابت ---
DB_FILE = 'wise_maestro_okx.db'
SETTINGS_FILE = 'wise_maestro_okx_settings.json'
EGYPT_TZ = ZoneInfo("Africa/Cairo")
try:
    import nltk
    NLTK_AVAILABLE = True
except ImportError:
    NLTK_AVAILABLE = False

# --- دوال مساعدة ---
async def safe_edit_message(query, text, **kwargs):
    try:
        await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, **kwargs)
    except BadRequest as e:
        if "Message is not modified" not in str(e): print(f"Edit Message Error: {e}")
    except Exception as e:
        print(f"Generic Edit Message Error: {e}")

def get_nested_value(d, keys, default="N/A"):
    # This improved helper can handle nested keys from callback data
    for key in keys:
        if isinstance(d, dict):
            d = d.get(key)
        else:
            return default
    return d if d is not None else default

def determine_active_preset_name(settings):
    # This is a simplified comparison logic
    for name, preset_settings in SETTINGS_PRESETS.items():
        # Compare only non-dict values for simplicity
        is_match = all(settings.get(k) == v for k, v in preset_settings.items() if not isinstance(v, dict))
        if is_match:
            # Lazy import to avoid circular dependency issues if PRESET_NAMES_AR is in the same file
            from settings_config import PRESET_NAMES_AR
            return PRESET_NAMES_AR.get(name, name.capitalize())
    return "مخصص"

# =======================================================================================
# --- كل دوال الواجهة (معرّفة أولاً لضمان عدم حدوث NameError) ---
# =======================================================================================

async def show_dashboard_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bot_data = context.bot_data
    ks_status_emoji = "🚨" if not bot_data.trading_enabled else "✅"
    ks_status_text = "الإيقاف مفعل" if not bot_data.trading_enabled else "يعمل"
    keyboard = [
        [InlineKeyboardButton("💼 نظرة عامة", callback_data="db_portfolio"), InlineKeyboardButton("📈 الصفقات النشطة", callback_data="db_trades")],
        [InlineKeyboardButton("📜 سجل الصفقات", callback_data="db_history"), InlineKeyboardButton("📊 الإحصائيات", callback_data="db_stats")],
        [InlineKeyboardButton("🌡️ مزاج السوق", callback_data="db_mood"), InlineKeyboardButton("🔬 فحص فوري", callback_data="db_manual_scan")],
        [InlineKeyboardButton("🗓️ تقرير اليوم", callback_data="db_daily_report")],
        [InlineKeyboardButton(f"{ks_status_emoji} {ks_status_text}", callback_data="kill_switch_toggle")],
        [InlineKeyboardButton("🕵️‍♂️ تقرير التشخيص", callback_data="db_diagnostics")]
    ]
    message_text = "🖥️ **لوحة تحكم البوت**"
    if not bot_data.trading_enabled: message_text += "\n\n**تحذير: تم تفعيل مفتاح الإيقاف.**"
    target_message = update.message or update.callback_query.message
    if update.callback_query: await safe_edit_message(update.callback_query, message_text, reply_markup=InlineKeyboardMarkup(keyboard))
    else: await target_message.reply_text(message_text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(keyboard))

async def show_portfolio_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer("جاري جلب بيانات المحفظة...")
    bot_data = context.bot_data
    try:
        balance = await bot_data.exchange.fetch_balance({'type': 'trading'})
        owned_assets = {asset: data['total'] for asset, data in balance.items() if isinstance(data, dict) and data.get('total', 0) > 0 and 'USDT' not in asset}
        usdt_balance = balance.get('USDT', {}); free_usdt = usdt_balance.get('free', 0)
        total_assets_value_usdt = 0; asset_details = []
        if owned_assets:
            assets_to_fetch = [f"{asset}/USDT" for asset in owned_assets.keys()]
            tickers = await bot_data.exchange.fetch_tickers(assets_to_fetch)
            for asset, total in owned_assets.items():
                symbol = f"{asset}/USDT"; value_usdt = tickers.get(symbol, {}).get('last', 0) * total
                total_assets_value_usdt += value_usdt
                if value_usdt >= 1.0: asset_details.append(f"  - `{asset}`: `{total:,.6f}` `(≈ ${value_usdt:,.2f})`")
        total_equity = free_usdt + total_assets_value_usdt
        async with aiosqlite.connect(DB_FILE) as conn:
            total_realized_pnl = (await (await conn.execute("SELECT SUM(pnl_usdt) FROM trades WHERE status NOT IN ('active', 'pending', 'closing')")).fetchone())[0] or 0.0
            active_trades_count = (await (await conn.execute("SELECT COUNT(*) FROM trades WHERE status = 'active'")).fetchone())[0]
        assets_str = "\n".join(asset_details) or "  لا توجد أصول أخرى."
        message = (f"**💼 نظرة عامة على المحفظة**\n━━━━━━━━━━━━━━━━━━━━\n"
                   f"**💰 إجمالي قيمة المحفظة:** `≈ ${total_equity:,.2f}`\n"
                   f"  - **السيولة المتاحة (USDT):** `${free_usdt:,.2f}`\n"
                   f"  - **قيمة الأصول الأخرى:** `≈ ${total_assets_value_usdt:,.2f}`\n━━━━━━━━━━━━━━━━━━━━\n"
                   f"**📊 تفاصيل الأصول:**\n{assets_str}\n━━━━━━━━━━━━━━━━━━━━\n"
                   f"**📈 أداء التداول:**\n  - **الربح/الخسارة المحقق:** `${total_realized_pnl:,.2f}`\n  - **الصفقات النشطة:** {active_trades_count}\n")
        keyboard = [[InlineKeyboardButton("🔄 تحديث", callback_data="db_portfolio")], [InlineKeyboardButton("🔙 عودة", callback_data="back_to_dashboard")]]
        await safe_edit_message(query, message, reply_markup=InlineKeyboardMarkup(keyboard))
    except Exception as e: await safe_edit_message(query, f"حدث خطأ: {e}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 عودة", callback_data="back_to_dashboard")]]))

async def show_trades_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    async with aiosqlite.connect(DB_FILE) as conn:
        conn.row_factory = aiosqlite.Row
        trades = await (await conn.execute("SELECT id, symbol, status FROM trades WHERE status IN ('active', 'pending') ORDER BY id DESC")).fetchall()
    if not trades:
        text = "لا توجد صفقات نشطة حاليًا."; keyboard = [[InlineKeyboardButton("🔙 العودة", callback_data="back_to_dashboard")]]
    else:
        text = "📈 *الصفقات النشطة*\nاختر صفقة لعرض تفاصيلها:"; keyboard = [[InlineKeyboardButton(f"#{t['id']} {'✅' if t['status'] == 'active' else '⏳'} | {t['symbol']}", callback_data=f"check_{t['id']}")] for t in trades]
        keyboard.append([InlineKeyboardButton("🔄 تحديث", callback_data="db_trades")]); keyboard.append([InlineKeyboardButton("🔙 العودة", callback_data="back_to_dashboard")])
    await safe_edit_message(update.callback_query, text, reply_markup=InlineKeyboardMarkup(keyboard))

async def check_trade_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; trade_id = int(query.data.split('_')[1])
    async with aiosqlite.connect(DB_FILE) as conn: conn.row_factory = aiosqlite.Row; trade = await (await conn.execute("SELECT * FROM trades WHERE id = ?", (trade_id,))).fetchone()
    if not trade: await query.answer("لم يتم العثور على الصفقة."); return
    trade = dict(trade); keyboard = [[InlineKeyboardButton("🚨 بيع فوري", callback_data=f"manual_sell_confirm_{trade_id}")], [InlineKeyboardButton("🔙 العودة للصفقات", callback_data="db_trades")]]
    if trade['status'] == 'pending':
        message = f"**⏳ حالة الصفقة #{trade_id}**\n- **العملة:** `{trade['symbol']}`\n- **الحالة:** في انتظار تأكيد التنفيذ..."; keyboard = [[InlineKeyboardButton("🔙 العودة للصفقات", callback_data="db_trades")]]
    elif trade['status'] != 'active':
        message = f"**ℹ️ حالة الصفقة #{trade_id}**\n- **العملة:** `{trade['symbol']}`\n- **الحالة:** `{trade['status']}`"; keyboard = [[InlineKeyboardButton("🔙 العودة للصفقات", callback_data="db_trades")]]
    else:
        try:
            ticker = await context.bot_data.exchange.fetch_ticker(trade['symbol']); current_price = ticker['last']
            pnl = (current_price - trade['entry_price']) * trade['quantity'] if trade.get('quantity') else 0
            pnl_percent = (current_price / trade['entry_price'] - 1) * 100 if trade['entry_price'] > 0 else 0
            pnl_text = f"💰 **الربح/الخسارة:** `${pnl:+.2f}` ({pnl_percent:+.2f}%)"; current_price_text = f"- **السعر الحالي:** `${current_price}`"
        except Exception: pnl_text, current_price_text = "💰 تعذر جلب الربح/الخسارة.", "- **السعر الحالي:** `تعذر الجلب`"
        message = (f"**✅ حالة الصفقة #{trade_id}**\n\n- **العملة:** `{trade['symbol']}`\n- **سعر الدخول:** `${trade['entry_price']}`\n{current_price_text}\n- **الكمية:** `{trade.get('quantity', 'N/A')}`\n----------------------------------\n- **الهدف (TP):** `${trade['take_profit']}`\n- **الوقف (SL):** `${trade['stop_loss']}`\n----------------------------------\n{pnl_text}")
    await safe_edit_message(query, message, reply_markup=InlineKeyboardMarkup(keyboard))

async def show_trade_history_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    async with aiosqlite.connect(DB_FILE) as conn: conn.row_factory = aiosqlite.Row; closed_trades = await (await conn.execute("SELECT symbol, pnl_usdt FROM trades WHERE status NOT IN ('active', 'pending', 'closing') ORDER BY id DESC LIMIT 10")).fetchall()
    if not closed_trades: text = "لم يتم إغلاق أي صفقات بعد."
    else:
        history_list = ["📜 *آخر 10 صفقات مغلقة*"]; [history_list.append(f"{'✅' if (t['pnl_usdt'] or 0) >= 0 else '🛑'} `{t['symbol']}` | الربح/الخسارة: `${(t['pnl_usdt'] or 0):,.2f}`") for t in closed_trades]; text = "\n".join(history_list)
    keyboard = [[InlineKeyboardButton("🔙 العودة للوحة التحكم", callback_data="back_to_dashboard")]]; await safe_edit_message(update.callback_query, text, reply_markup=InlineKeyboardMarkup(keyboard))

async def show_stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    async with aiosqlite.connect(DB_FILE) as conn: conn.row_factory = aiosqlite.Row; trades_data = await (await conn.execute("SELECT pnl_usdt FROM trades WHERE pnl_usdt IS NOT NULL")).fetchall()
    if not trades_data: text = "لم يتم إغلاق أي صفقات بعد."
    else:
        pnls = [t['pnl_usdt'] for t in trades_data]; total_pnl = sum(pnls); wins = [p for p in pnls if p >= 0]; losses = [p for p in pnls if p < 0]
        win_rate = (len(wins) / len(pnls) * 100) if pnls else 0; avg_win = sum(wins) / len(wins) if wins else 0; avg_loss = sum(losses) / len(losses) if losses else 0
        profit_factor = sum(wins) / abs(sum(losses)) if sum(losses) != 0 else float('inf')
        text = (f"📊 **إحصائيات الأداء**\n━━━━━━━━━━━━━━━━━━\n"
                f"**إجمالي الربح/الخسارة:** `${total_pnl:+.2f}`\n**متوسط الربح:** `${avg_win:+.2f}`\n**متوسط الخسارة:** `${avg_loss:+.2f}`\n"
                f"**عامل الربح:** `{profit_factor:,.2f}`\n**معدل النجاح:** {win_rate:.1f}%\n**إجمالي الصفقات:** {len(pnls)}")
    keyboard = [[InlineKeyboardButton("📜 تقرير الاستراتيجيات", callback_data="db_strategy_report")], [InlineKeyboardButton("🔙 العودة", callback_data="back_to_dashboard")]]; await safe_edit_message(update.callback_query, text, reply_markup=InlineKeyboardMarkup(keyboard))

async def show_strategy_report_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    performance = context.bot_data.get('strategy_performance', {}); text = "لا توجد بيانات أداء حاليًا."
    if performance:
        report = ["**📜 تقرير أداء الاستراتيجيات**"]; sorted_strategies = sorted(performance.items(), key=lambda item: item[1].get('total_trades', 0), reverse=True)
        for r, s in sorted_strategies: report.append(f"\n--- *{STRATEGY_NAMES_AR.get(r, r)}* ---\n  - **النجاح:** {s.get('win_rate', 0):.1f}% ({s.get('total_trades', 0)} صفقة)\n  - **عامل الربح:** {s.get('profit_factor', '∞')}"); text = "\n".join(report)
    keyboard = [[InlineKeyboardButton("🔙 العودة للإحصائيات", callback_data="db_stats")]]; await safe_edit_message(update.callback_query, text, reply_markup=InlineKeyboardMarkup(keyboard))

async def show_mood_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer("جاري تحليل مزاج السوق..."); fng_index, headlines, mood, markets = await asyncio.gather(get_fear_and_greed_index(), asyncio.to_thread(get_latest_crypto_news), get_market_mood(context.bot_data), get_okx_markets(context.bot_data))
    news_sentiment, _ = analyze_sentiment_of_headlines(headlines); gainers = sorted([m for m in markets if m.get('percentage') is not None], key=lambda m: m['percentage'], reverse=True)[:3]; losers = sorted([m for m in markets if m.get('percentage') is not None], key=lambda m: m['percentage'])[:3]
    verdict = "الحالة العامة للسوق تتطلب الحذر." + (" يسود الخوف على السوق." if fng_index and fng_index < 30 else ""); verdict = "المؤشرات الفنية إيجابية." if mood['mood'] == 'POSITIVE' else verdict
    gainers_str = "\n".join([f"  `{g['symbol']}` `({g.get('percentage', 0):+.2f}%)`" for g in gainers]) or "  لا توجد بيانات."
    losers_str = "\n".join([f"  `{l['symbol']}` `({l.get('percentage', 0):+.2f}%)`" for l in losers]) or "  لا توجد بيانات."
    news_str = "\n".join([f"  - _{h}_" for h in headlines[:5]]) or "  لا توجد أخبار."
    message = (f"**🌡️ تحليل مزاج السوق**\n━━━━━━━━━━━━━━━━━━━━\n**⚫️ الخلاصة:** *{verdict}*\n**📊 المؤشرات:**\n  - **اتجاه BTC:** {mood.get('btc_mood', 'N/A')}\n  - **الخوف والطمع:** {fng_index or 'N/A'}\n  - **مشاعر الأخبار:** {news_sentiment}\n━━━━━━━━━━━━━━━━━━━━\n**🚀 أبرز الرابحين:**\n{gainers_str}\n\n**📉 أبرز الخاسرين:**\n{losers_str}\n━━━━━━━━━━━━━━━━━━━━\n📰 **آخر الأخبار:**\n{news_str}\n")
    keyboard = [[InlineKeyboardButton("🔄 تحديث", callback_data="db_mood")], [InlineKeyboardButton("🔙 العودة", callback_data="back_to_dashboard")]]; await safe_edit_message(query, message, reply_markup=InlineKeyboardMarkup(keyboard))

async def show_diagnostics_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bot_data = context.bot_data; scan_info = bot_data.last_scan_info; db_size = f"{os.path.getsize(DB_FILE) / 1024:.2f} KB" if os.path.exists(DB_FILE) else "N/A"
    async with aiosqlite.connect(DB_FILE) as conn: total_trades, active_trades = (await (await conn.execute("SELECT COUNT(*) FROM trades")).fetchone())[0], (await (await conn.execute("SELECT COUNT(*) FROM trades WHERE status = 'active'")).fetchone())[0]
    ws_status = "متصل ✅" if bot_data.public_ws and hasattr(bot_data.public_ws, 'websocket') and bot_data.public_ws.websocket and bot_data.public_ws.websocket.open else "غير متصل ❌"
    report = (f"🕵️‍♂️ *تقرير التشخيص*\n\n**🔬 آخر فحص:**\n- المدة: {scan_info.get('duration_seconds', 'N/A')} ثانية\n- العملات: {scan_info.get('checked_symbols', 'N/A')}\n\n**🔧 الإعدادات:**\n- النمط: {bot_data.active_preset_name}\n\n**🔩 العمليات:**\n- WebSocket: {ws_status}\n- DB: {db_size} | {total_trades} ({active_trades} نشطة)")
    keyboard = [[InlineKeyboardButton("🔄 تحديث", callback_data="db_diagnostics")], [InlineKeyboardButton("🔙 العودة", callback_data="back_to_dashboard")]]; await safe_edit_message(update.callback_query, report, reply_markup=InlineKeyboardMarkup(keyboard))

async def send_daily_report(update: Update, context: ContextTypes.DEFAULT_TYPE): await context.bot.send_message(chat_id=update.effective_chat.id, text="تقرير اليوم تحت الإنشاء...")
    
async def manual_scan_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from okx_maestro import perform_scan
    await (update.message or update.callback_query.message).reply_text("🔬 أمر فحص يدوي... قد يستغرق بعض الوقت.")
    context.job_queue.run_once(lambda ctx: perform_scan(ctx), 1, name="manual_scan")

async def toggle_kill_switch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.bot_data.trading_enabled = not context.bot_data.trading_enabled; status = "استئناف التداول" if context.bot_data.trading_enabled else "إيقاف التداول"
    await context.bot.send_message(chat_id=context.bot_data.TELEGRAM_CHAT_ID, text=f"**{status}**"); await show_dashboard_command(update, context)

async def handle_manual_sell_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; trade_id = int(query.data.split('_')[-1])
    message = f"🛑 **تأكيد البيع الفوري** 🛑\nهل أنت متأكد أنك تريد بيع الصفقة رقم `#{trade_id}` بسعر السوق؟"
    keyboard = [[InlineKeyboardButton("✅ نعم، قم بالبيع", callback_data=f"manual_sell_execute_{trade_id}")], [InlineKeyboardButton("❌ لا، تراجع", callback_data=f"check_{trade_id}")]]
    await safe_edit_message(query, message, reply_markup=InlineKeyboardMarkup(keyboard))

async def handle_manual_sell_execute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; trade_id = int(query.data.split('_')[-1]); await safe_edit_message(query, "⏳ جاري إرسال أمر البيع...", reply_markup=None)
    async with aiosqlite.connect(DB_FILE) as conn: conn.row_factory = aiosqlite.Row; trade = await (await conn.execute("SELECT * FROM trades WHERE id = ? AND status = 'active'", (trade_id,))).fetchone()
    if not trade: await query.answer("لم يتم العثور على الصفقة.", show_alert=True); return
    try:
        ticker = await context.bot_data.exchange.fetch_ticker(trade['symbol'])
        await context.bot_data.guardian._close_trade(dict(trade), "إغلاق يدوي", ticker['last']); await query.answer("✅ تم إرسال أمر البيع بنجاح!")
    except Exception as e: await context.bot.send_message(chat_id=context.bot_data.TELEGRAM_CHAT_ID, text=f"🚨 فشل البيع اليدوي للصفقة #{trade_id}. السبب: {e}"); await query.answer("🚨 فشل أمر البيع.", show_alert=True)
        
async def show_settings_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[InlineKeyboardButton("🧠 الذكاء التكيفي", callback_data="settings_adaptive")], [InlineKeyboardButton("🎛️ المعايير المتقدمة", callback_data="settings_params")], [InlineKeyboardButton("🔭 الماسحات", callback_data="settings_scanners")], [InlineKeyboardButton("🗂️ أنماط جاهزة", callback_data="settings_presets")], [InlineKeyboardButton("🚫 القائمة السوداء", callback_data="settings_blacklist"), InlineKeyboardButton("🗑️ إدارة البيانات", callback_data="settings_data")]]
    message_text = "⚙️ *الإعدادات الرئيسية*";
    if update.callback_query: await safe_edit_message(update.callback_query, message_text, reply_markup=InlineKeyboardMarkup(keyboard))
    else: await update.message.reply_text(message_text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(keyboard))

async def show_adaptive_intelligence_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    s = context.bot_data.settings; bool_format = lambda key: "✅" if s.get(key, False) else "❌"
    keyboard = [[InlineKeyboardButton(f"الذكاء التكيفي: {bool_format('adaptive_intelligence_enabled')}", callback_data="param_toggle_adaptive_intelligence_enabled")], [InlineKeyboardButton(f"الحجم الديناميكي: {bool_format('dynamic_trade_sizing_enabled')}", callback_data="param_toggle_dynamic_trade_sizing_enabled")], [InlineKeyboardButton(f"اقتراحات الاستراتيجيات: {bool_format('strategy_proposal_enabled')}", callback_data="param_toggle_strategy_proposal_enabled")], [InlineKeyboardButton(f"حد التعطيل (%WR): {s.get('strategy_deactivation_threshold_wr', 45.0)}", callback_data="param_set_strategy_deactivation_threshold_wr")], [InlineKeyboardButton("🔙 العودة للإعدادات", callback_data="settings_main")]]
    await safe_edit_message(update.callback_query, "🧠 **إعدادات الذكاء التكيفي**", reply_markup=InlineKeyboardMarkup(keyboard))

async def show_parameters_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    s = context.bot_data.settings

    # دالة مساعدة مبسطة وصحيحة
    def bool_format(val):
        return "✅" if val else "❌"

    keyboard = [
        # General Settings
        [InlineKeyboardButton(f"حجم الصفقة ($): {s.get('real_trade_size_usdt')}", callback_data="param_set_real_trade_size_usdt")],
        [InlineKeyboardButton(f"أقصى عدد للصفقات: {s.get('max_concurrent_trades')}", callback_data="param_set_max_concurrent_trades")],
        [InlineKeyboardButton(f"عمال الفحص: {s.get('worker_threads')}", callback_data="param_set_worker_threads")],

        # Risk Settings
        [InlineKeyboardButton("--- إعدادات المخاطر ---", callback_data="noop")],
        [InlineKeyboardButton(f"مضاعف ATR للوقف: {s.get('atr_sl_multiplier')}", callback_data="param_set_atr_sl_multiplier")],
        [InlineKeyboardButton(f"نسبة المخاطرة/العائد: {s.get('risk_reward_ratio')}", callback_data="param_set_risk_reward_ratio")],
        [InlineKeyboardButton(f"الوقف المتحرك: {bool_format(s.get('trailing_sl_enabled'))}", callback_data="param_toggle_trailing_sl_enabled")],
        [InlineKeyboardButton(f"تفعيل الوقف (%): {s.get('trailing_sl_activation_percent')}", callback_data="param_set_trailing_sl_activation_percent")],
        [InlineKeyboardButton(f"مسافة الوقف (%): {s.get('trailing_sl_callback_percent')}", callback_data="param_set_trailing_sl_callback_percent")],

        # Filter Settings
        [InlineKeyboardButton("--- إعدادات الفلاتر ---", callback_data="noop")],
        [InlineKeyboardButton(f"فلتر ADX: {bool_format(s.get('adx_filter_enabled'))}", callback_data="param_toggle_adx_filter_enabled")],
        [InlineKeyboardButton(f"مستوى ADX: {s.get('adx_filter_level')}", callback_data="param_set_adx_filter_level")],
        [InlineKeyboardButton(f"أقصى سبريد (%): {get_nested_value(s, ['spread_filter', 'max_spread_percent'])}", callback_data="param_set_spread_filter_max_spread_percent")],
        [InlineKeyboardButton(f"أدنى حجم ($): {get_nested_value(s, ['liquidity_filters', 'min_quote_volume_24h_usd'])}", callback_data="param_set_liquidity_filters_min_quote_volume_24h_usd")],

        [InlineKeyboardButton("🔙 العودة للإعدادات", callback_data="settings_main")]
    ]
    await safe_edit_message(update.callback_query, "🎛️ **تعديل المعايير المتقدمة**", reply_markup=InlineKeyboardMarkup(keyboard))
async def show_scanners_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = []; active_scanners = context.bot_data.settings.get('active_scanners', [])
    for key, name in STRATEGY_NAMES_AR.items(): keyboard.append([InlineKeyboardButton(f"{'✅' if key in active_scanners else '❌'} {name}", callback_data=f"scanner_toggle_{key}")])
    keyboard.append([InlineKeyboardButton("🔙 العودة للإعدادات", callback_data="settings_main")]); await safe_edit_message(update.callback_query, "اختر الماسحات لتفعيلها أو تعطيلها:", reply_markup=InlineKeyboardMarkup(keyboard))

async def show_presets_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from settings_config import PRESET_NAMES_AR # Lazy import
    keyboard = [[InlineKeyboardButton(name, callback_data=f"preset_set_{key}")] for key, name in PRESET_NAMES_AR.items()]
    keyboard.append([InlineKeyboardButton("🔙 العودة للإعدادات", callback_data="settings_main")]); await safe_edit_message(update.callback_query, "اختر نمط إعدادات جاهز:", reply_markup=InlineKeyboardMarkup(keyboard))

async def show_blacklist_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    blacklist = context.bot_data.settings.get('asset_blacklist', []); blacklist_str = ", ".join(f"`{item}`" for item in blacklist) if blacklist else "القائمة فارغة."
    text = f"🚫 **القائمة السوداء**\n{blacklist_str}"; keyboard = [[InlineKeyboardButton("➕ إضافة", callback_data="blacklist_add"), InlineKeyboardButton("➖ إزالة", callback_data="blacklist_remove")], [InlineKeyboardButton("🔙 العودة", callback_data="settings_main")]]
    await safe_edit_message(update.callback_query, text, reply_markup=InlineKeyboardMarkup(keyboard))

async def show_data_management_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[InlineKeyboardButton("‼️ مسح كل الصفقات ‼️", callback_data="data_clear_confirm")], [InlineKeyboardButton("🔙 العودة", callback_data="settings_main")]]; await safe_edit_message(update.callback_query, "🗑️ **إدارة البيانات**\n\n**تحذير:** هذا الإجراء سيحذف سجل جميع الصفقات بشكل نهائي.", reply_markup=InlineKeyboardMarkup(keyboard))

async def handle_clear_data_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[InlineKeyboardButton("نعم، متأكد.", callback_data="data_clear_execute")], [InlineKeyboardButton("لا، تراجع.", callback_data="settings_data")]]; await safe_edit_message(update.callback_query, "🛑 **تأكيد نهائي**\nهل أنت متأكد أنك تريد حذف جميع بيانات الصفقات؟", reply_markup=InlineKeyboardMarkup(keyboard))

async def handle_clear_data_execute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await safe_edit_message(query, "جاري حذف البيانات...", reply_markup=None)
    try:
        if os.path.exists(DB_FILE): os.remove(DB_FILE)
        from okx_maestro import init_database
        await init_database(); await safe_edit_message(query, "✅ تم حذف البيانات بنجاح.")
    except Exception as e: await safe_edit_message(query, f"❌ حدث خطأ: {e}")
    await asyncio.sleep(2); await show_settings_menu(update, context)

async def handle_blacklist_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; action = query.data.replace("blacklist_", ""); context.user_data['blacklist_action'] = action
    await query.message.reply_text(f"أرسل رمز العملة التي تريد **{ 'إضافتها' if action == 'add' else 'إزالتها'}** (مثال: `BTC`)")

async def handle_parameter_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; param_key = query.data.replace("param_set_", "")
    context.user_data['setting_to_change'] = param_key; await query.message.reply_text(f"أرسل القيمة الرقمية الجديدة لـ `{param_key.replace('_', ' ')}`:")

async def handle_toggle_parameter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; param_key = query.data.replace("param_toggle_", "")
    settings = context.bot_data.settings; settings[param_key] = not settings.get(param_key, False)
    with open(SETTINGS_FILE, 'w') as f: import json; json.dump(settings, f, indent=4)
    if "adaptive" in param_key: await show_adaptive_intelligence_menu(update, context)
    else: await show_parameters_menu(update, context)

async def handle_scanner_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; scanner_key = query.data.replace("scanner_toggle_", "")
    active_scanners = context.bot_data.settings['active_scanners']
    if scanner_key in active_scanners:
        if len(active_scanners) > 1: active_scanners.remove(scanner_key)
        else: await query.answer("يجب تفعيل ماسح واحد على الأقل.", show_alert=True)
    else: active_scanners.append(scanner_key)
    with open(SETTINGS_FILE, 'w') as f: import json; json.dump(context.bot_data.settings, f, indent=4); await show_scanners_menu(update, context)

async def handle_preset_set(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; preset_key = query.data.replace("preset_set_", "")
    if preset_settings := SETTINGS_PRESETS.get(preset_key):
        context.bot_data.settings = copy.deepcopy(preset_settings)
        with open(SETTINGS_FILE, 'w') as f: import json; json.dump(context.bot_data.settings, f, indent=4)
        context.bot_data.active_preset_name = preset_key
        await query.answer(f"✅ تم تفعيل النمط: {preset_key}", show_alert=True)
    await show_presets_menu(update, context)

async def handle_strategy_adjustment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.message.edit_text("تم التعامل مع الاقتراح.")

async def handle_setting_value(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_input = update.message.text.strip(); settings = context.bot_data.settings
    def save():
        with open(SETTINGS_FILE, 'w') as f: import json; json.dump(settings, f, indent=4)

    if 'blacklist_action' in context.user_data:
        action = context.user_data.pop('blacklist_action'); symbol = user_input.upper().replace("/USDT", "")
        blacklist = settings.get('asset_blacklist', [])
        if action == 'add' and symbol not in blacklist: blacklist.append(symbol)
        elif action == 'remove' and symbol in blacklist: blacklist.remove(symbol)
        settings['asset_blacklist'] = blacklist; await update.message.reply_text(f"✅ تم تحديث القائمة السوداء."); save()
    
    elif setting_key := context.user_data.get('setting_to_change'):
        try:
            val = float(user_input)
            if val.is_integer(): val = int(val)
            keys = setting_key.split('_'); d = settings
            for key in keys[:-1]: d = d[key]
            d[keys[-1]] = val
            await update.message.reply_text(f"✅ تم تحديث `{setting_key.replace('_', ' ')}` إلى `{val}`.")
        except (ValueError, KeyError): await update.message.reply_text("❌ قيمة غير صالحة.")
        finally: del context.user_data['setting_to_change']; save()
