"""
Плагин: создание событий в Baikal (CalDAV) с поддержкой голоса
Версия: 1.4.0 (исправлен парсинг словесных дат)
"""

from irene.brain.abc import VAApiExt
import requests
from requests.auth import HTTPDigestAuth
from datetime import datetime, timedelta
import re

name = "baikal_events"
version = "1.4.0"

config = {
    "enabled": True,
    "baikal_url": "",
    "username": "",
    "password": "",
}

config_comment = """
Создание событий в Baikal (CalDAV)
Автор: mrSaT13
- baikal_url: CalDAV URL календаря из веб-интерфейса Baikal (обязательно с / в конце!)
- username: логин
- password: пароль
"""

# --- Словарь месяцев ---
MONTHS = {
    "января": 1, "февраля": 2, "марта": 3, "апреля": 4,
    "мая": 5, "июня": 6, "июля": 7, "августа": 8,
    "сентября": 9, "октября": 10, "ноября": 11, "декабря": 12
}

# --- Словарь словесных дат (1–31) в форме "двадцать седьмого", "первого" и т.д. ---
DAY_PHRASES = {
    "первого": 1,
    "второго": 2,
    "третьего": 3,
    "четвёртого": 4,
    "пятого": 5,
    "шестого": 6,
    "седьмого": 7,
    "восьмого": 8,
    "девятого": 9,
    "десятого": 10,
    "одиннадцатого": 11,
    "двенадцатого": 12,
    "тринадцатого": 13,
    "четырнадцатого": 14,
    "пятнадцатого": 15,
    "шестнадцатого": 16,
    "семнадцатого": 17,
    "восемнадцатого": 18,
    "девятнадцатого": 19,
    "двадцатого": 20,
    "двадцать первого": 21,
    "двадцать второго": 22,
    "двадцать третьего": 23,
    "двадцать четвёртого": 24,
    "двадцать пятого": 25,
    "двадцать шестого": 26,
    "двадцать седьмого": 27,
    "двадцать восьмого": 28,
    "двадцать девятого": 29,
    "тридцатого": 30,
    "тридцать первого": 31,
}

def _parse_date_time(text: str):
    text = text.lower().strip()

    for month_name, month_num in MONTHS.items():
        if month_name in text:
            pre_month = text.split(month_name)[0].strip()
            if not pre_month:
                return None

            day = None

            # 1. Сначала пробуем цифру
            digit_match = re.search(r'\d+', pre_month)
            if digit_match:
                day = int(digit_match.group())
            else:
                # 2. Пробуем словесные формы (в порядке убывания длины фразы)
                for phrase in sorted(DAY_PHRASES.keys(), key=lambda x: -len(x)):
                    if phrase in pre_month:
                        day = DAY_PHRASES[phrase]
                        break

            if day is not None and 1 <= day <= 31:
                year = datetime.now().year
                current = datetime.now()
                # Если дата уже прошла в этом году — переносим на следующий
                if month_num < current.month or (month_num == current.month and day < current.day):
                    year += 1
                return datetime(year, month_num, day, 12, 0)

    return None


def _create_event(va: VAApiExt, text: str):
    if not config["enabled"]:
        return

    # Удаляем оба префикса: "создай событие" и "создай новое событие"
    event_text = re.sub(r'^создай( новое)? событие\s*', '', text.lower()).strip()

    if not event_text:
        va.say("Не указано описание события")
        return

    if not all([config["baikal_url"], config["username"], config["password"]]):
        va.say("Не настроены данные Baikal")
        return

    start_dt = _parse_date_time(event_text)
    if not start_dt:
        va.say("Скажите дату, например: двадцать седьмого декабря")
        return

    # Извлекаем описание: всё до названия месяца
    summary = "Событие"
    for m in MONTHS:
        if m in event_text:
            pre_month_part = event_text.split(m)[0].strip()
            if pre_month_part:
                # Убираем из описания словесную дату, если она есть
                clean_summary = pre_month_part
                for phrase in DAY_PHRASES:
                    if phrase in clean_summary:
                        clean_summary = clean_summary.replace(phrase, "").strip()
                # Также удаляем возможные цифры в начале
                clean_summary = re.sub(r'^\d+\s*', '', clean_summary).strip()
                if clean_summary:
                    summary = clean_summary
            break

    start = start_dt.strftime("%Y%m%dT%H%M%S")
    end = (start_dt + timedelta(hours=1)).strftime("%Y%m%dT%H%M%S")
    uid = f"{datetime.now().strftime('%Y%m%dT%H%M%S%f')}@irina"

    ics = f"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Irina//Baikal//EN
BEGIN:VEVENT
UID:{uid}
DTSTAMP:{datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')}
DTSTART;TZID=Europe/Moscow:{start}
DTEND;TZID=Europe/Moscow:{end}
SUMMARY:{summary}
TRANSP:OPAQUE
END:VEVENT
END:VCALENDAR
"""

    try:
        filename = re.sub(r'[^\w\-_.]', '_', uid) + ".ics"
        url = config["baikal_url"].rstrip('/') + '/' + filename
        auth = HTTPDigestAuth(config["username"], config["password"])

        r = requests.put(
            url,
            data=ics.encode('utf-8'),
            auth=auth,
            headers={"Content-Type": "text/calendar; charset=utf-8"},
            timeout=10
        )

        if r.status_code in (200, 201, 204):
            va.say(f"Событие «{summary}» создано")
        else:
            va.say("Ошибка при создании события")
            print(f"[Baikal] HTTP {r.status_code}: {r.text}")
            print(f"[Baikal] URL: {url}")

    except Exception as e:
        va.say("Ошибка подключения к календарю")
        print(f"[Baikal] Исключение: {e}")


# Поддержка обеих команд
define_commands = {
    "создай событие": _create_event,
    "создай новое событие": _create_event,
}
