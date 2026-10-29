"""Загрузка прайса оператора по шаблону.

  python manage.py import_prices cargoloop [URL|файл.html]
  python manage.py import_prices atlantic TowingRates.xlsx
  python manage.py import_prices vs copart_calculator_export.xlsx [--sea LAX=900,SAV=500,ELZ=550,HOU=650]
  python manage.py import_prices shipper101 copart.json --auction Copart
  python manage.py import_prices aml copart.json --rates stavki.json --auction Copart
  python manage.py import_prices aml-land Прайс_собівартість.xlsx --replace-land
  python manage.py import_prices w8-land W8_Shipping_tarify_Klaipeda.xlsx
"""
from datetime import date

from django.core.management.base import BaseCommand, CommandError

from pricing.importers import providers


class Command(BaseCommand):
    help = "Загрузить прайс оператора (cargoloop / atlantic / vs / shipper101)"

    def add_arguments(self, parser):
        parser.add_argument("kind", choices=["cargoloop", "atlantic", "vs", "shipper101", "aml", "aml-land", "w8-land"])
        parser.add_argument("source", nargs="?", default="")
        parser.add_argument("--title", default="")
        parser.add_argument("--valid-from", default="")
        parser.add_argument("--auction", default="")
        parser.add_argument("--rates", default="", help="AML: JSON листа «Ставки»")
        parser.add_argument("--sea", default="", help="море для седана по складам, напр. LAX=900,SAV=500")
        parser.add_argument("--draft", action="store_true", help="не публиковать, оставить черновиком")
        parser.add_argument("--replace-land", action="store_true",
                            help="удалить сушу из других прайсов этого оператора (море и статьи расходов остаются)")

    def handle(self, kind, source, title, valid_from, auction, sea, draft, rates, replace_land=False, **_):
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
        elif kind == "w8-land":
            imp = providers.W8LandImporter(title or "Towing charges", source, valid_from=vf)
            imp.load(source)
        elif kind == "aml-land":
            imp = providers.AMLLandImporter(title or "Прайс собівартість (суша)", source, scope="land", valid_from=vf)
            imp.load(source)
        elif kind == "aml":
            if not (auction and rates):
                raise CommandError("Для aml нужны --auction Copart|IAAI и --rates <JSON листа «Ставки»>")
            imp = providers.AMLImporter(title or f"Порівняння {auction}", source, valid_from=vf)
            imp.load(source, rates, auction)
        else:
            if not auction:
                raise CommandError("Для shipper101 нужен --auction Copart или IAAI")
            imp = providers.Shipper101Importer(title or f"Location {auction}", source, valid_from=vf)
            imp.load(source, auction)
        price_list = imp.save(publish=not draft)
        if replace_land and not draft:
            from pricing.models import Rate
            removed = Rate.objects.filter(stage=Rate.LAND, price_list__provider=price_list.provider,
                                          price_list__is_manual=False).exclude(price_list=price_list).delete()[0]
            self.stdout.write(f"  удалено старой суши оператора: {removed} (море и статьи расходов не тронуты)")
        self.stdout.write(f"Готово: {price_list} [{price_list.get_status_display()}]")
        for k, v in price_list.stats.items():
            if k != "предупреждения":
                self.stdout.write(f"  {k}: {v}")
        for w in price_list.stats.get("предупреждения", []):
            self.stdout.write(f"  ! {w}")
