import re
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ContextTypes, ConversationHandler,
    MessageHandler, filters, CallbackQueryHandler
)
from database import get_db, Chat
from keyboards import chats_menu_keyboard, chat_actions_keyboard, back_keyboard, confirm_keyboard

CHAT_NAME, CHAT_USERNAME, CHAT_DELAY, CHAT_NOTE = range(4)
EDIT_VALUE = 5


def parse_chat_target(value: str) -> tuple[str | None, str | None, str | None]:
    """
    Парсит ввод пользователя и возвращает (username, chat_id, error).
    Поддерживает: @username, числовой ID, ссылки t.me, мусорный ввод.
    """
    value = value.strip()

    # Убираем мусор вида "Chat id: -100..."
    clean = re.sub(r'^.*?(-?\d{6,}).*$', r'\1', value)
    if clean != value and clean.lstrip("-").isdigit():
        value = clean

    # Ссылка https://t.me/username или https://t.me/c/channel_id
    tme = re.match(r'https?://t\.me/c/(\d+)', value)
    if tme:
        return None, f"-100{tme.group(1)}", None

    tme = re.match(r'https?://t\.me/([a-zA-Z_]\w{3,})', value)
    if tme:
        return f"@{tme.group(1)}", None, None

    # Чистый числовой ID
    if value.lstrip("-").isdigit():
        return None, value, None

    # @username
    if re.match(r'^@?[a-zA-Z_]\w{3,}$', value):
        username = value if value.startswith("@") else f"@{value}"
        return username, None, None

    return None, None, (
        "Неверный формат. Введите:\n"
        "• @username чата\n"
        "• Числовой ID (например -1001234567890)\n"
        "• Ссылку https://t.me/username"
    )


async def chats_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "📢 *Управление чатами*\n\nВыберите действие:",
        reply_markup=chats_menu_keyboard(),
        parse_mode="Markdown"
    )


async def chat_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    db = get_db()
    chats = db.query(Chat).all()

    if not chats:
        await query.edit_message_text(
            "📢 *Чаты*\n\nСписок пуст. Добавьте первый чат.",
            reply_markup=chats_menu_keyboard(),
            parse_mode="Markdown"
        )
        return

    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton(
            f"{'✅' if c.is_active else '❌'} {c.name}",
            callback_data=f"chat_view_{c.id}"
        )] for c in chats] +
        [[InlineKeyboardButton("➕ Добавить чат", callback_data="chat_add")]] +
        [[InlineKeyboardButton("🔙 Назад", callback_data="menu_chats")]]
    )
    await query.edit_message_text("📢 *Список чатов:*", reply_markup=keyboard, parse_mode="Markdown")


async def chat_view(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = int(query.data.split("_")[-1])
    db = get_db()
    chat = db.query(Chat).get(chat_id)

    if not chat:
        await query.edit_message_text("Чат не найден.", reply_markup=back_keyboard("chat_list"))
        return

    status = "✅ Активен" if chat.is_active else "❌ Отключён"
    text = (
        f"📢 *{chat.name}*\n\n"
        f"Username: {chat.username or '—'}\n"
        f"Chat ID: {chat.chat_id or '—'}\n"
        f"Задержка: {chat.delay_seconds} сек\n"
        f"Заметка: {chat.note or '—'}\n"
        f"Статус: {status}"
    )
    await query.edit_message_text(text, reply_markup=chat_actions_keyboard(chat.id), parse_mode="Markdown")


async def chat_add_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["new_chat"] = {}
    await query.edit_message_text(
        "➕ *Добавление чата*\n\nВведите название чата (для вашего удобства):",
        parse_mode="Markdown"
    )
    return CHAT_NAME


async def chat_add_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["new_chat"]["name"] = update.message.text.strip()
    await update.message.reply_text(
        "Введите @username чата или его числовой ID:\n\n"
        "💡 Узнать ID можно через @username_to_id_bot"
    )
    return CHAT_USERNAME


async def chat_add_username(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username, chat_id, error = parse_chat_target(update.message.text)
    if error:
        await update.message.reply_text(f"❌ {error}")
        return CHAT_USERNAME
    context.user_data["new_chat"]["username"] = username
    context.user_data["new_chat"]["chat_id"] = chat_id
    await update.message.reply_text("Задержка перед отправкой в секундах (0 = без задержки):")
    return CHAT_DELAY


async def chat_add_delay(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        delay = int(update.message.text.strip())
    except ValueError:
        delay = 0
    context.user_data["new_chat"]["delay_seconds"] = delay
    await update.message.reply_text(
        "Заметка о требованиях чата (или отправьте *—* чтобы пропустить):",
        parse_mode="Markdown"
    )
    return CHAT_NOTE


async def chat_add_note(update: Update, context: ContextTypes.DEFAULT_TYPE):
    note = update.message.text.strip()
    context.user_data["new_chat"]["note"] = None if note == "—" else note
    db = get_db()
    chat = Chat(**context.user_data["new_chat"])
    db.add(chat)
    db.commit()
    await update.message.reply_text(
        f"✅ Чат *{chat.name}* добавлен!",
        reply_markup=chats_menu_keyboard(),
        parse_mode="Markdown"
    )
    return ConversationHandler.END


async def chat_delete_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = int(query.data.split("_")[-1])
    db = get_db()
    chat = db.query(Chat).get(chat_id)
    if not chat:
        await query.edit_message_text("Чат уже удалён.", reply_markup=back_keyboard("chat_list"))
        return
    await query.edit_message_text(
        f"🗑 Удалить чат *{chat.name}*? Это нельзя отменить.",
        reply_markup=confirm_keyboard(f"chat_delete_yes_{chat_id}", "chat_list"),
        parse_mode="Markdown"
    )


async def chat_delete_yes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = int(query.data.split("_")[-1])
    db = get_db()
    chat = db.query(Chat).get(chat_id)
    if chat:
        db.delete(chat)
        db.commit()
        await query.edit_message_text("✅ Чат удалён.", reply_markup=chats_menu_keyboard())
        return
    await query.edit_message_text("Чат уже удалён.", reply_markup=back_keyboard("chat_list"))


async def chat_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = int(query.data.split("_")[-1])
    context.user_data["edit_chat_id"] = chat_id
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("Название", callback_data=f"chat_editfield_name_{chat_id}")],
        [InlineKeyboardButton("Username / ID", callback_data=f"chat_editfield_username_{chat_id}")],
        [InlineKeyboardButton("Задержка (сек)", callback_data=f"chat_editfield_delay_{chat_id}")],
        [InlineKeyboardButton("Заметка", callback_data=f"chat_editfield_note_{chat_id}")],
        [InlineKeyboardButton("🔙 Назад", callback_data=f"chat_view_{chat_id}")],
    ])
    await query.edit_message_text("✏️ Что редактируем?", reply_markup=keyboard)


async def chat_editfield(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    parts = query.data.split("_")  # chat_editfield_<field>_<id>
    field = parts[2]
    chat_id = int(parts[3])
    context.user_data["edit_chat_id"] = chat_id
    context.user_data["edit_field"] = field
    labels = {"name": "название", "username": "@username или ID", "delay": "задержку в секундах", "note": "заметку"}
    hint = "\n\n💡 Узнать ID можно через @username_to_id_bot" if field == "username" else ""
    await query.edit_message_text(f"Введите новое {labels.get(field, field)}:{hint}")
    return EDIT_VALUE


async def chat_editfield_value(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = context.user_data["edit_chat_id"]
    field = context.user_data["edit_field"]
    value = update.message.text.strip()
    db = get_db()
    chat = db.query(Chat).get(chat_id)
    if not chat:
        await update.message.reply_text("Чат уже удалён.", reply_markup=chats_menu_keyboard())
        return ConversationHandler.END

    if field == "name":
        chat.name = value
    elif field == "username":
        username, chat_id, error = parse_chat_target(value)
        if error:
            await update.message.reply_text(f"❌ {error}")
            return EDIT_VALUE
        chat.username = username
        chat.chat_id = chat_id
    elif field == "delay":
        chat.delay_seconds = int(value) if value.isdigit() else 0
    elif field == "note":
        chat.note = None if value == "—" else value

    db.commit()
    await update.message.reply_text("✅ Данные обновлены!", reply_markup=chat_actions_keyboard(chat_id))
    return ConversationHandler.END


def get_chats_conversation():
    return ConversationHandler(
        entry_points=[
            CallbackQueryHandler(chat_add_start, pattern="^chat_add$"),
            CallbackQueryHandler(chat_editfield, pattern=r"^chat_editfield_\w+_\d+$"),
        ],
        states={
            CHAT_NAME:     [MessageHandler(filters.TEXT & ~filters.COMMAND, chat_add_name)],
            CHAT_USERNAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, chat_add_username)],
            CHAT_DELAY:    [MessageHandler(filters.TEXT & ~filters.COMMAND, chat_add_delay)],
            CHAT_NOTE:     [MessageHandler(filters.TEXT & ~filters.COMMAND, chat_add_note)],
            EDIT_VALUE:    [MessageHandler(filters.TEXT & ~filters.COMMAND, chat_editfield_value)],
        },
        fallbacks=[],
        per_message=False,
    )
