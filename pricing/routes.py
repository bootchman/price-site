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


def _extras(option, charges, vehicle_type, port, eur, fuel="ice"):
    """Статьи расходов того же оператора (суша и море у него же)."""
    pid = option.sea.price_list.provider_id
    stages = {Charge.SEA_STAGE, Charge.LAND_STAGE, Charge.ANY_STAGE}
    by_cat = charges.get(pid, {})
    cats = CATEGORIES + ([Charge.HAZARD] if fuel in ("electric", "hybrid") else [])
    for cat in cats:
        items = applicable(by_cat.get(cat, []), vehicle_type, port, stages, option.sea.container, fuel)
        if not items:
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


@dataclass
class LandOnly:
    """Суша оператора, для которой у него же нет моря до выбранного порта."""
    land: Rate
    reason: str


def find_routes(yard, vehicle_type, port, fuel="ice"):
    """Пакеты операторов: суша, море и статьи расходов — у одного оператора, без смешивания.

    Возвращает (варианты по возрастанию полной стоимости — по строке на каждый вариант суши,
                суша без моря у того же оператора)."""
    land_rates = list(published(Rate.objects.filter(stage=Rate.LAND, yard=yard, vehicle_type=vehicle_type)))
    sea_by_key = {}  # (оператор, группа склада) → морские ставки этого оператора
    sea_providers = set()
    for s in effective_sea(port, vehicle_type).values():
        sea_by_key.setdefault((s.price_list.provider_id, s.from_terminal.group), []).append(s)
        sea_providers.add(s.price_list.provider_id)
    charges = effective_charges({r.price_list.provider_id for r in land_rates})
    eur = latest_eur_usd()

    full, land_only = [], []
    for land in land_rates:
        pid = land.price_list.provider_id
        seas = sea_by_key.get((pid, land.to_terminal.group), [])
        if not seas:
            reason = f"нет своего моря от склада {land.to_terminal}" if pid in sea_providers else f"нет своего моря до порта {port}"
            land_only.append(LandOnly(land, reason))
            continue
        candidates = []
        for sea in seas:
            option = RouteOption(land=land, sea=sea, base_total=land.amount + sea.amount, same_provider=True)
            _extras(option, charges, vehicle_type, port, eur, fuel)
            option.total = option.base_total + sum((e.amount_usd for e in option.extras), Decimal(0))
            candidates.append(option)
        # Контейнер — дешёвый из ставок этого же оператора (40'HC / 45'HC / цена за единицу)
        candidates.sort(key=lambda o: o.total)
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
        full.append(best)
    full.sort(key=lambda o: (o.total, bool(o.missing)))
    land_only.sort(key=lambda x: (x.land.price_list.provider.name, x.land.amount))
    return full, land_only
