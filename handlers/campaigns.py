from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ContextTypes, ConversationHandler,
    MessageHandler, filters, CallbackQueryHandler
)
from datetime import datetime
from database import get_db, Campaign, Chat, AdMessage, SendLog
from keyboards import (
    campaigns_menu_keyboard, campaign_actions_keyboard,
    back_keyboard, repeat_type_keyboard, confirm_keyboard
)
from tz_utils import format_local, parse_admin_input, TIMEZONE

CAMP_NAME, CAMP_SELECT_MSG, CAMP_SELECT_CHATS, CAMP_DATETIME, CAMP_REPEAT = range(20, 25)


async def campaigns_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "🗓 *Рассылки*\n\nВыберите действие:",
        reply_markup=campaigns_menu_keyboard(),
        parse_mode="Markdown"
    )


async def camp_list_active(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    db = get_db()
    campaigns = db.query(Campaign).filter(
        Campaign.status.in_(["active", "paused", "scheduled"])
    ).all()

    if not campaigns:
        await query.edit_message_text(
            "🗓 *Активные рассылки*\n\nПока нет активных рассылок.",
            reply_markup=campaigns_menu_keyboard(),
            parse_mode="Markdown"
        )
        return

    icons = {"active": "🟢", "paused": "⏸", "scheduled": "🕐"}
    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton(
            f"{icons.get(c.status, '❓')} {c.name}",
            callback_data=f"camp_detail_{c.id}"
        )] for c in campaigns] +
        [[InlineKeyboardButton("➕ Создать рассылку", callback_data="camp_add")]] +
        [[InlineKeyboardButton("🔙 Назад", callback_data="menu_campaigns")]]
    )
    await query.edit_message_text(
        "🗓 *Активные рассылки:*\n\n🟢 активна  ⏸ пауза  🕐 запланирована",
        reply_markup=keyboard,
        parse_mode="Markdown"
    )


async def camp_list_done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    db = get_db()
    campaigns = db.query(Campaign).filter(Campaign.status.in_(["done", "cancelled"])).all()

    if not campaigns:
        await query.edit_message_text(
            "📜 *История рассылок*\n\nПока нет завершённых рассылок.",
            reply_markup=campaigns_menu_keyboard(),
            parse_mode="Markdown"
        )
        return

    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton(
            f"{'✅' if c.status == 'done' else '⛔'} {c.name}",
            callback_data=f"camp_detail_{c.id}"
        )] for c in campaigns] +
        [[InlineKeyboardButton("🔙 Назад", callback_data="menu_campaigns")]]
    )
    await query.edit_message_text("📜 *История рассылок:*", reply_markup=keyboard, parse_mode="Markdown")


async def camp_errors(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Экран последних ошибок из send_logs"""
    query = update.callback_query
    await query.answer()
    db = get_db()

    logs = (
        db.query(SendLog)
        .filter(SendLog.status == "failed")
        .order_by(SendLog.sent_at.desc())
        .limit(20)
        .all()
    )

    if not logs:
        await query.edit_message_text(
            "⚠️ *Последние ошибки*\n\nОшибок нет — всё работает чисто! 🎉",
            reply_markup=back_keyboard("menu_campaigns"),
            parse_mode="Markdown"
        )
        return

    lines = ["⚠️ *Последние ошибки (до 20):*\n"]
    for log in logs:
        chat_name = log.chat.name if log.chat else f"id={log.chat_id}"
        camp_name = log.campaign.name if log.campaign else f"id={log.campaign_id}"
        when = format_local(log.sent_at)
        error_short = (log.error or "—")[:80]
        lines.append(f"🔴 *{camp_name}* → {chat_name}\n_{when}_\n`{error_short}`\n")

    await query.edit_message_text(
        "\n".join(lines),
        reply_markup=back_keyboard("menu_campaigns"),
        parse_mode="Markdown"
    )


async def camp_detail(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    camp_id = int(query.data.split("_")[-1])
    db = get_db()
    camp = db.query(Campaign).get(camp_id)

    if not camp:
        await query.edit_message_text("Рассылка не найдена.", reply_markup=back_keyboard("camp_list_active"))
        return

    status_names = {
        "active": "🟢 Активна", "paused": "⏸ Пауза",
        "scheduled": "🕐 Запланирована",
        "done": "✅ Завершена", "cancelled": "⛔ Отменена"
    }
    repeat_names = {
        None: "Разово", "none": "Разово",
        "hourly": "Каждый час", "daily": "Каждый день", "weekly": "Каждую неделю"
    }
    chats_str = ", ".join(c.name for c in camp.chats) or "—"

    # Подсчёт статистики из send_logs
    total_logs = db.query(SendLog).filter(SendLog.campaign_id == camp_id).count()
    failed_logs = db.query(SendLog).filter(SendLog.campaign_id == camp_id, SendLog.status == "failed").count()

    text = (
        f"🗓 *{camp.name}*\n\n"
        f"Статус: {status_names.get(camp.status, camp.status)}\n"
        f"Сообщение: {camp.ad_message.title if camp.ad_message else '—'}\n"
        f"Чаты: {chats_str}\n"
        f"Дата отправки: {format_local(camp.scheduled_at)}\n"
        f"Повтор: {repeat_names.get(camp.repeat_type, camp.repeat_type)}\n"
        f"Последний запуск: {format_local(camp.last_run_at)}\n"
        f"Отправок: {total_logs - failed_logs} ✅  Ошибок: {failed_logs} ❌"
    )
    await query.edit_message_text(
        text,
        reply_markup=campaign_actions_keyboard(camp.id, camp.status),
        parse_mode="Markdown"
    )


async def camp_add_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["new_camp"] = {"chat_ids": []}
    await query.edit_message_text(
        "➕ *Новая рассылка*\n\nВведите название рассылки:",
        parse_mode="Markdown"
    )
    return CAMP_NAME


async def camp_add_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["new_camp"]["name"] = update.message.text.strip()
    db = get_db()
    messages = db.query(AdMessage).all()

    if not messages:
        await update.message.reply_text(
            "❌ Нет рекламных сообщений. Сначала создайте сообщение.",
            reply_markup=back_keyboard("menu_messages")
        )
        return ConversationHandler.END

    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton(
            f"{'🖼' if m.media_file_id else '📝'} {m.title}",
            callback_data=f"camp_msg_{m.id}"
        )] for m in messages]
    )
    await update.message.reply_text("Выберите рекламное сообщение:", reply_markup=keyboard)
    return CAMP_SELECT_MSG


async def camp_select_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["new_camp"]["ad_message_id"] = int(query.data.split("_")[-1])
    db = get_db()
    chats = db.query(Chat).filter(Chat.is_active == True).all()

    if not chats:
        await query.edit_message_text(
            "❌ Нет активных чатов. Сначала добавьте чаты.",
            reply_markup=back_keyboard("menu_chats")
        )
        return ConversationHandler.END

    context.user_data["available_chats"] = {str(c.id): c.name for c in chats}
    await _show_chat_selector(query, context)
    return CAMP_SELECT_CHATS


async def _show_chat_selector(query_or_msg, context: ContextTypes.DEFAULT_TYPE):
    selected = context.user_data["new_camp"]["chat_ids"]
    available = context.user_data["available_chats"]
    buttons = []
    for cid, cname in available.items():
        is_sel = int(cid) in selected
        buttons.append([InlineKeyboardButton(
            f"{'✅' if is_sel else '☐'} {cname}",
            callback_data=f"camp_chat_toggle_{cid}"
        )])
    if selected:
        buttons.append([InlineKeyboardButton(f"➡️ Далее ({len(selected)} выбрано)", callback_data="camp_chats_done")])

    keyboard = InlineKeyboardMarkup(buttons)
    text = "Выберите чаты для рассылки (можно несколько):"
    if hasattr(query_or_msg, "edit_message_text"):
        await query_or_msg.edit_message_text(text, reply_markup=keyboard)
    else:
        await query_or_msg.reply_text(text, reply_markup=keyboard)


async def camp_chat_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    cid = int(query.data.split("_")[-1])
    selected = context.user_data["new_camp"]["chat_ids"]
    if cid in selected:
        selected.remove(cid)
    else:
        selected.append(cid)
    await _show_chat_selector(query, context)


async def camp_chats_done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        f"Введите дату и время отправки в формате:\n`ДД.ММ.ГГГГ ЧЧ:ММ` ({TIMEZONE})\n\n"
        "Например: `25.12.2024 15:00`\n\n"
        "Или отправьте *сейчас* для немедленной отправки.",
        parse_mode="Markdown"
    )
    return CAMP_DATETIME


async def camp_set_datetime(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip().lower()
    if text == "сейчас":
        context.user_data["new_camp"]["scheduled_at"] = None
    else:
        dt_utc = parse_admin_input(text)
        if dt_utc is None:
            await update.message.reply_text(
                f"❌ Неверный формат. Попробуйте: `ДД.ММ.ГГГГ ЧЧ:ММ` ({TIMEZONE})",
                parse_mode="Markdown"
            )
            return CAMP_DATETIME
        context.user_data["new_camp"]["scheduled_at"] = dt_utc

    await update.message.reply_text("Выберите тип повтора:", reply_markup=repeat_type_keyboard())
    return CAMP_REPEAT


async def camp_set_repeat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    repeat_type = query.data.replace("repeat_", "")
    context.user_data["new_camp"]["repeat_type"] = None if repeat_type == "none" else repeat_type
    await _save_campaign(query, context)
    return ConversationHandler.END


async def _save_campaign(query, context: ContextTypes.DEFAULT_TYPE):
    from scheduler import schedule_campaign
    import asyncio
    data = context.user_data["new_camp"]
    chat_ids = data.pop("chat_ids")
    db = get_db()

    camp = Campaign(
        name=data["name"],
        ad_message_id=data["ad_message_id"],
        scheduled_at=data.get("scheduled_at"),
        repeat_type=data.get("repeat_type"),
        status="active"
    )
    for cid in chat_ids:
        chat = db.query(Chat).get(cid)
        if chat:
            camp.chats.append(chat)
    db.add(camp)
    db.commit()

    asyncio.create_task(schedule_campaign(camp))

    await query.edit_message_text(
        f"✅ Рассылка *{camp.name}* создана и запланирована!",
        reply_markup=campaigns_menu_keyboard(),
        parse_mode="Markdown"
    )


async def camp_pause(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from scheduler import pause_campaign
    query = update.callback_query
    await query.answer()
    db = get_db()
    camp = db.query(Campaign).get(int(query.data.split("_")[-1]))
    await pause_campaign(camp)
    await query.edit_message_text(
        f"⏸ Рассылка *{camp.name}* приостановлена.",
        reply_markup=campaign_actions_keyboard(camp.id, camp.status),
        parse_mode="Markdown"
    )


async def camp_resume(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from scheduler import resume_campaign
    query = update.callback_query
    await query.answer()
    db = get_db()
    camp = db.query(Campaign).get(int(query.data.split("_")[-1]))
    await resume_campaign(camp)
    await query.edit_message_text(
        f"▶️ Рассылка *{camp.name}* возобновлена.",
        reply_markup=campaign_actions_keyboard(camp.id, camp.status),
        parse_mode="Markdown"
    )


async def camp_cancel_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    camp_id = int(query.data.split("_")[-1])
    db = get_db()
    camp = db.query(Campaign).get(camp_id)
    await query.edit_message_text(
        f"⛔ Отменить рассылку *{camp.name}*?\nОтложенные сообщения в Telegram тоже будут удалены.",
        reply_markup=confirm_keyboard(f"camp_cancel_yes_{camp_id}", f"camp_detail_{camp_id}"),
        parse_mode="Markdown"
    )


async def camp_cancel_yes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from scheduler import cancel_campaign
    query = update.callback_query
    await query.answer()
    db = get_db()
    camp = db.query(Campaign).get(int(query.data.split("_")[-1]))
    await cancel_campaign(camp)
    await query.edit_message_text("⛔ Рассылка отменена.", reply_markup=campaigns_menu_keyboard())


def get_campaigns_conversation():
    return ConversationHandler(
        entry_points=[CallbackQueryHandler(camp_add_start, pattern="^camp_add$")],
        states={
            CAMP_NAME:         [MessageHandler(filters.TEXT & ~filters.COMMAND, camp_add_name)],
            CAMP_SELECT_MSG:   [CallbackQueryHandler(camp_select_msg, pattern=r"^camp_msg_\d+$")],
            CAMP_SELECT_CHATS: [
                CallbackQueryHandler(camp_chat_toggle, pattern=r"^camp_chat_toggle_\d+$"),
                CallbackQueryHandler(camp_chats_done, pattern="^camp_chats_done$"),
            ],
            CAMP_DATETIME:     [MessageHandler(filters.TEXT & ~filters.COMMAND, camp_set_datetime)],
            CAMP_REPEAT:       [CallbackQueryHandler(camp_set_repeat, pattern=r"^repeat_")],
        },
        fallbacks=[],
        per_message=False,
    )
