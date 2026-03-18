import os
import logging
import warnings
from dotenv import load_dotenv
from telegram import Update, BotCommand
from telegram.error import BadRequest
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

warnings.filterwarnings("ignore", message=".*per_message=False.*")

from database import init_db
from keyboards import main_menu_keyboard
from scheduler import scheduler, restore_active_campaigns

from handlers.chats import (
    chats_menu, chat_list, chat_view,
    chat_delete_confirm, chat_delete_yes,
    chat_edit, get_chats_conversation
)
from handlers.messages import (
    messages_menu, msg_list, msg_view,
    msg_delete_confirm, msg_delete_yes,
    get_messages_conversation
)
from handlers.campaigns import (
    campaigns_menu, camp_list_active, camp_list_done,
    camp_detail, camp_errors,
    camp_pause, camp_resume,
    camp_cancel_confirm, camp_cancel_yes,
    get_campaigns_conversation
)

load_dotenv()
os.makedirs("data", exist_ok=True)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    handlers=[
        logging.FileHandler("data/bot.log", encoding="utf-8"),
        logging.StreamHandler(),
    ]
)


BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS = set(int(i.strip()) for i in os.getenv("ADMIN_ID", "0").split(",") if i.strip().isdigit())


def admin_only(func):
    """Декоратор: доступ только для администраторов из ADMIN_ID"""
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if user_id not in ADMIN_IDS:
            if update.callback_query:
                await update.callback_query.answer("❌ Нет доступа", show_alert=True)
            else:
                await update.message.reply_text("❌ У вас нет доступа к этому боту.")
            return
        return await func(update, context)
    return wrapper


@admin_only
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 *Добро пожаловать в бот рассылки рекламы!*\n\n"
        "Выберите раздел:",
        reply_markup=main_menu_keyboard(),
        parse_mode="Markdown"
    )


@admin_only
async def menu_main(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "👋 *Главное меню*\n\nВыберите раздел:",
        reply_markup=main_menu_keyboard(),
        parse_mode="Markdown"
    )


async def post_init(application: Application):
    await application.bot.set_my_commands([
        BotCommand("start", "Главное меню"),
    ])
    scheduler.start()
    restore_active_campaigns()
    print("✅ Планировщик запущен")


async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if isinstance(context.error, BadRequest) and "Message is not modified" in str(context.error):
        if update.callback_query:
            await update.callback_query.answer()
        return
    logging.getLogger(__name__).error("Unhandled exception:", exc_info=context.error)


def main():
    init_db()

    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()

    # ConversationHandlers — первыми
    app.add_handler(get_chats_conversation())
    app.add_handler(get_messages_conversation())
    app.add_handler(get_campaigns_conversation())

    # Команды
    app.add_handler(CommandHandler("start", start))

    # Навигация
    app.add_handler(CallbackQueryHandler(menu_main, pattern="^menu_main$"))

    # Чаты
    app.add_handler(CallbackQueryHandler(chats_menu, pattern="^menu_chats$"))
    app.add_handler(CallbackQueryHandler(chat_list, pattern="^chat_list$"))
    app.add_handler(CallbackQueryHandler(chat_view, pattern=r"^chat_view_\d+$"))
    app.add_handler(CallbackQueryHandler(chat_delete_confirm, pattern=r"^chat_delete_\d+$"))
    app.add_handler(CallbackQueryHandler(chat_delete_yes, pattern=r"^chat_delete_yes_\d+$"))
    app.add_handler(CallbackQueryHandler(chat_edit, pattern=r"^chat_edit_\d+$"))

    # Сообщения
    app.add_handler(CallbackQueryHandler(messages_menu, pattern="^menu_messages$"))
    app.add_handler(CallbackQueryHandler(msg_list, pattern="^msg_list$"))
    app.add_handler(CallbackQueryHandler(msg_view, pattern=r"^msg_view_\d+$"))
    app.add_handler(CallbackQueryHandler(msg_delete_confirm, pattern=r"^msg_delete_\d+$"))
    app.add_handler(CallbackQueryHandler(msg_delete_yes, pattern=r"^msg_delete_yes_\d+$"))

    # Рассылки
    app.add_handler(CallbackQueryHandler(campaigns_menu, pattern="^menu_campaigns$"))
    app.add_handler(CallbackQueryHandler(camp_list_active, pattern="^camp_list_active$"))
    app.add_handler(CallbackQueryHandler(camp_list_done, pattern="^camp_list_done$"))
    app.add_handler(CallbackQueryHandler(camp_detail, pattern=r"^camp_detail_\d+$"))
    app.add_handler(CallbackQueryHandler(camp_errors, pattern="^camp_errors$"))
    app.add_handler(CallbackQueryHandler(camp_pause, pattern=r"^camp_pause_\d+$"))
    app.add_handler(CallbackQueryHandler(camp_resume, pattern=r"^camp_resume_\d+$"))
    app.add_handler(CallbackQueryHandler(camp_cancel_confirm, pattern=r"^camp_cancel_\d+$"))
    app.add_handler(CallbackQueryHandler(camp_cancel_yes, pattern=r"^camp_cancel_yes_\d+$"))

    app.add_error_handler(error_handler)

    print("🤖 Бот запущен!")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
