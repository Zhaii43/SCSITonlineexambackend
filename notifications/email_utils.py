"""Send selected emails through the Next.js Nodemailer bridge."""

from __future__ import annotations

import logging
from typing import Any

import requests
from django.conf import settings

logger = logging.getLogger(__name__)


def _frontend_url() -> str:
    return (getattr(settings, "FRONTEND_URL", "") or "").strip().rstrip("/")


def _bridge_url() -> str:
    frontend_url = _frontend_url()
    return f"{frontend_url}/api/email-bridge" if frontend_url else ""


def _bridge_secret() -> str:
    return (getattr(settings, "EMAIL_BRIDGE_SECRET", "") or "").strip()


def _format_datetime(value) -> str:
    if not value:
        return "Not specified"
    try:
        return value.strftime("%B %d, %Y %I:%M %p")
    except Exception:
        return str(value)


def _full_name(user) -> str:
    if hasattr(user, "get_full_name"):
        full_name = (user.get_full_name() or "").strip()
        if full_name:
            return full_name
    return (getattr(user, "username", "") or "there").strip()


def _first_name(user) -> str:
    first_name = (getattr(user, "first_name", "") or "").strip()
    if first_name:
        return first_name
    full_name = _full_name(user)
    return full_name.split()[0] if full_name else "there"


def _display(value: Any, fallback: str = "Not specified") -> str:
    return str(value) if value not in (None, "") else fallback


def _send_bridge_message(payload: dict[str, Any]) -> bool:
    bridge_url = _bridge_url()
    secret = _bridge_secret()
    recipient = payload.get("to")

    if not recipient:
        logger.warning("Skipping email bridge call with empty recipient for type=%s", payload.get("emailType"))
        return False

    if not bridge_url or not secret:
        logger.error("Email bridge is not configured. Set FRONTEND_URL and EMAIL_BRIDGE_SECRET.")
        return False

    try:
        response = requests.post(
            bridge_url,
            json=payload,
            headers={
                "x-email-bridge-secret": secret,
                "Content-Type": "application/json",
            },
            timeout=20,
        )
        if response.ok:
            logger.info("Email bridge sent %s email to %s", payload.get("emailType"), recipient)
            return True

        logger.error(
            "Email bridge failed for %s -> %s | status=%s body=%s",
            payload.get("emailType"),
            recipient,
            response.status_code,
            response.text[:500],
        )
        return False
    except Exception as exc:
        logger.exception("Email bridge exception for %s -> %s | error: %s", payload.get("emailType"), recipient, exc)
        return False


def send_email_verification_otp(user, otp_code):
    return False


def send_pre_registration_otp(email, otp_code):
    return False


def send_student_approval_email(user):
    return _send_bridge_message(
        {
            "emailType": "student_approval",
            "to": getattr(user, "email", ""),
            "firstName": _first_name(user),
            "fullName": _full_name(user),
            "username": getattr(user, "username", ""),
            "email": getattr(user, "email", ""),
            "schoolId": getattr(user, "school_id", "") or "Not provided",
            "department": user.get_department_display() if hasattr(user, "get_department_display") else _display(getattr(user, "department", "")),
            "yearLevel": user.get_year_level_display() if getattr(user, "year_level", None) and hasattr(user, "get_year_level_display") else "Not specified",
            "approvedAt": _format_datetime(getattr(user, "approved_at", None)),
            "frontendUrl": _frontend_url(),
        }
    )


def send_staff_approval_email(user):
    return False


def send_student_rejected_email(user, rejection_reason=None):
    return _send_bridge_message(
        {
            "emailType": "student_rejected",
            "to": getattr(user, "email", ""),
            "firstName": _first_name(user),
            "fullName": _full_name(user),
            "schoolId": getattr(user, "school_id", "") or "Not provided",
            "department": user.get_department_display() if hasattr(user, "get_department_display") else _display(getattr(user, "department", "")),
            "yearLevel": user.get_year_level_display() if getattr(user, "year_level", None) and hasattr(user, "get_year_level_display") else "Not specified",
            "rejectionReason": rejection_reason or getattr(user, "rejection_reason", "") or "No reason provided.",
            "frontendUrl": _frontend_url(),
        }
    )


def _format_exam_year_level(exam) -> str:
    year_level = getattr(exam, "year_level", "")
    if not year_level:
        return "Not specified"
    if year_level == "ALL":
        return "All Year Levels"
    return str(year_level)


def send_exam_scheduled_email(user, exam):
    return _send_bridge_message(
        {
            "emailType": "exam_scheduled",
            "to": getattr(user, "email", ""),
            "firstName": _first_name(user),
            "fullName": _full_name(user),
            "exam": {
                "id": getattr(exam, "id", None),
                "title": getattr(exam, "title", ""),
                "subject": getattr(exam, "subject", ""),
                "department": _display(getattr(exam, "department", "")),
                "examType": exam.get_exam_type_display() if hasattr(exam, "get_exam_type_display") else _display(getattr(exam, "exam_type", "")),
                "questionType": exam.get_question_type_display() if hasattr(exam, "get_question_type_display") else _display(getattr(exam, "question_type", "")),
                "scheduledDate": _format_datetime(getattr(exam, "scheduled_date", None)),
                "expirationTime": _format_datetime(getattr(exam, "expiration_time", None)),
                "duration": getattr(exam, "duration_minutes", 0),
                "totalPoints": getattr(exam, "total_points", None),
                "passingScore": getattr(exam, "passing_score", None),
                "yearLevel": _format_exam_year_level(exam),
                "instructions": getattr(exam, "instructions", "") or "",
            },
            "frontendUrl": _frontend_url(),
        }
    )


def send_dean_exam_created_email(user, exam):
    return False


def send_results_published_email(user, result):
    return False


def send_password_reset_email(user, reset_code):
    return False


def send_bulk_import_email(user, set_password_token):
    return False


def send_bulk_exam_notification(users, exam):
    success_count = 0
    for user in users:
        if send_exam_scheduled_email(user, exam):
            success_count += 1
    return success_count


def _build_announcement_message(user, announcement, created_by):
    if not getattr(user, "email", ""):
        return None

    dashboard_path = "/dashboard/student" if getattr(user, "role", "") == "student" else "/dashboard"
    return {
        "emailType": "announcement",
        "to": getattr(user, "email", ""),
        "firstName": _first_name(user),
        "fullName": _full_name(user),
        "announcement": {
            "title": getattr(announcement, "title", ""),
            "message": getattr(announcement, "message", ""),
            "createdBy": created_by,
            "createdAt": _format_datetime(getattr(announcement, "created_at", None)),
            "targetAudience": announcement.get_target_audience_display() if hasattr(announcement, "get_target_audience_display") else _display(getattr(announcement, "target_audience", ""), "Everyone"),
            "department": getattr(announcement, "department", "") or "All Departments",
            "linkPath": dashboard_path,
        },
        "frontendUrl": _frontend_url(),
    }


def send_announcement_email(user, announcement, created_by):
    message = _build_announcement_message(user, announcement, created_by)
    if not message:
        return False
    return _send_bridge_message(message)


def send_bulk_emails(messages):
    success_count = 0
    for message in messages:
        if _send_bridge_message(message):
            success_count += 1
    return success_count


def send_time_extension_email(user, exam, extra_minutes, reason):
    return False


def send_exam_rejected_email(user, exam_title, dean_name):
    return False


def send_issue_report_email(user, report, actor_name):
    return False


def send_issue_report_reply_email(user, report, actor_name, message_text):
    return False


def _send_email_sync(to, subject, html, text=""):
    return False
