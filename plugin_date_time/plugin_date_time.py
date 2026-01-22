"""
Плагин: дата и время (минимальный)
Автор: mrSaT13
Репозиторий: ***https://github.com/mrSaT13/plugin_for_Irene/***
Версия: 1.0.2
"""

from irene.brain.abc import VAApiExt
import datetime

name = "date_time"
version = "1.0.2"

config = {"enabled": True}

def _say_today(va: VAApiExt, text: str):
    if not config["enabled"]:
        return
    now = datetime.datetime.now()
    weekdays = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]
    months = ["", "января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря"]
    weekday = weekdays[now.weekday()]
    month = months[now.month]
    season = "зима" if now.month in [12,1,2] else "весна" if now.month in [3,4,5] else "лето" if now.month in [6,7,8] else "осень"
    va.say(f"Сегодня {weekday}, {now.day} {month} {now.year} года ({season})")

def _say_days_to_new_year(va: VAApiExt, text: str):
    if not config["enabled"]:
        return
    now = datetime.datetime.now()
    new_year = datetime.datetime(now.year + 1, 1, 1)
    days = (new_year - now).days
    va.say(f"До Нового года осталось {days} дней")

def _say_time(va: VAApiExt, text: str):
    if not config["enabled"]:
        return
    now = datetime.datetime.now()
    va.say(f"Сейчас {now.hour}:{now.minute:02d}")

define_commands = {
    "какой сегодня день": _say_today,
    "какое сегодня число": _say_today,
    "сколько дней до нового года": _say_days_to_new_year,
    "сколько дней осталось до нового года": _say_days_to_new_year,
    "сколько времени": _say_time,
    "какое время": _say_time,
}
