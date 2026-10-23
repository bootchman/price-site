"""Общая часть разборщиков: справочники, сопоставление площадок, сохранение прайса."""
from collections import Counter
from decimal import Decimal

from django.db import transaction

from pricing.models import (
    Auction, DestinationPort, PriceList, Provider, Rate, Terminal, VehicleType, Yard, YardAlias,
)
from pricing.reference import AUCTIONS, CANADA, DESTINATION_PORTS, TERMINALS, VEHICLE_TYPES, name_key, normalize_state


def ensure_reference():
    for code, name, group, country in TERMINALS:
        Terminal.objects.update_or_create(code=code, defaults={"name": name, "group": group, "country": country})
    for code, name, country, sort in DESTINATION_PORTS:
        DestinationPort.objects.update_or_create(code=code, defaults={"name": name, "country": country, "sort": sort})
    for code, name, sort in VEHICLE_TYPES:
        VehicleType.objects.update_or_create(code=code, defaults={"name": name, "sort": sort})
    for code in AUCTIONS:
        Auction.objects.get_or_create(code=code)


class Importer:
    """Собирает строки прайса в памяти, затем одной транзакцией сохраняет версию."""

    provider_name = ""
    allow_city_match = True  # у мастер-источника (Cargoloop) каждая строка — своя площадка

    def __init__(self, title, source, scope="all", valid_from=None, is_bundle=False, notes=""):
        ensure_reference()
        self.provider, _ = Provider.objects.get_or_create(name=self.provider_name)
        self.meta = dict(title=title, source=source, scope=scope, valid_from=valid_from, is_bundle=is_bundle, notes=notes)
        self.terminals = {t.code: t for t in Terminal.objects.all()}
        self.ports = {p.code: p for p in DestinationPort.objects.all()}
        self.vtypes = {v.code: v for v in VehicleType.objects.all()}
        self.auctions = {a.code.lower(): a for a in Auction.objects.all()}
        self.rates = []
        self.counters = Counter()
        self.warnings = []
        self._yard_cache = {}

    # --- справочники ---
    def auction(self, code: str) -> Auction:
        key = code.strip().lower()
        if key not in self.auctions:
            self.auctions[key], _ = Auction.objects.get_or_create(code=code.strip())
        return self.auctions[key]

    def _candidates(self, auction, state):
        ck = ("cand", auction.id, state)
        if ck not in self._yard_cache:
            self._yard_cache[ck] = list(Yard.objects.filter(auction=auction, state=state))
        return self._yard_cache[ck]

    def _fallback(self, auction, state, key):
        """Уникальное совпадение по городу площадки (Shipper 101 пишет город: «EIGHT MILE» = Copart MOBILE).
        По началу названия не сопоставляем: «MOBILE» и «MOBILE SOUTH» — разные площадки."""
        cands = self._candidates(auction, state)
        by_city = [y for y in cands if y.city and name_key(y.city, state) == key]
        if len(by_city) == 1:
            return by_city[0], "по городу"
        return None, ""

    def yard(self, auction_code, state, raw_name, city="", zip_code=""):
        """Ищет площадку: ручная привязка → название → город/начало названия; иначе заводит новую."""
        auction = self.auction(auction_code)
        state = normalize_state(state)
        key = name_key(raw_name, state)
        if not key:
            self.counters["пустое название площадки"] += 1
            return None
        cache_key = (auction.id, state, key)
        if cache_key in self._yard_cache:
            return self._yard_cache[cache_key]
        alias = YardAlias.objects.filter(provider=self.provider, auction=auction, state=state, raw_key=key).first()
        yard = alias.yard if alias else Yard.objects.filter(auction=auction, state=state, name_key=key).first()
        if yard is None and self.allow_city_match:
            yard, how = self._fallback(auction, state, key)
            if yard is not None:
                self.counters[f"площадок найдено {how}"] += 1
                self._yard_cache[cache_key] = yard
                return yard
        if yard is None:
            yard = Yard.objects.create(
                auction=auction, state=state, name=str(raw_name).strip(), name_key=key, city=city, zip=zip_code,
                country="CA" if state in CANADA else "US", source=self.provider_name,
            )
            self._candidates(auction, state).append(yard)
            self.counters["новых площадок"] += 1
        else:
            self.counters["площадок найдено в справочнике"] += 1
            if zip_code and not yard.zip:
                yard.zip, yard.city = zip_code, yard.city or city
                yard.save(update_fields=["zip", "city"])
        self._yard_cache[cache_key] = yard
        return yard

    # --- строки прайса ---
    def land(self, yard, terminal_code, vtype, amount, preferred=False, estimate=False, note=""):
        if yard is None or terminal_code not in self.terminals or amount is None:
            return
        self.rates.append(Rate(
            stage=Rate.LAND, yard=yard, to_terminal=self.terminals[terminal_code], vehicle_type=self.vtypes[vtype],
            amount=Decimal(str(round(float(amount), 2))), is_preferred=preferred, is_estimate=estimate, note=note,
        ))

    def sea(self, terminal_code, port_code, vtype, amount, estimate=False, note=""):
        if amount is None:
            return
        self.rates.append(Rate(
            stage=Rate.SEA, from_terminal=self.terminals[terminal_code], to_port=self.ports[port_code],
            vehicle_type=self.vtypes[vtype], amount=Decimal(str(round(float(amount), 2))),
            is_estimate=estimate, note=note,
        ))

    @transaction.atomic
    def save(self, publish=True) -> PriceList:
        stats = dict(self.counters)
        stats["строк суши"] = sum(1 for r in self.rates if r.stage == Rate.LAND)
        stats["строк моря"] = sum(1 for r in self.rates if r.stage == Rate.SEA)
        if self.warnings:
            stats["предупреждения"] = self.warnings[:50]
        price_list = PriceList.objects.create(provider=self.provider, stats=stats, **self.meta)
        for rate in self.rates:
            rate.price_list = price_list
        Rate.objects.bulk_create(self.rates, batch_size=2000)
        if publish:
            PriceList.objects.filter(
                provider=self.provider, scope=price_list.scope, status=PriceList.PUBLISHED
            ).exclude(pk=price_list.pk).update(status=PriceList.ARCHIVED)
            price_list.status = PriceList.PUBLISHED
            price_list.save(update_fields=["status"])
        return price_list


def money(value):
    """'$1,350' / 1350 / '-' / '' → float или None."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).replace("$", "").replace(",", "").strip()
    if s in ("", "-", "—"):
        return None
    try:
        return float(s)
    except ValueError:
        return None
