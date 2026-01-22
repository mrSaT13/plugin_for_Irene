"""
Плагин: счёт (в обе стороны), поддержка прописных чисел
Говоришь:
  - «посчитай от 5» или «посчитай от пяти» → 5... 4... 3...
  - «посчитай до 3» или «посчитай до трёх» → 1... 2... 3
Автор: @MisterTA
Версия: 1.10.0
"""

from irene.brain.abc import VAApiExt
import time

name = "counter"
version = "1.10.0"

# === Настройки (в вебе) ===
config = {
    "enabled": True,
    "pause_seconds": 0.7,
    "max_number": 20,
}

config_comment = """
Счёт вперёд и назад

Автор: @MmrSaT13

Инструкция:
- «посчитай до 5» или «посчитай до пяти» → 1... 2... 3... 4... 5
- «посчитай от 8» или «посчитай от восьми» → 8... 7... 6...

Поддерживаются числа от 1 до 20 (настраивается в max_number)

- enabled: включить/выключить функцию счёта
- pause_seconds: пауза между числами (в секундах)
- max_number: максимальное число, до/от которого можно считать
"""

# === Словарь: пропись → цифра (включая падежные формы) ===
WORD_TO_NUM = {
    # 1–20
    "один": 1, "одного": 1,
    "два": 2, "двух": 2,
    "три": 3, "трех": 3,
    "четыре": 4, "четырех": 4,
    "пять": 5, "пяти": 5,
    "шесть": 6, "шести": 6,
    "семь": 7, "семи": 7,
    "восемь": 8, "восьми": 8,
    "девять": 9, "девяти": 9,
    "десять": 10, "десяти": 10,
    "одиннадцать": 11, "одиннадцати": 11,
    "двенадцать": 12, "двенадцати": 12,
    "тринадцать": 13, "тринадцати": 13,
    "четырнадцать": 14, "четырнадцати": 14,
    "пятнадцать": 15, "пятнадцати": 15,
    "шестнадцать": 16, "шестнадцати": 16,
    "семнадцать": 17, "семнадцати": 17,
    "восемнадцать": 18, "восемнадцати": 18,
    "девятнадцать": 19, "девятнадцати": 19,
    "двадцать": 20, "двадцати": 20,

    # 30–90 (десятки)
    "тридцать": 30, "тридцати": 30,
    "сорок": 40, "сорока": 40,
    "пятьдесят": 50, "пятидесяти": 50,
    "шестьдесят": 60, "шестидесяти": 60,
    "семьдесят": 70, "семидесяти": 70,
    "восемьдесят": 80, "восьмидесяти": 80,
    "девяносто": 90, "девяноста": 90,

    # 100
    "сто": 100, "ста": 100
}

def _count_down(va: VAApiExt, number: int):
    if not config["enabled"]:
        return

    if number <= 0 or number > config["max_number"]:
        va.say("Число должно быть от 1 до " + str(config["max_number"]))
        return

    for i in range(number, 0, -1):
        va.say(str(i))
        time.sleep(config["pause_seconds"])
    va.say("0")

def _count_up(va: VAApiExt, number: int):
    if not config["enabled"]:
        return

    if number <= 0 or number > config["max_number"]:
        va.say("Число должно быть от 1 до " + str(config["max_number"]))
        return

    va.say("Хорошо")
    for i in range(1, number + 1):
        va.say(str(i))

        time.sleep(config["pause_seconds"])

def _parse_number_from_text(text: str) -> int:
    """Извлекает число из фразы: 'посчитай до пяти' или 'посчитай до 5' → 5"""
    import re

    # Сначала ищем цифру
    match = re.search(r'(\d+)', text)
    if match:
        return int(match.group(1))

    # Потом ищем прописное число (включая падежи)
    for word, num in WORD_TO_NUM.items():
        if word in text:
            return num

    return 0

def _handle_count_down(va: VAApiExt, text: str):
    text_str = text.get_text() if hasattr(text, 'get_text') else text
    number = _parse_number_from_text(text_str)
    if number == 0:
        va.say("Скажите: посчитай от [число]")
        return
    _count_down(va, number)

def _handle_count_up(va: VAApiExt, text: str):
    text_str = text.get_text() if hasattr(text, 'get_text') else text
    number = _parse_number_from_text(text_str)
    if number == 0:
        va.say("Скажите: посчитай до [число]")
        return
    _count_up(va, number)

# === Генерация команд: цифры + прописные числа ===
def _build_commands():
    cmds = {}
    for n in range(1, config["max_number"] + 1):
        # Цифра: "посчитай до 5"
        cmds[f"посчитай до {n}"] = lambda va, t, num=n: _handle_count_up(va, str(num))
        cmds[f"посчитай от {n}"] = lambda va, t, num=n: _handle_count_down(va, str(num))

        # Пропись: "посчитай до пяти"
        for word, num in WORD_TO_NUM.items():
            if num == n:
                cmds[f"посчитай до {word}"] = lambda va, t, num=n: _handle_count_up(va, str(num))
                cmds[f"посчитай от {word}"] = lambda va, t, num=n: _handle_count_down(va, str(num))

    return cmds

define_commands = _build_commands()
