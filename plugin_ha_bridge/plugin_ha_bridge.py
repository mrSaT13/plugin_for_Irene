"""
Мост между Ириной и Home Assistant v1.7.1

Исправления:
- Убран ошибочный _load_areas() из __init__ (вызывал несуществующий HA API)
- Теперь инициализация не падает
- Rooms определяются только по имени устройства и room_mapping
- Улучшена надёжность find_device
"""

import json
import logging
import os
import re
import threading
import time
import urllib.request
import urllib.error
from typing import Any, Optional, Dict, List

_LOGGER = logging.getLogger(__name__)

name = 'ha_bridge'
version = '1.7.1'

config = {
    "ha_url": "http://homeassistant.local:8123",
    "ha_token": "",
    "refresh_interval": 300,
    "language": "ru",
    "enabled": True,
    "command_prefix": "хаб",
    "ignore_entities": [
        "adaptive_lighting",
        "browser_mod",
        "indicator_light",
        "indicator light",
        "sun_",
        "zone_",
        "device_tracker",
        "persistent_notification",
        "update_",
        "button_",
        "number_",
        "input_",
        "automation.",
        "script.",
        "scene.",
        "event.",
        "calendar.",
        "todo.",
        "tts.",
        "stt.",
        "weather.",
        "remote.",
        "siren.",
    ],
    "synonyms": {
        "кондиционер": ["ac", "snow leopard", "conditioner", "climate"],
        "телевизор": ["tv", "television", "media_player"],
        "пылесос": ["robot", "vacuum", "xiaomi"],
        "колонка": ["speaker", "mini", "media"],
        "свет": ["light", "лампа", "лампочка", "люстра", "бра", "торшер", "гирлянда", "ёлка", "подсветка", "led"],
        "розетка": ["switch", "relay", "реле", "выключатель"],
        "датчик": ["sensor", "sensor"],
        "камера": ["camera", "камера"],
    },
    "device_overrides": {
        "гирлянда": "light",
        "ёлка": "light",
        "подсветка": "light",
        "led лента": "light",
        "led": "light",
    },
    "room_mapping": {
        "гостиная": ["гостиная", "зал", "гостинная", "living", "гостинной"],
        "кухня": ["кухня", "kitchen", "кухне"],
        "спальня": ["спальня", "bedroom", "спальне"],
        "детская": ["детская", "kids", "child"],
        "ванная": ["ванная", "bathroom", "ванне"],
        "туалет": ["туалет", "wc", "toilet"],
        "коридор": ["коридор", "hallway", "коридоре"],
        "прихожая": ["прихожая", "entrance"],
        "кабинет": ["кабинет", "office"],
        "гараж": ["гараж", "garage"],
        "серверная": ["серверная", "server"],
        "балкон": ["балкон", "balcony"],
        "ассистент": ["ассистент"],
        "сервер": ["сервер"],
    },
}

config_comment = """
Настройки моста с Home Assistant v1.7.1

Параметры:
- `(ha_url)` - URL Home Assistant
- `(ha_token)` - Long-Lived Access Token
- `(refresh_interval)` - интервал обновления (секунды)
- `(command_prefix)` - префикс команд (по умолчанию "хаб")
- `(ignore_entities)` - список паттернов для исключения
- `(synonyms)` - словарь синонимов
- `(device_overrides)` - переопределение типа управления
- `(room_mapping)` - маппинг комнат
"""

_ha_client = None
_refresh_thread = None
_stop_event = threading.Event()
_timers = {}
_device_cache_file = "/tmp/ha_bridge_devices.json"

NUMBER_WORDS = {
    "одна": 1, "одно": 1, "один": 1, "минуту": 1, "минуты": 1, "минута": 1,
    "две": 2, "два": 2,
    "три": 3, "четыре": 4, "пять": 5,
    "шесть": 6, "семь": 7, "восемь": 8, "девять": 9,
    "десять": 10, "одиннадцать": 11, "двенадцать": 12,
    "тринадцать": 13, "четырнадцать": 14, "пятнадцать": 15,
    "двадцать": 20, "тридцать": 30, "сорок": 40,
    "час": 60, "часа": 60, "часов": 60,
}


def normalize_room(room: str) -> str:
    if not room:
        return ""
    room_lower = room.lower().strip()
    for prep in ["в ", "на ", "о ", "об "]:
        if room_lower.startswith(prep):
            room_lower = room_lower[len(prep):].strip()
    room_mapping = config.get("room_mapping", {})
    for canonical_name, variations in room_mapping.items():
        if room_lower in variations or room_lower == canonical_name:
            return canonical_name
    return room_lower


def parse_number(text: str) -> Optional[int]:
    if not text:
        return None
    match = re.search(r'(\d+)', text)
    if match:
        return int(match.group(1))
    text_lower = text.lower().strip()
    for word, number in NUMBER_WORDS.items():
        if word in text_lower:
            return number
    return None


def extract_minutes(text: str) -> tuple:
    text = text.strip()
    text = re.sub(r'^через\s+', '', text, flags=re.IGNORECASE)
    
    pattern = r'^(\d+|одна|одно|один|две|два|три|четыре|пять|шесть|семь|восемь|девять|десять|одиннадцать|двенадцать|час)\s*(минут[аыу]?|мин|минуты|минуту|минута|час[аы]?)?\s+(.+)$'
    match = re.match(pattern, text, re.IGNORECASE)
    
    if not match:
        pattern2 = r'^(\d+)\s+(.+)$'
        match2 = re.match(pattern2, text)
        if match2:
            return int(match2.group(1)), match2.group(2).strip()
        return None, text
    
    number_text = match.group(1)
    unit = match.group(2) or "минут"
    device_query = match.group(3).strip()
    
    minutes = parse_number(number_text)
    if minutes is None:
        return None, text
    
    if "час" in unit.lower():
        minutes *= 60
    
    return minutes, device_query


class HaClient:
    def __init__(self, cfg):
        self.config = dict(cfg)
        self.ha_url = cfg.get("ha_url", "").rstrip("/")
        self.token = cfg.get("ha_token", "")
        self.devices = {}
        self.areas = {}
        self._last_update = 0
        self._lock = threading.Lock()
        # ✅ Убран _load_areas() - его нет в API Ирины
        _LOGGER.info(f"HaClient created: url={self.ha_url}, token={'set' if self.token else 'EMPTY'}")
    
    def update_config(self, cfg):
        self.config = dict(cfg)
        self.ha_url = cfg.get("ha_url", "").rstrip("/")
        self.token = cfg.get("ha_token", "")
        _LOGGER.info(f"HaClient config updated")
    
    def _make_request(self, method, path, data=None):
        if not self.token:
            _LOGGER.error("HA token is empty!")
            return None
        
        url = f"{self.ha_url}{path}"
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }
        
        try:
            body = json.dumps(data).encode('utf-8') if data else None
            req = urllib.request.Request(url, data=body, headers=headers, method=method)
            
            with urllib.request.urlopen(req, timeout=10) as response:
                response_data = response.read().decode('utf-8')
                return json.loads(response_data) if response_data else None
                
        except urllib.error.HTTPError as e:
            _LOGGER.error(f"HTTP error {e.code} for {url}")
            return None
        except Exception as e:
            _LOGGER.error(f"Request error: {e} for {url}")
            return None
    
    def _should_ignore(self, entity_id: str, friendly_name: str) -> bool:
        ignore_patterns = self.config.get("ignore_entities", [])
        entity_lower = entity_id.lower()
        name_lower = friendly_name.lower()
        
        for pattern in ignore_patterns:
            pattern_lower = pattern.lower()
            if pattern_lower in entity_lower or pattern_lower in name_lower:
                return True
        return False
    
    def _save_device_cache(self):
        try:
            cache_data = {
                "devices": {k: v for k, v in self.devices.items()},
                "areas": self.areas,
                "timestamp": time.time(),
            }
            with open(_device_cache_file, 'w', encoding='utf-8') as f:
                json.dump(cache_data, f, ensure_ascii=False)
        except Exception as e:
            _LOGGER.debug(f"Cache save error: {e}")
    
    def _load_device_cache(self) -> bool:
        try:
            if os.path.exists(_device_cache_file):
                with open(_device_cache_file, 'r', encoding='utf-8') as f:
                    cache = json.load(f)
                    if time.time() - cache.get("timestamp", 0) < 3600:
                        self.devices = cache.get("devices", {})
                        self.areas = cache.get("areas", {})
                        _LOGGER.info(f"Loaded {len(self.devices)} devices from cache")
                        return True
        except Exception as e:
            _LOGGER.debug(f"Cache load error: {e}")
        return False
    
    def refresh_devices(self):
        current_time = time.time()
        if current_time - self._last_update < 60:
            return self.devices
        
        if self._load_device_cache():
            self._last_update = current_time
            return self.devices
        
        states = self._make_request("GET", "/api/states")
        if states is None:
            return self.devices
        
        with self._lock:
            self.devices = self._parse_devices(states)
            self.areas = self._group_by_areas()
            self._last_update = current_time
            self._save_device_cache()
        
        _LOGGER.info(f"Loaded {len(self.devices)} devices from HA")
        return self.devices
    
    def _parse_devices(self, states):
        devices = {}
        managed_domains = {"light", "switch", "climate", "cover", "fan", "lock", "media_player", "vacuum", "sensor"}
        
        for state in states:
            entity_id = state.get("entity_id", "")
            if "." not in entity_id:
                continue
            
            domain = entity_id.split(".")[0]
            if domain not in managed_domains:
                continue
            
            attributes = state.get("attributes", {})
            friendly_name = attributes.get("friendly_name", "")
            
            if not friendly_name:
                continue
            
            if self._should_ignore(entity_id, friendly_name):
                continue
            
            room = self._extract_room(attributes, friendly_name)
            
            device = {
                "entity_id": entity_id,
                "domain": domain,
                "friendly_name": friendly_name,
                "room": room,
                "state": state.get("state", ""),
                "attributes": attributes,
            }
            
            devices[friendly_name.lower()] = device
        
        return devices
    
    def _extract_room(self, attributes, friendly_name) -> str:
        """Извлекаем комнату из имени устройства."""
        # ✅ Используем только имя + room_mapping (area_id из HA атрибутов не всегда есть)
        name_lower = friendly_name.lower()
        
        room_mapping = config.get("room_mapping", {})
        for canonical_name, variations in room_mapping.items():
            for variation in variations:
                if variation in name_lower:
                    return canonical_name
        
        return ""
    
    def _group_by_areas(self):
        areas = {}
        for device in self.devices.values():
            room = device.get("room", "без комнаты")
            if room not in areas:
                areas[room] = []
            areas[room].append(device)
        return areas
    
    def call_service(self, domain, service, entity_id, data=None):
        payload = {"entity_id": entity_id}
        if data:
            payload.update(data)
        
        result = self._make_request("POST", f"/api/services/{domain}/{service}", data=payload)
        
        if result is not None:
            _LOGGER.info(f"Service called: {domain}.{service} -> {entity_id}")
            return True
        _LOGGER.error(f"Service call failed: {domain}.{service} -> {entity_id}")
        return False
    
    def get_device_type(self, device: Dict) -> str:
        overrides = self.config.get("device_overrides", {})
        name_lower = device["friendly_name"].lower()
        
        for keyword, override_type in overrides.items():
            if keyword in name_lower:
                return override_type
        
        return device["domain"]
    
    def find_device(self, query, exact_match=True):
        """Поиск устройства с приоритетом точного совпадения."""
        if not query or _ha_client is None:
            return None
        
        query_lower = query.lower().strip()
        
        for prep in ["в ", "на ", "о ", "об "]:
            if query_lower.startswith(prep):
                query_lower = query_lower[len(prep):].strip()
        
        if not query_lower:
            return None
        
        # 1. Точное совпадение
        if query_lower in self.devices:
            _LOGGER.info(f"Exact match: {query_lower}")
            return self.devices[query_lower]
        
        # 2. Начало имени
        for name, device in self.devices.items():
            if name.startswith(query_lower):
                _LOGGER.info(f"Start match: {name}")
                return device
        
        # 3. Содержит запрос
        best_match = None
        best_score = 0
        
        for name, device in self.devices.items():
            if query_lower in name:
                score = len(query_lower) / max(len(name), 1)
                if score > best_score:
                    best_score = score
                    best_match = device
        
        if best_match and best_score > 0.5:
            _LOGGER.info(f"Partial match: {best_match['friendly_name']} ({best_score})")
            return best_match
        
        # 4. Поиск по синонимам
        synonyms = self.config.get("synonyms", {})
        query_words = set(query_lower.split())
        
        for device in self.devices.values():
            name_lower = device["friendly_name"].lower()
            
            for keyword, syns in synonyms.items():
                if keyword in query_words:
                    for syn in syns:
                        if syn in name_lower:
                            _LOGGER.info(f"Synonym match: {device['friendly_name']}")
                            return device
        
        _LOGGER.warning(f"Device not found: '{query}'")
        return None
    
    def find_devices_by_type_and_room(self, device_type: str, room: str) -> List[Dict]:
        type_lower = device_type.lower().strip()
        room_normalized = normalize_room(room)
        
        results = []
        synonyms = self.config.get("synonyms", {})
        overrides = self.config.get("device_overrides", {})
        
        type_synonyms = set([type_lower])
        for keyword, syns in synonyms.items():
            if keyword == type_lower or type_lower in syns:
                type_synonyms.update(syns)
                type_synonyms.add(keyword)
        
        for keyword, override_type in overrides.items():
            if override_type == type_lower:
                type_synonyms.add(keyword)
        
        for device in self.devices.values():
            device_room = device.get("room", "").lower()
            device_room_normalized = normalize_room(device_room)
            
            if room_normalized:
                if room_normalized not in device_room and device_room_normalized not in room_normalized:
                    continue
            
            actual_type = self.get_device_type(device)
            name_lower = device["friendly_name"].lower()
            
            if actual_type == type_lower:
                results.append(device)
                continue
            
            for syn in type_synonyms:
                if syn in name_lower:
                    results.append(device)
                    break
        
        return results
    
    def get_rooms(self) -> List[str]:
        rooms = set()
        for device in self.devices.values():
            room = device.get("room", "")
            if room:
                rooms.add(room)
        return sorted(list(rooms))
    
    def get_temperature_in_room(self, room: str) -> Optional[Dict]:
        room_normalized = normalize_room(room)
        
        # 1. Climate устройства
        for device in self.devices.values():
            if device["domain"] != "climate":
                continue
            
            device_room = device.get("room", "").lower()
            device_room_normalized = normalize_room(device_room)
            
            if room_normalized in device_room or device_room_normalized in room_normalized:
                temp = device["attributes"].get("current_temperature")
                if temp:
                    return {"device": device, "temperature": temp, "type": "climate"}
        
        # 2. Только temperature sensors (НЕ battery!)
        for device in self.devices.values():
            if device["domain"] != "sensor":
                continue
            
            device_room = device.get("room", "").lower()
            device_room_normalized = normalize_room(device_room)
            
            if room_normalized not in device_room and device_room_normalized not in room_normalized:
                continue
            
            attributes = device["attributes"]
            device_class = attributes.get("device_class", "")
            unit = attributes.get("unit_of_measurement", "")
            friendly_name = device["friendly_name"].lower()
            
            if device_class == "temperature":
                state = device["state"]
                try:
                    temp = float(state)
                    return {"device": device, "temperature": temp, "type": "sensor"}
                except (ValueError, TypeError):
                    continue
            
            if "battery" not in friendly_name and ("градус" in unit.lower() or "°c" in unit or "°f" in unit):
                state = device["state"]
                try:
                    temp = float(state)
                    return {"device": device, "temperature": temp, "type": "sensor"}
                except (ValueError, TypeError):
                    continue
        
        return None


# ==================== Жизненный цикл ====================

def receive_config(cfg, *_args, **_kwargs):
    global config, _ha_client
    
    _LOGGER.info(f"HA Bridge: receive_config called")
    
    if cfg:
        config.update(cfg)
    
    token = config.get("ha_token", "")
    enabled = config.get("enabled", True)
    
    if enabled and token:
        if _ha_client is None:
            _LOGGER.info(f"HA Bridge: Creating client (token: {token[:10]}...)")
            _ha_client = HaClient(config)
        else:
            _LOGGER.info("HA Bridge: Updating client config")
            _ha_client.update_config(config)
    elif not token:
        _LOGGER.warning("HA Bridge: Token is empty!")
    elif not enabled:
        _LOGGER.info("HA Bridge: Plugin is disabled")


def init(*_args, **_kwargs):
    global _ha_client
    
    _LOGGER.info(f"HA Bridge: init() called. Client exists: {_ha_client is not None}")
    
    if _ha_client is None:
        if not config.get("enabled", True) or not config.get("ha_token"):
            _LOGGER.error("HA Bridge: init() but no token or disabled!")
            return
        _LOGGER.info("HA Bridge: Creating client in init()")
        _ha_client = HaClient(config)


def run(*_args, **_kwargs):
    global _refresh_thread
    
    if _ha_client is None:
        _LOGGER.warning("HA Bridge: run() but client is None")
        return
    
    _stop_event.clear()
    
    try:
        devices = _ha_client.refresh_devices()
        _LOGGER.info(f"HA Bridge: Loaded {len(devices)} devices")
    except Exception as e:
        _LOGGER.error(f"HA Bridge: Initial load error: {e}", exc_info=True)
    
    _refresh_thread = threading.Thread(target=_background_refresh, daemon=True)
    _refresh_thread.start()


def terminate(*_args, **_kwargs):
    _LOGGER.info("HA Bridge: terminate() called")
    _stop_event.set()
    _timers.clear()


def _background_refresh():
    interval = config.get("refresh_interval", 300)
    while not _stop_event.is_set():
        _stop_event.wait(interval)
        if _stop_event.is_set():
            break
        try:
            if _ha_client:
                _ha_client.refresh_devices()
        except Exception as e:
            _LOGGER.error(f"Background refresh error: {e}")


# ==================== Команды ====================

def define_commands(*_args, **_kwargs):
    _LOGGER.info(f"HA Bridge: define_commands called. Client: {_ha_client is not None}")
    prefix = config.get("command_prefix", "хаб")
    
    return {
        f"{prefix} обнови устройства": _cmd_refresh_devices,
        f"{prefix} обновить устройства": _cmd_refresh_devices,
        f"{prefix} список устройств": _cmd_list_devices,
        f"{prefix} какие комнаты": _cmd_list_rooms,
        f"{prefix} что в": _cmd_what_in_room,
        f"{prefix} что включено": _cmd_what_is_on,
        f"{prefix} помощь": _cmd_help,
        
        f"{prefix} включи": _cmd_turn_on_generic,
        f"{prefix} выключи": _cmd_turn_off_generic,
        f"{prefix} включи через": _cmd_turn_on_delayed,
        f"{prefix} выключи через": _cmd_turn_off_delayed,
        
        f"{prefix} какая температура": _cmd_get_temperature,
        f"{prefix} температура": _cmd_get_temperature,
        f"{prefix} температура в": _cmd_get_temperature_in_room,
        f"{prefix} какая температура в": _cmd_get_temperature_in_room,
        f"{prefix} установи температуру": _cmd_set_temperature,
        
        f"{prefix} вентиляция": _cmd_climate_ventilation,
        f"{prefix} проветрить": _cmd_climate_ventilation,
        f"{prefix} холодно": _cmd_climate_warmer,
        f"{prefix} жарко": _cmd_climate_cooler,
        f"{prefix} душно": _cmd_climate_cooler,
        f"{prefix} шторки вверх": _cmd_climate_swing_up,
        f"{prefix} шторки вниз": _cmd_climate_swing_down,
    }


def _cmd_help(va, text):
    prefix = config.get("command_prefix", "хаб")
    help_text = (
        f"Команды '{prefix}':\n"
        f"• обнови устройства\n"
        f"• список устройств\n"
        f"• какие комнаты\n"
        f"• что в [комнате]\n"
        f"• что включено\n"
        f"• включи/выключи [устройство]\n"
        f"• включи/выключи через [мин] [устройство]\n"
        f"• какая температура / температура в [комнате]\n"
        f"• установи температуру [число]\n"
        f"• вентиляция / проветрить\n"
        f"• холодно (теплее) / жарко (холоднее)\n"
        f"• шторки вверх/вниз"
    )
    va.say(help_text)


def _cmd_refresh_devices(va, text):
    if _ha_client is None:
        va.say("Мост не настроен. Укажите токен в настройках плагина.")
        return
    
    try:
        _ha_client._last_update = 0
        devices = _ha_client.refresh_devices()
        count = len(devices)
        
        if count == 0:
            va.say("Устройства не найдены. Проверьте токен и URL.")
            return
        
        by_domain = {}
        for device in devices.values():
            domain = device["domain"]
            by_domain[domain] = by_domain.get(domain, 0) + 1
        
        parts = []
        domain_names = {
            "light": "свет", "switch": "выключателей", "climate": "климат",
            "cover": "штор", "fan": "вентиляторов", "lock": "замков",
            "media_player": "медиа", "vacuum": "пылесосов", "sensor": "датчиков",
        }
        for domain, cnt in by_domain.items():
            name = domain_names.get(domain, domain)
            parts.append(f"{cnt} {name}")
        
        rooms = _ha_client.get_rooms()
        rooms_str = f". Комнаты: {', '.join(rooms[:5])}" if rooms else ""
        
        va.say(f"Найдено {count} устройств: " + ", ".join(parts) + rooms_str)
    except Exception as e:
        va.say(f"Ошибка: {e}")


def _cmd_list_devices(va, text):
    if _ha_client is None or not _ha_client.devices:
        va.say("Устройства не найдены.")
        return
    
    by_room = _ha_client.areas if _ha_client.areas else {}
    
    response_parts = []
    for room, devices in by_room.items():
        names = [d["friendly_name"] for d in devices[:5]]
        response_parts.append(f"В {room}: " + ", ".join(names))
        if len(devices) > 5:
            response_parts[-1] += f" и ещё {len(devices) - 5}"
    
    response = ". ".join(response_parts[:6])
    va.say(response)


def _cmd_list_rooms(va, text):
    if _ha_client is None:
        va.say("Мост не настроен.")
        return
    
    rooms = _ha_client.get_rooms()
    if not rooms:
        va.say("Комнаты не определены.")
        return
    va.say("Комнаты: " + ", ".join(rooms))


def _cmd_what_in_room(va, text):
    if _ha_client is None:
        va.say("Мост не настроен.")
        return
    
    if not text or not text.strip():
        va.say("Какую комнату?")
        return
    
    room = normalize_room(text.strip())
    devices = _ha_client.find_devices_by_type_and_room("", room)
    
    if not devices:
        va.say(f"В комнате '{room}' устройств не найдено.")
        return
    
    names = [d["friendly_name"] for d in devices[:7]]
    response = f"В {room}: " + ", ".join(names)
    if len(devices) > 7:
        response += f" и ещё {len(devices) - 7}"
    va.say(response)


def _cmd_what_is_on(va, text):
    if _ha_client is None or not _ha_client.devices:
        va.say("Устройства не найдены.")
        return
    
    on_devices = []
    for device in _ha_client.devices.values():
        state = device.get("state", "")
        if state in ("on", "open", "unlocked", "playing", "cool", "heat", "fan_only"):
            on_devices.append(device["friendly_name"])
    
    if not on_devices:
        va.say("Все устройства выключены.")
    else:
        va.say("Включено: " + ", ".join(on_devices[:10]))


def _turn_on_device(device):
    actual_type = _ha_client.get_device_type(device)
    entity_id = device["entity_id"]
    domain = device["domain"]
    
    _LOGGER.info(f"Turning on {device['friendly_name']} as {actual_type}")
    
    if actual_type == "light" or domain == "light":
        _ha_client.call_service("light", "turn_on", entity_id)
    elif actual_type == "switch" or domain == "switch":
        _ha_client.call_service("switch", "turn_on", entity_id)
    elif domain == "climate":
        _ha_client.call_service("climate", "turn_on", entity_id)
        hvac_mode = device["attributes"].get("hvac_mode", "cool")
        if hvac_mode in ["off", "unavailable"]:
            _ha_client.call_service("climate", "set_hvac_mode", entity_id, {"hvac_mode": "cool"})
    elif domain == "fan":
        _ha_client.call_service("fan", "turn_on", entity_id)
    elif domain == "media_player":
        _ha_client.call_service("media_player", "turn_on", entity_id)
    elif domain == "vacuum":
        _ha_client.call_service("vacuum", "start", entity_id)


def _turn_off_device(device):
    actual_type = _ha_client.get_device_type(device)
    entity_id = device["entity_id"]
    domain = device["domain"]
    
    _LOGGER.info(f"Turning off {device['friendly_name']} as {actual_type}")
    
    if actual_type == "light" or domain == "light":
        _ha_client.call_service("light", "turn_off", entity_id)
    elif actual_type == "switch" or domain == "switch":
        _ha_client.call_service("switch", "turn_off", entity_id)
    elif domain == "climate":
        _ha_client.call_service("climate", "turn_off", entity_id)
    elif domain == "fan":
        _ha_client.call_service("fan", "turn_off", entity_id)
    elif domain == "media_player":
        _ha_client.call_service("media_player", "turn_off", entity_id)
    elif domain == "vacuum":
        _ha_client.call_service("vacuum", "return_to_base", entity_id)


def _cmd_turn_on_generic(va, text):
    if _ha_client is None:
        va.say("Мост не настроен.")
        return
    
    if not text or not text.strip():
        va.say("Какое устройство включить?")
        return
    
    text = text.strip()
    
    room_match = re.search(r'\s+в\s+([а-яё\s]+)$', text, re.IGNORECASE)
    
    if room_match:
        device_type = text[:room_match.start()].strip()
        room = normalize_room(room_match.group(1).strip())
        
        devices = _ha_client.find_devices_by_type_and_room(device_type, room)
        
        if not devices:
            va.say(f"Не найдено устройств '{device_type}' в комнате '{room}'.")
            return
        
        for device in devices:
            _turn_on_device(device)
        
        if len(devices) == 1:
            va.say(f"Включаю {devices[0]['friendly_name']}")
        else:
            va.say(f"Включаю {len(devices)} устройств")
    else:
        device = _ha_client.find_device(text, exact_match=True)
        
        if device is None:
            va.say(f"Не найдено устройство '{text}'.")
            return
        
        _turn_on_device(device)
        va.say(f"Включаю {device['friendly_name']}")


def _cmd_turn_off_generic(va, text):
    if _ha_client is None:
        va.say("Мост не настроен.")
        return
    
    if not text or not text.strip():
        va.say("Какое устройство выключить?")
        return
    
    text = text.strip()
    
    room_match = re.search(r'\s+в\s+([а-яё\s]+)$', text, re.IGNORECASE)
    
    if room_match:
        device_type = text[:room_match.start()].strip()
        room = normalize_room(room_match.group(1).strip())
        
        devices = _ha_client.find_devices_by_type_and_room(device_type, room)
        
        if not devices:
            va.say(f"Не найдено устройств '{device_type}' в комнате '{room}'.")
            return
        
        for device in devices:
            _turn_off_device(device)
        
        if len(devices) == 1:
            va.say(f"Выключаю {devices[0]['friendly_name']}")
        else:
            va.say(f"Выключаю {len(devices)} устройств")
    else:
        device = _ha_client.find_device(text, exact_match=True)
        
        if device is None:
            va.say(f"Не найдено устройство '{text}'.")
            return
        
        _turn_off_device(device)
        va.say(f"Выключаю {device['friendly_name']}")


def _cmd_turn_on_delayed(va, text):
    if _ha_client is None:
        va.say("Мост не настроен.")
        return
    
    if not text:
        va.say("Пример: хаб включи через 5 минут свет")
        return
    
    minutes, device_query = extract_minutes(text)
    
    if minutes is None:
        va.say("Не удалось распознать время.")
        return
    
    device = _ha_client.find_device(device_query, exact_match=True)
    
    if device is None:
        va.say(f"Не найдено устройство '{device_query}'.")
        return
    
    timer_name = f"turn_on_{device['entity_id']}_{int(time.time())}"
    
    def delayed_turn_on():
        time.sleep(minutes * 60)
        _turn_on_device(device)
    
    thread = threading.Thread(target=delayed_turn_on, daemon=True)
    thread.start()
    
    _timers[timer_name] = {"thread": thread, "device": device}
    va.say(f"Хорошо, включу {device['friendly_name']} через {minutes} минут")


def _cmd_turn_off_delayed(va, text):
    if _ha_client is None:
        va.say("Мост не настроен.")
        return
    
    if not text:
        va.say("Пример: хаб выключи через 10 минут свет")
        return
    
    minutes, device_query = extract_minutes(text)
    
    if minutes is None:
        va.say("Не удалось распознать время.")
        return
    
    device = _ha_client.find_device(device_query, exact_match=True)
    
    if device is None:
        va.say(f"Не найдено устройство '{device_query}'.")
        return
    
    timer_name = f"turn_off_{device['entity_id']}_{int(time.time())}"
    
    def delayed_turn_off():
        time.sleep(minutes * 60)
        _turn_off_device(device)
    
    thread = threading.Thread(target=delayed_turn_off, daemon=True)
    thread.start()
    
    _timers[timer_name] = {"thread": thread, "device": device}
    va.say(f"Хорошо, выключу {device['friendly_name']} через {minutes} минут")


def _cmd_climate_ventilation(va, text):
    if _ha_client is None:
        va.say("Мост не настроен.")
        return
    
    room = normalize_room(text.strip()) if text and text.strip() else ""
    
    devices = []
    if room:
        devices = _ha_client.find_devices_by_type_and_room("climate", room)
    else:
        for device in _ha_client.devices.values():
            if device["domain"] == "climate":
                devices.append(device)
    
    if not devices:
        va.say("Не найдено кондиционеров." + (f" в комнате '{room}'" if room else ""))
        return
    
    for device in devices:
        _ha_client.call_service("climate", "set_hvac_mode", device["entity_id"], {"hvac_mode": "fan_only"})
    
    va.say(f"Включаю вентиляцию" + (f" в {room}" if room else ""))


def _cmd_climate_warmer(va, text):
    if _ha_client is None:
        va.say("Мост не настроен.")
        return
    
    room = normalize_room(text.strip()) if text and text.strip() else ""
    
    devices = []
    if room:
        devices = _ha_client.find_devices_by_type_and_room("climate", room)
    else:
        for device in _ha_client.devices.values():
            if device["domain"] == "climate":
                devices.append(device)
    
    if not devices:
        va.say("Не найдено кондиционеров.")
        return
    
    for device in devices:
        current_temp = device["attributes"].get("temperature", 22)
        new_temp = current_temp + 2
        _ha_client.call_service("climate", "set_temperature", device["entity_id"], {"temperature": new_temp})
    
    va.say(f"Делаю теплее" + (f" в {room}" if room else ""))


def _cmd_climate_cooler(va, text):
    if _ha_client is None:
        va.say("Мост не настроен.")
        return
    
    room = normalize_room(text.strip()) if text and text.strip() else ""
    
    devices = []
    if room:
        devices = _ha_client.find_devices_by_type_and_room("climate", room)
    else:
        for device in _ha_client.devices.values():
            if device["domain"] == "climate":
                devices.append(device)
    
    if not devices:
        va.say("Не найдено кондиционеров.")
        return
    
    for device in devices:
        current_temp = device["attributes"].get("temperature", 22)
        new_temp = current_temp - 2
        _ha_client.call_service("climate", "set_temperature", device["entity_id"], {"temperature": new_temp})
    
    va.say(f"Делаю холоднее" + (f" в {room}" if room else ""))


def _cmd_climate_swing_up(va, text):
    if _ha_client is None:
        va.say("Мост не настроен.")
        return
    
    room = normalize_room(text.strip()) if text and text.strip() else ""
    
    devices = []
    if room:
        devices = _ha_client.find_devices_by_type_and_room("climate", room)
    else:
        for device in _ha_client.devices.values():
            if device["domain"] == "climate":
                devices.append(device)
    
    if not devices:
        va.say("Не найдено кондиционеров.")
        return
    
    for device in devices:
        _ha_client.call_service("climate", "set_swing_mode", device["entity_id"], {"swing_mode": "up"})
    
    va.say(f"Поднимаю шторки" + (f" в {room}" if room else ""))


def _cmd_climate_swing_down(va, text):
    if _ha_client is None:
        va.say("Мост не настроен.")
        return
    
    room = normalize_room(text.strip()) if text and text.strip() else ""
    
    devices = []
    if room:
        devices = _ha_client.find_devices_by_type_and_room("climate", room)
    else:
        for device in _ha_client.devices.values():
            if device["domain"] == "climate":
                devices.append(device)
    
    if not devices:
        va.say("Не найдено кондиционеров.")
        return
    
    for device in devices:
        _ha_client.call_service("climate", "set_swing_mode", device["entity_id"], {"swing_mode": "down"})
    
    va.say(f"Опускаю шторки" + (f" в {room}" if room else ""))


def _cmd_get_temperature(va, text):
    if _ha_client is None:
        va.say("Мост не настроен.")
        return
    
    if not text or not text.strip():
        temps = []
        for device in _ha_client.devices.values():
            if device["domain"] != "climate":
                continue
            temp = device["attributes"].get("current_temperature")
            if temp:
                room = device.get("room", "")
                room_str = f" ({room})" if room else ""
                temps.append(f"{device['friendly_name']}{room_str}: {temp}°")
        
        if temps:
            va.say("Температура: " + ", ".join(temps[:5]))
        else:
            va.say("Нет данных о температуре")
        return
    
    _cmd_get_temperature_in_room(va, text)


def _cmd_get_temperature_in_room(va, text):
    if _ha_client is None:
        va.say("Мост не настроен.")
        return
    
    if not text or not text.strip():
        va.say("В какой комнате?")
        return
    
    room = normalize_room(text.strip())
    result = _ha_client.get_temperature_in_room(room)
    
    if result:
        device = result["device"]
        temp = result["temperature"]
        va.say(f"Температура {device['friendly_name']}: {temp} градусов")
    else:
        va.say(f"Не найдено датчиков температуры в комнате '{room}'")


def _cmd_set_temperature(va, text):
    if _ha_client is None or not text:
        va.say("Какую температуру установить?")
        return
    
    match = re.search(r'(\d+)', text)
    if not match:
        va.say("Не удалось распознать число.")
        return
    
    temp = int(match.group(1))
    device_text = re.sub(r'\d+', '', text).strip()
    device_text = re.sub(r'градус(ов|а|)|°', '', device_text).strip()
    
    device = _ha_client.find_device(device_text) if device_text else None
    
    if device is None:
        for d in _ha_client.devices.values():
            if d["domain"] == "climate":
                device = d
                break
    
    if device is None or device["domain"] != "climate":
        va.say("Не найдено устройство климата.")
        return
    
    success = _ha_client.call_service(
        "climate", "set_temperature",
        device["entity_id"],
        {"temperature": temp}
    )
    
    va.say(f"Установлена температура {temp} градусов" if success else "Не удалось")
