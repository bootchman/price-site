"""Тарифы операторов: море и статьи расходов с приоритетом ручного ввода над прайсом."""
from decimal import Decimal

from .models import Charge, ExchangeRate, PriceList, Rate

CATEGORIES = [Charge.SERVICES, Charge.MATERIAL]  # входят в итог всегда; экспедирование к операторам не относится
ALL_CATEGORIES = CATEGORIES + [Charge.HAZARD]  # hazardous fee — только для электро и гибридов
FUEL_CHOICES = [("ice", "ДВС (бензин / дизель)"), ("hybrid", "Гибрид"), ("electric", "Электро")]
CONTAINER_SLOTS = 4  # цена за машину = ¼ контейнера


def manual_list(provider) -> PriceList:
    pl, _ = PriceList.objects.get_or_create(
        provider=provider, scope="manual", is_manual=True,
        defaults={"title": "Ручные значения", "source": "сайт", "status": PriceList.PUBLISHED},
    )
    return pl


def effective_sea(port, vehicle_type):
    """{(оператор, склад, контейнер): Rate} — ручная ставка заменяет ставку из прайса; из прайса — самая дешёвая."""
    rates = Rate.objects.filter(
        stage=Rate.SEA, to_port=port, vehicle_type=vehicle_type, price_list__status=PriceList.PUBLISHED
    ).select_related("price_list__provider", "from_terminal", "to_port", "vehicle_type")
    manual, from_price = {}, {}
    for r in rates:
        key = (r.price_list.provider_id, r.from_terminal_id, r.container)
        target = manual if r.price_list.is_manual else from_price
        if key not in target or r.amount < target[key].amount:
            target[key] = r
    from_price.update(manual)
    return from_price


def effective_charges(provider_ids):
    """{оператор: {категория: [Charge]}} — если по категории есть ручные значения, они заменяют прайс."""
    result = {}
    qs = Charge.objects.filter(price_list__status=PriceList.PUBLISHED, price_list__provider_id__in=provider_ids) \
        .select_related("price_list__provider", "vehicle_type", "to_port")
    grouped = {}
    for c in qs:
        grouped.setdefault((c.price_list.provider_id, c.category), {"manual": [], "price": []})[
            "manual" if c.price_list.is_manual else "price"].append(c)
    for (pid, cat), parts in grouped.items():
        # Одна и та же статья может прийти из нескольких прайсов оператора (AML: Copart и IAAI) — считаем один раз
        unique, seen = [], set()
        for c in parts["manual"] or parts["price"]:
            key = (c.name, c.amount, c.currency, c.unit, c.applies_on, c.to_port_id, c.vehicle_type_id, c.container, c.fuel)
            if key not in seen:
                seen.add(key)
                unique.append(c)
        result.setdefault(pid, {})[cat] = unique
    return result


def latest_eur_usd():
    return ExchangeRate.objects.first()


def per_car(charge) -> Decimal:
    amount = charge.amount
    if charge.unit == "container":
        amount = amount / CONTAINER_SLOTS
    return amount


def applicable(charges, vehicle_type, port, stages, container="40HC", fuel="ice"):
    """Статьи одной категории, которые относятся к этой машине, порту, контейнеру, двигателю и роли оператора."""
    items = [c for c in charges if c.applies_on in stages and (c.to_port_id is None or c.to_port_id == port.id)
             and (c.container in ("", container) or container == "ANY" and c.container == "")
             and (c.category != Charge.HAZARD or c.fuel in ("", fuel))]
    specific_fuel = [c for c in items if c.category == Charge.HAZARD and c.fuel == fuel]
    if specific_fuel:  # «только электро» главнее «электро и гибрид»
        items = specific_fuel
    specific_cont = [c for c in items if c.container == container]  # ставка для этого контейнера главнее общей
    if specific_cont:
        items = specific_cont
    specific = [c for c in items if c.vehicle_type_id == vehicle_type.id]
    if specific:
        return specific
    return [c for c in items if c.vehicle_type_id is None]
