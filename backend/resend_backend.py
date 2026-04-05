"""
Custom Django email backend that sends via Resend HTTPS API.
Requires RESEND_API_KEY in environment. Falls back gracefully on error.
"""
import logging
from django.core.mail.backends.base import BaseEmailBackend
from django.conf import settings

logger = logging.getLogger(__name__)


class ResendEmailBackend(BaseEmailBackend):
    def __init__(self, fail_silently=False, **kwargs):
        super().__init__(fail_silently=fail_silently, **kwargs)
        self.api_key = getattr(settings, 'RESEND_API_KEY', '')

    def send_messages(self, email_messages):
        if not self.api_key:
            logger.error("RESEND_API_KEY is not set — cannot send emails")
            if not self.fail_silently:
                raise ValueError("RESEND_API_KEY is not configured")
            return 0

        import requests as req

        sent = 0
        for msg in email_messages:
            try:
                html_body = None
                for content, mimetype in getattr(msg, 'alternatives', []):
                    if mimetype == 'text/html':
                        html_body = content
                        break

                payload = {
                    'from': msg.from_email,
                    'to': msg.to,
                    'subject': msg.subject,
                    'text': msg.body,
                }
                if html_body:
                    payload['html'] = html_body

                response = req.post(
                    'https://api.resend.com/emails',
                    json=payload,
                    headers={
                        'Authorization': f'Bearer {self.api_key}',
                        'Content-Type': 'application/json',
                    },
                    timeout=15,
                )

                if response.status_code in (200, 201):
                    sent += 1
                    logger.info("Resend: email sent to %s | subject: %s", msg.to, msg.subject)
                else:
                    logger.error(
                        "Resend: failed to send to %s | status: %s | body: %s",
                        msg.to, response.status_code, response.text
                    )
                    if not self.fail_silently:
                        raise Exception(f"Resend API error {response.status_code}: {response.text}")

            except Exception as exc:
                logger.exception("Resend: exception sending to %s | error: %s", msg.to, exc)
                if not self.fail_silently:
                    raise

        return sent
