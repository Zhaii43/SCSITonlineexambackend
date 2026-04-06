"""
email_utils.py
- send_staff_approval_email: direct SMTP (triggered by Django admin signal, no frontend proxy)
- All other functions: no-op stubs — emails handled by Next.js Nodemailer proxy routes
"""

import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from django.conf import settings

logger = logging.getLogger(__name__)


def _send_direct(to, subject, html, text=""):
    if not to:
        return False
    user = getattr(settings, "MAILER_GMAIL_USER", "").strip()
    password = getattr(settings, "MAILER_GMAIL_APP_PASSWORD", "").replace(" ", "").strip()
    from_name = getattr(settings, "MAILER_FROM_NAME", "SCSIT Online Exam").strip()
    if not user or not password:
        logger.error("MAILER_GMAIL_USER or MAILER_GMAIL_APP_PASSWORD not configured")
        return False
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"{from_name} <{user}>"
    msg["To"] = to
    if text:
        msg.attach(MIMEText(text, "plain"))
    msg.attach(MIMEText(html, "html"))
    try:
        with smtplib.SMTP("smtp.gmail.com", 587, timeout=20) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.login(user, password)
            smtp.sendmail(user, [to], msg.as_string())
        logger.info("Email sent: %s to %s", subject, to)
        return True
    except Exception as exc:
        logger.exception("Email failed to %s: %s", to, exc)
        return False


def send_staff_approval_email(user):
    """Called by Django signal when admin approves a staff account."""
    name = (getattr(user, "first_name", "") or "").strip() or "there"
    role = getattr(user, "role", "Staff")
    frontend_url = getattr(settings, "FRONTEND_URL", "")
    html = f"""<div style="font-family:Arial,sans-serif;color:#0f172a;line-height:1.7;padding:24px">
      <h2>Staff Account Approved</h2>
      <p>Hello <strong>{name}</strong>,</p>
      <p>Your SCSIT Online Exam staff account has been approved with the role of <strong>{role}</strong>.</p>
      <p><a href="{frontend_url}/login" style="background:#0f172a;color:#fff;padding:10px 20px;border-radius:8px;text-decoration:none;display:inline-block">Go to Dashboard</a></p>
    </div>"""
    return _send_direct(
        getattr(user, "email", ""),
        "Your Staff Account Has Been Approved - SCSIT Online Exam",
        html,
        f"Hello {name},\n\nYour staff account ({role}) has been approved.\nLog in at {frontend_url}/login",
    )


# ── No-op stubs — all other emails handled by Next.js Nodemailer proxies ──────
def send_email_verification_otp(user, otp_code): pass
def send_pre_registration_otp(email, otp_code): pass
def send_student_approval_email(user): pass
def send_student_rejected_email(user, rejection_reason=None): pass
def send_exam_scheduled_email(user, exam): pass
def send_dean_exam_created_email(user, exam): pass
def send_results_published_email(user, result): pass
def send_password_reset_email(user, reset_code): pass
def send_bulk_import_email(user, set_password_token): pass
def send_bulk_exam_notification(users, exam): return 0
def send_announcement_email(user, announcement, created_by): pass
def _build_announcement_message(user, announcement, created_by): return None
def send_bulk_emails(messages): return 0
def send_time_extension_email(user, exam, extra_minutes, reason): pass
def send_exam_rejected_email(user, exam_title, dean_name): pass
def send_issue_report_email(user, report, actor_name): pass
def send_issue_report_reply_email(user, report, actor_name, message_text): pass
def _send_email_sync(to, subject, html, text=""): return False
