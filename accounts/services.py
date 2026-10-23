"""Логика входа, общая для сайта и бота (бот вызывает её через sync_to_async)."""
import json
import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from .access import find_entry, normalize_phone
from .models import LoginToken, TelegramProfile

DENY_NOT_IN_LIST = "Вашего номера нет в списке доступа. Обратитесь к администратору."
DENY_EXPIRED = "Ссылка для входа устарела. Вернитесь на сайт и нажмите «Войти» ещё раз."
DENY_FOREIGN_CONTACT = "Нужно поделиться своим контактом, а не чужим."
DENY_UNKNOWN_ROLE = "Ваша роль в списке доступа не распознана. Обратитесь к администратору."


def create_login_token(session_key: str) -> LoginToken:
    return LoginToken.objects.create(
        token=secrets.token_urlsafe(24),
        session_key=session_key,
        expires_at=timezone.now() + timedelta(seconds=settings.LOGIN_TOKEN_TTL_SECONDS),
    )


def get_pending_token(token: str):
    """Код, по которому ещё можно войти (бот проверяет его на /start)."""
    try:
        login = LoginToken.objects.get(token=token)
    except LoginToken.DoesNotExist:
        return None
    if login.status != LoginToken.PENDING or login.expires_at < timezone.now():
        return None
    return login


@transaction.atomic
def confirm_login(token: str, telegram_id: int, contact_user_id: int, phone: str, username: str, full_name: str):
    """Бот получил контакт. Возвращает (успех, текст для пользователя)."""
    login = LoginToken.objects.select_for_update().filter(token=token).first()
    if login is None or login.status != LoginToken.PENDING or login.expires_at < timezone.now():
        return False, DENY_EXPIRED
    if contact_user_id != telegram_id:
        return False, DENY_FOREIGN_CONTACT

    entry = find_entry(phone, username)
    if entry is None:
        login.status = LoginToken.DENIED
        login.telegram_id = telegram_id
        login.deny_reason = "нет в списке"
        login.save(update_fields=["status", "telegram_id", "deny_reason"])
        return False, DENY_NOT_IN_LIST
    if entry.access is None:
        login.status = LoginToken.DENIED
        login.telegram_id = telegram_id
        login.deny_reason = f"роль «{entry.role}» не распознана"
        login.save(update_fields=["status", "telegram_id", "deny_reason"])
        return False, DENY_UNKNOWN_ROLE

    user_model = get_user_model()
    profile = TelegramProfile.objects.filter(telegram_id=telegram_id).select_related("user").first()
    if profile is None:
        user, _ = user_model.objects.get_or_create(username=f"tg{telegram_id}")
        profile = TelegramProfile(user=user, telegram_id=telegram_id)
    user = profile.user
    user.first_name = (full_name or "")[:150]
    user.set_unusable_password()
    user.save()
    profile.phone = normalize_phone(phone)
    profile.username = (username or "")[:64]
    profile.full_name = (full_name or "")[:200]
    profile.last_login_via_bot = timezone.now()
    profile.save()

    login.status = LoginToken.APPROVED
    login.telegram_id = telegram_id
    login.user = user
    login.save(update_fields=["status", "telegram_id", "user"])

    record_auth_event(entry.row, telegram_id, profile.phone, profile.username, profile.full_name)
    return True, "Готово! Вернитесь на сайт — вход выполнен."


def record_auth_event(row: int, telegram_id: int, phone: str, username: str, full_name: str):
    """Строчка для root-скрипта: он заполнит «Пользователь» и «Время авторизации» в таблице."""
    event = {
        "row": row,
        "telegram_id": telegram_id,
        "phone": phone,
        "username": username,
        "full_name": full_name,
        "at": timezone.localtime().strftime("%Y-%m-%d %H:%M"),
    }
    with open(settings.AUTH_EVENTS_FILE, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(event, ensure_ascii=False) + "\n")
