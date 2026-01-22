# /irene/plugins/universal_news/plugin_universal_news.py
"""
Универсальный плагин новостей v1.0
• Основной источник: RSS Mail.ru
• Дополнительно: WorldNewsAPI, локальный FreshRSS
• Все настройки — через веб-интерфейс

Автор: mrSaT13
Репозиторий: ***https://github.com/mrSaT13/plugin_for_Irene***
"""

from irene.brain.abc import VAApiExt
import requests
import xml.etree.ElementTree as ET
import re
from datetime import datetime

name = "universal_news"
version = "1.0.0"

config = {
    # --- Общие ---
    "enabled": True,
    "max_headlines": 7,
    "triggers": ["новости", "расскажи новости", "какие новости", "прочитай новости"],

    # --- Mail.ru RSS (основной, всегда включён) ---
    "mail_ru_rss_url": "https://news.mail.ru/rss/98/",

    # --- WorldNewsAPI (опционально) ---
    "worldnewsapi_enabled": False,
    "worldnewsapi_key": "",
    "worldnewsapi_url": "https://api.worldnewsapi.com/top-news",

    # --- Локальный FreshRSS (опционально) ---
    "freshrss_enabled": False,
    "freshrss_api_url": "http://127.0.0.1:8880/api/greader.php",
    "freshrss_username": "",
    "freshrss_password": "",

    # --- Ответы ---
    "reply_fetching": "Сейчас подготовлю сводку новостей...",
    "reply_empty": "Свежих новостей пока нет.",
    "reply_error": "Не удалось получить новости. Проверьте настройки и интернет."
}

config_comment = """
УНИВЕРСАЛЬНЫЙ ПЛАГИН НОВОСТЕЙ v1.0
Автор: mrSaT13
Репозиторий: ***https://github.com/mrSaT13/plugin_for_Irene***
ИСТОЧНИКИ:
✅ Mail.ru RSS — основной, работает без ключа
✅ WorldNewsAPI — опционально (требуется ключ)
✅ FreshRSS — локальный сервер (требует IP, логин/пароль)

НАСТРОЙКИ:
- mail_ru_rss_url: URL RSS-ленты (не меняйте без необходимости)
- worldnewsapi_enabled: включить WorldNewsAPI
- worldnewsapi_key: ваш ключ с https://worldnewsapi.com  
- freshrss_enabled: включить локальный FreshRSS
- freshrss_api_url: адрес API (обычно http://IP:8880/api/greader.php)
- freshrss_username / password: учётные данные FreshRSS

РЕКОМЕНДАЦИИ:
- Если все источники отключены — будет использоваться только Mail.ru
"""


def _fetch_mail_ru() -> list:
    """Получает заголовки из RSS Mail.ru."""
    try:
        resp = requests.get(config["mail_ru_rss_url"], timeout=8)
        if resp.status_code != 200:
            return []
        root = ET.fromstring(resp.content)
        headlines = []
        for item in root.findall(".//item"):
            title = item.find("title")
            if title is not None and title.text:
                text = title.text.strip()
                if text and len(text) > 15:
                    headlines.append(text)
        return headlines
    except Exception as e:
        print(f"[News] Mail.ru RSS error: {e}")
        return []


def _fetch_worldnews() -> list:
    """Получает новости из WorldNewsAPI."""
    if not config["worldnewsapi_enabled"] or not config["worldnewsapi_key"]:
        return []
    try:
        headers = {"User-Agent": "Irene-Universal-News/1.0"}
        params = {
            "source-country": "ru",
            "language": "ru",
            "api-key": config["worldnewsapi_key"],
            "number": config["max_headlines"] * 2
        }
        resp = requests.get(config["worldnewsapi_url"], headers=headers, params=params, timeout=10)
        if resp.status_code != 200:
            return []
        data = resp.json()
        seen = set()
        headlines = []
        for group in data.get("top_news", []):
            if not group.get("news"):
                continue
            title = group["news"][0].get("title", "").strip()
            if not title:
                continue
            clean_title = re.sub(r'\s*\(\d+\s+sources?\)$', '', title)
            key = clean_title[:30].lower()
            if key not in seen:
                seen.add(key)
                headlines.append(clean_title)
                if len(headlines) >= config["max_headlines"]:
                    break
        return headlines
    except Exception as e:
        print(f"[News] WorldNewsAPI error: {e}")
        return []


def _fetch_freshrss() -> list:
    """Получает новости из локального FreshRSS (GReader API)."""
    if not config["freshrss_enabled"] or not config["freshrss_api_url"]:
        return []
    try:
        auth = None
        if config["freshrss_username"] and config["freshrss_password"]:
            auth = (config["freshrss_username"], config["freshrss_password"])
        params = {
            "output": "json",
            "n": config["max_headlines"]
        }
        resp = requests.get(
            config["freshrss_api_url"],
            params=params,
            auth=auth,
            timeout=8
        )
        if resp.status_code != 200:
            return []
        data = resp.json()
        headlines = []
        for item in data.get("items", []):
            title = item.get("title", "").strip()
            if title and len(title) > 15:
                headlines.append(title)
                if len(headlines) >= config["max_headlines"]:
                    break
        return headlines
    except Exception as e:
        print(f"[News] FreshRSS error: {e}")
        return []


def read_news(va: VAApiExt, text: str):
    if not config.get("enabled", True):
        return

    va.say(config["reply_fetching"])

    all_headlines = []

    # Сначала основной источник
    all_headlines.extend(_fetch_mail_ru())

    # Затем опциональные
    if config["worldnewsapi_enabled"]:
        all_headlines.extend(_fetch_worldnews())
    if config["freshrss_enabled"]:
        all_headlines.extend(_fetch_freshrss())

    # Убираем дубли по первым 30 символам
    seen = set()
    unique_headlines = []
    for title in all_headlines:
        key = title[:30].lower()
        if key not in seen:
            seen.add(key)
            unique_headlines.append(title)
            if len(unique_headlines) >= config["max_headlines"]:
                break

    if not unique_headlines:
        va.say(config["reply_empty"])
        return

    # Формируем дату
    now = datetime.now()
    month_names = ["", "января", "февраля", "марта", "апреля", "мая", "июня",
                   "июля", "августа", "сентября", "октября", "ноября", "декабря"]
    date_str = f"{now.day} {month_names[now.month]}"

    # Живые вводные фразы
    intro_phrases = [
        "Слушайте первую новость: {}.",
        "А вот что ещё произошло: {}.",
        "Также стало известно, что {}.",
        "Между тем, {}.",
        "Ещё одна важная новость: {}.",
        "На международной арене: {}.",
        "Интересное событие: {}."
    ]

    parts = [f"Добрый день! Сводка новостей на {date_str}."]
    for i, title in enumerate(unique_headlines):
        phrase = intro_phrases[i % len(intro_phrases)]
        parts.append(phrase.format(title))
    parts.append("Вот такие новости на сегодня. Спасибо, что остаётесь с нами!")

    va.say(" ".join(parts))


define_commands = {trigger: read_news for trigger in config["triggers"]}
