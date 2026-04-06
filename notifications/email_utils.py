import logging

import requests
from django.conf import settings

logger = logging.getLogger(__name__)


def _bridge_url() -> str:
    return f"{settings.FRONTEND_URL.rstrip('/')}/api/email-bridge"


def _bridge_secret() -> str:
    return getattr(settings, "EMAIL_BRIDGE_SECRET", "")


def _send(email_type: str, payload: dict) -> bool:
    secret = _bridge_secret()
    if not secret:
        logger.error("EMAIL_BRIDGE_SECRET is not configured – email not sent (%s)", email_type)
        return False
    url = _bridge_url()
    try:
        resp = requests.post(
            url,
            json={"emailType": email_type, **payload},
            headers={"x-email-bridge-secret": secret, "Content-Type": "application/json"},
            timeout=20,
        )
        if resp.ok:
            logger.info("Email sent via bridge: %s → %s", email_type, payload.get("to"))
            return True
        logger.error("Bridge rejected %s to %s: %s %s", email_type, url, resp.status_code, resp.text[:300])
        return False
    except requests.exceptions.Timeout:
        logger.error("Bridge timeout for %s – URL: %s", email_type, url)
        return False
    except requests.exceptions.ConnectionError as exc:
        logger.error("Bridge connection error for %s – URL: %s – %s", email_type, url, exc)
        return False
    except Exception as exc:
        logger.exception("Bridge unexpected error for %s: %s", email_type, exc)
        return False


def _first_name(user) -> str:
    return (getattr(user, "first_name", "") or "").strip() or "there"


def _full_name(user) -> str:
    name = (getattr(user, "get_full_name", lambda: "")() or "").strip()
    return name or getattr(user, "username", "there")


def send_email_verification_otp(user, otp_code):
    return _send("email_verification_otp", {
        "to": getattr(user, "email", ""),
        "firstName": _first_name(user),
        "otp": otp_code,
    })


def send_pre_registration_otp(email, otp_code):
    return _send("email_verification_otp", {
        "to": email,
        "firstName": "there",
        "otp": otp_code,
    })


def send_student_approval_email(user):
    return _send("student_approval", {
        "to": getattr(user, "email", ""),
        "firstName": _first_name(user),
        "frontendUrl": settings.FRONTEND_URL,
    })


def send_staff_approval_email(user):
    return _send("staff_approval", {
        "to": getattr(user, "email", ""),
        "firstName": _first_name(user),
        "role": getattr(user, "role", "Staff"),
        "frontendUrl": settings.FRONTEND_URL,
    })


def send_student_rejected_email(user, rejection_reason=None):
    return _send("student_rejected", {
        "to": getattr(user, "email", ""),
        "firstName": _first_name(user),
        "rejectionReason": rejection_reason or None,
        "frontendUrl": settings.FRONTEND_URL,
    })


def send_exam_scheduled_email(user, exam):
    return _send("exam_scheduled", {
        "to": getattr(user, "email", ""),
        "firstName": _first_name(user),
        "exam": {
            "title": str(exam.title),
            "subject": str(exam.subject),
            "department": str(exam.department),
            "examType": str(exam.exam_type),
            "scheduledDate": exam.scheduled_date.strftime("%B %d, %Y %I:%M %p"),
            "duration": int(exam.duration_minutes),
            "yearLevel": str(exam.year_level),
        },
        "frontendUrl": settings.FRONTEND_URL,
    })


def send_dean_exam_created_email(user, exam):
    return _send("dean_exam_created", {
        "to": getattr(user, "email", ""),
        "fullName": _full_name(user),
        "exam": {
            "id": exam.id,
            "title": str(exam.title),
            "subject": str(exam.subject),
            "department": str(exam.department),
            "examType": str(exam.exam_type),
            "scheduledDate": exam.scheduled_date.strftime("%B %d, %Y %I:%M %p"),
            "yearLevel": str(exam.year_level),
        },
        "frontendUrl": settings.FRONTEND_URL,
    })


def send_results_published_email(user, result):
    return _send("results_published", {
        "to": getattr(user, "email", ""),
        "firstName": _first_name(user),
        "result": {
            "examTitle": str(result.exam.title),
            "subject": str(result.exam.subject),
            "score": int(result.score),
            "totalItems": int(result.total_points),
            "percentage": round(float(result.percentage), 1),
            "passed": result.remarks == "Passed",
            "dateTaken": result.submitted_at.strftime("%B %d, %Y %I:%M %p"),
        },
        "frontendUrl": settings.FRONTEND_URL,
    })


def send_password_reset_email(user, reset_code):
    # Password reset emails are sent by the Next.js /api/password-reset/request route.
    # This path is only hit by the legacy request_password_reset Django view.
    from django.conf import settings as _s
    frontend_url = getattr(_s, 'FRONTEND_URL', '')
    return _send("password_reset", {
        "to": getattr(user, "email", ""),
        "firstName": _first_name(user),
        "otp": reset_code,
        "frontendUrl": frontend_url,
    })


def send_bulk_import_email(user, set_password_token):
    return _send("bulk_import", {
        "to": getattr(user, "email", ""),
        "firstName": _first_name(user),
        "setPasswordToken": set_password_token,
        "frontendUrl": settings.FRONTEND_URL,
    })


def send_bulk_exam_notification(users, exam):
    return sum(1 for user in users if send_exam_scheduled_email(user, exam))


def send_announcement_email(user, announcement, created_by):
    return _send("announcement", {
        "to": getattr(user, "email", ""),
        "firstName": _first_name(user),
        "announcement": {
            "title": str(announcement.title),
            "message": str(announcement.message),
            "createdBy": str(created_by),
            "createdAt": announcement.created_at.strftime("%B %d, %Y %I:%M %p"),
        },
        "frontendUrl": settings.FRONTEND_URL,
    })


def send_time_extension_email(user, exam, extra_minutes, reason):
    return _send("time_extension", {
        "to": getattr(user, "email", ""),
        "firstName": _first_name(user),
        "exam": {
            "title": str(exam.title),
            "subject": str(exam.subject),
            "scheduledDate": exam.scheduled_date.strftime("%B %d, %Y %I:%M %p"),
        },
        "extraMinutes": int(extra_minutes),
        "reason": reason or "No reason provided.",
        "frontendUrl": settings.FRONTEND_URL,
    })


def send_exam_rejected_email(user, exam_title, dean_name):
    return _send("exam_rejected", {
        "to": getattr(user, "email", ""),
        "firstName": _first_name(user),
        "examTitle": str(exam_title),
        "deanName": str(dean_name),
        "frontendUrl": settings.FRONTEND_URL,
    })


def send_issue_report_email(user, report, actor_name):
    role = getattr(user, "role", "instructor")
    return _send("issue_report", {
        "to": getattr(user, "email", ""),
        "firstName": _first_name(user),
        "report": {
            "id": report.id,
            "examTitle": str(report.exam.title),
            "questionOrder": int(report.question.order),
            "issueType": str(report.get_issue_type_display()),
            "reportedAnswer": report.reported_answer or None,
            "description": str(report.description),
        },
        "actorName": str(actor_name),
        "role": role,
        "frontendUrl": settings.FRONTEND_URL,
    })


def send_issue_report_reply_email(user, report, actor_name, message_text):
    return _send("issue_report_reply", {
        "to": getattr(user, "email", ""),
        "firstName": _first_name(user),
        "report": {
            "id": report.id,
            "examTitle": str(report.exam.title),
            "questionOrder": int(report.question.order),
            "status": str(report.get_status_display()),
        },
        "actorName": str(actor_name),
        "messageText": str(message_text),
        "frontendUrl": settings.FRONTEND_URL,
    })
