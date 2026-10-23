from django.contrib import messages
from django.contrib.auth import logout
from django.shortcuts import redirect

from .access import LAND, find_entry

OPEN_PREFIXES = ("/login", "/logout", "/static/", "/healthz")
LAND_PREFIXES = ("/land/",)  # роль «Суша» видит только «Сравнение суши»


class AccessListMiddleware:
    """Пускает только вошедших через бота, кто до сих пор есть в списке доступа; права — по роли из таблицы."""

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
        entry = find_entry(profile.phone, profile.username) if profile else None
        if entry is None:
            logout(request)
            messages.error(request, "Доступ закрыт: вашего номера нет в списке доступа.")
            return redirect("login")
        access = entry.access
        if access is None:
            logout(request)
            messages.error(request, f"Доступ закрыт: роль «{entry.role}» не распознана. Обратитесь к администратору.")
            return redirect("login")
        request.access = access
        if access == LAND and not path.startswith(LAND_PREFIXES):
            return redirect("land")
        return self.get_response(request)
