import requests
from irene.brain.abc import VAApiExt
from irene.plugin_loader.magic_plugin import operation

name = "plugin_music_assistant"
version = "1.1.0"
description = "Прямое управление Music Assistant (API token)"
author: mrSaT13
config = {
    "ma_url": "http://music-assistant:8095",
    "api_token": "",
    "player_id": ""
}

config_comment = """
ma_url — адрес Music Assistant (например http://music-assistant:8095)
api_token — API token из Music Assistant
player_id — ID плеера
"""


def ma_post(cfg, path):
    headers = {
        "Authorization": f"Bearer {cfg['api_token']}"
    }
    try:
        r = requests.post(
            f"{cfg['ma_url']}{path}",
            headers=headers,
            timeout=5
        )
        if r.status_code != 200:
            print("[MusicAssistant]", r.status_code, r.text)
            return False
        return True
    except Exception as e:
        print("[MusicAssistant] ERROR:", e)
        return False


@operation("command")
def музыка_пауза(ctx: VAApiExt):
    """
    Пауза
    Останови музыку
    """
    ma_post(ctx.config, f"/players/{ctx.config['player_id']}/pause")
    return "Музыка на паузе"


@operation("command")
def музыка_продолжи(ctx: VAApiExt):
    """
    Продолжи
    Включи музыку
    """
    ma_post(ctx.config, f"/players/{ctx.config['player_id']}/play")
    return "Продолжаю воспроизведение"


@operation("command")
def музыка_следующий(ctx: VAApiExt):
    """
    Следующий трек
    Далее
    """
    ma_post(ctx.config, f"/players/{ctx.config['player_id']}/next")
    return "Следующий трек"





