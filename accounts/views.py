from django.conf import settings
from django.contrib.auth import login, logout
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_POST

from .models import LoginToken
from .services import create_login_token

SESSION_TOKEN_KEY = "login_token_id"


@ensure_csrf_cookie
def login_page(request):
    if request.user.is_authenticated:
        return redirect("home")
    return render(request, "accounts/login.html", {"bot_username": settings.PRICE_BOT_USERNAME})


@require_POST
def login_start(request):
    if not request.session.session_key:
        request.session.save()
    login_token = create_login_token(request.session.session_key)
    request.session[SESSION_TOKEN_KEY] = login_token.id
    link = f"https://t.me/{settings.PRICE_BOT_USERNAME}?start=login_{login_token.token}"
    return JsonResponse({"link": link, "ttl": settings.LOGIN_TOKEN_TTL_SECONDS})


@require_GET
def login_status(request):
    token_id = request.session.get(SESSION_TOKEN_KEY)
    login_token = LoginToken.objects.filter(id=token_id, session_key=request.session.session_key).first()
    if login_token is None:
        return JsonResponse({"status": "none"})
    if login_token.status == LoginToken.APPROVED and login_token.user_id:
        login_token.status = LoginToken.USED
        login_token.save(update_fields=["status"])
        login(request, login_token.user, backend="django.contrib.auth.backends.ModelBackend")
        request.session.pop(SESSION_TOKEN_KEY, None)
        return JsonResponse({"status": "ok", "redirect": "/"})
    if login_token.status == LoginToken.DENIED:
        return JsonResponse({"status": "denied", "message": "Вашего номера нет в списке доступа."})
    if login_token.expires_at < timezone.now():
        return JsonResponse({"status": "expired"})
    return JsonResponse({"status": "pending"})


@require_POST
def logout_view(request):
    logout(request)
    return redirect("login")
