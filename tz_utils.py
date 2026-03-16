"""
Утилиты для работы с часовыми поясами.
Все даты в БД хранятся в UTC.
Ввод/вывод администратору — в его локальном TZ (TIMEZONE из .env).
"""
import os
from datetime import datetime
import pytz

TIMEZONE = os.getenv("TIMEZONE", "Europe/Moscow")


def get_admin_tz() -> pytz.BaseTzInfo:
    return pytz.timezone(TIMEZONE)


def local_to_utc(dt_naive: datetime) -> datetime:
    """Перевести наивный datetime из локального TZ администратора в UTC."""
    tz = get_admin_tz()
    local_dt = tz.localize(dt_naive)
    return local_dt.astimezone(pytz.utc).replace(tzinfo=None)


def utc_to_local(dt_utc: datetime) -> datetime:
    """Перевести UTC datetime в локальный TZ администратора."""
    if dt_utc is None:
        return None
    tz = get_admin_tz()
    aware = pytz.utc.localize(dt_utc)
    return aware.astimezone(tz)


def format_local(dt_utc: datetime) -> str:
    """Форматировать UTC datetime для отображения администратору."""
    if dt_utc is None:
        return "—"
    local = utc_to_local(dt_utc)
    return local.strftime("%d.%m.%Y %H:%M") + f" ({TIMEZONE})"


def parse_admin_input(text: str) -> datetime | None:
    """
    Разобрать строку вида 'ДД.ММ.ГГГГ ЧЧ:ММ' из ввода администратора
    и вернуть UTC datetime. Возвращает None если формат неверный.
    """
    try:
        naive = datetime.strptime(text.strip(), "%d.%m.%Y %H:%M")
        return local_to_utc(naive)
    except ValueError:
        return None
