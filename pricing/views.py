from django.db.models import Count, Q
from django.shortcuts import render

from .models import Auction, DestinationPort, PriceList, Rate, VehicleType, Yard
from .reference import AUCTIONS
from .routes import find_routes

LAND_PUBLISHED = Q(rate__stage=Rate.LAND, rate__price_list__status=PriceList.PUBLISHED)


def route(request):
    auctions = list(
        Auction.objects.filter(yards__rate__stage=Rate.LAND, yards__rate__price_list__status=PriceList.PUBLISHED)
        .distinct()
    )
    order = {code: i for i, code in enumerate(AUCTIONS)}
    auctions.sort(key=lambda a: (order.get(a.code, 99), a.code))
    vtypes = list(VehicleType.objects.all())
    ports = list(DestinationPort.objects.all())

    auction = next((a for a in auctions if str(a.id) == request.GET.get("auction")), auctions[0] if auctions else None)
    yards = []
    if auction:
        yards = list(
            Yard.objects.filter(auction=auction)
            .annotate(n=Count("rate", filter=LAND_PUBLISHED))
            .filter(n__gt=0)
            .order_by("state", "name")
        )
    yard = next((y for y in yards if str(y.id) == request.GET.get("yard")), None)
    vtype = next((v for v in vtypes if v.code == request.GET.get("vt")), vtypes[0] if vtypes else None)
    port = next((p for p in ports if p.code == request.GET.get("port")), ports[0] if ports else None)

    from .tariffs import FUEL_CHOICES
    fuel = request.GET.get("fuel") if request.GET.get("fuel") in dict(FUEL_CHOICES) else "ice"
    full, land_only, has_sea = [], [], False
    if yard and vtype and port:
        full, land_only = find_routes(yard, vtype, port, fuel)
        has_sea = Rate.objects.filter(
            stage=Rate.SEA, to_port=port, price_list__status=PriceList.PUBLISHED
        ).exists()
    from .tariffs import latest_eur_usd

    incomplete = {}
    for o in full:
        if o.missing:
            p = o.sea.price_list.provider
            incomplete.setdefault(p.pk, {"provider": p, "missing": set()})["missing"].update(o.missing)
    return render(request, "pricing/route.html", {
        "incomplete": [{"provider": v["provider"], "missing": sorted(v["missing"])} for v in incomplete.values()],
        "eur": latest_eur_usd(), "fuels": FUEL_CHOICES, "fuel": fuel, "fuel_name": dict(FUEL_CHOICES)[fuel],
        "auctions": auctions, "auction": auction, "yards": yards, "yard": yard,
        "vtypes": vtypes, "vtype": vtype, "ports": ports, "port": port,
        "full": full, "land_only": land_only, "has_sea": has_sea,
        "best": full[0].total if full else None,
    })


def operators(request):
    lists = (
        PriceList.objects.filter(status=PriceList.PUBLISHED)
        .select_related("provider")
        .annotate(
            land=Count("rates", filter=Q(rates__stage=Rate.LAND)),
            sea=Count("rates", filter=Q(rates__stage=Rate.SEA)),
            yards=Count("rates__yard", distinct=True),
        )
        .order_by("provider__name", "scope")
    )
    return render(request, "pricing/operators.html", {"lists": lists})
