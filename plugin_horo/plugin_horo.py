# /irene/plugins/horoscope_IRENE/plugin_horoscope_IRENE.py
"""
Плагин гороскопа — https://1001goroskop.ru
Автор: mrSaT13
Описание: Получает персонализированный гороскоп на сегодня и завтра.
Поддерживает любые формулировки: «гороскоп Скорпион», « гороскоп » и т.д.
"""

import requests
import re
from bs4 import BeautifulSoup
import random
from irene.brain.abc import VAApiExt

name = "horoscope_IRENE"
version = "1.0.0"

config = {
    "enabled": True,
    "default_sign": "taurus",  # ← английский ключ по умолчанию
    "use_intro_phrases": True,
    "timeout_sec": 8,
    "user_agent": "Irene-Voice-Assistant (+https://github.com/AlexeyBond/Irene-Voice-Assistant)",
}

config_comment = """
ГОРОСКОП НА СЕГОДНЯ -  1001goroskop.ru

Поддерживаемые команды:
- «гороскоп»
- «гороскоп Тельца»
- «гороскоп для Скорпиона»
- «гороскоп про Рака»
- «гороскоп на завтра»

❗ Важно: сайт принимает ТОЛЬКО английские названия знаков в URL.
Плагин автоматически преобразует русские названия в английские.

Параметры:
- enabled: включить/отключить плагин
- default_sign: знак по умолчанию (англ.: taurus, cancer, scorpio и т.д.)
- use_intro_phrases: добавлять вводные фразы
"""

# === МАППИНГ: русские формы → (англ. ключ, склонённая форма для речи) ===
ZODIAC_FORMS = {
    # Именительный
    "овен": ("aries", "Овна"),
    "телец": ("taurus", "Тельца"),
    "близнецы": ("gemini", "Близнецов"),
    "рак": ("cancer", "Рака"),
    "лев": ("leo", "Льва"),
    "дева": ("virgo", "Девы"),
    "весы": ("libra", "Весов"),
    "скорпион": ("scorpio", "Скорпиона"),
    "стрелец": ("sagittarius", "Стрельца"),
    "козерог": ("capricorn", "Козерога"),
    "водолей": ("aquarius", "Водолея"),
    "рыбы": ("pisces", "Рыб"),
    # Родительный
    "овна": ("aries", "Овна"),
    "тельца": ("taurus", "Тельца"),
    "близнецов": ("gemini", "Близнецов"),
    "рака": ("cancer", "Рака"),
    "льва": ("leo", "Льва"),
    "девы": ("virgo", "Девы"),
    "весов": ("libra", "Весов"),
    "скорпиона": ("scorpio", "Скорпиона"),
    "стрельца": ("sagittarius", "Стрельца"),
    "козерога": ("capricorn", "Козерога"),
    "водолея": ("aquarius", "Водолея"),
    "рыб": ("pisces", "Рыб"),
}

# Обратный словарь: англ. ключ → склонённая форма
EN_TO_SPEECH = {en: speech for (_, (en, speech)) in ZODIAC_FORMS.items()}

# Единственный триггер — всё, что начинается с "гороскоп"
_triggers = ["гороскоп"]
define_commands = {t: lambda va, txt: get_horoscope(va, txt) for t in _triggers}

def fetch_horoscope(sign_en: str, period: str = "today") -> str:
    if period == "tomorrow":
        url = f"https://1001goroskop.ru/?znak={sign_en}&kn=tomorrow"
    else:
        url = f"https://1001goroskop.ru/?znak={sign_en}"
    
    headers = {"User-Agent": config["user_agent"]}
    try:
        resp = requests.get(url, headers=headers, timeout=config["timeout_sec"])
        if resp.status_code != 200:
            return None
        soup = BeautifulSoup(resp.text, "html.parser")
        p = soup.find("p")
        if p:
            text = p.get_text(strip=True)
            if len(text) > 30 and "подписка" not in text.lower():
                return text
        return None
    except Exception as e:
        print(f"[Horoscope] Ошибка при загрузке {url}: {e}")
        return None

def get_horoscope(va: VAApiExt, text: str):
    if not config["enabled"]:
        return

    text_lower = text.lower()

    # Определяем период
    period = "tomorrow" if "завтра" in text_lower else "today"

    # Извлекаем слова
    words = re.findall(r'\b\w+\b', text_lower)

    sign_en = None
    speech_form = None

    for word in words:
        if word in ZODIAC_FORMS:
            sign_en, speech_form = ZODIAC_FORMS[word]
            break

    if sign_en is None:
        sign_en = config["default_sign"]
        speech_form = EN_TO_SPEECH.get(sign_en, "Тельца")

    horo = fetch_horoscope(sign_en, period)
    if not horo:
        va.say(random.choice([
            "Не удалось получить гороскоп. Возможно, звёзды временно недоступны.",
            "Гороскоп не отвечает. Попробуйте позже!"
        ]))
        return

    if config["use_intro_phrases"]:
        time_label = "на завтра" if period == "tomorrow" else "на сегодня"
        intro = random.choice([
            f"Звёзды подготовили для {speech_form} такой прогноз {time_label}:",
            f"Вот что говорят звёзды для {speech_form} {time_label}:",
            f"Гороскоп для {speech_form} {time_label}:",
            f"Астрологи сообщают для {speech_form} {time_label}:",
        ])
        va.say(f"{intro} {horo}")
    else:
        va.say(horo)
