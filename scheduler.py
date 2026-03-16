import asyncio
import json
from datetime import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from database import get_db, Campaign

scheduler = AsyncIOScheduler(timezone="UTC")


async def run_campaign(campaign_id: int):
    """Выполнить рассылку (вызывается планировщиком или напрямую)."""
    from sender import send_message_to_chat, check_chat_access

    db = get_db()
    campaign = db.query(Campaign).get(campaign_id)

    if not campaign or campaign.status == "paused":
        return

    print(f"🚀 Запуск рассылки: {campaign.name}")
    success_count = 0

    for chat in campaign.chats:
        if not chat.is_active:
            continue

        # Проверка прав перед отправкой
        ok, access_error = await check_chat_access(chat)
        if not ok:
            from database import SendLog
            log = SendLog(
                campaign_id=campaign.id,
                chat_id=chat.id,
                status="failed",
                error=f"Нет доступа: {access_error}",
            )
            db.add(log)
            db.commit()
            print(f"⛔ Нет доступа [{campaign.name}] → {chat.name}: {access_error}")
            continue

        sent, _ = await send_message_to_chat(chat, campaign)
        if sent:
            success_count += 1

    campaign.last_run_at = datetime.utcnow()
    if campaign.repeat_type in (None, "none"):
        campaign.status = "done"
    db.commit()

    print(f"✅ Рассылка [{campaign.name}]: {success_count}/{len(campaign.chats)} успешно")


async def schedule_campaign(campaign: Campaign) -> bool:
    """Запланировать рассылку согласно её настройкам."""
    from sender import schedule_message_telegram
    db = get_db()
    now = datetime.utcnow()

    # --- Разовая рассылка ---
    if campaign.repeat_type in (None, "none"):
        if campaign.scheduled_at and campaign.scheduled_at > now:
            # Создаём отложенные сообщения на серверах Telegram
            msg_ids = {}
            for chat in campaign.chats:
                if chat.is_active:
                    from sender import check_chat_access
                    ok, err = await check_chat_access(chat)
                    if not ok:
                        from database import SendLog
                        log = SendLog(
                            campaign_id=campaign.id,
                            chat_id=chat.id,
                            status="failed",
                            error=f"Нет доступа при планировании: {err}",
                        )
                        db.add(log)
                        db.commit()
                        continue
                    msg_id = await schedule_message_telegram(chat, campaign, campaign.scheduled_at)
                    if msg_id:
                        msg_ids[str(chat.id)] = msg_id

            campaign.tg_scheduled_msg_ids = json.dumps(msg_ids)
            campaign.status = "scheduled"
        else:
            # Немедленная отправка
            campaign.status = "active"
            db.commit()
            await run_campaign(campaign.id)
            return True

        db.commit()
        return True

    # --- Повторяющаяся рассылка ---
    interval_kwargs = {}
    if campaign.repeat_type == "hourly":
        interval_kwargs["hours"] = campaign.repeat_interval or 1
    elif campaign.repeat_type == "daily":
        interval_kwargs["days"] = campaign.repeat_interval or 1
    elif campaign.repeat_type == "weekly":
        interval_kwargs["weeks"] = campaign.repeat_interval or 1
    else:
        return False

    scheduler.add_job(
        run_campaign,
        trigger=IntervalTrigger(**interval_kwargs),
        args=[campaign.id],
        id=f"campaign_{campaign.id}",
        replace_existing=True,
        next_run_time=campaign.scheduled_at or now,
    )

    campaign.status = "active"
    db.commit()
    return True


async def pause_campaign(campaign: Campaign):
    db = get_db()
    job_id = f"campaign_{campaign.id}"
    if scheduler.get_job(job_id):
        scheduler.pause_job(job_id)
    campaign.status = "paused"
    db.commit()


async def resume_campaign(campaign: Campaign):
    db = get_db()
    job_id = f"campaign_{campaign.id}"
    if scheduler.get_job(job_id):
        scheduler.resume_job(job_id)
    campaign.status = "active"
    db.commit()


async def cancel_campaign(campaign: Campaign):
    from sender import cancel_scheduled_message
    db = get_db()

    job_id = f"campaign_{campaign.id}"
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)

    if campaign.tg_scheduled_msg_ids:
        msg_ids = json.loads(campaign.tg_scheduled_msg_ids)
        for chat in campaign.chats:
            chat_key = str(chat.id)
            if chat_key in msg_ids:
                await cancel_scheduled_message(chat, int(msg_ids[chat_key]))

    campaign.status = "cancelled"
    campaign.tg_scheduled_msg_ids = None
    db.commit()


def restore_active_campaigns():
    """Восстановить повторяющиеся рассылки после перезапуска бота."""
    db = get_db()
    active = db.query(Campaign).filter(
        Campaign.status == "active",
        Campaign.repeat_type.notin_(["none", None])
    ).all()

    for campaign in active:
        interval_kwargs = {}
        if campaign.repeat_type == "hourly":
            interval_kwargs["hours"] = campaign.repeat_interval or 1
        elif campaign.repeat_type == "daily":
            interval_kwargs["days"] = campaign.repeat_interval or 1
        elif campaign.repeat_type == "weekly":
            interval_kwargs["weeks"] = campaign.repeat_interval or 1
        else:
            continue

        scheduler.add_job(
            run_campaign,
            trigger=IntervalTrigger(**interval_kwargs),
            args=[campaign.id],
            id=f"campaign_{campaign.id}",
            replace_existing=True,
        )
        print(f"♻️ Восстановлена рассылка: {campaign.name}")
