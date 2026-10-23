"""Загрузка прайса оператора по шаблону.

  python manage.py import_prices cargoloop [URL|файл.html]
  python manage.py import_prices atlantic TowingRates.xlsx
  python manage.py import_prices vs copart_calculator_export.xlsx [--sea LAX=900,SAV=500,ELZ=550,HOU=650]
  python manage.py import_prices shipper101 copart.json --auction Copart
"""
from datetime import date

from django.core.management.base import BaseCommand, CommandError

from pricing.importers import providers


class Command(BaseCommand):
    help = "Загрузить прайс оператора (cargoloop / atlantic / vs / shipper101)"

    def add_arguments(self, parser):
        parser.add_argument("kind", choices=["cargoloop", "atlantic", "vs", "shipper101"])
        parser.add_argument("source", nargs="?", default="")
        parser.add_argument("--title", default="")
        parser.add_argument("--valid-from", default="")
        parser.add_argument("--auction", default="")
        parser.add_argument("--sea", default="", help="море для седана по складам, напр. LAX=900,SAV=500")
        parser.add_argument("--draft", action="store_true", help="не публиковать, оставить черновиком")

    def handle(self, kind, source, title, valid_from, auction, sea, draft, **_):
        vf = date.fromisoformat(valid_from) if valid_from else None
        if kind == "cargoloop":
            source = source or providers.CARGOLOOP_URL
            imp = providers.CargoloopImporter(title or "Local Transportation", source, valid_from=vf)
            imp.load(source)
        elif kind == "atlantic":
            imp = providers.AtlanticImporter(title or "TowingRates", source, valid_from=vf)
            imp.load(source)
        elif kind == "vs":
            sea_map = None
            if sea:
                sea_map = {k.strip(): float(v) for k, v in (p.split("=") for p in sea.split(","))}
            imp = providers.VSCalculatorImporter(title or "Калькулятор", source, valid_from=vf, sea_sedan=sea_map)
            imp.load(source)
        else:
            if not auction:
                raise CommandError("Для shipper101 нужен --auction Copart или IAAI")
            imp = providers.Shipper101Importer(title or f"Location {auction}", source, valid_from=vf)
            imp.load(source, auction)
        price_list = imp.save(publish=not draft)
        self.stdout.write(f"Готово: {price_list} [{price_list.get_status_display()}]")
        for k, v in price_list.stats.items():
            if k != "предупреждения":
                self.stdout.write(f"  {k}: {v}")
        for w in price_list.stats.get("предупреждения", []):
            self.stdout.write(f"  ! {w}")
