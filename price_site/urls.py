from django.http import HttpResponse
from django.urls import include, path

urlpatterns = [
    path("healthz", lambda request: HttpResponse("ok", content_type="text/plain")),
    path("", include("accounts.urls")),
    path("", include("core.urls")),
    path("", include("pricing.urls")),
]
