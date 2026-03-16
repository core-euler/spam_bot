from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def main_menu_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📢 Чаты", callback_data="menu_chats")],
        [InlineKeyboardButton("✍️ Рекламные сообщения", callback_data="menu_messages")],
        [InlineKeyboardButton("🗓 Рассылки", callback_data="menu_campaigns")],
    ])


def chats_menu_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Добавить чат", callback_data="chat_add")],
        [InlineKeyboardButton("📋 Список чатов", callback_data="chat_list")],
        [InlineKeyboardButton("🔙 Главное меню", callback_data="menu_main")],
    ])


def messages_menu_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Создать сообщение", callback_data="msg_add")],
        [InlineKeyboardButton("📋 Список сообщений", callback_data="msg_list")],
        [InlineKeyboardButton("🔙 Главное меню", callback_data="menu_main")],
    ])


def campaigns_menu_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Создать рассылку", callback_data="camp_add")],
        [InlineKeyboardButton("📋 Активные рассылки", callback_data="camp_list_active")],
        [InlineKeyboardButton("⚠️ Последние ошибки", callback_data="camp_errors")],
        [InlineKeyboardButton("📜 История", callback_data="camp_list_done")],
        [InlineKeyboardButton("🔙 Главное меню", callback_data="menu_main")],
    ])


def chat_actions_keyboard(chat_id: int):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✏️ Редактировать", callback_data=f"chat_edit_{chat_id}")],
        [InlineKeyboardButton("🗑 Удалить", callback_data=f"chat_delete_{chat_id}")],
        [InlineKeyboardButton("🔙 К списку", callback_data="chat_list")],
    ])


def message_actions_keyboard(msg_id: int):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✏️ Редактировать текст", callback_data=f"msg_edit_text_{msg_id}")],
        [InlineKeyboardButton("🖼 Заменить медиа", callback_data=f"msg_edit_media_{msg_id}")],
        [InlineKeyboardButton("🗑 Удалить", callback_data=f"msg_delete_{msg_id}")],
        [InlineKeyboardButton("🔙 К списку", callback_data="msg_list")],
    ])


def campaign_actions_keyboard(camp_id: int, status: str):
    buttons = []
    if status == "active":
        buttons.append([InlineKeyboardButton("⏸ Пауза", callback_data=f"camp_pause_{camp_id}")])
    elif status == "paused":
        buttons.append([InlineKeyboardButton("▶️ Возобновить", callback_data=f"camp_resume_{camp_id}")])
    if status in ("active", "paused", "scheduled"):
        buttons.append([InlineKeyboardButton("⛔ Отменить", callback_data=f"camp_cancel_{camp_id}")])
    buttons.append([InlineKeyboardButton("🔙 К списку", callback_data="camp_list_active")])
    return InlineKeyboardMarkup(buttons)


def back_keyboard(callback: str):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 Назад", callback_data=callback)]
    ])


def confirm_keyboard(yes_callback: str, no_callback: str):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Да", callback_data=yes_callback),
            InlineKeyboardButton("❌ Нет", callback_data=no_callback),
        ]
    ])


def repeat_type_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("1️⃣ Разово", callback_data="repeat_none")],
        [InlineKeyboardButton("🕐 Каждый час", callback_data="repeat_hourly")],
        [InlineKeyboardButton("📅 Каждый день", callback_data="repeat_daily")],
        [InlineKeyboardButton("📆 Каждую неделю", callback_data="repeat_weekly")],
    ])
