"""Справочники и прайсы.

Любая цена любого прайса сводится к одной из двух записей:
- Rate — тариф на сушу (площадка → склад в порту) или море (склад → порт получения);
- Charge — статья расходов оператора (услуги, material fee, hazardous fee).
  Экспедирование к операторам не относится и в сравнении не участвует (решение Alex 23.10.2026).
"""
from django.db import models


class Auction(models.Model):
    code = models.CharField(max_length=60, unique=True)  # «Copart», «IAAI», «Manheim»…

    class Meta:
        ordering = ["code"]

    def __str__(self):
        return self.code


class Yard(models.Model):
    """Площадка аукциона. name_key — нормализованное название для сопоставления."""

    auction = models.ForeignKey(Auction, on_delete=models.PROTECT, related_name="yards")
    name = models.CharField(max_length=200)
    name_key = models.CharField(max_length=200)
    state = models.CharField(max_length=8)
    city = models.CharField(max_length=120, blank=True)
    zip = models.CharField(max_length=16, blank=True)
    country = models.CharField(max_length=2, default="US")
    source = models.CharField(max_length=60, blank=True)  # из какого прайса площадка появилась
    verified = models.BooleanField(default=False)

    class Meta:
        ordering = ["state", "name"]
        constraints = [models.UniqueConstraint(fields=["auction", "state", "name_key"], name="uniq_yard_key")]

    def __str__(self):
        return f"{self.state} - {self.name}"


class YardAlias(models.Model):
    """Как площадка называется у конкретного оператора (ручная привязка)."""

    provider = models.ForeignKey("Provider", on_delete=models.CASCADE)
    auction = models.ForeignKey(Auction, on_delete=models.CASCADE)
    state = models.CharField(max_length=8)
    raw_key = models.CharField(max_length=200)
    yard = models.ForeignKey(Yard, on_delete=models.CASCADE, related_name="aliases")

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["provider", "auction", "state", "raw_key"], name="uniq_yard_alias")
        ]


class Terminal(models.Model):
    """Склад в порту отправки. group — эквивалентные склады (New York у Atlantic ≈ Elizabeth NJ)."""

    code = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=80)
    group = models.CharField(max_length=20)
    country = models.CharField(max_length=2, default="US")

    class Meta:
        ordering = ["group", "name"]

    def __str__(self):
        return self.name


class DestinationPort(models.Model):
    code = models.CharField(max_length=10, unique=True)
    name = models.CharField(max_length=80)
    country = models.CharField(max_length=60)
    sort = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["sort", "name"]

    def __str__(self):
        return self.name


class VehicleType(models.Model):
    code = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=60)
    sort = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["sort"]

    def __str__(self):
        return self.name


class Provider(models.Model):
    name = models.CharField(max_length=100, unique=True)
    note = models.TextField(blank=True)
    # Коррекция суши: прибавляется к каждой цене суши оператора (−25 = минус $25), если включена
    land_correction_enabled = models.BooleanField(default=False)
    land_correction = models.DecimalField(max_digits=8, decimal_places=2, default=0)

    def corrected_land(self, amount):
        """Цена суши с учётом коррекции (не ниже 0)."""
        if not self.land_correction_enabled or not self.land_correction:
            return amount
        return max(amount + self.land_correction, 0)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class PriceList(models.Model):
    DRAFT, PUBLISHED, ARCHIVED = "draft", "published", "archived"
    STATUS_CHOICES = [(DRAFT, "черновик"), (PUBLISHED, "опубликован"), (ARCHIVED, "архив")]

    provider = models.ForeignKey(Provider, on_delete=models.PROTECT, related_name="price_lists")
    scope = models.CharField(max_length=40, default="all")  # «copart», «iaai», «all» — что покрывает файл
    title = models.CharField(max_length=200)
    source = models.CharField(max_length=500)
    valid_from = models.DateField(null=True, blank=True)
    imported_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default=DRAFT)
    is_bundle = models.BooleanField(default=False)  # «суша + море» в одной цене
    is_manual = models.BooleanField(default=False)  # «ручные значения» оператора, введённые на сайте
    stats = models.JSONField(default=dict, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["provider__name", "-imported_at"]

    def __str__(self):
        return f"{self.provider} · {self.title}"


CONTAINER_CHOICES = [("40HC", "40'HC"), ("45HC", "45'HC")]
ANY_CONTAINER = "ANY"  # цена за единицу, не зависит ни от размера контейнера, ни от количества в нём
RATE_CONTAINER_CHOICES = CONTAINER_CHOICES + [(ANY_CONTAINER, "не зависит от контейнера")]


class Rate(models.Model):
    LAND, SEA = "land", "sea"
    STAGE_CHOICES = [(LAND, "суша"), (SEA, "море")]

    price_list = models.ForeignKey(PriceList, on_delete=models.CASCADE, related_name="rates")
    stage = models.CharField(max_length=8, choices=STAGE_CHOICES)
    yard = models.ForeignKey(Yard, null=True, blank=True, on_delete=models.CASCADE)
    from_terminal = models.ForeignKey(Terminal, null=True, blank=True, on_delete=models.CASCADE, related_name="+")
    to_terminal = models.ForeignKey(Terminal, null=True, blank=True, on_delete=models.CASCADE, related_name="+")
    to_port = models.ForeignKey(DestinationPort, null=True, blank=True, on_delete=models.CASCADE)
    vehicle_type = models.ForeignKey(VehicleType, on_delete=models.PROTECT)
    container = models.CharField(max_length=5, choices=RATE_CONTAINER_CHOICES, default="40HC")  # для моря
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=3, default="USD")
    is_preferred = models.BooleanField(default=False)  # «предпочтительный» склад оператора
    is_estimate = models.BooleanField(default=False)  # цена выведена (например, по коэффициенту)
    note = models.CharField(max_length=200, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["stage", "yard", "vehicle_type"]),
            models.Index(fields=["stage", "to_port", "vehicle_type"]),
        ]


class Charge(models.Model):
    SERVICES, MATERIAL, HAZARD = "services", "material_fee", "hazardous"
    CATEGORY_CHOICES = [(SERVICES, "услуги"), (MATERIAL, "material fee"), (HAZARD, "hazardous fee")]
    FUEL_CHOICES = [("", "электро и гибрид"), ("electric", "только электро"), ("hybrid", "только гибрид")]
    UNIT_CHOICES = [("car", "за машину"), ("container", "за контейнер"), ("lot", "за партию"), ("fixed", "фиксированно")]

    SEA_STAGE, LAND_STAGE, ANY_STAGE = "sea", "land", "any"
    APPLIES_ON_CHOICES = [
        (SEA_STAGE, "когда оператор везёт морем"),
        (LAND_STAGE, "когда оператор везёт по суше"),
        (ANY_STAGE, "при любом участии оператора"),
    ]

    price_list = models.ForeignKey(PriceList, on_delete=models.CASCADE, related_name="charges")
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES)
    applies_on = models.CharField(max_length=8, choices=APPLIES_ON_CHOICES, default=SEA_STAGE)
    to_port = models.ForeignKey(DestinationPort, null=True, blank=True, on_delete=models.CASCADE)
    container = models.CharField(max_length=5, choices=CONTAINER_CHOICES, blank=True, default="")  # пусто = любой
    fuel = models.CharField(max_length=10, choices=FUEL_CHOICES, blank=True, default="")  # для hazardous fee
    name = models.CharField(max_length=200)
    applies_to = models.CharField(max_length=120, blank=True)  # порт / страна / «все»
    unit = models.CharField(max_length=12, choices=UNIT_CHOICES, default="car")
    vehicle_type = models.ForeignKey(VehicleType, null=True, blank=True, on_delete=models.PROTECT)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=3, default="USD")
    note = models.CharField(max_length=200, blank=True)


class ExchangeRate(models.Model):
    """Курс EUR → USD для пересчёта статей в EUR в итог маршрута."""

    date = models.DateField()
    eur_usd = models.DecimalField(max_digits=10, decimal_places=4)
    source = models.CharField(max_length=40)  # «ЕЦБ» / «вручную»
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date", "-created_at"]


class TariffChange(models.Model):
    """Журнал ручных изменений тарифов операторов (все пользователи равны и могут править)."""

    provider = models.ForeignKey(Provider, on_delete=models.CASCADE, related_name="tariff_changes")
    user = models.ForeignKey("auth.User", null=True, on_delete=models.SET_NULL)
    at = models.DateTimeField(auto_now_add=True)
    action = models.CharField(max_length=20)
    description = models.CharField(max_length=300)

    class Meta:
        ordering = ["-at"]
