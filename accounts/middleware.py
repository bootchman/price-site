from django.contrib import messages
from django.contrib.auth import logout
from django.shortcuts import redirect

from .access import is_allowed

OPEN_PREFIXES = ("/login", "/logout", "/static/", "/healthz")


class AccessListMiddleware:
    """Пускает только вошедших через бота и до сих пор присутствующих в списке доступа."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path
        if path.startswith(OPEN_PREFIXES):
            return self.get_response(request)
        user = request.user
        if not user.is_authenticated:
            return redirect("login")
        profile = getattr(user, "telegram", None)
        if profile is None or not is_allowed(profile.phone, profile.username):
            logout(request)
            messages.error(request, "Доступ закрыт: вашего номера нет в списке доступа.")
            return redirect("login")
        return self.get_response(request)
