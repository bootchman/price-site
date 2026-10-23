"""Курс EUR→USD с сайта ЕЦБ (ежедневно по cron)."""
import re
import urllib.request
from datetime import date
from decimal import Decimal

from django.core.management.base import BaseCommand

from pricing.models import ExchangeRate

ECB_URL = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml"


class Command(BaseCommand):
    help = "Загрузить курс EUR→USD от ЕЦБ"

    def handle(self, *args, **options):
        xml = urllib.request.urlopen(ECB_URL, timeout=30).read().decode()
        rate = re.search(r"currency='USD'\s+rate='([\d.]+)'", xml)
        day = re.search(r"time='(\d{4}-\d{2}-\d{2})'", xml)
        if not rate:
            self.stderr.write("Курс USD не найден в ответе ЕЦБ")
            return
        d = date.fromisoformat(day.group(1)) if day else date.today()
        obj, _ = ExchangeRate.objects.update_or_create(date=d, source="ЕЦБ", defaults={"eur_usd": Decimal(rate.group(1))})
        self.stdout.write(f"EUR→USD {obj.eur_usd} на {obj.date}")
