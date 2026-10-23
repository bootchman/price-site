#!/usr/bin/env python3
"""Синхронизация списка доступа price.interalex.pro с Google Таблицей.

Запускается от root по cron (у сайта нет доступа к токену Google):
  1. читает лист «Лист1» (Телефон / Ник / Пользователь / Время авторизации / Роль);
  2. переносит в таблицу входы из auth_events.jsonl (заполняет «Пользователь» и
     «Время авторизации», только если они ещё пустые — фиксируем первый вход);
  3. пишет /srv/price/data/allowed.json для сайта и бота.
Только стандартная библиотека Python.
"""
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone

SHEET_ID = "1Ve4u6yhd_0A9NlZeUInTpuesy3UqC-eaMA4vhRMmVkM"
SHEET_TAB = "Лист1"
TOKEN_FILE = "/root/.hermes/google_token.json"
DATA_DIR = "/srv/price/data"
ALLOWED = os.path.join(DATA_DIR, "allowed.json")
EVENTS = os.path.join(DATA_DIR, "auth_events.jsonl")
API = "https://sheets.googleapis.com/v4/spreadsheets/" + SHEET_ID


def access_token():
    with open(TOKEN_FILE) as fh:
        tok = json.load(fh)
    body = urllib.parse.urlencode({
        "client_id": tok["client_id"],
        "client_secret": tok["client_secret"],
        "refresh_token": tok["refresh_token"],
        "grant_type": "refresh_token",
    }).encode()
    resp = urllib.request.urlopen("https://oauth2.googleapis.com/token", body, timeout=30)
    return json.loads(resp.read())["access_token"]


def call(method, url, token, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": "Bearer " + token, "Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=30).read() or b"{}")


def digits(value):
    return "".join(ch for ch in str(value or "") if ch.isdigit())


def take_events():
    """Забираем файл событий целиком (бот при следующем входе создаст новый)."""
    if not os.path.exists(EVENTS):
        return []
    work = EVENTS + ".processing"
    if not os.path.exists(work):
        os.rename(EVENTS, work)
    events = []
    with open(work, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                try:
                    events.append(json.loads(line))
                except ValueError:
                    pass
    return events


def main():
    token = access_token()
    rng = urllib.parse.quote(f"{SHEET_TAB}!A1:E2000")
    rows = call("GET", f"{API}/values/{rng}", token).get("values", [])

    events = take_events()
    updates = []
    for ev in events:
        row = int(ev.get("row") or 0)
        if row < 2 or row > len(rows):
            continue
        current = rows[row - 1] + [""] * 5
        if current[2].strip() or current[3].strip():
            continue
        who = f"{ev.get('full_name') or ev.get('username') or ''} ({ev.get('telegram_id')})".strip()
        updates.append({"range": f"{SHEET_TAB}!C{row}:D{row}", "values": [[who, ev.get("at", "")]]})
        rows[row - 1] = current[:2] + [who, ev.get("at", "")] + current[4:5]
    if updates:
        call("POST", f"{API}/values:batchUpdate", token, {"valueInputOption": "USER_ENTERED", "data": updates})
    if os.path.exists(EVENTS + ".processing"):
        os.remove(EVENTS + ".processing")

    entries = []
    for i, r in enumerate(rows[1:], start=2):
        r = r + [""] * 5
        phone, nick, role = digits(r[0]), r[1].strip().lstrip("@"), r[4].strip()
        if phone or nick:
            entries.append({"phone": phone, "nick": nick, "row": i, "role": role})
    payload = {"updated": datetime.now(timezone.utc).isoformat(timespec="seconds"), "entries": entries}
    tmp = ALLOWED + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False)
    os.chmod(tmp, 0o640)
    try:
        import grp
        os.chown(tmp, 0, grp.getgrnam("price").gr_gid)
    except (KeyError, PermissionError):
        pass
    os.replace(tmp, ALLOWED)
    print(f"{payload['updated']} доступ: {len(entries)} записей, записано входов в таблицу: {len(updates)}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # cron: пишем в лог и выходим с ошибкой, старый allowed.json остаётся
        print(f"{datetime.now(timezone.utc).isoformat(timespec='seconds')} ОШИБКА: {exc}", file=sys.stderr)
        sys.exit(1)
