"""Подбор маршрута: полная стоимость = суша + море + услуги + material fee + экспедирование."""
from dataclasses import dataclass, field
from decimal import Decimal

from .models import ANY_CONTAINER, CONTAINER_CHOICES, RATE_CONTAINER_CHOICES, Charge, PriceList, Rate
from .tariffs import CATEGORIES, applicable, effective_charges, effective_sea, latest_eur_usd, per_car

CATEGORY_NAMES = dict(Charge.CATEGORY_CHOICES)
CONTAINER_NAMES = dict(RATE_CONTAINER_CHOICES)


@dataclass
class Extra:
    category: str
    provider: str
    amount_usd: Decimal
    label: str
    manual: bool


@dataclass
class RouteOption:
    land: Rate
    sea: Rate = None
    total: Decimal = None  # полная стоимость, USD
    base_total: Decimal = None  # суша + море
    extras: list = field(default_factory=list)
    missing: list = field(default_factory=list)  # статьи без данных у морского оператора
    same_provider: bool = False
    notes: list = field(default_factory=list)
    by_container: dict = field(default_factory=dict)  # {«40'HC»: лучший итог или None, «45'HC»: …}

    @property
    def container(self):
        return CONTAINER_NAMES.get(self.sea.container, self.sea.container) if self.sea else ""


def published(qs):
    return qs.filter(price_list__status=PriceList.PUBLISHED).select_related(
        "price_list__provider", "to_terminal", "from_terminal", "to_port", "vehicle_type"
    )


def _extras(option, charges, vehicle_type, port, eur):
    sea_pid = option.sea.price_list.provider_id
    land_pid = option.land.price_list.provider_id
    roles = [(sea_pid, {Charge.SEA_STAGE, Charge.ANY_STAGE})]
    if land_pid != sea_pid:
        roles.append((land_pid, {Charge.LAND_STAGE, Charge.ANY_STAGE}))
    for pid, stages in roles:
        by_cat = charges.get(pid, {})
        for cat in CATEGORIES:
            items = applicable(by_cat.get(cat, []), vehicle_type, port, stages, option.sea.container)
            if pid == sea_pid and not items:
                option.missing.append(CATEGORY_NAMES[cat])
            for c in items:
                amount = per_car(c)
                sign = "€" if c.currency == "EUR" else "$"
                label = f"{CATEGORY_NAMES[cat]} {sign}{amount:.0f}"
                if c.currency == "EUR":
                    if eur is None:
                        option.missing.append(f"{CATEGORY_NAMES[cat]} (нет курса EUR)")
                        continue
                    amount = amount * eur.eur_usd
                    label += f" ≈ ${amount:.0f}"
                option.extras.append(Extra(cat, c.price_list.provider.name, amount.quantize(Decimal("1")), label,
                                           c.price_list.is_manual))


def find_routes(yard, vehicle_type, port):
    """Возвращает (варианты по возрастанию полной стоимости, суша без морской ставки до этого порта)."""
    land_rates = list(published(Rate.objects.filter(stage=Rate.LAND, yard=yard, vehicle_type=vehicle_type)))
    sea_by_group = {}
    for s in effective_sea(port, vehicle_type).values():
        sea_by_group.setdefault(s.from_terminal.group, []).append(s)
    provider_ids = {r.price_list.provider_id for r in land_rates}
    provider_ids |= {s.price_list.provider_id for seas in sea_by_group.values() for s in seas}
    charges = effective_charges(provider_ids)
    eur = latest_eur_usd()

    full, land_only = [], []
    for land in land_rates:
        seas = sea_by_group.get(land.to_terminal.group, [])
        if not seas:
            land_only.append(land)
            continue
        candidates = []
        for sea in seas:
            option = RouteOption(land=land, sea=sea, base_total=land.amount + sea.amount)
            option.same_provider = land.price_list.provider_id == sea.price_list.provider_id
            _extras(option, charges, vehicle_type, port, eur)
            option.total = option.base_total + sum((e.amount_usd for e in option.extras), Decimal(0))
            candidates.append(option)
        # Лучшее море для этой суши — по полной стоимости (оба контейнера); при равной — тот же оператор.
        candidates.sort(key=lambda o: (o.total, not o.same_provider))
        best = candidates[0]
        if best.sea.container != ANY_CONTAINER:
            for code, name in CONTAINER_CHOICES:
                in_cont = [o for o in candidates if o.sea.container in (code, ANY_CONTAINER)]
                best.by_container[name] = in_cont[0].total if in_cont else None
        if land.is_estimate:
            best.notes.append(f"суша: {land.note or 'оценка'}")
        if best.sea.is_estimate:
            best.notes.append(f"море: {best.sea.note or 'оценка'}")
        if best.sea.price_list.is_manual:
            best.notes.append("море задано вручную")
        if land.to_terminal_id != best.sea.from_terminal_id:
            best.notes.append(f"склад {land.to_terminal} ≈ {best.sea.from_terminal}")
        others = [f"{o.sea.price_list.provider.name} {o.container} ${o.total:.0f}" for o in candidates[1:]
                  if o.sea.price_list.provider_id != best.sea.price_list.provider_id]
        if others:
            best.notes.append("с морем другого оператора: " + ", ".join(dict.fromkeys(others)))
        full.append(best)
    full.sort(key=lambda o: (o.total, bool(o.missing), not o.same_provider))
    land_only.sort(key=lambda r: r.amount)
    return full, land_only
