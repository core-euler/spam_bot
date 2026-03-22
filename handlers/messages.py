import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ContextTypes, ConversationHandler,
    MessageHandler, filters, CallbackQueryHandler
)
from database import get_db, AdMessage
from keyboards import messages_menu_keyboard, message_actions_keyboard, back_keyboard, confirm_keyboard

MSG_TITLE, MSG_TEXT, MSG_MEDIA, MSG_EDIT_TEXT = range(10, 14)


async def messages_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "✍️ *Рекламные сообщения*\n\nВыберите действие:",
        reply_markup=messages_menu_keyboard(),
        parse_mode="Markdown"
    )


async def msg_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    db = get_db()
    messages = db.query(AdMessage).all()

    if not messages:
        await query.edit_message_text(
            "✍️ *Сообщения*\n\nСписок пуст. Создайте первое рекламное сообщение.",
            reply_markup=messages_menu_keyboard(),
            parse_mode="Markdown"
        )
        return

    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton(
            f"{'🖼' if m.media_file_id else '📝'} {m.title}",
            callback_data=f"msg_view_{m.id}"
        )] for m in messages] +
        [[InlineKeyboardButton("➕ Создать сообщение", callback_data="msg_add")]] +
        [[InlineKeyboardButton("🔙 Назад", callback_data="menu_messages")]]
    )
    await query.edit_message_text("✍️ *Рекламные сообщения:*", reply_markup=keyboard, parse_mode="Markdown")


async def msg_view(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    msg_id = int(query.data.split("_")[-1])
    db = get_db()
    msg = db.query(AdMessage).get(msg_id)

    if not msg:
        await query.edit_message_text("Сообщение не найдено.", reply_markup=back_keyboard("msg_list"))
        return

    preview = msg.text[:200] + "..." if len(msg.text) > 200 else msg.text
    media_icons = {"photo": "🖼 Фото", "video": "🎥 Видео", "document": "📎 Файл"}
    media_info = media_icons.get(msg.media_type, "—") if msg.media_file_id else "—"

    text = (
        f"✍️ *{msg.title}*\n\n"
        f"📄 Текст:\n{preview}\n\n"
        f"Медиа: {media_info}\n"
        f"Формат: {msg.parse_mode}"
    )
    await query.edit_message_text(text, reply_markup=message_actions_keyboard(msg.id), parse_mode="Markdown")


async def msg_add_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["new_msg"] = {}
    await query.edit_message_text(
        "➕ *Новое рекламное сообщение*\n\nВведите название (для вашего удобства):",
        parse_mode="Markdown"
    )
    return MSG_TITLE


async def msg_add_title(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["new_msg"]["title"] = update.message.text.strip()
    await update.message.reply_text(
        "Введите текст рекламного сообщения.\n\n"
        "Поддерживается HTML: <b>жирный</b>, <i>курсив</i>, <a href='url'>ссылка</a>"
    )
    return MSG_TEXT


async def msg_add_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["new_msg"]["text"] = update.message.text
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📎 Прикрепить медиа", callback_data="msg_attach_media")],
        [InlineKeyboardButton("✅ Сохранить без медиа", callback_data="msg_save_nomedia")],
    ])
    await update.message.reply_text("Прикрепить медиа (фото/видео)?", reply_markup=keyboard)
    return MSG_MEDIA


async def msg_attach_media_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("Отправьте фото или видео:")
    return MSG_MEDIA


async def msg_receive_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    os.makedirs("data/media", exist_ok=True)
    if update.message.photo:
        file = await update.message.photo[-1].get_file()
        media_type = "photo"
    elif update.message.video:
        file = await update.message.video.get_file()
        media_type = "video"
    elif update.message.document:
        file = await update.message.document.get_file()
        media_type = "document"
    else:
        await update.message.reply_text("Пожалуйста, отправьте фото, видео или документ.")
        return MSG_MEDIA

    ext = os.path.splitext(file.file_path or "")[1] or {
        "photo": ".jpg", "video": ".mp4", "document": ""
    }.get(media_type, "")
    local_path = f"data/media/{file.file_unique_id}{ext}"
    await file.download_to_drive(local_path)

    context.user_data["new_msg"]["media_file_id"] = local_path
    context.user_data["new_msg"]["media_type"] = media_type
    return await _save_msg_from_message(update, context)


async def msg_save_nomedia(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["new_msg"]["media_file_id"] = None
    context.user_data["new_msg"]["media_type"] = None
    data = context.user_data["new_msg"]
    data.setdefault("parse_mode", "HTML")
    db = get_db()
    msg = AdMessage(**data)
    db.add(msg)
    db.commit()
    await query.edit_message_text(
        f"✅ Сообщение *{msg.title}* сохранено!",
        reply_markup=messages_menu_keyboard(),
        parse_mode="Markdown"
    )
    return ConversationHandler.END


async def _save_msg_from_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = context.user_data["new_msg"]
    data.setdefault("parse_mode", "HTML")
    db = get_db()
    msg = AdMessage(**data)
    db.add(msg)
    db.commit()
    await update.message.reply_text(
        f"✅ Сообщение *{msg.title}* сохранено!",
        reply_markup=messages_menu_keyboard(),
        parse_mode="Markdown"
    )
    return ConversationHandler.END


async def msg_delete_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    msg_id = int(query.data.split("_")[-1])
    db = get_db()
    msg = db.query(AdMessage).get(msg_id)
    await query.edit_message_text(
        f"🗑 Удалить сообщение *{msg.title}*?",
        reply_markup=confirm_keyboard(f"msg_delete_yes_{msg_id}", "msg_list"),
        parse_mode="Markdown"
    )


async def msg_delete_yes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    msg_id = int(query.data.split("_")[-1])
    db = get_db()
    msg = db.query(AdMessage).get(msg_id)
    if msg:
        db.delete(msg)
        db.commit()
    await query.edit_message_text("✅ Сообщение удалено.", reply_markup=messages_menu_keyboard())


async def msg_edit_text_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    msg_id = int(query.data.split("_")[-1])
    context.user_data["edit_msg_id"] = msg_id
    await query.edit_message_text("Введите новый текст сообщения:")
    return MSG_EDIT_TEXT


async def msg_edit_text_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg_id = context.user_data["edit_msg_id"]
    db = get_db()
    msg = db.query(AdMessage).get(msg_id)
    msg.text = update.message.text
    db.commit()
    await update.message.reply_text("✅ Текст обновлён!", reply_markup=message_actions_keyboard(msg_id))
    return ConversationHandler.END


def get_messages_conversation():
    return ConversationHandler(
        entry_points=[
            CallbackQueryHandler(msg_add_start, pattern="^msg_add$"),
            CallbackQueryHandler(msg_edit_text_start, pattern=r"^msg_edit_text_\d+$"),
        ],
        states={
            MSG_TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, msg_add_title)],
            MSG_TEXT:  [MessageHandler(filters.TEXT & ~filters.COMMAND, msg_add_text)],
            MSG_MEDIA: [
                CallbackQueryHandler(msg_attach_media_prompt, pattern="^msg_attach_media$"),
                CallbackQueryHandler(msg_save_nomedia, pattern="^msg_save_nomedia$"),
                MessageHandler(filters.PHOTO | filters.VIDEO | filters.Document.ALL, msg_receive_media),
            ],
            MSG_EDIT_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, msg_edit_text_save)],
        },
        fallbacks=[],
        per_message=False,
    )
