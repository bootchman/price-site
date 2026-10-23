from django.urls import path

from . import views

urlpatterns = [
    path("login/", views.login_page, name="login"),
    path("login/start/", views.login_start, name="login_start"),
    path("login/status/", views.login_status, name="login_status"),
    path("logout/", views.logout_view, name="logout"),
]
