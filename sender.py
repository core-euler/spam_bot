import asyncio
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


async def get_telethon_client() -> TelegramClient:
    global telethon_client
    if telethon_client is None or not telethon_client.is_connected():
        telethon_client = TelegramClient("data/session", API_ID, API_HASH)
        await telethon_client.start(phone=PHONE_NUMBER)
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
        entity = await client.get_entity(target)
        # Попытка получить права — если чат недоступен, упадёт исключение
        await client.get_permissions(entity)
        return True, None
    except ChatWriteForbiddenError:
        return False, "Нет права на отправку сообщений"
    except UserNotParticipantError:
        return False, "Аккаунт не является участником чата"
    except Exception as e:
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

            # Успех — пишем в лог
            log = SendLog(campaign_id=campaign.id, chat_id=chat.id, status="sent")
            db.add(log)
            db.commit()
            print(f"✅ [{campaign.name}] → {chat.name}")
            return True, None

        except FloodWaitError as e:
            last_error = f"FloodWait {e.seconds}s (попытка {attempt}/{MAX_RETRIES})"
            print(f"⏳ {last_error} — чат {chat.name}")
            await asyncio.sleep(e.seconds)

        except Exception as e:
            last_error = str(e)
            print(f"❌ [{campaign.name}] → {chat.name}: {last_error} (попытка {attempt}/{MAX_RETRIES})")
            if attempt < MAX_RETRIES:
                await asyncio.sleep(3)

    # Все попытки исчерпаны — пишем failed в лог
    log = SendLog(
        campaign_id=campaign.id,
        chat_id=chat.id,
        status="failed",
        error=last_error,
    )
    db.add(log)
    db.commit()
    return False, last_error


async def schedule_message_telegram(chat, campaign, send_at: datetime) -> str | None:
    """
    Создать отложенное сообщение на серверах Telegram.
    Возвращает ID запланированного сообщения или None при ошибке.
    """
    db = get_db()
    msg = campaign.ad_message
    target = resolve_target(chat)

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

        print(f"🕐 Запланировано [{campaign.name}] → {chat.name} на {send_at}")
        return str(result.id)

    except Exception as e:
        log = SendLog(
            campaign_id=campaign.id,
            chat_id=chat.id,
            status="failed",
            error=f"Ошибка планирования: {e}",
        )
        db.add(log)
        db.commit()
        print(f"❌ Ошибка планирования [{campaign.name}] → {chat.name}: {e}")
        return None


async def cancel_scheduled_message(chat, message_id: int) -> bool:
    try:
        client = await get_telethon_client()
        target = resolve_target(chat)
        await client.delete_messages(target, [message_id], revoke=True)
        return True
    except Exception as e:
        print(f"❌ Ошибка отмены сообщения: {e}")
        return False
