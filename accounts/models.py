from django.conf import settings
from django.db import models


class TelegramProfile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="telegram")
    telegram_id = models.BigIntegerField(unique=True)
    phone = models.CharField(max_length=32, blank=True)
    username = models.CharField(max_length=64, blank=True)
    full_name = models.CharField(max_length=200, blank=True)
    last_login_via_bot = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.full_name or self.username or self.telegram_id}"


class LoginToken(models.Model):
    """Одноразовый код входа: сайт создаёт, бот подтверждает, сайт погашает."""

    PENDING, APPROVED, DENIED, USED = "pending", "approved", "denied", "used"
    STATUS_CHOICES = [(PENDING, "ожидает"), (APPROVED, "подтверждён"), (DENIED, "отказ"), (USED, "использован")]

    token = models.CharField(max_length=64, unique=True)
    session_key = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=PENDING)
    telegram_id = models.BigIntegerField(null=True, blank=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.CASCADE)
    deny_reason = models.CharField(max_length=200, blank=True)

    class Meta:
        indexes = [models.Index(fields=["session_key"])]
