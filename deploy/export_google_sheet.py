#!/usr/bin/env python3
"""Выгрузить лист Google Таблицы в JSON (запускает root: токен Google есть только у него).

  python3 export_google_sheet.py <spreadsheet_id> "<лист>" /srv/price/data/incoming/<файл>.json
"""
import json
import os
import sys
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(__file__))
from price_access_sync import access_token  # noqa: E402


def main(sheet_id, tab, out):
    token = access_token()
    rng = urllib.parse.quote(f"'{tab}'!A1:Z5000")
    url = f"https://sheets.googleapis.com/v4/spreadsheets/{sheet_id}/values/{rng}"
    req = urllib.request.Request(url, headers={"Authorization": "Bearer " + token})
    values = json.loads(urllib.request.urlopen(req, timeout=60).read()).get("values", [])
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(values, fh, ensure_ascii=False)
    os.chmod(out, 0o644)
    print(f"{len(values)} строк → {out}")


if __name__ == "__main__":
    main(*sys.argv[1:4])
