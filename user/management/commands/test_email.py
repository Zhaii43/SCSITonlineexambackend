from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.core.mail import get_connection, send_mail


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
            sent = send_mail(
                subject="SCSIT Online Exam email test",
                message=(
                    "This is a test email from the SCSIT Online Exam backend. "
                    "If you received this, SMTP is configured correctly."
                ),
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[recipient],
                fail_silently=False,
            )
        except Exception as exc:
            raise CommandError(f"SMTP send failed: {exc}") from exc

        if sent != 1:
            raise CommandError(f"Expected to send 1 email, but send_mail returned {sent}.")

        self.stdout.write(self.style.SUCCESS("Test email sent successfully."))
