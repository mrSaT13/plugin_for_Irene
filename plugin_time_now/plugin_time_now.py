"""
Плагин времени — говорит время по-человечески
Автор mrSaT13
репозиторий **https://github.com/mrSaT13/plugin_for_Irene**
"""

from irene.brain.abc import VAApiExt
from datetime import datetime

name = "time_now"
version = "1.2.1"

config = {
    "enabled": True,
    "reply": "Сейчас {time}",
    "triggers": ["который час", "сколько время", "время сейчас", "скажи время"]
}

config_comment = """
Плагин времени — говорит "четырнадцать часов девять минут"

- enabled: включить/выключить
- reply: шаблон ответа
- triggers: фразы, на которые отвечает плагин (не используй "время" или "час")
"""

def _format_time_human(hour: int, minute: int) -> str:
    nums = [
        "ноль", "один", "два", "три", "четыре", "пять", "шесть", "семь", "восемь", "девять",
        "десять", "одиннадцать", "двенадцать", "тринадцать", "четырнадцать", "пятнадцать",
        "шестнадцать", "семнадцать", "восемнадцать", "девятнадцать", "двадцать",
        "двадцать один", "двадцать два", "двадцать три", "двадцать четыре", "двадцать пять",
        "двадцать шесть", "двадцать семь", "двадцать восемь", "двадцать девять", "тридцать",
        "тридцать один", "тридцать два", "тридцать три", "тридцать четыре", "тридцать пять",
        "тридцать шесть", "тридцать семь", "тридцать восемь", "тридцать девять", "сорок",
        "сорок один", "сорок два", "сорок три", "сорок четыре", "сорок пять",
        "сорок шесть", "сорок семь", "сорок восемь", "сорок девять", "пятьдесят",
        "пятьдесят один", "пятьдесят два", "пятьдесят три", "пятьдесят четыре", "пятьдесят пять",
        "пятьдесят шесть", "пятьдесят семь", "пятьдесят восемь", "пятьдесят девять"
    ]

    hour_str = nums[hour]
    minute_str = nums[minute]

    if minute == 0:
        return f"{hour_str} часов ровно"
    else:
        return f"{hour_str} часов {minute_str} минут"

def say_time(va: VAApiExt, text: str):
    if not config["enabled"]:
        return

    now = datetime.now()
    hour = now.hour
    minute = now.minute

    time_str = _format_time_human(hour, minute)
    response = config["reply"].format(time=time_str)
    va.say(response)

define_commands = {trigger: say_time for trigger in config["triggers"]}
