from django.db.models import Count, Q
from django.shortcuts import render

from .models import Auction, Charge, DestinationPort, PriceList, Rate, VehicleType, Yard
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

    full, land_only, has_sea = [], [], False
    if yard and vtype and port:
        full, land_only = find_routes(yard, vtype, port)
        has_sea = Rate.objects.filter(
            stage=Rate.SEA, to_port=port, price_list__status=PriceList.PUBLISHED
        ).exists()
    charges = []
    provider_ids = {o.land.price_list.provider_id for o in full} | {o.sea.price_list.provider_id for o in full}
    provider_ids |= {r.price_list.provider_id for r in land_only}
    seen = set()
    for c in Charge.objects.filter(price_list__status=PriceList.PUBLISHED, price_list__provider_id__in=provider_ids) \
            .select_related("price_list__provider").order_by("category", "price_list__provider__name"):
        key = (c.price_list.provider_id, c.category, c.name, c.amount, c.currency)
        if key not in seen:
            seen.add(key)
            charges.append(c)
    by_provider = {}
    for c in charges:
        sign = "€" if c.currency == "EUR" else "$"
        by_provider.setdefault(c.price_list.provider_id, []).append(f"{c.get_category_display()} {sign}{c.amount:.0f}")
    for o in full:
        o.charges = sorted({
            f"{o.land.price_list.provider.name}: {x}" for x in by_provider.get(o.land.price_list.provider_id, [])
        } | {f"{o.sea.price_list.provider.name}: {x}" for x in by_provider.get(o.sea.price_list.provider_id, [])})
    return render(request, "pricing/route.html", {
        "charges": charges,
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
