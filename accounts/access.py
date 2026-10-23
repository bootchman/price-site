"""Список доступа: кто из Telegram может входить на сайт.

Файл allowed.json выгружает из Google Таблицы root-скрипт deploy/price_access_sync.py
(у сайта нет доступа к токену Google). Если файла нет — не пускаем никого.
"""
import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path

from django.conf import settings

log = logging.getLogger(__name__)

_cache = {"mtime": None, "entries": []}


FULL, LAND = "full", "land"
ROLE_ALIASES = {"": FULL, "суперадмин": FULL, "суша": LAND}


@dataclass(frozen=True)
class Entry:
    phone: str
    nick: str
    row: int
    role: str = ""

    @property
    def access(self):
        """«full» — весь сайт, «land» — только «Сравнение суши», None — роль не распознана."""
        return ROLE_ALIASES.get(self.role.strip().lower())


def normalize_phone(value) -> str:
    return re.sub(r"\D", "", str(value or ""))


def normalize_nick(value) -> str:
    return str(value or "").strip().lstrip("@").lower()


def phones_match(a: str, b: str) -> bool:
    a, b = normalize_phone(a), normalize_phone(b)
    if not a or not b:
        return False
    if a == b:
        return True
    # Номер мог быть записан без кода страны: сравниваем последние 9 цифр.
    return len(a) >= 9 and len(b) >= 9 and a[-9:] == b[-9:]


def load_entries(path: Path = None) -> list:
    path = Path(path or settings.ACCESS_LIST_FILE)
    try:
        mtime = path.stat().st_mtime
    except FileNotFoundError:
        log.warning("Список доступа %s не найден — вход закрыт для всех", path)
        return []
    if _cache["mtime"] != mtime:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            _cache["entries"] = [
                Entry(normalize_phone(e.get("phone")), normalize_nick(e.get("nick")), int(e.get("row") or 0),
                      str(e.get("role") or ""))
                for e in data.get("entries", [])
            ]
            _cache["mtime"] = mtime
        except (ValueError, OSError) as exc:
            log.error("Не удалось прочитать список доступа %s: %s", path, exc)
            return _cache["entries"]
    return _cache["entries"]


def find_entry(phone: str = "", username: str = "", path: Path = None):
    """Сначала по телефону, затем по нику (как у ботов InterAlex)."""
    entries = load_entries(path)
    if phone:
        for entry in entries:
            if phones_match(entry.phone, phone):
                return entry
    nick = normalize_nick(username)
    if nick:
        for entry in entries:
            if entry.nick and entry.nick == nick:
                return entry
    return None


def is_allowed(phone: str = "", username: str = "", path: Path = None) -> bool:
    return find_entry(phone, username, path) is not None
