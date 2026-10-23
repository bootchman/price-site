"""Выгрузка «VS против конкурентов» по суше (с учётом коррекции операторов) в JSON.

  python manage.py export_land_vs [--vt sedan] > land_vs.json
JSON затем записывает в Google Таблицу root-скрипт deploy/write_land_vs_sheet.py.
"""
import json
from collections import defaultdict
from statistics import mean

from django.core.management.base import BaseCommand
from django.utils import timezone

from pricing.models import PriceList, Provider, Rate, VehicleType

PORTS = [("GA", "Savannah"), ("NJ", "Elizabeth / New York"), ("TX", "Houston"), ("CA", "Los Angeles")]
VS = "VS Brothers"
ORDER = [VS, "Atlantic", "AML", "Cargoloop", "Shipper 101"]


class Command(BaseCommand):
    help = "Выгрузить сравнение суши VS с конкурентами (JSON в stdout)"

    def add_arguments(self, parser):
        parser.add_argument("--vt", default="sedan")
        parser.add_argument("--auctions", default="Copart,IAAI")

    def handle(self, vt, auctions, **_):
        vtype = VehicleType.objects.get(code=vt)
        groups = [g for g, _ in PORTS]
        providers = {p.name: p for p in Provider.objects.all()}
        operators = [o for o in ORDER if o in providers] + sorted(set(providers) - set(ORDER))
        # Море VS для седана по складу — чтобы показать полную цену калькулятора (суша + море)
        vs_sea = {}
        for r in Rate.objects.filter(stage=Rate.SEA, price_list__status=PriceList.PUBLISHED, price_list__is_manual=False,
                                     price_list__provider__name=VS, vehicle_type=vtype, container="40HC",
                                     to_port__code="KLJ").select_related("from_terminal"):
            vs_sea[r.from_terminal.group] = float(r.amount)

        out = {
            "generated": timezone.localtime().strftime("%d.%m.%Y %H:%M"),
            "vehicle_type": vtype.name, "ports": PORTS, "operators": operators, "vs_sea": vs_sea,
            "corrections": [[p.name, float(p.land_correction)] for p in providers.values()
                            if p.land_correction_enabled and p.land_correction],
            "auctions": {}, "summary": [],
        }
        for auction in [a.strip() for a in auctions.split(",") if a.strip()]:
            cell = defaultdict(dict)
            yards = {}
            for r in Rate.objects.filter(
                stage=Rate.LAND, price_list__status=PriceList.PUBLISHED, vehicle_type=vtype,
                yard__auction__code=auction, to_terminal__group__in=groups,
            ).select_related("yard", "to_terminal", "price_list__provider"):
                p = r.price_list.provider
                amount = float(p.corrected_land(r.amount))
                key = (r.yard_id, r.to_terminal.group)
                if p.name not in cell[key] or amount < cell[key][p.name]:
                    cell[key][p.name] = amount
                yards[r.yard_id] = r.yard
            rows = []
            stats = {g: {"compared": 0, "dearer": [], "cheaper_or_equal": 0} for g in groups}
            for yard in sorted(yards.values(), key=lambda y: (y.state, y.name)):
                row = {"yard": f"{yard.state} - {yard.name}", "city": yard.city, "ports": {}}
                for g in groups:
                    prices = cell.get((yard.id, g), {})
                    if not prices:
                        continue
                    vs = prices.get(VS)
                    rivals = {o: v for o, v in prices.items() if o != VS}
                    best = min(rivals.values()) if rivals else None
                    best_ops = [o for o, v in rivals.items() if v == best] if rivals else []
                    diff = round(vs - best) if vs is not None and best is not None else None
                    if diff is not None:
                        stats[g]["compared"] += 1
                        if diff > 0:
                            stats[g]["dearer"].append(diff)
                        else:
                            stats[g]["cheaper_or_equal"] += 1
                    row["ports"][g] = {
                        "prices": prices, "vs_full": (vs + vs_sea[g]) if vs is not None and g in vs_sea else None,
                        "best": best, "best_ops": best_ops, "diff": diff,
                    }
                if any(VS in x["prices"] for x in row["ports"].values()):  # только площадки, где есть VS
                    rows.append(row)
            out["auctions"][auction] = rows
            for g, name in PORTS:
                st = stats[g]
                out["summary"].append({
                    "auction": auction, "port": name, "compared": st["compared"], "dearer": len(st["dearer"]),
                    "share": round(100 * len(st["dearer"]) / st["compared"]) if st["compared"] else 0,
                    "avg": round(mean(st["dearer"])) if st["dearer"] else 0,
                    "max": max(st["dearer"]) if st["dearer"] else 0, "cheaper_or_equal": st["cheaper_or_equal"],
                })
        self.stdout.write(json.dumps(out, ensure_ascii=False))
