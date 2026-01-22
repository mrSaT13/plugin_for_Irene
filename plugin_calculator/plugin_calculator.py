"""
Плагин: калькулятор и счёт по шагам
Умеет:
- Складывать, вычитать, умножать, делить
- Считать по шагам (до 10 через 2)
- Решать простые примеры с несколькими действиями
- Поддержка прописных чисел: "десять плюс пять"
Автор: mrSaT13
Версия: 1.1.0
"""

from irene.brain.abc import VAApiExt
import re

name = "calculator"
version = "1.1.0"

# === Настройки (в вебе) ===
config = {
    "enabled": True,
    "max_number": 1000,
    "max_result": 10000,
}

config_comment = """
Калькулятор и счёт по шагам

- enabled: включить/выключить калькулятор
- max_number: максимальное число в расчётах
- max_result: максимальный результат (чтобы не считать до 1000000)
"""

# === Словарь: пропись → цифра (для калькулятора) ===
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

def _text_to_number(text: str) -> float:
    """Преобразует текст в число: 'десять' → 10"""
    import re
    # Сначала ищем цифру
    match = re.search(r'(\d+(?:\.\d+)?)', text)
    if match:
        return float(match.group(1))

    # Потом ищем прописное число (включая падежи)
    for word, num in WORD_TO_NUM.items():
        if word in text:
            return float(num)

    return None

def _parse_expression(text: str):
    """Разбирает выражение: 'десять плюс пять и минус три' → [10, '+', 5, '-', 3]"""
    # Заменим прописные числа на цифры
    text = text.lower()
    for word, num in WORD_TO_NUM.items():
        text = text.replace(word, str(num))

    # Заменим операции на символы
    text = text.replace("плюс", "+").replace("минус", "-").replace("умножить на", "*").replace("разделить на", "/").replace("x", "*")

    # Извлечём числа и операции
    tokens = re.split(r'(\+|\-|\*|\/|\s+и\s+)', text)
    tokens = [t.strip() for t in tokens if t.strip()]

    # Соберём выражение: [число, операция, число, ...]
    expr = []
    for token in tokens:
        if token in ['+', '-', '*', '/', 'и']:
            expr.append(token)
        else:
            try:
                num = float(token)
                expr.append(num)
            except:
                pass

    return expr

def _calculate_expression(expr):
    """Вычисляет выражение вида [10, '+', 5, '-', 3] → 12"""
    if not expr:
        return None

    # Сначала обработаем "и" как продолжение операции
    # Например: [10, '+', 5, 'и', '-', 3] → [10, '+', 5, '-', 3]
    new_expr = []
    i = 0
    while i < len(expr):
        if expr[i] == 'и':
            # Пропускаем "и"
            i += 1
            continue
        new_expr.append(expr[i])
        i += 1

    # Теперь вычисляем по порядку: 10 + 5 - 3 = 12
    result = new_expr[0]
    i = 1
    while i < len(new_expr):
        op = new_expr[i]
        num = new_expr[i + 1]
        if op == '+':
            result += num
        elif op == '-':
            result -= num
        elif op == '*':
            result *= num
        elif op == '/':
            if num == 0:
                return "zero_divide"
            result /= num
        i += 2

    return result

def _calculate(va: VAApiExt, text: str):
    if not config["enabled"]:
        return

    text = text.lower().strip()

    # === Счёт по шагам: "посчитай до 10 через 2" ===
    step_match = re.search(r'посчитай до (\d+) через (\d+)', text)
    if step_match:
        end = int(step_match.group(1))
        step = int(step_match.group(2))
        if end > config["max_number"] or step <= 0:
            va.say("Число или шаг слишком велики")
            return

        result = []
        current = step
        while current <= end:
            result.append(str(current))
            current += step

        if result:
            va.say(", ".join(result) + ".")
        else:
            va.say("Нет чисел для счёта.")
        return

    # === Разбор выражения ===
    expr = _parse_expression(text)
    if not expr:
        va.say("Не поняла пример. Повторите, пожалуйста.")
        return

    result = _calculate_expression(expr)

    if result == "zero_divide":
        va.say("Нельзя делить на ноль")
        return

    if result is None:
        va.say("Не поняла пример. Повторите, пожалуйста.")
        return

    if abs(result) > config["max_result"]:
        va.say("Результат слишком большой")
        return

    # Округляем до целого, если результат целочисленный
    if result == int(result):
        result = int(result)

    va.say(str(result))

# === Команды ===
define_commands = {
    "посчитай до * через *": lambda va, t: _calculate(va, t),
    "сколько будет *": lambda va, t: _calculate(va, t),
    "сколько будет": lambda va, t: _calculate(va, t),
    "посчитай *": lambda va, t: _calculate(va, t),
    "решить *": lambda va, t: _calculate(va, t),
    "решить пример *": lambda va, t: _calculate(va, t),
}
