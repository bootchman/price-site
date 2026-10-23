#!/usr/bin/env python3
"""Создать Google Таблицу «Суша: VS против конкурентов» из JSON команды export_land_vs (запускает root).

  python3 write_land_vs_sheet.py land_vs.json [ID существующей таблицы]
Без ID создаёт новую таблицу, с ID — пересоздаёт листы в ней (ссылка не меняется). Печатает ссылку. Доступ к таблице выдаёт владелец вручную.
"""
import json
import os
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(__file__))
from price_access_sync import access_token  # noqa: E402

API = "https://sheets.googleapis.com/v4/spreadsheets"
PORT_COLORS = {"GA": "#47d78d", "NJ": "#f9b65a", "TX": "#fb8948", "CA": "#5ca9fb"}
GREEN, RED, GREY = "#6aa84f", "#e06666", "#6b6b6b"


def rgb(hex_color):
    h = hex_color.lstrip("#")
    return {"red": int(h[0:2], 16) / 255, "green": int(h[2:4], 16) / 255, "blue": int(h[4:6], 16) / 255}


def call(token, method, url, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=120).read() or b"{}")


def cell(value=None, bold=False, fg=None, bg=None, money=False, align=None, wrap=False, italic=False):
    c = {}
    if value is not None and value != "":
        c["userEnteredValue"] = {"numberValue": value} if isinstance(value, (int, float)) else {"stringValue": str(value)}
    fmt = {"textFormat": {"bold": bold, "italic": italic, "fontFamily": "Roboto", "fontSize": 10}}
    if fg:
        fmt["textFormat"]["foregroundColor"] = rgb(fg)
    if bg:
        fmt["backgroundColor"] = rgb(bg)
    if money:
        fmt["numberFormat"] = {"type": "CURRENCY", "pattern": "$#,##0"}
    if align:
        fmt["horizontalAlignment"] = align
    if wrap:
        fmt["wrapStrategy"] = "WRAP"
    fmt["verticalAlignment"] = "MIDDLE"
    c["userEnteredFormat"] = fmt
    return c


def auction_sheet(data, auction, sheet_id):
    ports, ops = data["ports"], data["operators"]
    rivals = [o for o in ops if o != "VS Brothers"]
    block = ["VS Brothers"] + rivals + ["Лучший конкурент", "VS дороже на"]
    width = len(block)
    row1 = [cell("Площадка", bold=True), cell("Город", bold=True)]
    row2 = [cell(f"{auction}: площадка", bold=True, wrap=True), cell("", bold=True)]
    merges = []
    for i, (g, name) in enumerate(ports):
        start = 2 + i * width
        row1 += [cell(name, bold=True, fg="#ffffff", bg=PORT_COLORS[g], align="CENTER")] + \
                [cell(bg=PORT_COLORS[g]) for _ in range(width - 1)]
        merges.append({"mergeCells": {"mergeType": "MERGE_ALL", "range": {
            "sheetId": sheet_id, "startRowIndex": 0, "endRowIndex": 1, "startColumnIndex": start, "endColumnIndex": start + width}}})
        labels = ["VS Brothers"] + rivals + ["Лучший конкурент", "VS дороже лучшего на"]
        row2 += [cell(t, bold=True, wrap=True, align="CENTER", bg="#f3f6f8") for t in labels]
    rows = [{"values": row1}, {"values": row2}]
    for r in data["auctions"][auction]:
        values = [cell(r["yard"], bold=True), cell(r["city"], fg=GREY)]
        for g, _ in ports:
            p = r["ports"].get(g)
            if not p:
                values += [cell() for _ in range(width)]
                continue
            prices = p["prices"]
            present = [v for v in prices.values() if v is not None]
            mn = min(present) if len(present) >= 2 else None
            mx = max(present) if len(present) >= 2 else None
            for o in ["VS Brothers"] + rivals:
                v = prices.get(o)
                bg = fg = None
                if v is not None and mn is not None and mn != mx:
                    if v == mn:
                        bg, fg = GREEN, "#ffffff"
                    elif v == mx:
                        bg, fg = RED, "#ffffff"
                values.append(cell(v, money=True, bold=bool(bg), fg=fg, bg=bg, align="CENTER"))
            values.append(cell(", ".join(p["best_ops"]) if p["best_ops"] else "", fg=GREY, align="CENTER"))
            d = p["diff"]
            if d is None:
                values.append(cell())
            else:
                values.append(cell(d, money=True, bold=True, fg=RED if d > 0 else GREEN, align="CENTER"))
        rows.append({"values": values})
    total_cols = 2 + len(ports) * width
    requests = [{"updateCells": {"rows": rows, "fields": "userEnteredValue,userEnteredFormat",
                                 "start": {"sheetId": sheet_id, "rowIndex": 0, "columnIndex": 0}}}] + merges
    requests += [
        {"updateSheetProperties": {"properties": {"sheetId": sheet_id, "gridProperties": {
            "frozenRowCount": 2, "frozenColumnCount": 1}}, "fields": "gridProperties(frozenRowCount,frozenColumnCount)"}},
        {"updateDimensionProperties": {"range": {"sheetId": sheet_id, "dimension": "COLUMNS", "startIndex": 0, "endIndex": 1},
                                       "properties": {"pixelSize": 230}, "fields": "pixelSize"}},
        {"updateDimensionProperties": {"range": {"sheetId": sheet_id, "dimension": "COLUMNS", "startIndex": 1, "endIndex": total_cols},
                                       "properties": {"pixelSize": 92}, "fields": "pixelSize"}},
        {"updateDimensionProperties": {"range": {"sheetId": sheet_id, "dimension": "ROWS", "startIndex": 1, "endIndex": 2},
                                       "properties": {"pixelSize": 48}, "fields": "pixelSize"}},
    ]
    for i in range(len(ports)):  # граница слева у каждого блока склада
        start = 2 + i * width
        requests.append({"updateBorders": {"range": {"sheetId": sheet_id, "startRowIndex": 0, "endRowIndex": len(rows),
                                                     "startColumnIndex": start, "endColumnIndex": start + 1},
                                           "left": {"style": "SOLID_MEDIUM", "color": rgb("#9e9e9e")}}})
    return requests


def summary_sheet(data, sheet_id):
    sea = ", ".join(f"{name} ${data['vs_sea'][g]:.0f}" for g, name in data["ports"] if g in data["vs_sea"])
    rows = [
        [cell("Суша: VS Brothers против конкурентов", bold=True)],
        [cell(f"Источник: price.interalex.pro, {data['generated']}. Тип машины: {data['vehicle_type']}. "
              "Сравнивается цена суши VS с самой дешёвой ценой конкурента на той же площадке до того же склада.",
              fg=GREY)],
        [cell(f"Суша VS = полная цена калькулятора VS до Клайпеды − море VS ({sea}).", fg=GREY)],
        [],
        [cell(t, bold=True, wrap=True, align="CENTER", bg="#f3f6f8") for t in
         ["Аукцион", "Склад", "Площадок, где есть VS и конкурент", "VS дороже лучшего конкурента",
          "Доля", "VS дороже в среднем на", "Максимум", "VS дешевле или так же"]],
    ]
    for s in data["summary"]:
        rows.append([
            cell(s["auction"], bold=True), cell(s["port"]), cell(s["compared"], align="CENTER"),
            cell(s["dearer"], align="CENTER", bold=True, fg=RED), cell(f"{s['share']}%", align="CENTER", bold=True, fg=RED),
            cell(s["avg"], money=True, align="CENTER"), cell(s["max"], money=True, align="CENTER"),
            cell(s["cheaper_or_equal"], align="CENTER", fg=GREEN),
        ])
    grid = [{"values": r} for r in rows]
    return [
        {"updateCells": {"rows": grid, "fields": "userEnteredValue,userEnteredFormat",
                         "start": {"sheetId": sheet_id, "rowIndex": 0, "columnIndex": 0}}},
        {"repeatCell": {"range": {"sheetId": sheet_id, "startRowIndex": 0, "endRowIndex": 1},
                        "cell": {"userEnteredFormat": {"textFormat": {"bold": True, "fontSize": 14, "fontFamily": "Roboto"}}},
                        "fields": "userEnteredFormat.textFormat"}},
        {"updateDimensionProperties": {"range": {"sheetId": sheet_id, "dimension": "COLUMNS", "startIndex": 0, "endIndex": 8},
                                       "properties": {"pixelSize": 150}, "fields": "pixelSize"}},
        {"updateDimensionProperties": {"range": {"sheetId": sheet_id, "dimension": "ROWS", "startIndex": 4, "endIndex": 5},
                                       "properties": {"pixelSize": 48}, "fields": "pixelSize"}},
    ]


def main(path, into=None):
    data = json.load(open(path, encoding="utf-8"))
    token = access_token()
    auctions = list(data["auctions"])
    sheets = [{"properties": {"sheetId": 1, "title": "Сводка"}}] + [
        {"properties": {"sheetId": 10 + i, "title": a,
                        "gridProperties": {"rowCount": len(data["auctions"][a]) + 5, "columnCount": 2 + 7 * len(data["ports"]) + 2}}}
        for i, a in enumerate(auctions)]
    if into:  # пересоздать листы в существующей таблице — ссылка остаётся прежней
        sid = into
        old = call(token, "GET", f"{API}/{sid}?fields=sheets.properties.sheetId")["sheets"]
        reqs = [{"addSheet": {"properties": {"sheetId": 999, "title": "tmp"}}}]
        reqs += [{"deleteSheet": {"sheetId": s["properties"]["sheetId"]}} for s in old]
        reqs += [{"addSheet": s} for s in sheets] + [{"deleteSheet": {"sheetId": 999}}]
        reqs.append({"updateSpreadsheetProperties": {
            "properties": {"title": f"Суша: VS против конкурентов ({data['generated'][:10]})"}, "fields": "title"}})
        call(token, "POST", f"{API}/{sid}:batchUpdate", {"requests": reqs})
        url = f"https://docs.google.com/spreadsheets/d/{sid}/edit"
    else:
        created = call(token, "POST", API, {
            "properties": {"title": f"Суша: VS против конкурентов ({data['generated'][:10]})", "locale": "en_US"},
            "sheets": sheets})
        sid, url = created["spreadsheetId"], created["spreadsheetUrl"]
    requests = summary_sheet(data, 1)
    for i, a in enumerate(auctions):
        requests += auction_sheet(data, a, 10 + i)
    call(token, "POST", f"{API}/{sid}:batchUpdate", {"requests": requests})
    print(url)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
