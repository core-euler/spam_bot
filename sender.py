import asyncio
import logging
import os
from datetime import datetime
from telethon import TelegramClient
from telethon.tl.types import PeerChannel, PeerChat
from telethon.errors import FloodWaitError, ChatWriteForbiddenError, UserNotParticipantError
from database import get_db, SendLog

API_ID = int(os.getenv("API_ID", 0))
API_HASH = os.getenv("API_HASH", "")
PHONE_NUMBER = os.getenv("PHONE_NUMBER", "")
MAX_RETRIES = int(os.getenv("MAX_RETRIES", 3))

telethon_client: TelegramClient = None
logger = logging.getLogger(__name__)


def _mask_phone(phone: str) -> str:
    if len(phone) < 4:
        return "***"
    return f"{phone[:3]}***{phone[-2:]}"


async def get_telethon_client() -> TelegramClient:
    global telethon_client
    if telethon_client is None or not telethon_client.is_connected():
        session_base = os.path.abspath("data/session")
        session_file = f"{session_base}.session"
        logger.info(
            "Initializing Telethon client: session=%s exists=%s phone=%s api_id=%s",
            session_file,
            os.path.exists(session_file),
            _mask_phone(PHONE_NUMBER),
            API_ID,
        )
        telethon_client = TelegramClient("data/session", API_ID, API_HASH)
        try:
            await telethon_client.start(phone=PHONE_NUMBER)
            logger.info(
                "Telethon client started: authorized=%s",
                await telethon_client.is_user_authorized(),
            )
        except EOFError as exc:
            logger.exception(
                "Telethon requested interactive input while starting. "
                "The session is likely missing, expired, or requires re-login."
            )
            telethon_client = None
            raise RuntimeError(
                "Telethon session is missing or expired; interactive login is required on the server"
            ) from exc
        except Exception:
            logger.exception("Failed to start Telethon client")
            telethon_client = None
            raise
    return telethon_client


def resolve_target(chat):
    """Получить правильный target для Telethon из объекта Chat."""
    if chat.username:
        return chat.username
    raw_id = int(chat.chat_id)
    # Каналы/супергруппы: -100XXXXXXXXXX
    if raw_id < -1000000000000:
        return PeerChannel(channel_id=int(str(raw_id)[4:]))
    # Обычные группы: отрицательный ID
    if raw_id < 0:
        return PeerChat(chat_id=-raw_id)
    return raw_id


async def check_chat_access(chat) -> tuple[bool, str | None]:
    """
    Проверить, что Telethon-аккаунт имеет право писать в чат.
    Возвращает (ok, error_text).
    """
    try:
        client = await get_telethon_client()
        target = resolve_target(chat)
        logger.info(
            "Checking chat access: chat_id=%s name=%s username=%s target=%r",
            chat.id,
            chat.name,
            chat.username,
            target,
        )
        entity = await client.get_entity(target)
        # Попытка получить права — если чат недоступен, упадёт исключение
        await client.get_permissions(entity)
        return True, None
    except ChatWriteForbiddenError:
        logger.warning("Chat write forbidden: chat_id=%s name=%s", chat.id, chat.name)
        return False, "Нет права на отправку сообщений"
    except UserNotParticipantError:
        logger.warning("User not participant: chat_id=%s name=%s", chat.id, chat.name)
        return False, "Аккаунт не является участником чата"
    except Exception as e:
        logger.exception(
            "Unexpected error while checking chat access: chat_id=%s name=%s username=%s chat_db_id=%s",
            getattr(chat, "chat_id", None),
            getattr(chat, "name", None),
            getattr(chat, "username", None),
            getattr(chat, "id", None),
        )
        return False, str(e)


async def send_message_to_chat(chat, campaign) -> tuple[bool, str | None]:
    """
    Отправить сообщение в чат с retry при FloodWait.
    Возвращает (success, error_text).
    Записывает результат в send_logs.
    """
    db = get_db()
    msg = campaign.ad_message
    target = resolve_target(chat)
    campaign_name = campaign.name
    campaign_id = campaign.id
    chat_name = chat.name
    chat_id = chat.id

    try:
        if chat.delay_seconds and chat.delay_seconds > 0:
            await asyncio.sleep(chat.delay_seconds)

        last_error = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                client = await get_telethon_client()

                if msg.media_file_id:
                    await client.send_file(
                        target,
                        file=msg.media_file_id,
                        caption=msg.text,
                        parse_mode=msg.parse_mode.lower(),
                    )
                else:
                    await client.send_message(
                        target,
                        msg.text,
                        parse_mode=msg.parse_mode.lower(),
                    )

                log = SendLog(campaign_id=campaign_id, chat_id=chat_id, status="sent")
                db.add(log)
                db.commit()
                logger.info("Message sent: campaign=%s chat=%s", campaign_name, chat_name)
                return True, None

            except FloodWaitError as e:
                last_error = f"FloodWait {e.seconds}s (попытка {attempt}/{MAX_RETRIES})"
                logger.warning(
                    "FloodWait during send: campaign=%s chat=%s wait=%ss attempt=%s/%s",
                    campaign_name,
                    chat_name,
                    e.seconds,
                    attempt,
                    MAX_RETRIES,
                )
                await asyncio.sleep(e.seconds)

            except Exception as e:
                last_error = str(e)
                logger.exception(
                    "Send attempt failed: campaign=%s chat=%s attempt=%s/%s",
                    campaign_name,
                    chat_name,
                    attempt,
                    MAX_RETRIES,
                )
                if attempt < MAX_RETRIES:
                    await asyncio.sleep(3)

        log = SendLog(
            campaign_id=campaign_id,
            chat_id=chat_id,
            status="failed",
            error=last_error,
        )
        db.add(log)
        db.commit()
        return False, last_error
    finally:
        db.close()


async def schedule_message_telegram(chat, campaign, send_at: datetime) -> str | None:
    """
    Создать отложенное сообщение на серверах Telegram.
    Возвращает ID запланированного сообщения или None при ошибке.
    """
    db = get_db()
    msg = campaign.ad_message
    target = resolve_target(chat)
    campaign_name = campaign.name
    campaign_id = campaign.id
    chat_name = chat.name
    chat_id = chat.id

    try:
        client = await get_telethon_client()

        if msg.media_file_id:
            result = await client.send_file(
                target,
                file=msg.media_file_id,
                caption=msg.text,
                parse_mode=msg.parse_mode.lower(),
                schedule=send_at,
            )
        else:
            result = await client.send_message(
                target,
                msg.text,
                parse_mode=msg.parse_mode.lower(),
                schedule=send_at,
            )

        logger.info(
            "Telegram scheduled message created: campaign=%s chat=%s send_at=%s message_id=%s",
            campaign_name,
            chat_name,
            send_at,
            result.id,
        )
        return str(result.id)

    except Exception as e:
        log = SendLog(
            campaign_id=campaign_id,
            chat_id=chat_id,
            status="failed",
            error=f"Ошибка планирования: {e}",
        )
        db.add(log)
        db.commit()
        logger.exception(
            "Failed to create Telegram scheduled message: campaign=%s chat=%s send_at=%s",
            campaign_name,
            chat_name,
            send_at,
        )
        return None
    finally:
        db.close()


async def cancel_scheduled_message(chat, message_id: int) -> bool:
    try:
        client = await get_telethon_client()
        target = resolve_target(chat)
        await client.delete_messages(target, [message_id], revoke=True)
        logger.info("Scheduled message cancelled: chat=%s message_id=%s", chat.name, message_id)
        return True
    except Exception:
        logger.exception(
            "Failed to cancel scheduled message: chat_id=%s name=%s message_id=%s",
            chat.id,
            chat.name,
            message_id,
        )
        return False
