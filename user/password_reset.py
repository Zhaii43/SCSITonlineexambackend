from django.db import models
from django.contrib.auth import get_user_model
import secrets
from datetime import timedelta, datetime
from django.utils import timezone
from django.conf import settings

User = get_user_model()


def _now():
    """Return current datetime consistent with USE_TZ setting."""
    if getattr(settings, 'USE_TZ', True):
        return timezone.now()
    return datetime.now()

class PasswordResetToken(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    token = models.CharField(max_length=100, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    is_used = models.BooleanField(default=False)

    def save(self, *args, **kwargs):
        if not self.token:
            self.token = secrets.token_urlsafe(32)
        if not self.expires_at:
            self.expires_at = _now() + timedelta(hours=1)
        super().save(*args, **kwargs)

    def is_valid(self):
        return not self.is_used and _now() < self.expires_at

    class Meta:
        db_table = 'password_reset_tokens'
