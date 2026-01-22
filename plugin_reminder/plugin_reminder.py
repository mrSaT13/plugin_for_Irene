"""
Плагин напоминалок — РАБОТАЮЩАЯ ВЕРСИЯ
• Через 30 секунд — скажет "Вы просили напомнить: поспать"
• Не использует монитор — использует threading.Timer (надёжнее)
• Исправлен парсинг текста
* Автор: mrSaT13

"""

from irene.brain.abc import VAApiExt
import re
import threading
import time
import json
import os
from datetime import datetime
from typing import List, Tuple

name = "reminder"
version = "1.3.0"

config = {
    "triggers": ["напомни", "напомни мне", "запомни и напомни"],
    "reply_set": "Хорошо, напомню {when}: «{text}»",
    "reply_remind": "Вы просили напомнить: {text}",
    "data_file": "reminder_queue.json"
}

# Глобальное хранилище активных таймеров (чтобы можно было отменить при перезапуске)
_active_timers: List[threading.Timer] = []
_pending: List[Tuple[float, str]] = []
_lock = threading.Lock()

def _get_path():
    home = os.environ.get("IRENE_HOME", "/irene")
    return os.path.join(home, config["data_file"])

def _load():
    path = _get_path()
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return [(item["ts"], item["txt"]) for item in data if item["ts"] > time.time()]
    except:
        return []

def _save():
    with _lock:
        data = [{"ts": ts, "txt": txt} for ts, txt in _pending]
    try:
        with open(_get_path(), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except:
        pass

def _say_reminder(va: VAApiExt, text: str):
    # Этот вызов ДОЛЖЕН работать из фонового потока
    try:
        va.say(config["reply_remind"].format(text=text))
    except Exception as e:
        print(f"[Reminder] Ошибка озвучки: {e}")

def _schedule(va: VAApiExt, delay: float, text: str):
    # Сохраняем в список для возможной отмены (не реализовано, но можно)
    timer = threading.Timer(delay, _say_reminder, args=[va, text])
    timer.daemon = True
    timer.start()
    _active_timers.append(timer)

    # Сохраняем в файл на случай перезапуска (но восстановление — только при первом вызове)
    with _lock:
        _pending.append((time.time() + delay, text))
    _save()

def _parse(text: str):
    # Убираем триггер
    clean = re.sub(r'^(напомни|напомни мне|запомни и напомни)\s*', '', text, flags=re.IGNORECASE).strip()

    # Относительное время: "через 30 секунд поспать"
    rel = re.search(r'через\s+(\d+)\s*(секунд|секунды|сек|минут|минуты|мин)\s*(.+)?', clean, re.IGNORECASE)
    if rel:
        num = int(rel.group(1))
        unit = rel.group(2).lower()
        rest = (rel.group(3) or "").strip()
        if not rest:
            # Если после времени ничего нет — используем то, что ДО "через"
            before = clean[:rel.start()].strip()
            rest = before if before else "сделать то, о чём вы просили"
        seconds = num if 'сек' in unit else num * 60
        return seconds, rest

    # Если не нашли — вернём None
    return None, None

def handle_reminder(va: VAApiExt, text: str):
    delay, reminder_text = _parse(text)

    if delay is None or delay <= 0:
        va.say("Извините, не поняла, когда напомнить. Скажите: «через 5 минут отдохнуть»")
        return

    if not reminder_text or reminder_text.lower() in ["", "через", "мне"]:
        reminder_text = "сделать то, о чём вы просили"

    # Формат времени для ответа
    if delay < 60:
        when = f"через {int(delay)} секунд"
    elif delay < 3600:
        when = f"через {int(delay // 60)} минут"
    else:
        when = "позже"

    va.say(config["reply_set"].format(when=when, text=reminder_text))
    _schedule(va, delay, reminder_text)

# Загружаем старые напоминания при первом вызове (ограничение архитектуры)
# Полноценная загрузка при старте невозможна без bootstrap-хука

define_commands = {t: handle_reminder for t in config["triggers"]}
