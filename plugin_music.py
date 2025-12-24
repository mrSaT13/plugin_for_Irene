"""
Музыкальный навык для Irene Voice Assistant 0.9.1
Управление через Home Assistant media_player
"""
# author: MisterTA
from irene.brain.abc import VAApiExt
from typing import Optional
import requests

name = "music"
version = "1.0.1"

# ================= НАСТРОЙКИ (ОТОБРАЗЯТСЯ В WEB) =================

config = {
    "hass_url": "http://ip:port",
    "hass_token": "",
    "player_entity": "media_player....id",
}

config_comment = """
Управление музыкой через Home Assistant

Обязательно:
- Указать URL Home Assistant
- Указать Long-Lived Access Token
- Указать entity_id плеера

Команды:
- пауза
- следующий / дальше
- предыдущий / назад
- играть / продолжи
"""

# ================= HA API =================

def ha_call(
    va: VAApiExt,
    service: str,
    data: Optional[dict] = None
) -> bool:
    if not config.get("hass_token"):
        va.say("Не настроен токен Home Assistant")
        return False

    url = f"{config['hass_url']}/api/services/{service}"
    headers = {
        "Authorization": f"Bearer {config['hass_token']}",
        "Content-Type": "application/json",
    }

    payload = data or {}
    payload.setdefault("entity_id", config["player_entity"])

    try:
        r = requests.post(url, json=payload, headers=headers, timeout=10)
        if r.status_code in (200, 201):
            return True

        print(f"[music] HA error {r.status_code}: {r.text}")
        return False

    except Exception as e:
        print(f"[music] HA exception: {e}")
        return False

# ================= КОМАНДЫ =================

def pause(va: VAApiExt, text: str):
    if ha_call(va, "media_player/media_pause"):
        va.say("Пауза")

def play(va: VAApiExt, text: str):
    if ha_call(va, "media_player/media_play"):
        va.say("Продолжаю")

def next_track(va: VAApiExt, text: str):
    if ha_call(va, "media_player/media_next_track"):
        va.say("Следующий трек")

def prev_track(va: VAApiExt, text: str):
    if ha_call(va, "media_player/media_previous_track"):
        va.say("Предыдущий трек")

# ================= COMMAND TREE =================
define_commands = {
    "пауза": pause,
    "стоп": pause,
    "замри": pause,

    "играй": play,
    "продолжи": play,

    "следующий": next_track,
    "дальше": next_track,

    "предыдущий": prev_track,
    "назад": prev_track,
}


