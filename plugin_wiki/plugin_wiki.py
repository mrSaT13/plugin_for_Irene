# /irene/plugins/wiki/plugin_wiki.py

import requests

name = "wikipedia_search"
version = "1.2"  # обновил версию

config = {
    "enabled": True,
    "language": "ru",
    "max_extract_length": 1500,  # увеличил длину извлечения
    "timeout_sec": 10,
    "user_agent": "Irene-Voice-Assistant (+https://github.com/AlexeyBond/Irene-Voice-Assistant)",
}

config_comment = """
Поиск в Википедии по фразам:
- «кто такой ...»
- «что такое ...»
- «расскажи про ...»
и др.

Параметры:
- enabled: включить/отключить плагин
- language: язык Википедии (ru, en, de и т.д.)
- max_extract_length: макс. длина описания в символах (рекомендуется 1000–2000)
- timeout_sec: таймаут запроса (сек)
- user_agent: обязательно для Википедии — укажите контакт
"""

def _search_and_speak(term: str, va_api):
    if not config.get("enabled", True):
        return

    lang = config.get("language", "ru")
    api_url = f"https://{lang}.wikipedia.org/w/api.php"
    timeout = config.get("timeout_sec", 10)
    user_agent = config.get("user_agent", "Irene-Voice-Assistant")
    max_len = config.get("max_extract_length", 1500)

    try:
        # Поиск статьи
        resp = requests.get(
            api_url,
            params={'action': 'opensearch', 'search': term, 'limit': 1, 'format': 'json'},
            headers={'User-Agent': user_agent},
            timeout=timeout
        )
        resp.raise_for_status()
        data = resp.json()

        if not data[1]:
            va_api.say(f"В Википедии ничего не найдено по запросу «{term}».")
            return

        title = data[1][0]

        # Получение краткого описания
        extract_resp = requests.get(
            api_url,
            params={
                'action': 'query',
                'prop': 'extracts',
                'exintro': True,
                'explaintext': True,
                'titles': title,
                'format': 'json',
            },
            headers={'User-Agent': user_agent},
            timeout=timeout
        )
        extract_resp.raise_for_status()
        pages = extract_resp.json()['query']['pages']
        page = next(iter(pages.values()))
        extract = page.get('extract', '').strip() or f"Статья о «{title}» найдена."

        # Обрезаем аккуратно — по последней точке, восклицательному или вопросительному знаку
        if len(extract) > max_len:
            # Ищем последнее завершённое предложение до лимита
            cut_point = max(
                extract.rfind('.', 0, max_len),
                extract.rfind('!', 0, max_len),
                extract.rfind('?', 0, max_len)
            )
            if cut_point == -1:  # если не нашли — просто режем по лимиту
                extract = extract[:max_len]
            else:
                extract = extract[:cut_point + 1]  # включаем знак препинания

        va_api.say(extract)

    except Exception as e:
        va_api.say("Не удалось получить данные из Википедии.")
        print(f"[Wikipedia] Ошибка: {e}")

# === ОБРАБОТЧИКИ ===
def _handle_who_is(va_api, query_text: str):
    _search_and_speak(query_text.strip(), va_api)

def _handle_what_is(va_api, query_text: str):
    _search_and_speak(query_text.strip(), va_api)

def _handle_about(va_api, query_text: str):
    _search_and_speak(query_text.strip(), va_api)

# === КОМАНДЫ ===
define_commands = {
    "кто такой": _handle_who_is,
    "кто такая": _handle_who_is,
    "что такое": _handle_what_is,
    "расскажи про": _handle_about,
    "что за": _handle_what_is,
}
