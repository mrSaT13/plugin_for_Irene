"""
Универсальный плагин погоды для Irene Voice Assistant
Поддерживает OpenWeather, Yandex (неофициальный) и wttr.in
Автоматически переключается между источниками при ошибках или лимитах
Все настройки — через веб-интерфейс
Автор: mrSaT13
Версия: 1.1.0
"""

from irene.brain.abc import VAApiExt
import requests
import time
import json
import os

# ==================== МЕТАИНФОРМАЦИЯ ====================
name = "weather_universal"
version = "1.1.0"

# ==================== НАСТРОЙКИ (все через веб) ====================
config = {
    # --- OpenWeather ---
    "owm_enabled": True,
    "owm_api_key": "",
    
    # --- Yandex (неофициальный) ---
    "yandex_enabled": False,
    "yandex_api_key": "",
    # Лимит 40/день — отслеживается автоматически через файл
    "yandex_quota_file": "yandex_quota.json",

    # --- wttr.in (без API) ---
    "wttr_enabled": True,
    "wttr_lang": "ru",  # 'ru' или 'en'

    # --- Общие ---
    "city": "Moscow",
    "auto_fallback": True,

    # --- Триггеры ---
    "triggers": [
        "погода",
        "какая погода",
        "скажи погоду",
        "погода сейчас",
        "что на улице"
    ],

    # --- Ответы ---
    "no_source_configured": "Ни один источник погоды не настроен",
    "all_sources_failed": "Не удалось получить погоду ни от одного источника",
    "owm_error": "Ошибка OpenWeather",
    "yandex_error": "Ошибка Yandex",
    "wttr_error": "Ошибка wttr.in",
}

config_comment = """
УНИВЕРСАЛЬНЫЙ ПЛАГИН ПОГОДЫ

ИСТОЧНИКИ:
✅ OpenWeather — до 1000 запросов/день (бесплатно). Получить ключ: https://openweathermap.org/api
✅ Yandex — ~40 запросов/день через неофициальный API (требует токен из DevTools). ⚠️ Может не работать!
✅ wttr.in — бесплатно, без ключа, но на английском (если не ru).

НАСТРОЙКИ:
- city: город на английском (Moscow, Berlin, Tokyo и т.д.)
- auto_fallback: пробовать следующий источник при ошибке
- triggers: список голосовых команд для вызова погоды
- Все источники можно включать/выключать

КВОТА YANDEX:
Используется файл yandex_quota.json для отслеживания лимита (40/день).
Файл сохраняется в папке данных Ирины (~/irene/).

ВНИМАНИЕ:
Yandex API неофициальный
"""


# ==================== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ====================

def _load_yandex_quota():
    path = os.path.join(os.environ.get("IRENE_HOME", "/irene"), config["yandex_quota_file"])
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                now = int(time.time())
                day_start = now - (now % 86400)
                if data.get("reset", 0) >= day_start:
                    return data.get("used", 0), data["reset"]
        return 0, int(time.time()) - (int(time.time()) % 86400) + 86400
    except Exception as e:
        print(f"[Weather] Ошибка загрузки квоты Yandex: {e}")
        return 0, int(time.time()) + 86400


def _save_yandex_quota(used, reset):
    path = os.path.join(os.environ.get("IRENE_HOME", "/irene"), config["yandex_quota_file"])
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"used": used, "reset": reset}, f)
    except Exception as e:
        print(f"[Weather] Ошибка сохранения квоты Yandex: {e}")


# ==================== ИСТОЧНИКИ ПОГОДЫ ====================

def _get_owm(va: VAApiExt):
    if not config["owm_enabled"] or not config["owm_api_key"]:
        return None
    try:
        r = requests.get(
            "https://api.openweathermap.org/data/2.5/weather",
            params={
                "q": config["city"],
                "appid": config["owm_api_key"],
                "lang": "ru" if config["wttr_lang"] == "ru" else "en",
                "units": "metric"
            },
            timeout=8
        )
        if r.status_code == 200:
            d = r.json()
            desc = d["weather"][0]["description"]
            temp = round(d["main"]["temp"])
            return f"{desc}, {temp}°C"
        elif r.status_code == 429:
            print("[Weather] OpenWeather: лимит исчерпан")
        return None
    except Exception as e:
        print(f"[Weather] OpenWeather ошибка: {e}")
        return None


def _get_yandex(va: VAApiExt):
    if not config["yandex_enabled"] or not config["yandex_api_key"]:
        return None

    used, reset = _load_yandex_quota()
    now = int(time.time())
    if now >= reset:
        used = 0
        reset = now - (now % 86400) + 86400

    if used >= 40:
        print("[Weather] Yandex: лимит 40/день исчерпан")
        return None

    # Для упрощения — координаты Москвы (можно заменить через GeoAPI позже)
    # В будущем можно добавить геокодинг по городу
    lat, lon = 55.7558, 37.6176

    try:
        r = requests.get(
            "https://api.weather.yandex.ru/v2/forecast",
            params={"lat": lat, "lon": lon, "limit": 1, "hours": False, "extra": False},
            headers={"X-Yandex-API-Key": config["yandex_api_key"]},
            timeout=8
        )
        if r.status_code == 200:
            _save_yandex_quota(used + 1, reset)
            fact = r.json()["fact"]
            # Условия на русском по умолчанию от Yandex
            return f"{fact['condition']}, {fact['temp']}°C"
        elif r.status_code == 429 or r.status_code == 403:
            _save_yandex_quota(40, reset)  # помечаем как исчерпанный
            print(f"[Weather] Yandex ошибка {r.status_code}")
        return None
    except Exception as e:
        print(f"[Weather] Yandex ошибка: {e}")
        return None


def _get_wttr(va: VAApiExt):
    if not config["wttr_enabled"]:
        return None
    try:
        lang = config["wttr_lang"]
        url = f"https://{lang}.wttr.in/{config['city']}?format=3"
        r = requests.get(url, timeout=10)
        if r.status_code == 200:
            return r.text.strip()
        return None
    except Exception as e:
        print(f"[Weather] wttr.in ошибка: {e}")
        return None


# ==================== ОСНОВНАЯ ФУНКЦИЯ ====================

def get_weather(va: VAApiExt, text: str):
    sources = []

    if config["owm_enabled"]:
        sources.append(("OpenWeather", lambda: _get_owm(va)))
    if config["yandex_enabled"]:
        sources.append(("Yandex", lambda: _get_yandex(va)))
    if config["wttr_enabled"]:
        sources.append(("wttr.in", lambda: _get_wttr(va)))

    if not sources:
        va.say(config["no_source_configured"])
        return

    for name_src, fetcher in sources:
        result = fetcher()
        if result:
            va.say(f"Погода в {config['city']}: {result}")
            return

    # Все источники провалились
    if config["auto_fallback"]:
        va.say(config["all_sources_failed"])
    else:
        va.say("Погода недоступна")


# ==================== КОМАНДЫ ====================

define_commands = {trigger.strip(): get_weather for trigger in config["triggers"]}
