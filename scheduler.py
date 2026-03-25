import asyncio
import json
from datetime import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from database import get_db, Campaign

scheduler = AsyncIOScheduler(timezone="UTC")


def _campaign_id(campaign_or_id) -> int | None:
    if isinstance(campaign_or_id, int):
        return campaign_or_id
    return getattr(campaign_or_id, "id", None)


async def run_campaign(campaign_id: int):
    """Выполнить рассылку (вызывается планировщиком или напрямую)."""
    from sender import send_message_to_chat, check_chat_access
    from database import SendLog

    db = get_db()
    try:
        campaign = db.get(Campaign, campaign_id)
        if not campaign or campaign.status in {"paused", "cancelled"}:
            return

        campaign_name = campaign.name
        repeat_type = campaign.repeat_type
        chats = [chat for chat in campaign.chats if chat.is_active]
        if not campaign.ad_message:
            for chat in chats:
                db.add(SendLog(
                    campaign_id=campaign_id,
                    chat_id=chat.id,
                    status="failed",
                    error="У рассылки не привязано рекламное сообщение",
                ))
            campaign.status = "cancelled"
            campaign.last_run_at = datetime.utcnow()
            db.commit()
            print(f"⛔ Рассылка [{campaign_name}] отменена: нет рекламного сообщения")
            return
        print(f"🚀 Запуск рассылки: {campaign_name}")
        success_count = 0

        for chat in chats:
            current_campaign = db.get(Campaign, campaign_id)
            if not current_campaign or current_campaign.status in {"paused", "cancelled"}:
                print(f"⏹ Рассылка [{campaign_name}] остановлена во время выполнения")
                return

            chat_name = chat.name
            ok, access_error = await check_chat_access(chat)
            if not ok:
                log = SendLog(
                    campaign_id=campaign_id,
                    chat_id=chat.id,
                    status="failed",
                    error=f"Нет доступа: {access_error}",
                )
                db.add(log)
                db.commit()
                print(f"⛔ Нет доступа [{campaign_name}] → {chat_name}: {access_error}")
                continue

            sent, _ = await send_message_to_chat(chat, current_campaign)
            if sent:
                success_count += 1

        campaign_to_update = db.get(Campaign, campaign_id)
        if not campaign_to_update:
            print(f"ℹ️ Рассылка [{campaign_name}] уже удалена, статус не обновляю")
            return

        campaign_to_update.last_run_at = datetime.utcnow()
        if repeat_type in (None, "none"):
            campaign_to_update.status = "done"
        db.commit()

        print(f"✅ Рассылка [{campaign_name}]: {success_count}/{len(chats)} успешно")
    finally:
        db.close()


async def schedule_campaign(campaign_or_id) -> bool:
    """Запланировать рассылку согласно её настройкам."""
    from sender import schedule_message_telegram
    from sender import check_chat_access
    from database import SendLog

    campaign_id = _campaign_id(campaign_or_id)
    if campaign_id is None:
        return False

    db = get_db()
    now = datetime.utcnow()

    try:
        campaign = db.get(Campaign, campaign_id)
        if not campaign:
            return False
        if not campaign.ad_message:
            chats = [chat for chat in campaign.chats if chat.is_active]
            for chat in chats:
                db.add(SendLog(
                    campaign_id=campaign.id,
                    chat_id=chat.id,
                    status="failed",
                    error="Невозможно запланировать: у рассылки нет рекламного сообщения",
                ))
            campaign.status = "cancelled"
            db.commit()
            print(f"⛔ Рассылка [{campaign.name}] отменена при планировании: нет рекламного сообщения")
            return False

        # --- Разовая рассылка ---
        if campaign.repeat_type in (None, "none"):
            if campaign.scheduled_at and campaign.scheduled_at > now:
                msg_ids = {}
                for chat in campaign.chats:
                    if not chat.is_active:
                        continue

                    ok, err = await check_chat_access(chat)
                    if not ok:
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
                campaign.status = "active"
                db.commit()
                await run_campaign(campaign.id)
                return True

            db.commit()
            return True

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
    finally:
        db.close()


async def pause_campaign(campaign_or_id) -> bool:
    campaign_id = _campaign_id(campaign_or_id)
    if campaign_id is None:
        return False

    db = get_db()
    try:
        campaign = db.get(Campaign, campaign_id)
        if not campaign:
            return False

        job_id = f"campaign_{campaign.id}"
        if scheduler.get_job(job_id):
            scheduler.pause_job(job_id)
        campaign.status = "paused"
        db.commit()
        return True
    finally:
        db.close()


async def resume_campaign(campaign_or_id) -> bool:
    campaign_id = _campaign_id(campaign_or_id)
    if campaign_id is None:
        return False

    db = get_db()
    try:
        campaign = db.get(Campaign, campaign_id)
        if not campaign:
            return False

        job_id = f"campaign_{campaign.id}"
        if scheduler.get_job(job_id):
            scheduler.resume_job(job_id)
        campaign.status = "active"
        db.commit()
        return True
    finally:
        db.close()


async def cancel_campaign(campaign_or_id) -> bool:
    from sender import cancel_scheduled_message
    campaign_id = _campaign_id(campaign_or_id)
    if campaign_id is None:
        return False

    db = get_db()
    try:
        campaign = db.get(Campaign, campaign_id)
        if not campaign:
            return False

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
        return True
    finally:
        db.close()


def restore_active_campaigns():
    """Восстановить повторяющиеся рассылки после перезапуска бота."""
    db = get_db()
    try:
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
    finally:
        db.close()
