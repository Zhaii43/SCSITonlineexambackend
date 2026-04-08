"""
email_utils.py
- send_staff_approval_email: calls Next.js Nodemailer endpoint
- OTP emails: prefer the protected Next.js email bridge, fall back to Django email
- All other functions: no-op stubs handled by Next.js proxy routes
"""

import logging

import requests
from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string

logger = logging.getLogger(__name__)


def _bridge_config():
    frontend_url = getattr(settings, "FRONTEND_URL", "").rstrip("/")
    secret = getattr(settings, "EMAIL_BRIDGE_SECRET", "").strip()
    if not frontend_url or not secret:
        return None, None
    return frontend_url, secret


def _post_email_bridge(payload):
    frontend_url, secret = _bridge_config()
    if not frontend_url or not secret:
        return None

    try:
        response = requests.post(
            f"{frontend_url}/api/email-bridge",
            json=payload,
            headers={"x-email-bridge-secret": secret, "Content-Type": "application/json"},
            timeout=15,
        )
        if response.ok:
            return True

        logger.error("Email bridge failed: %s %s", response.status_code, response.text[:200])
        return False
    except Exception as exc:
        logger.exception("Email bridge request failed: %s", exc)
        return False


def _send_templated_email(to, subject, template_name, context, text_body):
    if not to:
        return False

    try:
        html_body = render_to_string(template_name, context)
        message = EmailMultiAlternatives(
            subject=subject,
            body=text_body,
            from_email=getattr(settings, "DEFAULT_FROM_EMAIL", ""),
            to=[to],
        )
        message.attach_alternative(html_body, "text/html")
        return bool(message.send())
    except Exception as exc:
        logger.exception("Direct email send failed for %s | subject=%s | error=%s", to, subject, exc)
        return False


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


def send_email_verification_otp(user, otp_code):
    to = getattr(user, "email", "")
    first_name = (getattr(user, "first_name", "") or "").strip() or getattr(user, "username", "") or "there"

    bridge_result = _post_email_bridge(
        {
            "emailType": "email_verification_otp",
            "to": to,
            "firstName": first_name,
            "otp": otp_code,
        }
    )
    if bridge_result is True:
        return True

    text_body = (
        f"Hello {first_name},\n\n"
        f"Your SCSIT Online Exam verification code is: {otp_code}\n\n"
        "This code expires in 10 minutes.\n\n"
        "If you did not request this, you can safely ignore this email."
    )
    return _send_templated_email(
        to,
        "Verify Your Email - SCSIT Online Exam",
        "emails/email_verification.html",
        {"user": user, "otp_code": otp_code},
        text_body,
    )


def send_pre_registration_otp(email, otp_code):
    bridge_result = _post_email_bridge(
        {
            "emailType": "email_verification_otp",
            "to": email,
            "firstName": "there",
            "otp": otp_code,
        }
    )
    if bridge_result is True:
        return True

    text_body = (
        "Hello,\n\n"
        f"Your SCSIT Online Exam verification code is: {otp_code}\n\n"
        "This code expires in 10 minutes.\n\n"
        "If you did not request this, you can safely ignore this email."
    )
    return _send_templated_email(
        email,
        "Verify Your Email - SCSIT Online Exam",
        "emails/email_verification.html",
        {"user": None, "otp_code": otp_code},
        text_body,
    )


def send_password_reset_email(user, reset_code):
    to = getattr(user, "email", "")
    first_name = (getattr(user, "first_name", "") or "").strip() or getattr(user, "username", "") or "there"
    frontend_url = getattr(settings, "FRONTEND_URL", "").rstrip("/")

    bridge_result = _post_email_bridge(
        {
            "emailType": "password_reset",
            "to": to,
            "firstName": first_name,
            "otp": reset_code,
            "frontendUrl": frontend_url,
        }
    )
    if bridge_result is True:
        return True

    reset_link = f"{frontend_url}/reset-password?token={reset_code}" if frontend_url else reset_code
    text_body = (
        f"Hello {first_name},\n\n"
        f"Your password reset code is: {reset_code}\n\n"
        "This code expires in 15 minutes.\n\n"
        f"Reset page: {reset_link}\n\n"
        "If you did not request a password reset, you can safely ignore this email."
    )
    return _send_templated_email(
        to,
        "Password Reset Request - SCSIT Online Exam",
        "emails/password_reset.html",
        {"user": user, "reset_code": reset_code, "frontend_url": frontend_url},
        text_body,
    )


# No-op stubs - all other emails handled by Next.js Nodemailer proxies
def send_student_approval_email(user): pass
def send_student_rejected_email(user, rejection_reason=None): pass
def send_exam_scheduled_email(user, exam): pass
def send_dean_exam_created_email(user, exam): pass
def send_results_published_email(user, result): pass
def send_bulk_import_email(user, set_password_token):
    to = getattr(user, "email", "")
    first_name = (getattr(user, "first_name", "") or "").strip() or getattr(user, "username", "") or "there"
    frontend_url = getattr(settings, "FRONTEND_URL", "").rstrip("/")

    bridge_result = _post_email_bridge(
        {
            "emailType": "bulk_import",
            "to": to,
            "firstName": first_name,
            "setPasswordToken": set_password_token,
            "frontendUrl": frontend_url,
        }
    )
    if bridge_result is True:
        return True

    set_password_link = f"{frontend_url}/reset-password?token={set_password_token}" if frontend_url else set_password_token
    text_body = (
        f"Hello {first_name},\n\n"
        "Your student account has been approved.\n\n"
        f"Set your password here: {set_password_link}\n\n"
        "After setting your password, log in using your Student ID and new password."
    )
    return _send_templated_email(
        to,
        "Your Student Account Has Been Approved - SCSIT Online Exam",
        "emails/bulk_import.html",
        {"user": user, "set_password_token": set_password_token, "frontend_url": frontend_url},
        text_body,
    )
def send_bulk_exam_notification(users, exam): return 0
def send_announcement_email(user, announcement, created_by): pass
def _build_announcement_message(user, announcement, created_by): return None
def send_bulk_emails(messages): return 0
def send_time_extension_email(user, exam, extra_minutes, reason): pass
def send_exam_rejected_email(user, exam_title, dean_name): pass
def send_issue_report_email(user, report, actor_name): pass
def send_issue_report_reply_email(user, report, actor_name, message_text): pass
def _send_email_sync(to, subject, html, text=""): return False
