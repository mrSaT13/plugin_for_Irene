# === plugin_music_search_v2_7.py ===
"""
Плагин для поиска артистов и треков.

Особенности:
- Сканирование в фоне (не блокирует Ирину)
- Поиск только по ЧИСТЫМ артистам (игнорирует фиты)
- Поддержка команд:
    • "найди артиста ..." → воспроизводит ВСЮ ДИСКОГРАФИЮ
    • "включи радио ..." → радио + don't stop the music
    • "просканируй музыку" → фоновое сканирование
    • "статус сканирования" → показывает прогресс
- Интеграция с Home Assistant
- Кэширование базы
- Автоматическое уведомление о завершении сканирования
- Версия: 2.7

Автор: mrSaT13
"""

import os
import json
import threading
from pathlib import Path
import requests
from mutagen import File as MutagenFile

# === Поддерживаемые форматы ===
SUPPORTED_EXTENSIONS = {'.mp3', '.flac', '.m4a', '.ogg', '.wav'}

# === Фонетика ===
PHONETIC_MAP = {
    'ch': 'ч', 'sh': 'ш', 'th': 'с', 'ph': 'ф', 'kh': 'х',
    'ee': 'и', 'oo': 'у', 'ea': 'и', 'ie': 'и', 'ou': 'ау',
    'a': 'а', 'b': 'б', 'c': 'к', 'd': 'д', 'e': 'е', 'f': 'ф',
    'g': 'г', 'h': 'х', 'i': 'и', 'j': 'дж', 'k': 'к', 'l': 'л',
    'm': 'м', 'n': 'н', 'o': 'о', 'p': 'п', 'q': 'кв', 'r': 'р',
    's': 'с', 't': 'т', 'u': 'у', 'v': 'в', 'w': 'в', 'x': 'кс', 'y': 'и', 'z': 'з'
}

EXCEPTIONS = {"eminem": "эминем", "bts": "бтс"} # === примеры(можно и нужно дополнить по желанию) ===

def eng_to_ru_phonetic(name: str) -> str:
    if not name or not isinstance(name, str):
        return ""
    name_clean = name.lower().strip()
    if name_clean in EXCEPTIONS:
        return EXCEPTIONS[name_clean]
    temp = name_clean
    for eng in sorted(PHONETIC_MAP.keys(), key=len, reverse=True):
        ru = PHONETIC_MAP[eng]
        temp = temp.replace(eng, ru.upper())
    return temp.lower()

def extract_tags(filepath: str):
    try:
        audio = MutagenFile(filepath, easy=True)
        if not audio or not audio.tags:
            return "", ""
        artist = audio.get('artist', [''])[0].strip()
        title = audio.get('title', [''])[0].strip()
        return artist, title
    except Exception:
        return "", ""

# === Конфигурация ===
name = 'music_search'
version = '2.7'

config = {
    "enabled": True,
    "music_folder": "",
    "ha_url": "http://localhost:8123",
    "ha_token": "",
    "ha_entity_id": "media_player.your_speaker",
    "min_similarity": 85,
    "use_intro_phrases": True,
}

config_comment = """
Команды:
- "найди артиста ..." → воспроизводит всю дискографию
- "включи радио ..." → радио + don't stop the music
- "просканируй музыку" → обновляет кэш
- "статус сканирования" → проверяет, завершено ли сканирование

Настройки:
- music_folder: путь к папке с музыкой
- ha_url / ha_token / ha_entity_id: данные Home Assistant
"""

# === Глобальное состояние ===
_cache_file = "music_cache_v2_7.json"
_cache = {"pure_artists": set(), "tracks": []}
_scan_lock = threading.Lock()
_scan_thread = None
_scan_in_progress = False

def _load_cache():
    global _cache
    try:
        with open(_cache_file, "r", encoding="utf-8") as f:
            data = json.load(f)
            _cache["pure_artists"] = set(data.get("pure_artists", []))
            _cache["tracks"] = data.get("tracks", [])
    except FileNotFoundError:
        _cache = {"pure_artists": set(), "tracks": []}

def _save_cache():
    with open(_cache_file, "w", encoding="utf-8") as f:
        json.dump({
            "pure_artists": list(_cache["pure_artists"]),
            "tracks": _cache["tracks"]
        }, f, ensure_ascii=False, indent=2)

def _is_pure_artist(artist: str) -> bool:
    return not any(x in artist for x in ["feat.", "ft.", "/", "&", " x ", " and ", " с "])

def _scan_worker(va_interface):
    """Фоновый сканер с уведомлением о завершении"""
    global _scan_in_progress
    folder = config.get("music_folder", "").strip()
    
    try:
        if not folder or not os.path.isdir(folder):
            va_interface.say("Папка с музыкой не настроена или не существует.")
            return

        pure_artists = set()
        tracks = []
        total_files = 0

        for root, _, files in os.walk(folder):
            for file in files:
                if Path(file).suffix.lower() in SUPPORTED_EXTENSIONS:
                    total_files += 1
                    filepath = os.path.join(root, file)
                    artist, title = extract_tags(filepath)
                    if not artist:
                        artist = os.path.basename(root)
                    if not title:
                        title = Path(file).stem

                    if artist and _is_pure_artist(artist):
                        pure_artists.add(artist)

                    tracks.append({
                        "artist": artist,
                        "title": title,
                        "search_name": f"{artist} - {title}",
                        "search_ru": eng_to_ru_phonetic(f"{artist} - {title}")
                    })

        # Сохраняем результат
        with _scan_lock:
            _cache["pure_artists"] = pure_artists
            _cache["tracks"] = tracks
            _save_cache()

        # Уведомляем об успешном завершении
        va_interface.say(
            f"Сканирование музыки завершено. "
            f"Обработано файлов: {total_files}. "
            f"Чистых артистов найдено: {len(pure_artists)}."
        )

    except Exception as e:
        try:
            va_interface.say(f"Ошибка при сканировании: {str(e)[:100]}")
        except:
            pass
    finally:
        _scan_in_progress = False

def handle_scan_music(va, phrase=None):
    global _scan_thread, _scan_in_progress
    if not config.get("enabled"):
        return
        
    if _scan_in_progress:
        va.say("Сканирование уже выполняется.")
        return

    if config.get("use_intro_phrases"):
        va.say("Запускаю фоновое сканирование музыки...")

    _scan_in_progress = True
    # Передаём интерфейс VA в поток (безопасно, так как только для say)
    _scan_thread = threading.Thread(
        target=_scan_worker,
        args=(va,),
        daemon=True
    )
    _scan_thread.start()

def handle_scan_status(va, phrase=None):
    if _scan_in_progress:
        va.say("Сканирование музыки ещё выполняется. Пожалуйста, подождите.")
    else:
        artist_count = len(_cache["pure_artists"])
        if artist_count == 0:
            va.say("Музыка не просканирована или не найдено чистых артистов.")
        else:
            va.say(f"Сканирование завершено. Найдено чистых артистов: {artist_count}.")

def _play_via_ha(media_id: str, media_type: str, radio_mode: bool = False):
    url = config["ha_url"].rstrip("/") + "/api/services/media_player/play_media"
    headers = {
        "Authorization": f"Bearer {config['ha_token']}",
        "Content-Type": "application/json"
    }
    payload = {
        "entity_id": config["ha_entity_id"],
        "media_content_type": media_type,
        "media_content_id": media_id,
        "extra": {
            "radio_mode": radio_mode,
            "dont_stop_the_music": radio_mode
        }
    }
    try:
        requests.post(url, json=payload, headers=headers, timeout=10)
    except Exception:
        pass

def handle_find_artist(va, phrase):
    if not config.get("enabled"):
        return
    if config.get("use_intro_phrases"):
        va.say("Ищу артиста...")

    from rapidfuzz import process, fuzz
    min_score = config.get("min_similarity", 85)

    if not _cache["pure_artists"]:
        va.say("Музыка не просканирована.")
        return

    choices = [eng_to_ru_phonetic(a) for a in _cache["pure_artists"]]
    result = process.extractOne(phrase.lower(), choices, scorer=fuzz.partial_ratio)

    if result and result[1] >= min_score:
        artist = list(_cache["pure_artists"])[result[2]]
        _play_via_ha(artist, "artist", radio_mode=False)
        va.say(f"Включаю артиста {artist}.")
        return

    va.say("Артист не найден.")

def handle_radio_artist(va, phrase):
    if not config.get("enabled"):
        return
    if config.get("use_intro_phrases"):
        va.say("Запускаю радио...")

    from rapidfuzz import process, fuzz
    min_score = config.get("min_similarity", 85)

    if not _cache["pure_artists"]:
        va.say("Музыка не просканирована.")
        return

    choices = [eng_to_ru_phonetic(a) for a in _cache["pure_artists"]]
    result = process.extractOne(phrase.lower(), choices, scorer=fuzz.partial_ratio)

    if result and result[1] >= min_score:
        artist = list(_cache["pure_artists"])[result[2]]
        _play_via_ha(artist, "artist", radio_mode=True)
        va.say(f"Запускаю радио по артисту {artist}.")
        return

    va.say("Артист для радио не найден.")

# === Команды ===
define_commands = {
    "найди артиста": handle_find_artist,
    "включи радио": handle_radio_artist,
    "просканируй музыку": handle_scan_music,
    "статус сканирования": handle_scan_status,
}

# === Загрузка ===
_load_cache()
