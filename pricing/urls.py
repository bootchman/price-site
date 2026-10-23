from django.urls import path

from . import views_tariffs as t

urlpatterns = [
    path("tariffs/", t.index, name="tariffs"),
    path("tariffs/add/", t.add_provider, name="tariff_add_provider"),
    path("tariffs/rate/", t.set_rate, name="tariff_set_rate"),
    path("tariffs/<int:pk>/", t.provider_page, name="tariff_provider"),
    path("tariffs/<int:pk>/sea/", t.add_sea, name="tariff_add_sea"),
    path("tariffs/<int:pk>/charge/", t.add_charge, name="tariff_add_charge"),
    path("tariffs/<int:pk>/<str:kind>/<int:item_id>/delete/", t.delete_manual, name="tariff_delete"),
]
