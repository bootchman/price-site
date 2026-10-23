from django.urls import path

from pricing import views as pricing_views

urlpatterns = [
    path("", pricing_views.route, name="home"),
    path("operators/", pricing_views.operators, name="operators"),
]
