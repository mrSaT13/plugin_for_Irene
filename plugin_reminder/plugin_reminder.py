"""
Плагин напоминалок для Irene Voice Assistant
Поддерживает команды вида: "напомни через 5 минут отдохнуть"
Автор: mrSaT13  
https://github.com/mrSaT13/plugin_for_Irene
"""

from irene.brain.abc import VAApiExt
import re
import threading
import time

name = "reminder"
version = "1.0.0"

config = {
    "triggers": [
        "напомни",
        "напомни мне",
        "запомни и напомни"
    ],
    "reply_set": "Хорошо, напомню через {duration} {unit}: «{text}»",
    "reply_remind": "Вы просили напомнить: {text}",
    "enable_debug": False
}

config_comment = """
Плагин напоминаний

РАСПОЗНАВАЕТ КОМАНДЫ ВИДА:
- «напомни через 5 минут отдохнуть»
- «напомни через 30 секунд проверить чайник»

ПОДДЕРЖИВАЕТСЯ:
- секунды, минуты (только целые числа)
- любой текст после указания времени

НАСТРОЙКИ:
- triggers: фразы-триггеры
- reply_set: ответ при установке напоминания
- reply_remind: текст при напоминании
- enable_debug: печатать подробности в лог
"""


def _parse_duration(text: str):
    """
    Извлекает из текста "через X минут/секунд ..."
    Возвращает (секунды, оставшийся_текст_напоминания) или (None, None)
    """
    match = re.search(r'через\s+(\d+)\s*(секунд|секунды|сек|минут|минуты|мин)', text, re.IGNORECASE)
    if not match:
        return None, None

    num = int(match.group(1))
    unit = match.group(2).lower()

    if "сек" in unit:
        seconds = num
    elif "мин" in unit:
        seconds = num * 60
    else:
        return None, None

    # Обрезаем часть с "через ...", оставляем только напоминание
    reminder_text = text[match.end():].strip()
    if not reminder_text:
        reminder_text = "сделать то, о чём вы просили"

    return seconds, reminder_text


def _do_reminder(va: VAApiExt, text: str):
    """Фоновая функция напоминания"""
    def worker():
        va.say(config["reply_remind"].format(text=text))

    # Запускаем в отдельном потоке, чтобы не мешать основному циклу
    threading.Thread(target=worker, daemon=True).start()


def handle_reminder(va: VAApiExt, text: str):
    full_text = text.lower()
    seconds, reminder_text = _parse_duration(full_text)

    if seconds is None:
        # Можно добавить поддержку "завтра в 9:00" позже
        va.say("Извините, я понимаю только напоминания вида «через X минут/секунд»")
        return

    if config["enable_debug"]:
        print(f"[Reminder] Запланировано через {seconds} сек: {reminder_text}")

    # Ответ пользователю
    unit = "минуту" if seconds // 60 == 1 else "минут" if seconds >= 60 else "секунд"
    if seconds < 60 and seconds % 10 == 1 and seconds != 11:
        unit = "секунду"
    elif seconds < 60 and seconds % 10 in (2, 3, 4) and seconds not in (12, 13, 14):
        unit = "секунды"

    duration = seconds // 60 if seconds >= 60 else seconds
    va.say(config["reply_set"].format(
        duration=duration,
        unit=unit,
        text=reminder_text
    ))

    # Запускаем отложенный вызов
    def delayed():
        time.sleep(seconds)
        _do_reminder(va, reminder_text)

    threading.Thread(target=delayed, daemon=True).start()


# Формируем словарь команд
define_commands = {}
for trigger in config["triggers"]:
    # Поддерживаем полные фразы вида "напомни через ..."
    # Но так как Ирина передаёт ПОЛНУЮ распознанную фразу,
    # мы просто назначаем одну функцию на все триггеры
    define_commands[trigger] = handle_reminder

# Дополнительно: можно добавить "напомни через" как отдельный триггер,
# но это не обязательно — функция сама парсит текст.
