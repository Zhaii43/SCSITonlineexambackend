from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.core.mail import get_connection
from notifications.email_utils import _send_html_email


class Command(BaseCommand):
    help = "Test the configured SMTP connection and send a test email."

    def add_arguments(self, parser):
        parser.add_argument(
            "recipient",
            nargs="?",
            help="Recipient email address. Defaults to DEFAULT_FROM_EMAIL/EMAIL_HOST_USER.",
        )

    def handle(self, *args, **options):
        recipient = options.get("recipient") or settings.EMAIL_HOST_USER

        if not recipient:
            raise CommandError(
                "No recipient email provided and EMAIL_HOST_USER is empty."
            )

        self.stdout.write("Checking email configuration...")
        self.stdout.write(f"EMAIL_HOST={settings.EMAIL_HOST}")
        self.stdout.write(f"EMAIL_PORT={settings.EMAIL_PORT}")
        self.stdout.write(f"EMAIL_USE_TLS={settings.EMAIL_USE_TLS}")
        self.stdout.write(f"EMAIL_USE_SSL={getattr(settings, 'EMAIL_USE_SSL', False)}")
        self.stdout.write(f"EMAIL_HOST_USER={settings.EMAIL_HOST_USER}")
        self.stdout.write(f"DEFAULT_FROM_EMAIL={settings.DEFAULT_FROM_EMAIL}")
        self.stdout.write(f"Recipient={recipient}")

        try:
            connection = get_connection(fail_silently=False)
            connection.open()
            self.stdout.write(self.style.SUCCESS("SMTP connection opened successfully."))
        except Exception as exc:
            raise CommandError(f"SMTP connection failed: {exc}") from exc
        finally:
            try:
                connection.close()
            except Exception:
                pass

        try:
            sent = _send_html_email(
                subject="SCSIT Online Exam email test",
                recipient=recipient,
                html_message=(
                    "<p>This is a test email from the SCSIT Online Exam backend. "
                    "If you received this, SMTP is configured correctly.</p>"
                ),
                plain_message=(
                    "This is a test email from the SCSIT Online Exam backend. "
                    "If you received this, SMTP is configured correctly."
                ),
            )
        except Exception as exc:
            raise CommandError(f"SMTP send failed: {exc}") from exc

        if not sent:
            raise CommandError("SMTP send failed. Check the backend logs for the exact SMTP error.")

        self.stdout.write(self.style.SUCCESS("Test email sent successfully."))
