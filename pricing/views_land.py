"""Сравнение только суши: площадка × склад × оператор (отдельно от подбора маршрута)."""
from collections import defaultdict
from statistics import mean

from django.shortcuts import render

from .models import Auction, PriceList, Provider, Rate, Terminal, VehicleType
from .reference import AUCTIONS

GROUP_ORDER = ["GA", "NJ", "TX", "CA", "FL", "IN", "IL", "VA", "WA", "QC", "ON", "HI", "AK"]
DEFAULT_GROUPS = ["GA", "NJ", "TX", "CA"]


def _percent_shares(points, total):
    """Целые проценты, в сумме ровно 100 (метод наибольшего остатка)."""
    if not total:
        return [0] * len(points)
    raw = [100 * p / total for p in points]
    base = [int(x) for x in raw]
    rest = 100 - sum(base)
    for i in sorted(range(len(raw)), key=lambda i: raw[i] - base[i], reverse=True)[:rest]:
        base[i] += 1
    return base


def land_compare(request):
    auctions = list(Auction.objects.filter(
        yards__rate__stage=Rate.LAND, yards__rate__price_list__status=PriceList.PUBLISHED).distinct())
    order = {code: i for i, code in enumerate(AUCTIONS)}
    auctions.sort(key=lambda a: (order.get(a.code, 99), a.code))
    auction = next((a for a in auctions if str(a.id) == request.GET.get("auction")), auctions[0] if auctions else None)
    vtypes = list(VehicleType.objects.all())
    vtype = next((v for v in vtypes if v.code == request.GET.get("vt")), vtypes[0] if vtypes else None)

    # Склады, сгруппированные по эквивалентам (New York ≈ Elizabeth)
    terminals = list(Terminal.objects.all())
    group_terms = defaultdict(list)
    for t in terminals:
        group_terms[t.group].append(t)
    groups_all = [g for g in GROUP_ORDER if g in group_terms] + sorted(set(group_terms) - set(GROUP_ORDER))
    chosen = [g for g in request.GET.getlist("g") if g in group_terms] or DEFAULT_GROUPS
    state = request.GET.get("state", "")
    providers = list(Provider.objects.filter(
        price_lists__status=PriceList.PUBLISHED, price_lists__rates__stage=Rate.LAND).distinct().order_by("name"))
    chosen_ops = [p.id for p in providers if str(p.id) in request.GET.getlist("op")] or [p.id for p in providers]

    rates = Rate.objects.filter(
        stage=Rate.LAND, price_list__status=PriceList.PUBLISHED, vehicle_type=vtype, yard__auction=auction,
        to_terminal__group__in=chosen, price_list__provider_id__in=chosen_ops,
    ).select_related("yard", "to_terminal", "price_list__provider")
    states = sorted(set(Rate.objects.filter(
        stage=Rate.LAND, price_list__status=PriceList.PUBLISHED, yard__auction=auction
    ).values_list("yard__state", flat=True)))
    if state:
        rates = rates.filter(yard__state=state)

    # cell[(yard, group, оператор)] = минимальная цена (у оператора бывает несколько строк на площадку)
    cell, estimate, yards = {}, set(), {}
    ops_in_group = defaultdict(set)
    for r in rates:
        g, op = r.to_terminal.group, r.price_list.provider.name
        key = (r.yard_id, g, op)
        if key not in cell or r.amount < cell[key]:
            cell[key] = r.amount
            if r.is_estimate:
                estimate.add(key)
            else:
                estimate.discard(key)
        yards[r.yard_id] = r.yard
        ops_in_group[g].add(op)

    columns = []  # [(группа, название, [операторы])]
    for g in [x for x in groups_all if x in chosen]:
        ops = sorted(ops_in_group.get(g, []))
        if ops:
            names = " / ".join(t.name.split(",")[0] for t in group_terms[g])
            columns.append({"group": g, "code": group_terms[g][0].code, "name": names, "ops": ops})

    rows, summary = [], []
    stats = {c["group"]: {"compared": 0, "wins": defaultdict(int), "ties": defaultdict(int),
                          "points": defaultdict(float), "overpay": defaultdict(list),
                          "coverage": defaultdict(int)} for c in columns}
    for yard in sorted(yards.values(), key=lambda y: (y.state, y.name)):
        row_cells = []
        for c in columns:
            g = c["group"]
            values = {op: cell.get((yard.id, g, op)) for op in c["ops"]}
            present = {op: v for op, v in values.items() if v is not None}
            for op in present:
                stats[g]["coverage"][op] += 1
            mn = min(present.values()) if len(present) >= 2 else None
            mx = max(present.values()) if len(present) >= 2 else None
            if mn is not None and mn != mx:
                stats[g]["compared"] += 1
                cheapest = [op for op, v in present.items() if v == mn]
                for op, v in present.items():
                    stats[g]["overpay"][op].append(v - mn)  # насколько дороже лучшей цены на этой же площадке
                for op in cheapest:
                    # Ничья делит площадку поровну — доли в сумме дают 100%
                    stats[g]["points"][op] += 1 / len(cheapest)
                    if len(cheapest) == 1:
                        stats[g]["wins"][op] += 1
                    else:
                        stats[g]["ties"][op] += 1
            for i, op in enumerate(c["ops"]):
                v = values[op]
                css = ""
                if v is not None and mn is not None and mn != mx:
                    css = "cell-min" if v == mn else ("cell-max" if v == mx else "")
                if i == 0:
                    css += " group-start"
                row_cells.append({"value": v, "css": css, "estimate": (yard.id, g, op) in estimate})
        rows.append({"yard": yard, "cells": row_cells})

    for c in columns:
        st = stats[c["group"]]
        shares = _percent_shares([st["points"][op] for op in c["ops"]], st["compared"])
        summary.append({
            "column": c, "compared": st["compared"],
            "ops": [{
                "name": op,
                "coverage": st["coverage"][op],
                "wins": st["wins"][op],
                "ties": st["ties"][op],
                "share": share,
                "overpay": round(mean(st["overpay"][op])) if st["overpay"][op] else None,
                "compared_here": len(st["overpay"][op]),
            } for op, share in zip(c["ops"], shares)],
        })

    # Общая сводка: строки — операторы, колонки — склады
    all_ops = sorted({o["name"] for s in summary for o in s["ops"]})
    summary_rows = []
    for op in all_ops:
        cells = []
        for s in summary:
            o = next((x for x in s["ops"] if x["name"] == op), None)
            cells.append(o)
        summary_rows.append({"name": op, "cells": cells})
    return render(request, "pricing/land.html", {
        "summary_rows": summary_rows,
        "auctions": auctions, "auction": auction, "vtypes": vtypes, "vtype": vtype,
        "groups_all": [(g, " / ".join(t.name.split(",")[0] for t in group_terms[g])) for g in groups_all],
        "chosen": chosen, "providers": providers, "chosen_ops": chosen_ops, "states": states, "state": state, "columns": columns, "rows": rows, "summary": summary,
    })
