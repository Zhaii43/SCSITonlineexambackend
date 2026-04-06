"""
email_utils.py
- send_staff_approval_email: calls Next.js Nodemailer endpoint
- All other functions: no-op stubs handled by Next.js proxy routes
"""

import logging
import requests
from django.conf import settings

logger = logging.getLogger(__name__)


def send_staff_approval_email(user):
    """Called by Django signal - POSTs to Next.js to send via Nodemailer."""
    to = getattr(user, "email", "")
    if not to:
        return False
    name = (getattr(user, "first_name", "") or "").strip() or "there"
    role = getattr(user, "role", "Staff")
    frontend_url = getattr(settings, "FRONTEND_URL", "").rstrip("/")
    secret = getattr(settings, "EMAIL_BRIDGE_SECRET", "")
    if not secret or not frontend_url:
        logger.error("EMAIL_BRIDGE_SECRET or FRONTEND_URL not configured")
        return False
    try:
        resp = requests.post(
            f"{frontend_url}/api/internal/staff-approved",
            json={"to": to, "firstName": name, "role": role},
            headers={"x-email-bridge-secret": secret, "Content-Type": "application/json"},
            timeout=15,
        )
        if resp.ok:
            logger.info("Staff approval email sent to %s", to)
            return True
        logger.error("Staff approval email failed: %s %s", resp.status_code, resp.text[:200])
        return False
    except Exception as exc:
        logger.exception("Staff approval email error for %s: %s", to, exc)
        return False


# No-op stubs - all other emails handled by Next.js Nodemailer proxies
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
