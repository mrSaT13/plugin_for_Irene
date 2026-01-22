"""
Игра в города — Irina и пользователь по очереди называют города (VACore)
"""

from irene.brain.abc import VAApiExt
import random
import re

name = "game_cities_vacore"
version = "1.1.0"

# Глобальные переменные
_current_game = {
    "active": False,
    "last_city": "",
    "used_cities": [],
    "player_turn": True
}

cities_list = [
    "Москва", "Санкт-Петербург", "Новосибирск", "Екатеринбург", "Казань",
    "Нижний Новгород", "Челябинск", "Самара", "Омск", "Ростов-на-Дону",
    "Уфа", "Красноярск", "Воронеж", "Пермь", "Волгоград",
    "Краснодар", "Саратов", "Тюмень", "Тольятти", "Ижевск",
    "Барнаул", "Ульяновск", "Иркутск", "Хабаровск", "Ярославль",
    "Махачкала", "Новокузнецк", "Томск", "Кемерово", "Оренбург",
    "Набережные Челны", "Астрахань", "Рязань", "Пенза", "Липецк",
    "Киров", "Чебоксары", "Тула", "Калининград", "Курск",
    "Улан-Удэ", "Ставрополь", "Севастополь", "Сочи", "Петропавловск-Камчатский",
    "Архангельск", "Владивосток", "Якутск", "Иваново", "Белгород",
    "Мурманск", "Сургут", "Владикавказ", "Курган", "Тамбов",
    "Смоленск", "Калуга", "Чита", "Орёл", "Вологда",
    "Новороссийск", "Южно-Сахалинск", "Магадан", "Комсомольск-на-Амуре", "Салехард"
]

def _normalize_city(city: str) -> str:
    return re.sub(r'[-\s]', '', city.lower())

def _get_last_letter(city: str) -> str:
    city_clean = _normalize_city(city)
    if city_clean[-1] in 'ьъы':
        return city_clean[-2]
    return city_clean[-1]

def _find_city_by_letter(letter: str, used: list) -> str:
    available = [c for c in cities_list if _normalize_city(c)[0] == letter and c not in used]
    return random.choice(available) if available else ""

def start_game(va: VAApiExt, text: str):
    global _current_game
    _current_game = {
        "active": True,
        "last_city": "",
        "used_cities": [],
        "player_turn": True
    }

    first_city = random.choice(cities_list)
    _current_game["last_city"] = first_city
    _current_game["used_cities"].append(first_city)

    va.say(f"Правила: называем города по очереди. Следующий город должен начинаться на последнюю букву предыдущего. Я начну: {first_city}. Твоя очередь.")
    va.context_set(continue_game_context)

def continue_game_context(va: VAApiExt, text: str):
    if not _current_game["active"]:
        va.say("Скажи «игра города», чтобы начать.")
        return

    # Проверка команды выхода
    if text.lower() in ["хватит", "стоп", "выход", "выйти", "закончить", "конец"]:
        va.say("Хорошо, игра закончена. Скажи «игра города», если захочешь снова.")
        _current_game["active"] = False
        return

    city = text.strip()

    # Проверить, есть ли такой город
    if not any(_normalize_city(city) == _normalize_city(c) for c in cities_list):
        va.say("Это не город. Назови настоящий город.")
        va.context_set(continue_game_context)
        return

    # Проверить, подходит ли по букве
    if _current_game["last_city"]:
        last_letter = _get_last_letter(_current_game["last_city"])
        if _normalize_city(city)[0] != last_letter:
            va.say(f"Город должен начинаться на букву '{last_letter.upper()}'!")
            va.context_set(continue_game_context)
            return

    # Проверить, не использовался ли уже
    if city in _current_game["used_cities"]:
        va.say("Этот город уже был. Назови другой.")
        va.context_set(continue_game_context)
        return

    # Запомнить город
    _current_game["used_cities"].append(city)
    _current_game["last_city"] = city

    # Ход Irina
    next_letter = _get_last_letter(city)
    irina_city = _find_city_by_letter(next_letter, _current_game["used_cities"])

    if not irina_city:
        va.say("Поздравляю, ты выиграл!")
        _current_game["active"] = False
        return

    _current_game["last_city"] = irina_city
    _current_game["used_cities"].append(irina_city)

    va.say(f"Мой ход: {irina_city}. Твоя очередь.")
    va.context_set(continue_game_context)

define_commands = {
    "игра города": start_game,
}
