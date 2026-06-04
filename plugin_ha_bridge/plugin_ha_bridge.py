"""
Мост между Ириной и Home Assistant v2.1.0

Новое в v2.1.0:
- Управление яркостью света (0-100%, максимум, минимум)
- Относительное изменение яркости (ярче/тусклее на 20%)
- Управление цветовой температурой (теплый/холодный/нейтральный свет)
- Автоматическая проверка поддержки функций устройством
"""

import difflib
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
version = '2.1.0'

_PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
_CACHE_FILE = os.path.join(_PLUGIN_DIR, "ha_bridge_cache.json")

config = {
    "ha_url": "http://homeassistant.local:8123",
    "ha_token": "",
    "refresh_interval": 300,
    "language": "ru",
    "enabled": True,
    "command_prefix": "хаб",
    "ignore_entities": [
        "adaptive_lighting", "browser_mod", "indicator_light", "indicator light",
        "sun_", "zone_", "device_tracker", "persistent_notification", "update_",
        "button_", "number_", "input_", "event.", "calendar.", "todo.", "tts.",
        "stt.", "weather.", "remote.", "siren.",
    ],
    "synonyms": {
        "кондиционер": ["ac", "snow leopard", "conditioner", "climate"],
        "телевизор": ["tv", "television", "media_player"],
        "пылесос": ["robot", "vacuum", "xiaomi"],
        "колонка": ["speaker", "mini", "media"],
        "свет": ["light", "лампа", "лампочка", "люстра", "бра", "торшер", "гирлянда", "ёлка", "подсветка", "led"],
        "розетка": ["switch", "relay", "реле", "выключатель"],
        "датчик": ["sensor"],
        "камера": ["camera", "камера"],
        "сцена": ["scene", "сценарий"],
        "автоматизация": ["automation", "автосценарий"],
    },
    "device_overrides": {
        "гирлянда": "light", "ёлка": "light", "подсветка": "light",
        "led лента": "light", "led": "light",
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
        "ассистент": ["ассистент"], "сервер": ["сервер"],
    },
    "entity_rooms": {
        "sensor.ts0201_temperature": "кухня",
        "sensor.ts0201_humidity": "кухня",
    },
}

config_comment = """
Настройки моста с Home Assistant v2.1.0

Новые команды для света:
- хаб яркость [устройство] [0-100]
- хаб яркость [устройство] на максимум/минимум
- хаб сделай ярче/тусклее [устройство]
- хаб теплый/холодный/нейтральный свет [устройство]
"""

_ha_client = None
_refresh_thread = None
_stop_event = threading.Event()
_timers = {}

NUMBER_WORDS = {
    "одна": 1, "одно": 1, "один": 1, "минуту": 1, "минуты": 1, "минута": 1,
    "две": 2, "два": 2, "три": 3, "четыре": 4, "пять": 5, "шесть": 6, "семь": 7,
    "восемь": 8, "девять": 9, "десять": 10, "одиннадцать": 11, "двенадцать": 12,
    "тринадцать": 13, "четырнадцать": 14, "пятнадцать": 15, "двадцать": 20,
    "тридцать": 30, "сорок": 40, "пятьдесят": 50, "шестьдесят": 60,
    "семьдесят": 70, "восемьдесят": 80, "девяносто": 90, "сто": 100,
    "час": 60, "часа": 60, "часов": 60,
}

# ✅ НОВОЕ: Слова для яркости
BRIGHTNESS_WORDS = {
    "максимум": 100, "макс": 100, "максимальная": 100, "максимально": 100,
    "полная": 100, "полный": 100, "полностью": 100,
    "минимум": 1, "мин": 1, "минимальная": 1, "минимально": 1,
    "половина": 50, "половинная": 50, "средняя": 50, "средне": 50,
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


def is_room_match(device_room: str, target_room: str) -> bool:
    if not target_room:
        return True
    if not device_room:
        return False
    target_norm = normalize_room(target_room)
    device_norm = normalize_room(device_room)
    if not target_norm or not device_norm:
        return False
    return (target_norm == device_norm or 
            target_norm in device_norm or 
            device_norm in target_norm)


def parse_device_and_room(text: str) -> tuple:
    text = text.strip()
    room_match = re.search(r'\s+(в|на)\s+([а-яё\s]+)$', text, re.IGNORECASE)
    if room_match:
        device_type = text[:room_match.start()].strip()
        room = normalize_room(room_match.group(2).strip())
        return device_type, room

    if text.lower().endswith(" везде"):
        return text.rsplit(" ", 1)[0].strip(), "везде"
    
    room_mapping = config.get("room_mapping", {})
    words = text.split()
    if len(words) >= 2:
        for i in range(1, min(3, len(words))):
            potential_room = " ".join(words[-i:])
            normalized_potential = normalize_room(potential_room)
            if normalized_potential and normalized_potential in room_mapping:
                device_type = " ".join(words[:-i]).strip()
                return device_type, normalized_potential
                
    return text, None


# ✅ НОВОЕ: Парсинг яркости
def parse_brightness(text: str) -> Optional[int]:
    """Парсит значение яркости из текста. Возвращает 0-100 или None."""
    text_lower = text.lower().strip()
    
    # Проверяем специальные слова
    for word, value in BRIGHTNESS_WORDS.items():
        if word in text_lower:
            return value
    
    # Ищем число
    match = re.search(r'(\d+)\s*(%|процент|процента|процентов)?', text_lower)
    if match:
        value = int(match.group(1))
        return max(0, min(100, value))
    
    # Числа прописью
    for word, number in NUMBER_WORDS.items():
        if word in text_lower and number <= 100:
            return number
    
    return None


# ✅ НОВОЕ: Разбор команды яркости на устройство и значение
def parse_brightness_command(text: str) -> tuple:
    """Разбирает команду на (устройство, значение_яркости).
    
    Примеры:
    "люстра 50" → ("люстра", 50)
    "люстра на максимум" → ("люстра", 100)
    "led лента 30 процентов" → ("led лента", 30)
    """
    text = text.strip()
    
    # Ищем специальные слова яркости
    for word, value in BRIGHTNESS_WORDS.items():
        pattern = r'^(.+?)\s+(?:на\s+)?' + re.escape(word) + r'$'
        match = re.match(pattern, text, re.IGNORECASE)
        if match:
            device = match.group(1).strip()
            return device, value
    
    # Ищем число с процентами или без
    match = re.search(r'^(.+?)\s+(?:на\s+)?(\d+)\s*(%|процент[аов]?)?\s*$', text, re.IGNORECASE)
    if match:
        device = match.group(1).strip()
        value = int(match.group(2))
        return device, max(0, min(100, value))
    
    # Числа прописью
    for word, number in NUMBER_WORDS.items():
        if number > 100:
            continue
        pattern = r'^(.+?)\s+(?:на\s+)?' + re.escape(word) + r'\s*(процент[аов]?)?\s*$'
        match = re.match(pattern, text, re.IGNORECASE)
        if match:
            device = match.group(1).strip()
            return device, number
    
    return text, None


def parse_number(text: str) -> Optional[int]:
    if not text: return None
    match = re.search(r'(\d+)', text)
    if match: return int(match.group(1))
    text_lower = text.lower().strip()
    for word, number in NUMBER_WORDS.items():
        if word in text_lower: return number
    return None


def extract_minutes(text: str) -> tuple:
    text = text.strip()
    text = re.sub(r'^через\s+', '', text, flags=re.IGNORECASE)
    pattern = r'^(\d+|одна|одно|один|две|два|три|четыре|пять|шесть|семь|восемь|девять|десять|одиннадцать|двенадцать|час)\s*(минут[аыу]?|мин|минуты|минуту|минута|час[аы]?)?\s+(.+)$'
    match = re.match(pattern, text, re.IGNORECASE)
    
    if not match:
        pattern2 = r'^(\d+)\s+(.+)$'
        match2 = re.match(pattern2, text)
        if match2: return int(match2.group(1)), match2.group(2).strip()
        return None, text
    
    number_text = match.group(1)
    unit = match.group(2) or "минут"
    device_query = match.group(3).strip()
    
    minutes = parse_number(number_text)
    if minutes is None: return None, text
    if "час" in unit.lower(): minutes *= 60
    return minutes, device_query


class HaClient:
    def __init__(self, cfg):
        self.config = dict(cfg)
        self.ha_url = cfg.get("ha_url", "").rstrip("/")
        self.token = cfg.get("ha_token", "")
        self.devices = {}
        self.areas = {}
        self._ha_areas = {}
        self._entity_registry = {}
        self._last_update = 0
        self._lock = threading.Lock()
        _LOGGER.info(f"HaClient v2.1.0 created: url={self.ha_url}")
    
    def update_config(self, cfg):
        self.config = dict(cfg)
        self.ha_url = cfg.get("ha_url", "").rstrip("/")
        self.token = cfg.get("ha_token", "")
    
    def _make_request(self, method, path, data=None):
        if not self.token:
            _LOGGER.error("HA token is empty!")
            return None
        url = f"{self.ha_url}{path}"
        headers = {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"}
        try:
            body = json.dumps(data).encode('utf-8') if data else None
            req = urllib.request.Request(url, data=body, headers=headers, method=method)
            with urllib.request.urlopen(req, timeout=10) as response:
                response_data = response.read().decode('utf-8')
                return json.loads(response_data) if response_data else None
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
                "devices": self.devices, "areas": self.areas, "ha_areas": self._ha_areas,
                "entity_registry": self._entity_registry, "timestamp": time.time(), "count": len(self.devices),
            }
            with open(_CACHE_FILE, 'w', encoding='utf-8') as f:
                json.dump(cache_data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            _LOGGER.error(f"Cache save error: {e}", exc_info=True)
    
    def _load_device_cache(self, force=False) -> bool:
        if force: return False
        try:
            if os.path.exists(_CACHE_FILE):
                with open(_CACHE_FILE, 'r', encoding='utf-8') as f:
                    cache = json.load(f)
                    if time.time() - cache.get("timestamp", 0) < 3600:
                        self.devices = cache.get("devices", {})
                        self.areas = cache.get("areas", {})
                        self._ha_areas = cache.get("ha_areas", {})
                        self._entity_registry = cache.get("entity_registry", {})
                        return True
        except Exception as e:
            _LOGGER.debug(f"Cache load error: {e}")
        return False
    
    def _load_ha_areas(self):
        try:
            areas_data = self._make_request("GET", "/api/area_registry/list")
            if not areas_data: return
            for area in areas_data:
                area_id = area.get("area_id", "")
                area_name = area.get("name", "").lower().strip()
                if area_id and area_name:
                    self._ha_areas[area_id] = area_name
        except Exception as e:
            _LOGGER.warning(f"Could not load HA areas: {e}")
    
    def _load_entity_registry(self):
        try:
            registry_data = self._make_request("GET", "/api/entity_registry/list")
            if not registry_data: return
            for entity in registry_data:
                entity_id = entity.get("entity_id", "")
                if entity_id:
                    self._entity_registry[entity_id] = {
                        "area_id": entity.get("area_id", ""),
                        "aliases": entity.get("aliases", []),
                        "hidden": entity.get("hidden", False),
                    }
        except Exception as e:
            _LOGGER.warning(f"Could not load entity registry: {e}")
    
    def refresh_devices(self, force=False):
        current_time = time.time()
        if not force and current_time - self._last_update < 60:
            return self.devices
        if self._load_device_cache(force=force):
            self._last_update = current_time
            return self.devices
        
        self._load_ha_areas()
        self._load_entity_registry()
        states = self._make_request("GET", "/api/states")
        if states is None: return self.devices
        
        with self._lock:
            self.devices = self._parse_devices(states)
            self.areas = self._group_by_areas()
            self._last_update = current_time
            self._save_device_cache()
        return self.devices
    
    def _parse_devices(self, states):
        managed_domains = {"light", "switch", "climate", "cover", "fan", "lock", 
                          "media_player", "vacuum", "scene", "automation", "sensor"}
        devices = {}
        for state in states:
            entity_id = state.get("entity_id", "")
            if "." not in entity_id: continue
            domain = entity_id.split(".")[0]
            if domain not in managed_domains: continue
            attributes = state.get("attributes", {})
            friendly_name = attributes.get("friendly_name", "")
            if not friendly_name: continue
            if self._should_ignore(entity_id, friendly_name): continue
            
            room = self._extract_room(entity_id, attributes, friendly_name)
            aliases = self._entity_registry.get(entity_id, {}).get("aliases", [])
            
            device = {
                "entity_id": entity_id, "domain": domain, "friendly_name": friendly_name,
                "room": room, "aliases": aliases, "state": state.get("state", ""), "attributes": attributes,
            }
            devices[entity_id] = device
        return devices
    
    def _extract_room(self, entity_id, attributes, friendly_name) -> str:
        name_lower = friendly_name.lower()
        entity_lower = entity_id.lower()
        
        if entity_id in self._entity_registry:
            area_id = self._entity_registry[entity_id].get("area_id", "")
            if area_id and area_id in self._ha_areas:
                return self._ha_areas[area_id]
        
        entity_rooms = self.config.get("entity_rooms", {})
        for eid_pattern, room in entity_rooms.items():
            eid_lower = eid_pattern.lower()
            eid_parts = set(eid_lower.replace(".", "_").split("_"))
            entity_parts = set(entity_lower.replace(".", "_").split("_"))
            if len(eid_parts & entity_parts) >= len(eid_parts) * 0.7:
                return normalize_room(room)
        
        room_mapping = config.get("room_mapping", {})
        for canonical_name, variations in room_mapping.items():
            for variation in variations:
                if variation in name_lower: return canonical_name
        
        for area_id, area_name in self._ha_areas.items():
            if area_name in name_lower: return area_name
        return ""
    
    def _group_by_areas(self):
        areas = {}
        for device in self.devices.values():
            room = device.get("room", "без комнаты")
            if room not in areas: areas[room] = []
            areas[room].append(device)
        for room in areas:
            areas[room].sort(key=lambda d: (d['domain'], d['friendly_name']))
        return areas
    
    def call_service(self, domain, service, entity_id, data=None):
        payload = {"entity_id": entity_id}
        if data: payload.update(data)
        result = self._make_request("POST", f"/api/services/{domain}/{service}", data=payload)
        return result is not None
    
    def get_device_type(self, device: Dict) -> str:
        overrides = self.config.get("device_overrides", {})
        name_lower = device["friendly_name"].lower()
        for keyword, override_type in overrides.items():
            if keyword in name_lower: return override_type
        return device["domain"]
    
    # ✅ НОВОЕ: Проверка поддержки функций света
    def light_supports_brightness(self, device: Dict) -> bool:
        """Проверяет, поддерживает ли устройство управление яркостью."""
        if device["domain"] != "light":
            return False
        supported_modes = device["attributes"].get("supported_color_modes", [])
        # Яркость поддерживается во всех режимах кроме "onoff"
        return bool(supported_modes) and "onoff" not in supported_modes
    
    def light_supports_color_temp(self, device: Dict) -> bool:
        """Проверяет, поддерживает ли устройство цветовую температуру."""
        if device["domain"] != "light":
            return False
        supported_modes = device["attributes"].get("supported_color_modes", [])
        return "color_temp" in supported_modes
    
    def get_light_brightness_pct(self, device: Dict) -> int:
        """Получить текущую яркость в процентах (0-100)."""
        brightness = device["attributes"].get("brightness")
        if brightness is None:
            return 0
        return round(brightness / 255 * 100)
    
    def get_light_color_temp_kelvin(self, device: Dict) -> Optional[int]:
        """Получить текущую цветовую температуру в Кельвинах."""
        return device["attributes"].get("color_temp_kelvin")
    
    def find_device_fuzzy(self, query: str, cutoff=0.6) -> Optional[Dict]:
        if not query or not self.devices: return None
        query_lower = query.lower().strip()
        for prep in ["в ", "на ", "о ", "об "]:
            if query_lower.startswith(prep):
                query_lower = query_lower[len(prep):].strip()
        if not query_lower: return None
        
        names, name_to_device = [], {}
        for entity_id, device in self.devices.items():
            friendly_name = device["friendly_name"].lower()
            names.append(friendly_name)
            name_to_device[friendly_name] = device
            for alias in device.get("aliases", []):
                alias_lower = alias.lower()
                names.append(alias_lower)
                name_to_device[alias_lower] = device
        
        if query_lower in name_to_device: return name_to_device[query_lower]
        matches = difflib.get_close_matches(query_lower, names, n=1, cutoff=cutoff)
        if matches: return name_to_device[matches[0]]
        return None
    
    def find_devices_by_type(self, device_type: str) -> List[Dict]:
        type_lower = device_type.lower().strip()
        results = []
        synonyms = self.config.get("synonyms", {})
        overrides = self.config.get("device_overrides", {})
        type_synonyms = set([type_lower])
        for keyword, syns in synonyms.items():
            if keyword == type_lower or type_lower in syns:
                type_synonyms.update(syns); type_synonyms.add(keyword)
        for keyword, override_type in overrides.items():
            if override_type == type_lower: type_synonyms.add(keyword)
        
        for device in self.devices.values():
            actual_type = self.get_device_type(device)
            name_lower = device["friendly_name"].lower()
            if actual_type == type_lower:
                results.append(device); continue
            for syn in type_synonyms:
                if syn in name_lower: results.append(device); break
        results.sort(key=lambda d: d['friendly_name'])
        return results
    
    def find_scene(self, query: str) -> Optional[Dict]:
        query_lower = query.lower().strip()
        if not query_lower: return None
        candidates = [d for d in self.devices.values() if d["domain"] == "scene"]
        for scene in candidates:
            if scene["friendly_name"].lower() == query_lower: return scene
            if query_lower in scene["entity_id"].lower(): return scene
        names = [s["friendly_name"].lower() for s in candidates]
        matches = difflib.get_close_matches(query_lower, names, n=1, cutoff=0.6)
        if matches:
            for scene in candidates:
                if scene["friendly_name"].lower() == matches[0]: return scene
        return None
    
    def find_automation(self, query: str) -> Optional[Dict]:
        query_lower = query.lower().strip()
        if not query_lower: return None
        candidates = [d for d in self.devices.values() if d["domain"] == "automation"]
        for auto in candidates:
            if auto["friendly_name"].lower() == query_lower: return auto
        names = [a["friendly_name"].lower() for a in candidates]
        matches = difflib.get_close_matches(query_lower, names, n=1, cutoff=0.6)
        if matches:
            for auto in candidates:
                if auto["friendly_name"].lower() == matches[0]: return auto
        for auto in candidates:
            entity_id_clean = auto["entity_id"].replace("automation.", "").lower()
            if query_lower in entity_id_clean or entity_id_clean in query_lower: return auto
        return None
    
    def find_all_devices_in_room(self, room: str) -> List[Dict]:
        room_normalized = normalize_room(room)
        results = []
        controllable_domains = {"light", "switch", "fan", "media_player"}
        for device in self.devices.values():
            if device["domain"] not in controllable_domains: continue
            if is_room_match(device.get("room", ""), room_normalized):
                results.append(device)
        results.sort(key=lambda d: d['friendly_name'])
        return results
    
    def find_devices_by_type_and_room(self, device_type: str, room: str) -> List[Dict]:
        type_lower = device_type.lower().strip()
        room_normalized = normalize_room(room)
        results = []
        synonyms = self.config.get("synonyms", {})
        overrides = self.config.get("device_overrides", {})
        type_synonyms = set([type_lower])
        for keyword, syns in synonyms.items():
            if keyword == type_lower or type_lower in syns:
                type_synonyms.update(syns); type_synonyms.add(keyword)
        for keyword, override_type in overrides.items():
            if override_type == type_lower: type_synonyms.add(keyword)
        
        for device in self.devices.values():
            if room_normalized:
                if not is_room_match(device.get("room", ""), room_normalized):
                    continue
            actual_type = self.get_device_type(device)
            name_lower = device["friendly_name"].lower()
            if actual_type == type_lower:
                results.append(device); continue
            for syn in type_synonyms:
                if syn in name_lower: results.append(device); break
        results.sort(key=lambda d: d['friendly_name'])
        return results
    
    def get_rooms(self) -> List[str]:
        rooms = set()
        for device in self.devices.values():
            room = device.get("room", "")
            if room: rooms.add(room)
        return sorted(list(rooms))
    
    def get_temperature_in_room(self, room: str) -> Optional[Dict]:
        room_normalized = normalize_room(room)
        
        for device in self.devices.values():
            if device["domain"] != "climate": continue
            if is_room_match(device.get("room", ""), room_normalized):
                temp = device["attributes"].get("current_temperature")
                if temp: return {"device": device, "temperature": temp, "type": "climate"}
        
        candidates = []
        for device in self.devices.values():
            if device["domain"] != "sensor": continue
            entity_id = device["entity_id"].lower()
            friendly_name = device["friendly_name"].lower()
            
            room_match = False
            if room_normalized:
                if is_room_match(device.get("room", ""), room_normalized):
                    room_match = True
                elif room_normalized in entity_id:
                    room_match = True
            
            if not room_normalized or room_match:
                attributes = device["attributes"]
                device_class = attributes.get("device_class", "")
                unit = attributes.get("unit_of_measurement", "")
                
                is_battery = "battery" in entity_id or "battery" in friendly_name or device_class == "battery"
                if is_battery: continue
                
                is_temperature = (device_class == "temperature" or 
                                  "градус" in unit.lower() or "°c" in unit or "°f" in unit or
                                  "temperature" in entity_id or "temp" in entity_id)
                
                if is_temperature:
                    try:
                        temp = float(device["state"])
                        candidates.append({"device": device, "temperature": temp, "type": "sensor"})
                    except (ValueError, TypeError): continue
        
        if candidates:
            candidates.sort(key=lambda c: "mi" in c["device"]["friendly_name"].lower())
            return candidates[0]
        return None


def receive_config(cfg, *_args, **_kwargs):
    global config, _ha_client
    if cfg: config.update(cfg)
    token = config.get("ha_token", "")
    enabled = config.get("enabled", True)
    if enabled and token:
        if _ha_client is None: _ha_client = HaClient(config)
        else: _ha_client.update_config(config)

def init(*_args, **_kwargs):
    global _ha_client
    if _ha_client is None:
        if not config.get("enabled", True) or not config.get("ha_token"): return
        _ha_client = HaClient(config)

def run(*_args, **_kwargs):
    global _refresh_thread
    if _ha_client is None: return
    _stop_event.clear()
    try:
        devices = _ha_client.refresh_devices()
        _LOGGER.info(f"HA Bridge: Loaded {len(devices)} devices")
    except Exception as e:
        _LOGGER.error(f"HA Bridge: Initial load error: {e}", exc_info=True)
    _refresh_thread = threading.Thread(target=_background_refresh, daemon=True)
    _refresh_thread.start()

def terminate(*_args, **_kwargs):
    _stop_event.set()
    _timers.clear()

def _background_refresh():
    interval = config.get("refresh_interval", 300)
    while not _stop_event.is_set():
        _stop_event.wait(interval)
        if _stop_event.is_set(): break
        try:
            if _ha_client: _ha_client.refresh_devices()
        except Exception as e:
            _LOGGER.error(f"Background refresh error: {e}")


def define_commands(*_args, **_kwargs):
    prefix = config.get("command_prefix", "хаб")
    return {
        # Базовые
        f"{prefix} обнови устройства": _cmd_refresh_devices,
        f"{prefix} обновить устройства": _cmd_refresh_devices,
        f"{prefix} список устройств": _cmd_list_devices,
        f"{prefix} какие комнаты": _cmd_list_rooms,
        f"{prefix} что в": _cmd_what_in_room,
        f"{prefix} что включено": _cmd_what_is_on,
        f"{prefix} помощь": _cmd_help,
        f"{prefix} что загружено": _cmd_what_loaded,
        f"{prefix} диагностика": _cmd_diagnostics,
        
        # Включение/выключение
        f"{prefix} включи": _cmd_turn_on_generic,
        f"{prefix} выключи": _cmd_turn_off_generic,
        f"{prefix} включи через": _cmd_turn_on_delayed,
        f"{prefix} выключи через": _cmd_turn_off_delayed,
        
        # Сцены и автоматизации
        f"{prefix} включи сцену": _cmd_activate_scene,
        f"{prefix} активируй сцену": _cmd_activate_scene,
        f"{prefix} запусти сцену": _cmd_activate_scene,
        f"{prefix} сцену": _cmd_activate_scene,
        f"{prefix} запусти": _cmd_trigger_automation,
        f"{prefix} активируй": _cmd_trigger_automation,
        
        # Всё в комнате
        f"{prefix} включи всё в": _cmd_all_in_room_on,
        f"{prefix} включи всё на": _cmd_all_in_room_on,
        f"{prefix} выключи всё в": _cmd_all_in_room_off,
        f"{prefix} выключи всё на": _cmd_all_in_room_off,
        
        # Климат
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
        
        # ✅ НОВОЕ: Управление яркостью
        f"{prefix} яркость": _cmd_set_brightness,
        f"{prefix} поставь яркость": _cmd_set_brightness,
        f"{prefix} установи яркость": _cmd_set_brightness,
        f"{prefix} сделай яркость": _cmd_set_brightness,
        f"{prefix} сделай ярче": _cmd_brightness_up,
        f"{prefix} сделай тусклее": _cmd_brightness_down,
        f"{prefix} максимальная яркость": _cmd_brightness_max,
        f"{prefix} минимальная яркость": _cmd_brightness_min,
        
        # ✅ НОВОЕ: Цветовая температура
        f"{prefix} теплый свет": _cmd_color_temp_warm,
        f"{prefix} холодный свет": _cmd_color_temp_cold,
        f"{prefix} нейтральный свет": _cmd_color_temp_neutral,
        f"{prefix} белый свет": _cmd_color_temp_neutral,
    }


def _cmd_help(va, text):
    prefix = config.get("command_prefix", "хаб")
    va.say(f"Команды '{prefix}':\n"
           f"• включи/выключи [устройство]\n"
           f"• включи/выключи [тип] везде\n"
           f"• включи/выключи через [мин] [устройство]\n"
           f"• включи/выключи всё в [комнате]\n"
           f"• яркость [устройство] [0-100 или максимум/минимум]\n"
           f"• сделай ярче/тусклее [устройство]\n"
           f"• теплый/холодный/нейтральный свет [устройство]\n"
           f"• какая температура / температура в [комнате]\n"
           f"• обнови устройства / список устройств / диагностика")


def _cmd_diagnostics(va, text):
    if _ha_client is None: va.say("Мост не настроен."); return
    devices = _ha_client.devices
    if not devices: va.say("Устройства не загружены."); return
    
    by_domain = {}
    for device in devices.values():
        domain = device["domain"]
        if domain not in by_domain: by_domain[domain] = []
        by_domain[domain].append(device)
    
    domain_names = {
        "light": "Свет", "switch": "Розетки", "climate": "Климат", "cover": "Шторы",
        "fan": "Вентиляторы", "lock": "Замки", "media_player": "Медиа", "vacuum": "Пылесосы",
        "sensor": "Датчики", "scene": "Сцены", "automation": "Автоматизации",
    }
    
    response_parts = []
    for domain, devs in by_domain.items():
        type_name = domain_names.get(domain, domain)
        names = [f"{d['friendly_name']} ({d['room'] or 'без комнаты'})" for d in devs[:3]]
        response_parts.append(f"{type_name} ({len(devs)}): {', '.join(names)}")
        if len(devs) > 3: response_parts[-1] += f" и ещё {len(devs) - 3}"
    
    rooms = _ha_client.get_rooms()
    rooms_str = f". Комнаты: {', '.join(rooms[:5])}" if rooms else ""
    va.say(f"Загружено {len(devices)} устройств{rooms_str}. {'. '.join(response_parts[:6])}")


def _cmd_what_loaded(va, text): _cmd_diagnostics(va, text)

def _cmd_refresh_devices(va, text):
    if _ha_client is None: va.say("Мост не настроен."); return
    try:
        devices = _ha_client.refresh_devices(force=True)
        if not devices: va.say("Устройства не найдены."); return
        by_domain = {}
        for device in devices.values():
            domain = device["domain"]
            by_domain[domain] = by_domain.get(domain, 0) + 1
        parts = []
        domain_names = {
            "light": "свет", "switch": "розеток", "climate": "климат", "cover": "штор",
            "fan": "вентиляторов", "lock": "замков", "media_player": "медиа", "vacuum": "пылесосов",
            "sensor": "датчиков", "scene": "сцен", "automation": "автоматизаций",
        }
        for domain, cnt in by_domain.items():
            parts.append(f"{cnt} {domain_names.get(domain, domain)}")
        rooms = _ha_client.get_rooms()
        rooms_str = f". Комнаты: {', '.join(rooms[:5])}" if rooms else ""
        va.say(f"Обновлено. Найдено {len(devices)} устройств: " + ", ".join(parts) + rooms_str)
    except Exception as e:
        va.say(f"Ошибка: {e}")


def _cmd_list_devices(va, text):
    if _ha_client is None or not _ha_client.devices: va.say("Устройства не найдены."); return
    by_room = _ha_client.areas if _ha_client.areas else {}
    response_parts = []
    for room, devices in by_room.items():
        names = [d["friendly_name"] for d in devices[:5]]
        response_parts.append(f"В {room}: " + ", ".join(names))
        if len(devices) > 5: response_parts[-1] += f" и ещё {len(devices) - 5}"
    va.say(". ".join(response_parts[:6]))


def _cmd_list_rooms(va, text):
    if _ha_client is None: va.say("Мост не настроен."); return
    rooms = _ha_client.get_rooms()
    va.say("Комнаты: " + ", ".join(rooms) if rooms else "Комнаты не определены.")


def _cmd_what_in_room(va, text):
    if _ha_client is None: va.say("Мост не настроен."); return
    if not text or not text.strip(): va.say("Какую комнату?"); return
    room = normalize_room(text.strip())
    useful_domains = {"light", "switch", "climate", "cover", "fan", "lock", "media_player", "vacuum", "scene", "automation"}
    devices = [d for d in _ha_client.devices.values() if d["domain"] in useful_domains and is_room_match(d.get("room", ""), room)]
    if not devices: va.say(f"В комнате '{room}' нет устройств."); return
    
    by_type = {}
    for device in devices:
        domain = device["domain"]
        if domain not in by_type: by_type[domain] = []
        by_type[domain].append(device["friendly_name"])
    
    type_names = {"light": "Свет", "switch": "Розетки", "climate": "Климат", "cover": "Шторы", "fan": "Вентиляторы", "lock": "Замки", "media_player": "Медиа", "vacuum": "Пылесосы", "scene": "Сцены", "automation": "Автоматизации"}
    response_parts = []
    for domain, names in by_type.items():
        type_name = type_names.get(domain, domain)
        names_str = ", ".join(names[:5])
        if len(names) > 5: names_str += f" и ещё {len(names) - 5}"
        response_parts.append(f"{type_name}: {names_str}")
    va.say(f"В {room}: {'. '.join(response_parts[:5])}")


def _cmd_what_is_on(va, text):
    if _ha_client is None or not _ha_client.devices: va.say("Устройства не найдены."); return
    on_devices = [d["friendly_name"] for d in _ha_client.devices.values() if d.get("state", "") in ("on", "open", "unlocked", "playing", "cool", "heat", "fan_only")]
    va.say("Включено: " + ", ".join(on_devices[:10]) if on_devices else "Все устройства выключены.")


def _turn_on_device(device):
    entity_id = device["entity_id"]
    domain = device["domain"]
    if domain == "light": _ha_client.call_service("light", "turn_on", entity_id)
    elif domain == "switch": _ha_client.call_service("switch", "turn_on", entity_id)
    elif domain == "climate":
        _ha_client.call_service("climate", "turn_on", entity_id)
        if device["attributes"].get("hvac_mode") in ["off", "unavailable"]:
            _ha_client.call_service("climate", "set_hvac_mode", entity_id, {"hvac_mode": "cool"})
    elif domain == "fan": _ha_client.call_service("fan", "turn_on", entity_id)
    elif domain == "media_player": _ha_client.call_service("media_player", "turn_on", entity_id)
    elif domain == "vacuum": _ha_client.call_service("vacuum", "start", entity_id)


def _turn_off_device(device):
    entity_id = device["entity_id"]
    domain = device["domain"]
    if domain == "light": _ha_client.call_service("light", "turn_off", entity_id)
    elif domain == "switch": _ha_client.call_service("switch", "turn_off", entity_id)
    elif domain == "climate": _ha_client.call_service("climate", "turn_off", entity_id)
    elif domain == "fan": _ha_client.call_service("fan", "turn_off", entity_id)
    elif domain == "media_player": _ha_client.call_service("media_player", "turn_off", entity_id)
    elif domain == "vacuum": _ha_client.call_service("vacuum", "return_to_base", entity_id)


def _cmd_turn_on_generic(va, text):
    if _ha_client is None: va.say("Мост не настроен."); return
    if not text or not text.strip(): va.say("Какое устройство включить?"); return
    text = text.strip()
    
    device = _ha_client.find_device_fuzzy(text)
    if device is not None:
        _turn_on_device(device)
        va.say(f"Включаю {device['friendly_name']}")
        return
    
    device_type, room = parse_device_and_room(text)
    
    if room == "везде":
        devices = _ha_client.find_devices_by_type(device_type)
        if not devices: va.say(f"Не найдено устройств типа '{device_type}'."); return
        for d in devices: _turn_on_device(d)
        va.say(f"Включаю {len(devices)} устройств типа '{device_type}' везде")
        return
        
    if room:
        devices = _ha_client.find_devices_by_type_and_room(device_type, room)
        if not devices: va.say(f"Не найдено устройств '{device_type}' в комнате '{room}'."); return
        for d in devices: _turn_on_device(d)
        if len(devices) == 1: va.say(f"Включаю {devices[0]['friendly_name']}")
        else: va.say(f"Включаю {len(devices)} устройств в {room}")
        return

    va.say(f"Устройство '{text}' не найдено.")


def _cmd_turn_off_generic(va, text):
    if _ha_client is None: va.say("Мост не настроен."); return
    if not text or not text.strip(): va.say("Какое устройство выключить?"); return
    text = text.strip()
    
    device = _ha_client.find_device_fuzzy(text)
    if device is not None:
        _turn_off_device(device)
        va.say(f"Выключаю {device['friendly_name']}")
        return
    
    device_type, room = parse_device_and_room(text)
    
    if room == "везде":
        devices = _ha_client.find_devices_by_type(device_type)
        if not devices: va.say(f"Не найдено устройств типа '{device_type}'."); return
        for d in devices: _turn_off_device(d)
        va.say(f"Выключаю {len(devices)} устройств типа '{device_type}' везде")
        return
        
    if room:
        devices = _ha_client.find_devices_by_type_and_room(device_type, room)
        if not devices: va.say(f"Не найдено устройств '{device_type}' в комнате '{room}'."); return
        for d in devices: _turn_off_device(d)
        if len(devices) == 1: va.say(f"Выключаю {devices[0]['friendly_name']}")
        else: va.say(f"Выключаю {len(devices)} устройств в {room}")
        return

    va.say(f"Устройство '{text}' не найдено.")


def _cmd_turn_on_delayed(va, text):
    if _ha_client is None: va.say("Мост не настроен."); return
    if not text: va.say("Пример: хаб включи через 5 минут свет"); return
    minutes, device_query = extract_minutes(text)
    if minutes is None: va.say("Не удалось распознать время."); return
    device = _ha_client.find_device_fuzzy(device_query)
    if device is None: va.say(f"Не найдено устройство '{device_query}'."); return
    
    def delayed():
        time.sleep(minutes * 60)
        _turn_on_device(device)
    threading.Thread(target=delayed, daemon=True).start()
    va.say(f"Хорошо, включу {device['friendly_name']} через {minutes} минут")


def _cmd_turn_off_delayed(va, text):
    if _ha_client is None: va.say("Мост не настроен."); return
    if not text: va.say("Пример: хаб выключи через 10 минут свет"); return
    minutes, device_query = extract_minutes(text)
    if minutes is None: va.say("Не удалось распознать время."); return
    device = _ha_client.find_device_fuzzy(device_query)
    if device is None: va.say(f"Не найдено устройство '{device_query}'."); return
    
    def delayed():
        time.sleep(minutes * 60)
        _turn_off_device(device)
    threading.Thread(target=delayed, daemon=True).start()
    va.say(f"Хорошо, выключу {device['friendly_name']} через {minutes} минут")


def _cmd_activate_scene(va, text):
    if _ha_client is None: va.say("Мост не настроен."); return
    if not text or not text.strip(): va.say("Какую сцену включить?"); return
    scene = _ha_client.find_scene(text.strip())
    if scene is None:
        scenes = [d["friendly_name"] for d in _ha_client.devices.values() if d["domain"] == "scene"]
        va.say(f"Сцена не найдена. Доступные: " + ", ".join(scenes[:7]) if scenes else "Сцены не настроены.")
        return
    if _ha_client.call_service("scene", "turn_on", scene["entity_id"]):
        va.say(f"Включаю сцену {scene['friendly_name']}")


def _cmd_trigger_automation(va, text):
    if _ha_client is None: va.say("Мост не настроен."); return
    if not text or not text.strip(): va.say("Что запустить?"); return
    auto = _ha_client.find_automation(text.strip())
    if auto is None:
        autos = [d["friendly_name"] for d in _ha_client.devices.values() if d["domain"] == "automation"]
        va.say(f"Автоматизация не найдена. Доступные: " + ", ".join(autos[:7]) if autos else "Автоматизации не найдены.")
        return
    if _ha_client.call_service("automation", "trigger", auto["entity_id"]):
        va.say(f"Запускаю {auto['friendly_name']}")


def _cmd_all_in_room_on(va, text):
    if _ha_client is None: va.say("Мост не настроен."); return
    if not text or not text.strip(): va.say("В какой комнате?"); return
    room = normalize_room(text.strip())
    devices = _ha_client.find_all_devices_in_room(room)
    if not devices: va.say(f"В комнате '{room}' нет устройств."); return
    for d in devices: _turn_on_device(d)
    va.say(f"Включаю всё в {room} ({len(devices)} устройств)")


def _cmd_all_in_room_off(va, text):
    if _ha_client is None: va.say("Мост не настроен."); return
    if not text or not text.strip(): va.say("В какой комнате?"); return
    room = normalize_room(text.strip())
    devices = _ha_client.find_all_devices_in_room(room)
    if not devices: va.say(f"В комнате '{room}' нет устройств."); return
    for d in devices: _turn_off_device(d)
    va.say(f"Выключаю всё в {room} ({len(devices)} устройств)")


# ✅ НОВЫЕ КОМАНДЫ: Управление яркостью

def _cmd_set_brightness(va, text):
    """Установить яркость: 'хаб яркость люстра 50' или 'хаб яркость люстра на максимум'."""
    if _ha_client is None:
        va.say("Мост не настроен."); return
    if not text or not text.strip():
        va.say("Пример: хаб яркость люстра 50 или хаб яркость люстра на максимум"); return
    
    device_name, brightness = parse_brightness_command(text.strip())
    
    if brightness is None:
        va.say("Не удалось распознать значение яркости. Используйте число от 0 до 100 или слова: максимум, минимум, половина.")
        return
    
    device = _ha_client.find_device_fuzzy(device_name)
    if device is None:
        va.say(f"Устройство '{device_name}' не найдено."); return
    
    if device["domain"] != "light":
        va.say(f"{device['friendly_name']} не является светильником."); return
    
    if not _ha_client.light_supports_brightness(device):
        va.say(f"{device['friendly_name']} не поддерживает управление яркостью."); return
    
    # Если свет выключен - включаем его
    if device["state"] != "on":
        _ha_client.call_service("light", "turn_on", device["entity_id"])
    
    # Устанавливаем яркость
    success = _ha_client.call_service(
        "light", "turn_on", 
        device["entity_id"],
        {"brightness_pct": brightness}
    )
    
    if success:
        if brightness == 100:
            va.say(f"Яркость {device['friendly_name']} на максимуме")
        elif brightness <= 1:
            va.say(f"Яркость {device['friendly_name']} на минимуме")
        else:
            va.say(f"Яркость {device['friendly_name']} установлена на {brightness} процентов")
    else:
        va.say(f"Не удалось установить яркость {device['friendly_name']}")


def _cmd_brightness_up(va, text):
    """Увеличить яркость на 20%: 'хаб сделай ярче люстра'."""
    if _ha_client is None:
        va.say("Мост не настроен."); return
    if not text or not text.strip():
        va.say("Какое устройство?"); return
    
    device = _ha_client.find_device_fuzzy(text.strip())
    if device is None:
        va.say(f"Устройство '{text}' не найдено."); return
    
    if device["domain"] != "light":
        va.say(f"{device['friendly_name']} не является светильником."); return
    
    if not _ha_client.light_supports_brightness(device):
        va.say(f"{device['friendly_name']} не поддерживает управление яркостью."); return
    
    current = _ha_client.get_light_brightness_pct(device)
    new_brightness = min(100, current + 20)
    
    if device["state"] != "on":
        _ha_client.call_service("light", "turn_on", device["entity_id"])
    
    success = _ha_client.call_service(
        "light", "turn_on",
        device["entity_id"],
        {"brightness_pct": new_brightness}
    )
    
    if success:
        va.say(f"Яркость {device['friendly_name']}: {new_brightness} процентов")


def _cmd_brightness_down(va, text):
    """Уменьшить яркость на 20%: 'хаб сделай тусклее люстра'."""
    if _ha_client is None:
        va.say("Мост не настроен."); return
    if not text or not text.strip():
        va.say("Какое устройство?"); return
    
    device = _ha_client.find_device_fuzzy(text.strip())
    if device is None:
        va.say(f"Устройство '{text}' не найдено."); return
    
    if device["domain"] != "light":
        va.say(f"{device['friendly_name']} не является светильником."); return
    
    if not _ha_client.light_supports_brightness(device):
        va.say(f"{device['friendly_name']} не поддерживает управление яркостью."); return
    
    current = _ha_client.get_light_brightness_pct(device)
    new_brightness = max(1, current - 20)
    
    if device["state"] != "on":
        _ha_client.call_service("light", "turn_on", device["entity_id"])
    
    success = _ha_client.call_service(
        "light", "turn_on",
        device["entity_id"],
        {"brightness_pct": new_brightness}
    )
    
    if success:
        va.say(f"Яркость {device['friendly_name']}: {new_brightness} процентов")


def _cmd_brightness_max(va, text):
    """Максимальная яркость: 'хаб максимальная яркость люстра'."""
    if _ha_client is None:
        va.say("Мост не настроен."); return
    if not text or not text.strip():
        va.say("Какое устройство?"); return
    
    device = _ha_client.find_device_fuzzy(text.strip())
    if device is None:
        va.say(f"Устройство '{text}' не найдено."); return
    
    if device["domain"] != "light":
        va.say(f"{device['friendly_name']} не является светильником."); return
    
    if not _ha_client.light_supports_brightness(device):
        va.say(f"{device['friendly_name']} не поддерживает управление яркостью."); return
    
    if device["state"] != "on":
        _ha_client.call_service("light", "turn_on", device["entity_id"])
    
    success = _ha_client.call_service(
        "light", "turn_on",
        device["entity_id"],
        {"brightness_pct": 100}
    )
    
    if success:
        va.say(f"Яркость {device['friendly_name']} на максимуме")


def _cmd_brightness_min(va, text):
    """Минимальная яркость: 'хаб минимальная яркость люстра'."""
    if _ha_client is None:
        va.say("Мост не настроен."); return
    if not text or not text.strip():
        va.say("Какое устройство?"); return
    
    device = _ha_client.find_device_fuzzy(text.strip())
    if device is None:
        va.say(f"Устройство '{text}' не найдено."); return
    
    if device["domain"] != "light":
        va.say(f"{device['friendly_name']} не является светильником."); return
    
    if not _ha_client.light_supports_brightness(device):
        va.say(f"{device['friendly_name']} не поддерживает управление яркостью."); return
    
    if device["state"] != "on":
        _ha_client.call_service("light", "turn_on", device["entity_id"])
    
    success = _ha_client.call_service(
        "light", "turn_on",
        device["entity_id"],
        {"brightness_pct": 1}
    )
    
    if success:
        va.say(f"Яркость {device['friendly_name']} на минимуме")


# ✅ НОВЫЕ КОМАНДЫ: Цветовая температура

def _set_color_temp_kelvin(va, device_name: str, kelvin: int, description: str):
    """Установить цветовую температуру в Кельвинах."""
    if _ha_client is None:
        va.say("Мост не настроен."); return
    if not device_name:
        va.say("Какое устройство?"); return
    
    device = _ha_client.find_device_fuzzy(device_name)
    if device is None:
        va.say(f"Устройство '{device_name}' не найдено."); return
    
    if device["domain"] != "light":
        va.say(f"{device['friendly_name']} не является светильником."); return
    
    if not _ha_client.light_supports_color_temp(device):
        va.say(f"{device['friendly_name']} не поддерживает регулировку цветовой температуры."); return
    
    if device["state"] != "on":
        _ha_client.call_service("light", "turn_on", device["entity_id"])
    
    success = _ha_client.call_service(
        "light", "turn_on",
        device["entity_id"],
        {"kelvin": kelvin}
    )
    
    if success:
        va.say(f"{description} свет на {device['friendly_name']}")


def _cmd_color_temp_warm(va, text):
    """Теплый свет (~2700K): 'хаб теплый свет люстра'."""
    _set_color_temp_kelvin(va, text.strip() if text else "", 2700, "Теплый")


def _cmd_color_temp_cold(va, text):
    """Холодный свет (~6500K): 'хаб холодный свет люстра'."""
    _set_color_temp_kelvin(va, text.strip() if text else "", 6500, "Холодный")


def _cmd_color_temp_neutral(va, text):
    """Нейтральный белый свет (~4000K): 'хаб нейтральный свет люстра'."""
    _set_color_temp_kelvin(va, text.strip() if text else "", 4000, "Нейтральный")


# Климат (без изменений)

def _get_climate_devices(room: str) -> list:
    if room:
        return _ha_client.find_devices_by_type_and_room("climate", room)
    return [d for d in _ha_client.devices.values() if d["domain"] == "climate"]


def _cmd_climate_ventilation(va, text):
    if _ha_client is None: va.say("Мост не настроен."); return
    room = normalize_room(text.strip()) if text and text.strip() else ""
    devices = _get_climate_devices(room)
    if not devices: va.say("Не найдено кондиционеров."); return
    for d in devices: _ha_client.call_service("climate", "set_hvac_mode", d["entity_id"], {"hvac_mode": "fan_only"})
    va.say(f"Включаю вентиляцию" + (f" в {room}" if room else ""))


def _cmd_climate_warmer(va, text):
    if _ha_client is None: va.say("Мост не настроен."); return
    room = normalize_room(text.strip()) if text and text.strip() else ""
    devices = _get_climate_devices(room)
    if not devices: va.say("Не найдено кондиционеров."); return
    for d in devices:
        new_temp = d["attributes"].get("temperature", 22) + 2
        _ha_client.call_service("climate", "set_temperature", d["entity_id"], {"temperature": new_temp})
    va.say(f"Делаю теплее" + (f" в {room}" if room else ""))


def _cmd_climate_cooler(va, text):
    if _ha_client is None: va.say("Мост не настроен."); return
    room = normalize_room(text.strip()) if text and text.strip() else ""
    devices = _get_climate_devices(room)
    if not devices: va.say("Не найдено кондиционеров."); return
    for d in devices:
        new_temp = d["attributes"].get("temperature", 22) - 2
        _ha_client.call_service("climate", "set_temperature", d["entity_id"], {"temperature": new_temp})
    va.say(f"Делаю холоднее" + (f" в {room}" if room else ""))


def _cmd_climate_swing_up(va, text):
    if _ha_client is None: va.say("Мост не настроен."); return
    room = normalize_room(text.strip()) if text and text.strip() else ""
    devices = _get_climate_devices(room)
    if not devices: va.say("Не найдено кондиционеров."); return
    for d in devices: _ha_client.call_service("climate", "set_swing_mode", d["entity_id"], {"swing_mode": "up"})
    va.say(f"Поднимаю шторки" + (f" в {room}" if room else ""))


def _cmd_climate_swing_down(va, text):
    if _ha_client is None: va.say("Мост не настроен."); return
    room = normalize_room(text.strip()) if text and text.strip() else ""
    devices = _get_climate_devices(room)
    if not devices: va.say("Не найдено кондиционеров."); return
    for d in devices: _ha_client.call_service("climate", "set_swing_mode", d["entity_id"], {"swing_mode": "down"})
    va.say(f"Опускаю шторки" + (f" в {room}" if room else ""))


def _cmd_get_temperature(va, text):
    if _ha_client is None: va.say("Мост не настроен."); return
    if not text or not text.strip():
        temps = []
        for device in _ha_client.devices.values():
            if device["domain"] != "climate": continue
            temp = device["attributes"].get("current_temperature")
            if temp:
                room = device.get("room", "")
                temps.append(f"{device['friendly_name']} ({room}): {temp}°" if room else f"{device['friendly_name']}: {temp}°")
        va.say("Температура: " + ", ".join(temps[:5]) if temps else "Нет данных о температуре")
        return
    _cmd_get_temperature_in_room(va, text)


def _cmd_get_temperature_in_room(va, text):
    if _ha_client is None: va.say("Мост не настроен."); return
    if not text or not text.strip(): va.say("В какой комнате?"); return
    room = normalize_room(text.strip())
    result = _ha_client.get_temperature_in_room(room)
    if result:
        va.say(f"Температура {result['device']['friendly_name']}: {result['temperature']} градусов")
    else:
        temp_sensors = [d for d in _ha_client.devices.values() if d["domain"] == "sensor" and 
                       ("temperature" in d["entity_id"].lower() or d["attributes"].get("device_class") == "temperature") and
                       "battery" not in d["entity_id"].lower() and "battery" not in d["friendly_name"].lower()]
        if temp_sensors:
            sensor_list = ", ".join([f"{d['friendly_name']}" for d in temp_sensors[:3]])
            va.say(f"Не найдено датчиков в комнате '{room}'. Найдены: {sensor_list}. Добавьте их в entity_rooms.")
        else:
            va.say(f"Не найдено датчиков температуры в комнате '{room}'.")


def _cmd_set_temperature(va, text):
    if _ha_client is None or not text: va.say("Какую температуру установить?"); return
    match = re.search(r'(\d+)', text)
    if not match: va.say("Не удалось распознать число."); return
    temp = int(match.group(1))
    device_text = re.sub(r'\d+|градус(ов|а|)|°', '', text).strip()
    device = _ha_client.find_device_fuzzy(device_text) if device_text else None
    if device is None:
        for d in _ha_client.devices.values():
            if d["domain"] == "climate": device = d; break
    if device is None or device["domain"] != "climate": va.say("Не найдено устройство климата."); return
    if _ha_client.call_service("climate", "set_temperature", device["entity_id"], {"temperature": temp}):
        va.say(f"Установлена температура {temp} градусов")
