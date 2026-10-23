"""Подбор маршрута: суша (площадка → склад) + море (склад → порт получения)."""
from dataclasses import dataclass, field
from decimal import Decimal

from .models import PriceList, Rate


@dataclass
class RouteOption:
    land: Rate
    sea: Rate = None
    total: Decimal = None
    same_provider: bool = False
    notes: list = field(default_factory=list)


def published(qs):
    return qs.filter(price_list__status=PriceList.PUBLISHED).select_related(
        "price_list__provider", "to_terminal", "from_terminal", "to_port", "vehicle_type"
    )


def find_routes(yard, vehicle_type, port):
    """Возвращает (полные варианты по возрастанию цены, суша без морской ставки до этого порта)."""
    land_rates = list(published(Rate.objects.filter(stage=Rate.LAND, yard=yard, vehicle_type=vehicle_type)))
    sea_rates = list(published(Rate.objects.filter(stage=Rate.SEA, to_port=port, vehicle_type=vehicle_type)))
    # Одна морская ставка на оператора и склад: у VS море приходит и из прайса Copart, и из прайса IAAI.
    best_sea = {}
    for s in sea_rates:
        key = (s.price_list.provider_id, s.from_terminal_id)
        if key not in best_sea or s.amount < best_sea[key].amount:
            best_sea[key] = s
    sea_by_group = {}
    for s in best_sea.values():
        sea_by_group.setdefault(s.from_terminal.group, []).append(s)

    full, land_only = [], []
    for land in land_rates:
        seas = sea_by_group.get(land.to_terminal.group, [])
        if not seas:
            land_only.append(land)
            continue
        for sea in seas:
            option = RouteOption(land=land, sea=sea, total=land.amount + sea.amount)
            option.same_provider = land.price_list.provider_id == sea.price_list.provider_id
            if land.is_estimate:
                option.notes.append(f"суша: {land.note or 'оценка'}")
            if sea.is_estimate:
                option.notes.append(f"море: {sea.note or 'оценка'}")
            if land.to_terminal_id != sea.from_terminal_id:
                option.notes.append(f"склад {land.to_terminal} ≈ {sea.from_terminal}")
            full.append(option)
    full.sort(key=lambda o: (o.total, not o.same_provider))
    land_only.sort(key=lambda r: r.amount)
    return full, land_only
