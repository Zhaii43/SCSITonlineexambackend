import logging

from django.conf import settings
from django.core.mail.backends.base import BaseEmailBackend
from django.core.mail.backends.smtp import EmailBackend as SmtpEmailBackend

from .resend_backend import ResendEmailBackend

logger = logging.getLogger(__name__)


class FailoverEmailBackend(BaseEmailBackend):
    """
    Try Resend first when configured, then fall back to SMTP.
    This is useful on platforms where SMTP ports may be unreliable or blocked.
    """

    def __init__(self, fail_silently=False, **kwargs):
        super().__init__(fail_silently=fail_silently, **kwargs)
        self._backends = []

        resend_key = getattr(settings, "RESEND_API_KEY", "").strip()
        smtp_user = getattr(settings, "EMAIL_HOST_USER", "").strip()
        smtp_password = getattr(settings, "EMAIL_HOST_PASSWORD", "").strip()

        if resend_key:
            self._backends.append(("resend", ResendEmailBackend(fail_silently=fail_silently, **kwargs)))

        if smtp_user and smtp_password:
            self._backends.append(("smtp", SmtpEmailBackend(fail_silently=fail_silently, **kwargs)))

        if not self._backends:
            logger.error("No usable email backend configured. Set RESEND_API_KEY or SMTP credentials.")

    def send_messages(self, email_messages):
        if not email_messages:
            return 0

        last_exception = None

        for name, backend in self._backends:
            try:
                sent = backend.send_messages(email_messages)
                if sent:
                    logger.info("Email sent using %s backend (%s/%s)", name, sent, len(email_messages))
                    return sent
                logger.warning("%s backend returned 0 sent messages", name)
            except Exception as exc:
                last_exception = exc
                logger.exception("Email backend %s failed", name)

        if last_exception and not self.fail_silently:
            raise last_exception
        return 0
