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


def send_student_approval_email(user):
    to = getattr(user, "email", "")
    if not to:
        return False
    first_name = (getattr(user, "first_name", "") or "").strip() or getattr(user, "username", "") or "there"
    frontend_url = getattr(settings, "FRONTEND_URL", "").rstrip("/")
    approved_at = getattr(user, "approved_at", None)
    bridge_result = _post_email_bridge({
        "emailType": "student_approval",
        "to": to,
        "firstName": first_name,
        "fullName": f"{user.first_name} {user.last_name}".strip(),
        "username": getattr(user, "username", ""),
        "email": to,
        "schoolId": getattr(user, "school_id", "") or "",
        "department": getattr(user, "department", "") or "",
        "yearLevel": getattr(user, "year_level", "") or "",
        "approvedAt": approved_at.strftime("%B %d, %Y %I:%M %p") if approved_at else "",
        "frontendUrl": frontend_url,
    })
    if bridge_result is True:
        return True

    text_body = (
        f"Hello {first_name},\n\n"
        "Your student account has been approved.\n\n"
        f"Username: {getattr(user, 'username', '')}\n"
        f"Email: {to}\n"
        f"School ID: {getattr(user, 'school_id', '') or 'N/A'}\n"
        f"Department: {getattr(user, 'department', '') or 'N/A'}\n"
        f"Year Level: {getattr(user, 'year_level', '') or 'N/A'}\n\n"
        "You can now log in and access your dashboard to view available exams.\n\n"
    )
    if frontend_url:
        text_body += f"Login page: {frontend_url}/login"
    return _send_templated_email(
        to,
        "Your Student Account Has Been Approved - SCSIT Online Exam",
        "emails/student_approval.html",
        {"user": user, "frontend_url": frontend_url},
        text_body,
    )


def send_masterlist_approval_email(user):
    """Send approval email for masterlist-imported students with their temporary credentials."""
    to = getattr(user, "email", "")
    if not to:
        return False
    first_name = (getattr(user, "first_name", "") or "").strip() or getattr(user, "username", "") or "there"
    frontend_url = getattr(settings, "FRONTEND_URL", "").rstrip("/")
    username = getattr(user, "school_id", "") or getattr(user, "username", "")
    subjects = getattr(user, "enrolled_subjects", None) or []
    bridge_result = _post_email_bridge({
        "emailType": "masterlist_approval",
        "to": to,
        "firstName": first_name,
        "username": username,
        "schoolId": getattr(user, "school_id", "") or "",
        "department": getattr(user, "department", "") or "",
        "yearLevel": getattr(user, "year_level", "") or "",
        "enrolledSubjects": subjects,
        "frontendUrl": frontend_url,
    })
    if bridge_result is True:
        return True

    subjects_text = ("\nEnrolled Subjects:\n" + "\n".join(f"  - {s}" for s in subjects)) if subjects else ""
    text_body = (
        f"Hello {first_name},\n\n"
        "Your student account has been approved.\n\n"
        f"Username: {username}\n"
        f"Temporary Password: {getattr(user, 'school_id', '') or username}\n"
        f"Department: {getattr(user, 'department', '') or 'N/A'}\n"
        f"Year Level: {getattr(user, 'year_level', '') or 'N/A'}"
        f"{subjects_text}\n\n"
        "Use your School ID as both username and temporary password on your first login.\n"
        "You will be required to change your password immediately after signing in.\n\n"
    )
    if frontend_url:
        text_body += f"Login page: {frontend_url}/login"
    return _send_templated_email(
        to,
        "Your Student Account Has Been Approved - SCSIT Online Exam",
        "emails/masterlist_approval.html",
        {"user": user, "frontend_url": frontend_url, "username": username, "subjects": subjects},
        text_body,
    )


def send_student_rejected_email(user, rejection_reason=None):
    to = getattr(user, "email", "")
    if not to:
        return False
    first_name = (getattr(user, "first_name", "") or "").strip() or getattr(user, "username", "") or "there"
    frontend_url = getattr(settings, "FRONTEND_URL", "").rstrip("/")
    bridge_result = _post_email_bridge({
        "emailType": "student_rejected",
        "to": to,
        "firstName": first_name,
        "fullName": f"{user.first_name} {user.last_name}".strip(),
        "schoolId": getattr(user, "school_id", "") or "",
        "department": getattr(user, "department", "") or "",
        "yearLevel": getattr(user, "year_level", "") or "",
        "rejectionReason": rejection_reason or None,
        "frontendUrl": frontend_url,
    })
    if bridge_result is True:
        return True
    return _send_templated_email(
        to,
        "Your Application Was Not Approved - SCSIT Online Exam",
        "emails/student_rejected.html",
        {"user": user, "rejection_reason": rejection_reason, "frontend_url": frontend_url},
        f"Hello {first_name},\n\nUnfortunately your student account application was not approved.\n"
        + (f"Reason: {rejection_reason}\n" if rejection_reason else "")
        + "\nPlease contact your department for assistance.",
    )


def send_exam_scheduled_email(user, exam):
    to = getattr(user, "email", "")
    if not to:
        return False
    first_name = (getattr(user, "first_name", "") or "").strip() or getattr(user, "username", "") or "there"
    full_name = f"{getattr(user, 'first_name', '')} {getattr(user, 'last_name', '')}".strip() or first_name
    frontend_url = getattr(settings, "FRONTEND_URL", "").rstrip("/")
    exam_data = {
        "title": exam.title,
        "subject": exam.subject,
        "department": exam.department,
        "examType": exam.exam_type,
        "scheduledDate": exam.scheduled_date.strftime("%B %d, %Y %I:%M %p"),
        "expirationTime": exam.expiration_time.strftime("%B %d, %Y %I:%M %p") if exam.expiration_time else None,
        "durationMinutes": exam.duration_minutes,
        "totalPoints": exam.total_points,
        "passingScore": exam.passing_score,
        "instructions": exam.instructions or "",
        "yearLevel": exam.year_level,
    }
    bridge_result = _post_email_bridge({
        "emailType": "exam_scheduled",
        "to": to,
        "firstName": first_name,
        "fullName": full_name,
        "exam": exam_data,
        "frontendUrl": frontend_url,
    })
    if bridge_result is True:
        return True
    return _send_templated_email(
        to,
        f'New Exam Scheduled: {exam.title} - SCSIT Online Exam',
        "emails/exam_scheduled.html",
        {"user": user, "exam": exam, "frontend_url": frontend_url},
        (
            f"Hello {first_name},\n\n"
            f'A new {exam.exam_type} exam "{exam.title}" has been scheduled.\n'
            f"Subject: {exam.subject}\n"
            f"Date: {exam.scheduled_date.strftime('%B %d, %Y %I:%M %p')}\n"
            f"Duration: {exam.duration_minutes} minutes\n\n"
            "Log in to your dashboard to view the exam details."
        ),
    )


def send_dean_exam_created_email(user, exam):
    to = getattr(user, "email", "")
    if not to:
        return False
    full_name = f"{getattr(user, 'first_name', '')} {getattr(user, 'last_name', '')}".strip() or getattr(user, "username", "")
    frontend_url = getattr(settings, "FRONTEND_URL", "").rstrip("/")
    exam_data = {
        "title": exam.title,
        "subject": exam.subject,
        "department": exam.department,
        "examType": exam.exam_type,
        "scheduledDate": exam.scheduled_date.strftime("%B %d, %Y %I:%M %p"),
        "yearLevel": exam.year_level,
    }
    bridge_result = _post_email_bridge({
        "emailType": "dean_exam_created",
        "to": to,
        "fullName": full_name,
        "exam": exam_data,
        "frontendUrl": frontend_url,
    })
    if bridge_result is True:
        return True
    return _send_templated_email(
        to,
        f'Exam Created: {exam.title} - SCSIT Online Exam',
        "emails/exam_scheduled.html",
        {"user": user, "exam": exam, "frontend_url": frontend_url},
        f"Hello {full_name},\n\nYour exam \"{exam.title}\" has been created and published.\n"
        f"Subject: {exam.subject}\nDate: {exam.scheduled_date.strftime('%B %d, %Y %I:%M %p')}",
    )


def send_results_published_email(user, result):
    to = getattr(user, "email", "")
    if not to:
        return False
    first_name = (getattr(user, "first_name", "") or "").strip() or getattr(user, "username", "") or "there"
    frontend_url = getattr(settings, "FRONTEND_URL", "").rstrip("/")
    exam = result.exam
    result_data = {
        "id": result.id,
        "examTitle": exam.title,
        "subject": exam.subject,
        "score": result.score,
        "totalPoints": result.total_points,
        "percentage": round(result.percentage, 1),
        "grade": result.grade,
        "remarks": result.remarks,
        "passed": result.remarks == "Passed",
        "submittedAt": result.submitted_at.strftime("%B %d, %Y %I:%M %p"),
    }
    bridge_result = _post_email_bridge({
        "emailType": "results_published",
        "to": to,
        "firstName": first_name,
        "result": result_data,
        "frontendUrl": frontend_url,
    })
    if bridge_result is True:
        return True
    return _send_templated_email(
        to,
        f'Your Result for "{exam.title}" - SCSIT Online Exam',
        "emails/results_published.html",
        {"user": user, "result": result, "frontend_url": frontend_url},
        f"Hello {first_name},\n\nYour result for \"{exam.title}\" is now available.\n"
        f"Score: {result.score}/{result.total_points} | Grade: {result.grade} | {result.remarks}",
    )
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

    set_password_link = f"{frontend_url}/forgot-password?token={set_password_token}" if frontend_url else set_password_token
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
def send_time_extension_email(user, exam, extra_minutes, reason):
    to = getattr(user, "email", "")
    if not to:
        return False
    first_name = (getattr(user, "first_name", "") or "").strip() or getattr(user, "username", "") or "there"
    frontend_url = getattr(settings, "FRONTEND_URL", "").rstrip("/")
    exam_data = {
        "title": exam.title,
        "subject": exam.subject,
        "scheduledDate": exam.scheduled_date.strftime("%B %d, %Y %I:%M %p"),
    }
    bridge_result = _post_email_bridge({
        "emailType": "time_extension",
        "to": to,
        "firstName": first_name,
        "exam": exam_data,
        "extraMinutes": extra_minutes,
        "reason": reason or "No reason provided.",
        "frontendUrl": frontend_url,
    })
    if bridge_result is True:
        return True
    return _send_templated_email(
        to,
        f'Exam Time Extended: {exam.title} - SCSIT Online Exam',
        "emails/time_extension.html",
        {"user": user, "exam": exam, "extra_minutes": extra_minutes, "reason": reason, "frontend_url": frontend_url},
        f"Hello {first_name},\n\nYour time for \"{exam.title}\" has been extended by {extra_minutes} minute(s).\n"
        f"Reason: {reason or 'No reason provided.'}",
    )


def send_exam_rejected_email(user, exam_title, dean_name):
    to = getattr(user, "email", "")
    if not to:
        return False
    first_name = (getattr(user, "first_name", "") or "").strip() or getattr(user, "username", "") or "there"
    frontend_url = getattr(settings, "FRONTEND_URL", "").rstrip("/")
    bridge_result = _post_email_bridge({
        "emailType": "exam_rejected",
        "to": to,
        "firstName": first_name,
        "examTitle": exam_title,
        "deanName": dean_name,
        "frontendUrl": frontend_url,
    })
    if bridge_result is True:
        return True
    return _send_templated_email(
        to,
        f'Exam Rejected: {exam_title} - SCSIT Online Exam',
        "emails/exam_rejected.html",
        {"user": user, "exam_title": exam_title, "dean_name": dean_name, "frontend_url": frontend_url},
        f"Hello {first_name},\n\nYour exam \"{exam_title}\" was rejected by {dean_name}.\n"
        "Please review and resubmit your exam for approval.",
    )


def send_issue_report_email(user, report, actor_name):
    to = getattr(user, "email", "")
    if not to:
        return False
    first_name = (getattr(user, "first_name", "") or "").strip() or getattr(user, "username", "") or "there"
    frontend_url = getattr(settings, "FRONTEND_URL", "").rstrip("/")
    report_data = {
        "id": report.id,
        "examTitle": report.exam.title,
        "questionOrder": report.question.order,
        "issueType": report.get_issue_type_display(),
        "description": report.description,
        "reportedAnswer": report.reported_answer or None,
    }
    bridge_result = _post_email_bridge({
        "emailType": "issue_report",
        "to": to,
        "firstName": first_name,
        "report": report_data,
        "actorName": actor_name,
        "role": getattr(user, "role", ""),
        "frontendUrl": frontend_url,
    })
    if bridge_result is True:
        return True
    return _send_templated_email(
        to,
        f'New Issue Report: {report.exam.title} - SCSIT Online Exam',
        "emails/exam_scheduled.html",
        {"user": user, "frontend_url": frontend_url},
        f"Hello {first_name},\n\n{actor_name} reported an issue in \"{report.exam.title}\" "
        f"(Question {report.question.order}).\nType: {report.get_issue_type_display()}\n"
        f"Description: {report.description}",
    )


def send_issue_report_reply_email(user, report, actor_name, message_text):
    to = getattr(user, "email", "")
    if not to:
        return False
    first_name = (getattr(user, "first_name", "") or "").strip() or getattr(user, "username", "") or "there"
    frontend_url = getattr(settings, "FRONTEND_URL", "").rstrip("/")
    report_data = {
        "id": report.id,
        "examTitle": report.exam.title,
        "questionOrder": report.question.order,
        "issueType": report.get_issue_type_display(),
    }
    bridge_result = _post_email_bridge({
        "emailType": "issue_report_reply",
        "to": to,
        "firstName": first_name,
        "report": report_data,
        "actorName": actor_name,
        "messageText": message_text,
        "frontendUrl": frontend_url,
    })
    if bridge_result is True:
        return True
    return _send_templated_email(
        to,
        f'Issue Report Update: {report.exam.title} - SCSIT Online Exam',
        "emails/exam_scheduled.html",
        {"user": user, "frontend_url": frontend_url},
        f"Hello {first_name},\n\n{actor_name} replied to your issue report for \"{report.exam.title}\".\n"
        f"Message: {message_text}",
    )
def _send_email_sync(to, subject, html, text=""): return False
