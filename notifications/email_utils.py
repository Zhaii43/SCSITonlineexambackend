import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from django.conf import settings

logger = logging.getLogger(__name__)


# ─── Core sender ──────────────────────────────────────────────────────────────

def _get_gmail_config():
    user = getattr(settings, "MAILER_GMAIL_USER", "").strip()
    password = getattr(settings, "MAILER_GMAIL_APP_PASSWORD", "").replace(" ", "").strip()
    from_name = getattr(settings, "MAILER_FROM_NAME", "SCSIT Online Exam").strip()
    return user, password, from_name


def _send_email(to: str, subject: str, html: str, text: str = "") -> bool:
    if not to:
        logger.warning("Skipping email — empty recipient for subject: %s", subject)
        return False

    user, password, from_name = _get_gmail_config()
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
        logger.info("Email sent: %s → %s", subject, to)
        return True
    except smtplib.SMTPAuthenticationError:
        logger.error("Gmail auth failed — check MAILER_GMAIL_USER and MAILER_GMAIL_APP_PASSWORD")
        return False
    except Exception as exc:
        logger.exception("Failed to send email to %s | subject: %s | error: %s", to, subject, exc)
        return False


# ─── Shared HTML layout ────────────────────────────────────────────────────────

def _layout(title: str, body: str) -> str:
    year = __import__("datetime").datetime.now().year
    return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><title>{title}</title></head>
<body style="margin:0;padding:0;background:#f1f5f9;font-family:Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#f1f5f9;padding:32px 0;">
    <tr><td align="center">
      <table width="600" cellpadding="0" cellspacing="0" style="background:#ffffff;border-radius:12px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,.08);">
        <tr><td style="background:#0f172a;padding:24px 32px;">
          <p style="margin:0;color:#ffffff;font-size:20px;font-weight:bold;">SCSIT Online Exam</p>
        </td></tr>
        <tr><td style="padding:32px;color:#0f172a;line-height:1.7;font-size:15px;">
          {body}
        </td></tr>
        <tr><td style="background:#f8fafc;padding:16px 32px;text-align:center;font-size:12px;color:#94a3b8;">
          &copy; {year} SCSIT Online Exam &mdash; This is an automated message, please do not reply.
        </td></tr>
      </table>
    </td></tr>
  </table>
</body>
</html>"""


def _btn(href: str, label: str, secondary: bool = False) -> str:
    bg = "#e2e8f0" if secondary else "#0f172a"
    color = "#0f172a" if secondary else "#ffffff"
    return f'<a href="{href}" style="display:inline-block;background:{bg};color:{color};padding:10px 20px;border-radius:8px;text-decoration:none;font-size:14px;font-weight:600;margin-right:8px;">{label}</a>'


def _row(label: str, value: str) -> str:
    return f'<tr><td style="padding:6px 0;font-size:14px;color:#64748b;width:160px;">{label}</td><td style="padding:6px 0;font-size:14px;color:#0f172a;font-weight:600;">{value}</td></tr>'


def _first_name(user) -> str:
    return (getattr(user, "first_name", "") or "").strip() or "there"


def _full_name(user) -> str:
    name = (getattr(user, "get_full_name", lambda: "")() or "").strip()
    return name or getattr(user, "username", "there")


# ─── Email functions ───────────────────────────────────────────────────────────

def send_email_verification_otp(user, otp_code):
    name = _first_name(user)
    to = getattr(user, "email", "")
    html = _layout("Verify Your Email", f"""
        <h2 style="margin:0 0 8px;">Verify Your Email Address</h2>
        <p>Hello <strong>{name}</strong>,</p>
        <p>Use the code below to verify your email. It expires in <strong>10 minutes</strong>.</p>
        <div style="background:#f1f5f9;border-radius:8px;padding:20px;text-align:center;margin:24px 0;">
          <p style="margin:0 0 4px;font-size:13px;color:#64748b;">Your verification code</p>
          <p style="margin:0;font-size:36px;font-weight:bold;letter-spacing:12px;color:#0f172a;">{otp_code}</p>
        </div>
        <p style="font-size:13px;color:#64748b;">If you did not request this, you can safely ignore this email.</p>
    """)
    return _send_email(to, "Verify Your Email – SCSIT Online Exam", html,
                       f"Hello {name},\n\nYour verification code is: {otp_code}\n\nExpires in 10 minutes.")


def send_pre_registration_otp(email, otp_code):
    html = _layout("Verify Your Email", f"""
        <h2 style="margin:0 0 8px;">Verify Your Email Address</h2>
        <p>Use the code below to verify your email. It expires in <strong>10 minutes</strong>.</p>
        <div style="background:#f1f5f9;border-radius:8px;padding:20px;text-align:center;margin:24px 0;">
          <p style="margin:0 0 4px;font-size:13px;color:#64748b;">Your verification code</p>
          <p style="margin:0;font-size:36px;font-weight:bold;letter-spacing:12px;color:#0f172a;">{otp_code}</p>
        </div>
    """)
    return _send_email(email, "Verify Your Email – SCSIT Online Exam", html,
                       f"Your verification code is: {otp_code}\n\nExpires in 10 minutes.")


def send_student_approval_email(user):
    name = _first_name(user)
    frontend_url = settings.FRONTEND_URL
    html = _layout("Account Approved", f"""
        <h2 style="margin:0 0 8px;">🎉 Your Account Has Been Approved!</h2>
        <p>Hello <strong>{name}</strong>,</p>
        <p>Congratulations! Your SCSIT Online Exam student account has been reviewed and <strong>approved</strong>. You can now log in and access your exams.</p>
        <p style="margin-top:24px;">{_btn(f"{frontend_url}/login", "Log In Now")}</p>
    """)
    return _send_email(getattr(user, "email", ""),
                       "Your Account Has Been Approved – SCSIT Online Exam", html,
                       f"Hello {name},\n\nYour account has been approved. Log in at {frontend_url}/login")


def send_staff_approval_email(user):
    name = _first_name(user)
    role = getattr(user, "role", "Staff")
    frontend_url = settings.FRONTEND_URL
    html = _layout("Staff Account Approved", f"""
        <h2 style="margin:0 0 8px;">✅ Staff Account Approved</h2>
        <p>Hello <strong>{name}</strong>,</p>
        <p>Your SCSIT Online Exam staff account has been approved with the role of <strong>{role}</strong>.</p>
        <p style="margin-top:24px;">{_btn(f"{frontend_url}/login", "Go to Dashboard")}</p>
    """)
    return _send_email(getattr(user, "email", ""),
                       "Your Staff Account Has Been Approved – SCSIT Online Exam", html,
                       f"Hello {name},\n\nYour staff account ({role}) has been approved. Log in at {frontend_url}/login")


def send_student_rejected_email(user, rejection_reason=None):
    name = _first_name(user)
    frontend_url = settings.FRONTEND_URL
    reason_block = f'<div style="background:#fef2f2;border-left:4px solid #ef4444;padding:12px 16px;border-radius:4px;margin:16px 0;"><strong>Reason:</strong> {rejection_reason}</div>' if rejection_reason else ""
    html = _layout("Registration Not Approved", f"""
        <h2 style="margin:0 0 8px;">Registration Not Approved</h2>
        <p>Hello <strong>{name}</strong>,</p>
        <p>Unfortunately, your SCSIT Online Exam registration was reviewed and <strong>not approved</strong> at this time.</p>
        {reason_block}
        <p>If you believe this is a mistake, please contact your department administrator.</p>
    """)
    return _send_email(getattr(user, "email", ""),
                       "Your Account Registration Was Not Approved – SCSIT Online Exam", html,
                       f"Hello {name},\n\nYour registration was not approved.\nReason: {rejection_reason or 'No reason provided.'}")


def send_exam_scheduled_email(user, exam):
    name = _first_name(user)
    frontend_url = settings.FRONTEND_URL
    scheduled = exam.scheduled_date.strftime("%B %d, %Y %I:%M %p")
    html = _layout(f"New Exam Scheduled: {exam.title}", f"""
        <h2 style="margin:0 0 8px;">📋 New Exam Scheduled</h2>
        <p>Hello <strong>{name}</strong>,</p>
        <p>A new exam has been scheduled for you.</p>
        <table cellpadding="0" cellspacing="0" style="margin:20px 0;width:100%;">
          {_row("Exam Title", exam.title)}
          {_row("Subject", exam.subject)}
          {_row("Department", exam.department)}
          {_row("Exam Type", exam.exam_type)}
          {_row("Scheduled Date", scheduled)}
          {_row("Duration", f"{exam.duration_minutes} minutes")}
          {_row("Year Level", exam.year_level)}
        </table>
        <p style="margin-top:24px;">{_btn(f"{frontend_url}/dashboard/student/exams", "View My Exams")}</p>
    """)
    return _send_email(getattr(user, "email", ""),
                       f"New Exam Scheduled: {exam.title} – SCSIT Online Exam", html,
                       f"Hello {name},\n\nNew exam: {exam.title}\nScheduled: {scheduled}\nDuration: {exam.duration_minutes} minutes")


def send_dean_exam_created_email(user, exam):
    full = _full_name(user)
    frontend_url = settings.FRONTEND_URL
    scheduled = exam.scheduled_date.strftime("%B %d, %Y %I:%M %p")
    exam_link = f"{frontend_url}/exam/questions/{exam.id}"
    html = _layout(f"Exam Created: {exam.title}", f"""
        <h2 style="margin:0 0 8px;">✅ Exam Created Successfully</h2>
        <p>Hello <strong>{full}</strong>,</p>
        <p>Your exam has been created and <strong>automatically approved</strong>.</p>
        <table cellpadding="0" cellspacing="0" style="margin:20px 0;width:100%;">
          {_row("Exam Title", exam.title)}
          {_row("Subject", exam.subject)}
          {_row("Department", exam.department)}
          {_row("Exam Type", exam.exam_type)}
          {_row("Scheduled Date", scheduled)}
          {_row("Year Level", exam.year_level)}
        </table>
        <p style="margin-top:24px;">{_btn(exam_link, "Add Questions")}{_btn(f"{frontend_url}/dashboard/dean", "Open Dashboard", True)}</p>
    """)
    return _send_email(getattr(user, "email", ""),
                       f"Exam Created Successfully: {exam.title} – SCSIT Online Exam", html,
                       f"Hello {full},\n\nYour exam '{exam.title}' was created and auto-approved.\nAdd questions: {exam_link}")


def send_results_published_email(user, result):
    name = _first_name(user)
    frontend_url = settings.FRONTEND_URL
    passed = result.remarks == "Passed"
    badge = '<span style="background:#dcfce7;color:#16a34a;padding:4px 12px;border-radius:20px;font-size:13px;font-weight:600;">PASSED</span>' if passed else '<span style="background:#fee2e2;color:#dc2626;padding:4px 12px;border-radius:20px;font-size:13px;font-weight:600;">FAILED</span>'
    date_taken = result.submitted_at.strftime("%B %d, %Y %I:%M %p")
    html = _layout(f"Results: {result.exam.title}", f"""
        <h2 style="margin:0 0 8px;">📊 Exam Results Available</h2>
        <p>Hello <strong>{name}</strong>,</p>
        <p>Your results for <strong>{result.exam.title}</strong> have been published. {badge}</p>
        <table cellpadding="0" cellspacing="0" style="margin:20px 0;width:100%;">
          {_row("Exam", result.exam.title)}
          {_row("Subject", result.exam.subject)}
          {_row("Score", f"{result.score} / {result.total_points}")}
          {_row("Percentage", f"{round(result.percentage, 1)}%")}
          {_row("Date Taken", date_taken)}
        </table>
        <p style="margin-top:24px;">{_btn(f"{frontend_url}/dashboard/student/results", "View Full Results")}</p>
    """)
    return _send_email(getattr(user, "email", ""),
                       f"Results Available: {result.exam.title} – SCSIT Online Exam", html,
                       f"Hello {name},\n\nResults for '{result.exam.title}': {result.score}/{result.total_points} ({round(result.percentage,1)}%) — {'PASSED' if passed else 'FAILED'}")


def send_password_reset_email(user, reset_code):
    name = _first_name(user)
    frontend_url = settings.FRONTEND_URL
    reset_link = f"{frontend_url}/reset-password?token={reset_code}"
    html = _layout("Password Reset Request", f"""
        <h2 style="margin:0 0 8px;">Password Reset Request</h2>
        <p>Hello <strong>{name}</strong>,</p>
        <p>Your password reset code is below. It expires in <strong>15 minutes</strong>.</p>
        <div style="background:#f1f5f9;border-radius:8px;padding:20px;text-align:center;margin:24px 0;">
          <p style="margin:0 0 4px;font-size:13px;color:#64748b;">Your reset code</p>
          <p style="margin:0;font-size:36px;font-weight:bold;letter-spacing:12px;color:#0f172a;">{reset_code}</p>
        </div>
        <p style="margin-top:24px;">{_btn(reset_link, "Reset Password")}</p>
    """)
    return _send_email(getattr(user, "email", ""),
                       "Password Reset Request – SCSIT Online Exam", html,
                       f"Hello {name},\n\nYour reset code: {reset_code}\n\nExpires in 15 minutes.\n{reset_link}")


def send_bulk_import_email(user, set_password_token):
    name = _first_name(user)
    frontend_url = settings.FRONTEND_URL
    link = f"{frontend_url}/set-password?token={set_password_token}"
    html = _layout("Account Created", f"""
        <h2 style="margin:0 0 8px;">🎓 Your Student Account Is Ready</h2>
        <p>Hello <strong>{name}</strong>,</p>
        <p>A SCSIT Online Exam student account has been created for you. Click below to set your password.</p>
        <p style="margin-top:24px;">{_btn(link, "Set My Password")}</p>
        <p style="font-size:13px;color:#64748b;margin-top:16px;">This link expires in <strong>48 hours</strong>.</p>
    """)
    return _send_email(getattr(user, "email", ""),
                       "Your Student Account Has Been Created – SCSIT Online Exam", html,
                       f"Hello {name},\n\nSet your password: {link}\n\nExpires in 48 hours.")


def send_bulk_exam_notification(users, exam):
    return sum(1 for user in users if send_exam_scheduled_email(user, exam))


def send_announcement_email(user, announcement, created_by):
    name = _first_name(user)
    frontend_url = settings.FRONTEND_URL
    created_at = announcement.created_at.strftime("%B %d, %Y %I:%M %p")
    html = _layout(f"Announcement: {announcement.title}", f"""
        <h2 style="margin:0 0 8px;">📢 New Announcement</h2>
        <p>Hello <strong>{name}</strong>,</p>
        <h3 style="margin:16px 0 8px;">{announcement.title}</h3>
        <div style="background:#f8fafc;border-left:4px solid #0f172a;padding:12px 16px;border-radius:4px;margin:0 0 16px;">{announcement.message}</div>
        <table cellpadding="0" cellspacing="0" style="margin:0 0 20px;width:100%;">
          {_row("Posted by", str(created_by))}
          {_row("Date", created_at)}
        </table>
        <p>{_btn(f"{frontend_url}/dashboard", "View Dashboard", True)}</p>
    """)
    return _send_email(getattr(user, "email", ""),
                       f"New Announcement: {announcement.title} – SCSIT Online Exam", html,
                       f"Hello {name},\n\n{announcement.title}\n\n{announcement.message}\n\nPosted by: {created_by}")


def send_time_extension_email(user, exam, extra_minutes, reason):
    name = _first_name(user)
    frontend_url = settings.FRONTEND_URL
    scheduled = exam.scheduled_date.strftime("%B %d, %Y %I:%M %p")
    html = _layout(f"Time Extended: {exam.title}", f"""
        <h2 style="margin:0 0 8px;">⏱ Exam Time Extended</h2>
        <p>Hello <strong>{name}</strong>,</p>
        <p>The duration for your upcoming exam has been extended.</p>
        <table cellpadding="0" cellspacing="0" style="margin:20px 0;width:100%;">
          {_row("Exam Title", exam.title)}
          {_row("Subject", exam.subject)}
          {_row("Scheduled Date", scheduled)}
          {_row("Extra Time Added", f"{extra_minutes} minutes")}
          {_row("Reason", reason or "No reason provided.")}
        </table>
        <p style="margin-top:24px;">{_btn(f"{frontend_url}/dashboard/student/exams", "View My Exams")}</p>
    """)
    return _send_email(getattr(user, "email", ""),
                       f"Exam Time Extended: {exam.title} – SCSIT Online Exam", html,
                       f"Hello {name},\n\n'{exam.title}' extended by {extra_minutes} minutes.\nReason: {reason or 'No reason provided.'}")


def send_exam_rejected_email(user, exam_title, dean_name):
    name = _first_name(user)
    frontend_url = settings.FRONTEND_URL
    html = _layout(f"Exam Rejected: {exam_title}", f"""
        <h2 style="margin:0 0 8px;">❌ Exam Rejected</h2>
        <p>Hello <strong>{name}</strong>,</p>
        <p>Your exam <strong>{exam_title}</strong> was reviewed by <strong>{dean_name}</strong> and has been <strong>rejected</strong>.</p>
        <p>Please revise your exam and resubmit it for approval.</p>
        <p style="margin-top:24px;">{_btn(f"{frontend_url}/dashboard/teacher", "Go to My Exams")}</p>
    """)
    return _send_email(getattr(user, "email", ""),
                       f"Exam Rejected: {exam_title} – SCSIT Online Exam", html,
                       f"Hello {name},\n\nYour exam '{exam_title}' was rejected by {dean_name}.")


def send_issue_report_email(user, report, actor_name):
    name = _first_name(user)
    role = getattr(user, "role", "instructor")
    frontend_url = settings.FRONTEND_URL
    report_link = f"{frontend_url}/dashboard/teacher/reports?report={report.id}" if role == "instructor" else f"{frontend_url}/dashboard/dean/reports?report={report.id}"
    html = _layout(f"Issue Report: {report.exam.title}", f"""
        <h2 style="margin:0 0 8px;">🚩 New Exam Issue Report</h2>
        <p>Hello <strong>{name}</strong>,</p>
        <p><strong>{actor_name}</strong> submitted an issue report that requires your attention.</p>
        <table cellpadding="0" cellspacing="0" style="margin:20px 0;width:100%;">
          {_row("Exam", report.exam.title)}
          {_row("Question", f"#{report.question.order}")}
          {_row("Issue Type", report.get_issue_type_display())}
          {_row("Reported Answer", report.reported_answer or "N/A")}
        </table>
        <div style="background:#f8fafc;border-left:4px solid #f59e0b;padding:12px 16px;border-radius:4px;margin:0 0 20px;"><strong>Description:</strong><br>{report.description}</div>
        <p>{_btn(report_link, "Open Issue Report")}</p>
    """)
    return _send_email(getattr(user, "email", ""),
                       f"Issue Report: {report.exam.title} – Question {report.question.order}", html,
                       f"Hello {name},\n\n{actor_name} submitted an issue report for {report.exam.title} Q#{report.question.order}.")


def send_issue_report_reply_email(user, report, actor_name, message_text):
    name = _first_name(user)
    frontend_url = settings.FRONTEND_URL
    report_link = f"{frontend_url}/dashboard/student/reports?report={report.id}"
    html = _layout(f"Issue Report Reply: {report.exam.title}", f"""
        <h2 style="margin:0 0 8px;">💬 Update on Your Issue Report</h2>
        <p>Hello <strong>{name}</strong>,</p>
        <p><strong>{actor_name}</strong> replied to your issue report for <strong>{report.exam.title}</strong>.</p>
        <table cellpadding="0" cellspacing="0" style="margin:20px 0;width:100%;">
          {_row("Exam", report.exam.title)}
          {_row("Question", f"#{report.question.order}")}
          {_row("Status", report.get_status_display())}
        </table>
        <div style="background:#f8fafc;border-left:4px solid #0f172a;padding:12px 16px;border-radius:4px;margin:0 0 20px;"><strong>Reply:</strong><br>{message_text}</div>
        <p>{_btn(report_link, "View My Report")}</p>
    """)
    return _send_email(getattr(user, "email", ""),
                       f"Issue Report Reply: {report.exam.title} – Question {report.question.order}", html,
                       f"Hello {name},\n\n{actor_name} replied to your issue report.\nStatus: {report.get_status_display()}\nReply: {message_text}")
