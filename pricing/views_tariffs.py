"""Вкладка «Тарифы операторов»: море, услуги, material fee, hazardous fee; ручной ввод главнее прайса."""
from datetime import date
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .models import CONTAINER_CHOICES, RATE_CONTAINER_CHOICES, Charge, DestinationPort, ExchangeRate, PriceList, Provider, Rate, TariffChange, Terminal, VehicleType
from .tariffs import ALL_CATEGORIES, CONTAINER_SLOTS, effective_charges, manual_list

CATEGORY_NAMES = dict(Charge.CATEGORY_CHOICES)
CONTAINER_NAMES = dict(RATE_CONTAINER_CHOICES)
CAR_TYPES = ["sedan", "suv", "suv_big", "pickup"]  # «все легковые» в форме моря
TERMINAL_ORDER = ["SAV", "ELZ", "NYC", "HOU", "LAX", "IND", "MTL", "MIA", "CHI", "ORF", "SEA", "YTO", "HNL", "ANC"]


def _decimal(value):
    try:
        d = Decimal(str(value).replace(",", ".").replace(" ", "").strip())
    except (InvalidOperation, ValueError):
        return None
    return d if d >= 0 else None


def _charge_key(c):
    return (c.category, c.name, c.amount, c.currency, c.unit, c.applies_on, c.to_port_id, c.vehicle_type_id,
            c.container, c.fuel)


def _log(request, provider, action, description):
    TariffChange.objects.create(provider=provider, user=request.user, action=action, description=description[:300])


def index(request):
    providers = list(Provider.objects.all())
    rows = []
    for p in providers:
        sea = Rate.objects.filter(price_list__provider=p, price_list__status=PriceList.PUBLISHED, stage=Rate.SEA)
        eff = effective_charges([p.id]).get(p.id, {})
        cats = {}
        for cat in ALL_CATEGORIES:
            use = eff.get(cat, [])
            cats[cat] = {"items": use, "manual": any(c.price_list.is_manual for c in use)}
        rows.append({
            "provider": p,
            "sea_ports": sorted({r.to_port.name for r in sea.select_related("to_port")}),
            "sea_manual": sea.filter(price_list__is_manual=True).exists(),
            "cats": [(CATEGORY_NAMES[c], cats[c]) for c in ALL_CATEGORIES],
        })
    return render(request, "pricing/tariffs.html", {"rows": rows, "eur": ExchangeRate.objects.first()})


def provider_page(request, pk):
    provider = get_object_or_404(Provider, pk=pk)
    published = PriceList.objects.filter(provider=provider, status=PriceList.PUBLISHED)
    sea = (Rate.objects.filter(price_list__in=published, stage=Rate.SEA)
           .select_related("price_list", "from_terminal", "to_port", "vehicle_type")
           .order_by("container", "to_port__sort", "from_terminal__group", "vehicle_type__sort", "price_list__is_manual"))
    # Действующая ставка: из прайса — самая дешёвая по ключу, ручная заменяет её
    from_price, manual = {}, {}
    for r in sea:
        key = (r.from_terminal_id, r.to_port_id, r.vehicle_type_id, r.container)
        target = manual if r.price_list.is_manual else from_price
        if key not in target or r.amount < target[key].amount:
            target[key] = r
    overridden = set(from_price) & set(manual)
    effective = {**from_price, **manual}
    charges = Charge.objects.filter(price_list__in=published).select_related("price_list", "to_port", "vehicle_type") \
        .order_by("category", "price_list__is_manual", "id")
    manual_cats = {c.category for c in charges if c.price_list.is_manual}
    # Одинаковая статья из нескольких прайсов оператора (AML: Copart и IAAI) — одной строкой
    unique, seen = [], {}
    for c in charges:
        key = (c.price_list.is_manual, *_charge_key(c))
        if key in seen:
            seen[key].sources.append(c.price_list.title)
            continue
        c.sources = [c.price_list.title]
        seen[key] = c
        unique.append(c)
    charges = unique
    # Матрица как в прайсе Cargoloop: строки — порт получения и тип машины, колонки — склады
    order = {code: i for i, code in enumerate(TERMINAL_ORDER)}
    columns = sorted({r.from_terminal for r in effective.values()}, key=lambda t: (order.get(t.code, 99), t.name))
    row_keys = sorted({(r.container, r.to_port, r.vehicle_type) for r in effective.values()},
                      key=lambda k: (k[0], k[1].sort, k[2].sort))
    matrix = [
        {"container": CONTAINER_NAMES.get(c, c), "port": port, "vtype": vt,
         "cells": [effective.get((t.id, port.id, vt.id, c)) for t in columns]}
        for c, port, vt in row_keys
    ]
    manual_sea = [r for r in effective.values() if r.price_list.is_manual]
    return render(request, "pricing/tariff_provider.html", {
        "provider": provider, "columns": columns, "matrix": matrix,
        "manual_sea": sorted(manual_sea, key=lambda r: (r.container, r.to_port.sort, order.get(r.from_terminal.code, 99), r.vehicle_type.sort)),
        "containers": CONTAINER_CHOICES, "sea_containers": RATE_CONTAINER_CHOICES,
        "overridden": overridden,
        "charges": [(c, c.price_list.is_manual or c.category not in manual_cats) for c in charges],
        "terminals": sorted(Terminal.objects.all(), key=lambda t: (order.get(t.code, 99), t.name)), "ports": DestinationPort.objects.all(),
        "vtypes": VehicleType.objects.all(), "categories": Charge.CATEGORY_CHOICES,
        "applies": Charge.APPLIES_ON_CHOICES, "fuel_choices": Charge.FUEL_CHOICES, "history": provider.tariff_changes.select_related("user")[:30],
    })


@require_POST
def add_provider(request):
    name = request.POST.get("name", "").strip()
    if name:
        provider, created = Provider.objects.get_or_create(name=name[:100])
        if created:
            _log(request, provider, "оператор", f"Добавлен оператор {provider.name}")
        return redirect("tariff_provider", pk=provider.pk)
    return redirect("tariffs")


@require_POST
def add_sea(request, pk):
    provider = get_object_or_404(Provider, pk=pk)
    terminal = Terminal.objects.filter(pk=request.POST.get("terminal")).first()
    port = DestinationPort.objects.filter(pk=request.POST.get("port")).first()
    amount = _decimal(request.POST.get("amount"))
    vt = request.POST.get("vehicle_type")
    vtypes = list(VehicleType.objects.filter(code__in=CAR_TYPES)) if vt == "all" else list(VehicleType.objects.filter(pk=vt))
    if not (terminal and port and vtypes and amount is not None):
        messages.error(request, "Море: укажите склад, порт, тип машины и сумму.")
        return redirect("tariff_provider", pk=pk)
    unit = request.POST.get("unit", "car")
    container = request.POST.get("container") if request.POST.get("container") in CONTAINER_NAMES else "40HC"
    note = request.POST.get("note", "").strip()[:150]
    if container == "ANY":
        unit = "car"  # цена за единицу — на 4 не делим
    per_car = amount / CONTAINER_SLOTS if unit == "container" else amount
    if unit == "container":
        note = f"контейнер ${amount:.0f} / {CONTAINER_SLOTS}" + (f"; {note}" if note else "")
    pl = manual_list(provider)
    for v in vtypes:
        Rate.objects.filter(price_list=pl, stage=Rate.SEA, from_terminal=terminal, to_port=port, vehicle_type=v,
                            container=container).delete()
        Rate.objects.create(price_list=pl, stage=Rate.SEA, from_terminal=terminal, to_port=port, vehicle_type=v,
                            container=container, amount=per_car.quantize(Decimal("0.01")), note=note or "задано вручную")
    types = "все легковые" if vt == "all" else vtypes[0].name
    _log(request, provider, "море", f"Море {CONTAINER_NAMES[container]} {terminal} → {port}, {types}: "
                                    f"${per_car:.0f} за машину. {note}")
    messages.success(request, "Морская ставка сохранена.")
    return redirect("tariff_provider", pk=pk)


@require_POST
def add_charge(request, pk):
    provider = get_object_or_404(Provider, pk=pk)
    category = request.POST.get("category")
    amount = _decimal(request.POST.get("amount"))
    if category not in CATEGORY_NAMES or amount is None:
        messages.error(request, "Статья расходов: выберите статью и укажите сумму (0 — «не берёт»).")
        return redirect("tariff_provider", pk=pk)
    currency = "EUR" if request.POST.get("currency") == "EUR" else "USD"
    unit = "container" if request.POST.get("unit") == "container" else "car"
    applies_on = request.POST.get("applies_on") or Charge.SEA_STAGE
    port = DestinationPort.objects.filter(pk=request.POST.get("port") or None).first()
    vtype = VehicleType.objects.filter(pk=request.POST.get("vehicle_type") or None).first()
    name = request.POST.get("name", "").strip()[:200] or CATEGORY_NAMES[category].capitalize()
    container = request.POST.get("container") if request.POST.get("container") in CONTAINER_NAMES else ""
    fuel = request.POST.get("fuel") if category == Charge.HAZARD and request.POST.get("fuel") in ("electric", "hybrid") else ""
    pl = manual_list(provider)
    Charge.objects.filter(price_list=pl, category=category, name=name, to_port=port, vehicle_type=vtype,
                          container=container, fuel=fuel).delete()
    Charge.objects.create(price_list=pl, category=category, name=name, amount=amount, currency=currency, unit=unit,
                          applies_on=applies_on, to_port=port, vehicle_type=vtype, container=container, fuel=fuel,
                          applies_to=port.name if port else "все порты", note=request.POST.get("note", "").strip()[:200])
    sign = "€" if currency == "EUR" else "$"
    _log(request, provider, CATEGORY_NAMES[category],
         f"{name}: {sign}{amount:.0f} {'за контейнер' if unit == 'container' else 'за машину'}"
         f"{', ' + port.name if port else ''}{', ' + vtype.name if vtype else ''}"
         f"{', ' + CONTAINER_NAMES[container] if container else ''}")
    messages.success(request, "Статья расходов сохранена.")
    return redirect("tariff_provider", pk=pk)


@require_POST
def delete_manual(request, pk, kind, item_id):
    """Удалить ручное значение; статью расходов можно удалить и из прайса (вместе с её копиями в других прайсах)."""
    provider = get_object_or_404(Provider, pk=pk)
    if kind == "sea":
        obj = get_object_or_404(Rate, pk=item_id, price_list__provider=provider, price_list__is_manual=True)
        desc = f"Удалено море {obj.get_container_display()} {obj.from_terminal} → {obj.to_port}, {obj.vehicle_type}: ${obj.amount:.0f}"
        obj.delete()
        messages.success(request, "Ручное значение удалено — снова действует значение из прайса (если есть).")
    else:
        obj = get_object_or_404(Charge, pk=item_id, price_list__provider=provider)
        if obj.price_list.is_manual:
            obj.delete()
            desc = f"Удалено ручное: {obj.name} {obj.amount:.0f} {obj.currency}"
            messages.success(request, "Ручное значение удалено — снова действует значение из прайса (если есть).")
        else:
            key = _charge_key(obj)
            same = [c for c in Charge.objects.filter(price_list__provider=provider, price_list__is_manual=False,
                                                     category=obj.category).select_related("price_list")
                    if _charge_key(c) == key]
            titles = ", ".join(sorted({c.price_list.title for c in same}))
            Charge.objects.filter(pk__in=[c.pk for c in same]).delete()
            desc = f"Удалено из прайса ({titles}): {obj.name} {obj.amount:.0f} {obj.currency}"
            messages.success(request, "Статья удалена из прайса. При повторной загрузке этого прайса она появится снова.")
    _log(request, provider, "удаление", desc)
    return redirect("tariff_provider", pk=pk)


@require_POST
def set_rate(request):
    value = _decimal(request.POST.get("eur_usd"))
    if value:
        ExchangeRate.objects.create(date=date.today(), eur_usd=value, source="вручную")
        messages.success(request, f"Курс EUR→USD {value} сохранён.")
    else:
        messages.error(request, "Укажите курс, например 1.08")
    return redirect("tariffs")
