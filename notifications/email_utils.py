import logging

from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.conf import settings
from django.utils.html import strip_tags

logger = logging.getLogger(__name__)


def send_email_verification_otp(user, otp_code):
    """Send OTP code for email verification during registration"""
    subject = '✉️ Verify Your Email — SCSIT Online Exam'
    html_message = render_to_string('emails/email_verification.html', {
        'user': user,
        'otp_code': otp_code,
    })
    plain_message = strip_tags(html_message)
    try:
        send_mail(
            subject=subject,
            message=plain_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            html_message=html_message,
            fail_silently=False,
        )
        return True
    except Exception as e:
        logger.exception("Failed to send email verification OTP to %s", user.email)
        return False


def send_pre_registration_otp(email, otp_code):
    """Send OTP to an email address before user account is created"""
    subject = '✉️ Verify Your Email — SCSIT Online Exam'
    html_message = render_to_string('emails/email_verification.html', {
        'user': None,
        'otp_code': otp_code,
    })
    plain_message = strip_tags(html_message)
    try:
        send_mail(
            subject=subject,
            message=plain_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[email],
            html_message=html_message,
            fail_silently=False,
        )
        return True
    except Exception as e:
        logger.exception("Failed to send pre-registration OTP to %s", email)
        return False


def send_student_approval_email(user):
    """Send email when student account is approved"""
    subject = '🎉 Your Account Has Been Approved!'
    
    html_message = render_to_string('emails/student_approval.html', {
        'user': user,
        'frontend_url': settings.FRONTEND_URL,
    })
    
    plain_message = strip_tags(html_message)
    
    try:
        send_mail(
            subject=subject,
            message=plain_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            html_message=html_message,
            fail_silently=False,
        )
        return True
    except Exception as e:
        print(f"Failed to send approval email: {e}")
        return False


def send_staff_approval_email(user):
    """Send email when instructor/dean account is approved"""
    subject = 'ðŸŽ‰ Your Staff Account Has Been Approved!'

    html_message = render_to_string('emails/staff_approval.html', {
        'user': user,
        'frontend_url': settings.FRONTEND_URL,
    })

    plain_message = strip_tags(html_message)

    try:
        send_mail(
            subject=subject,
            message=plain_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            html_message=html_message,
            fail_silently=False,
        )
        return True
    except Exception as e:
        print(f"Failed to send staff approval email: {e}")
        return False


def send_exam_scheduled_email(user, exam):
    """Send email when new exam is scheduled"""
    subject = f'📝 New Exam Scheduled: {exam.title}'
    
    html_message = render_to_string('emails/exam_scheduled.html', {
        'user': user,
        'exam': exam,
        'frontend_url': settings.FRONTEND_URL,
    })
    
    plain_message = strip_tags(html_message)
    
    try:
        send_mail(
            subject=subject,
            message=plain_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            html_message=html_message,
            fail_silently=False,
        )
        return True
    except Exception as e:
        print(f"Failed to send exam scheduled email: {e}")
        return False


def send_dean_exam_created_email(user, exam):
    """Send confirmation email when a dean successfully creates an exam."""
    subject = f'Exam Created Successfully: {exam.title}'
    exam_link = f"{settings.FRONTEND_URL}/exam/questions/{exam.id}"
    dashboard_link = f"{settings.FRONTEND_URL}/dashboard/dean"
    html_message = f"""
        <div style="font-family: Arial, sans-serif; line-height: 1.6; color: #0f172a;">
          <h2 style="margin-bottom: 8px;">Exam Created Successfully</h2>
          <p>Hello {user.get_full_name() or user.username},</p>
          <p>Your exam <strong>{exam.title}</strong> for <strong>{exam.subject}</strong> was created successfully.</p>
          <p>Because you created it as dean, it was approved automatically and is ready for question setup.</p>
          <ul style="padding-left: 18px;">
            <li><strong>Department:</strong> {exam.department}</li>
            <li><strong>Type:</strong> {exam.exam_type}</li>
            <li><strong>Schedule:</strong> {exam.scheduled_date.strftime('%B %d, %Y %I:%M %p')}</li>
            <li><strong>Year Level:</strong> {exam.year_level}</li>
          </ul>
          <p style="margin-top: 20px;">
            <a href="{exam_link}" style="background:#0f172a;color:#ffffff;padding:10px 16px;border-radius:8px;text-decoration:none;margin-right:8px;">
              Add Questions
            </a>
            <a href="{dashboard_link}" style="background:#e2e8f0;color:#0f172a;padding:10px 16px;border-radius:8px;text-decoration:none;">
              Open Dashboard
            </a>
          </p>
        </div>
    """
    plain_message = (
        f"Exam Created Successfully\n\n"
        f"Hello {user.get_full_name() or user.username},\n\n"
        f"Your exam '{exam.title}' for '{exam.subject}' was created successfully.\n"
        f"Because you created it as dean, it was approved automatically and is ready for question setup.\n\n"
        f"Department: {exam.department}\n"
        f"Type: {exam.exam_type}\n"
        f"Schedule: {exam.scheduled_date.strftime('%B %d, %Y %I:%M %p')}\n"
        f"Year Level: {exam.year_level}\n\n"
        f"Add questions: {exam_link}\n"
        f"Dashboard: {dashboard_link}"
    )
    try:
        send_mail(
            subject=subject,
            message=plain_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            html_message=html_message,
            fail_silently=False,
        )
        return True
    except Exception as e:
        print(f"Failed to send dean exam created email: {e}")
        return False


def send_results_published_email(user, result):
    """Send email when exam results are published"""
    subject = f'📊 Results Available: {result.exam_title}'
    
    html_message = render_to_string('emails/results_published.html', {
        'user': user,
        'result': result,
        'frontend_url': settings.FRONTEND_URL,
    })
    
    plain_message = strip_tags(html_message)
    
    try:
        send_mail(
            subject=subject,
            message=plain_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            html_message=html_message,
            fail_silently=False,
        )
        return True
    except Exception as e:
        print(f"Failed to send results email: {e}")
        return False


def send_password_reset_email(user, reset_code):
    """Send email with password reset code"""
    subject = '🔐 Password Reset Request'
    
    html_message = render_to_string('emails/password_reset.html', {
        'user': user,
        'reset_code': reset_code,
        'frontend_url': settings.FRONTEND_URL,
    })
    
    plain_message = strip_tags(html_message)
    
    try:
        send_mail(
            subject=subject,
            message=plain_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            html_message=html_message,
            fail_silently=False,
        )
        return True
    except Exception as e:
        print(f"Failed to send password reset email: {e}")
        return False


def send_bulk_import_email(user, set_password_token):
    """Send email to bulk-imported student with a set-password link"""
    subject = '📋 Your Student Account Has Been Created'

    html_message = render_to_string('emails/bulk_import.html', {
        'user': user,
        'set_password_token': set_password_token,
        'frontend_url': settings.FRONTEND_URL,
    })

    plain_message = strip_tags(html_message)

    try:
        send_mail(
            subject=subject,
            message=plain_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            html_message=html_message,
            fail_silently=False,
        )
        return True
    except Exception as e:
        print(f"Failed to send bulk import email: {e}")
        return False


def send_bulk_exam_notification(users, exam):
    """Send exam notification to multiple users"""
    success_count = 0
    for user in users:
        if send_exam_scheduled_email(user, exam):
            success_count += 1
    return success_count


def send_student_rejected_email(user, rejection_reason=None):
    """Send email when student account is rejected"""
    subject = '❌ Your Account Registration Was Not Approved'
    html_message = render_to_string('emails/student_rejected.html', {
        'user': user,
        'rejection_reason': rejection_reason,
        'frontend_url': settings.FRONTEND_URL,
    })
    plain_message = strip_tags(html_message)
    try:
        send_mail(
            subject=subject,
            message=plain_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            html_message=html_message,
            fail_silently=False,
        )
        return True
    except Exception as e:
        print(f"Failed to send rejection email: {e}")
        return False


def send_exam_rejected_email(user, exam_title, dean_name):
    """Send email when exam is rejected by dean"""
    subject = f'❌ Exam Rejected: {exam_title}'
    html_message = render_to_string('emails/exam_rejected.html', {
        'user': user,
        'exam_title': exam_title,
        'dean_name': dean_name,
        'frontend_url': settings.FRONTEND_URL,
    })
    plain_message = strip_tags(html_message)
    try:
        send_mail(
            subject=subject,
            message=plain_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            html_message=html_message,
            fail_silently=False,
        )
        return True
    except Exception as e:
        print(f"Failed to send exam rejected email: {e}")
        return False


def send_announcement_email(user, announcement, created_by):
    """Send email when a new announcement is posted"""
    subject = f'📢 New Announcement: {announcement.title}'
    html_message = render_to_string('emails/announcement.html', {
        'user': user,
        'title': announcement.title,
        'message': announcement.message,
        'created_by': created_by,
        'created_at': announcement.created_at.strftime('%B %d, %Y %I:%M %p'),
        'frontend_url': settings.FRONTEND_URL,
    })
    plain_message = strip_tags(html_message)
    try:
        send_mail(
            subject=subject,
            message=plain_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            html_message=html_message,
            fail_silently=False,
        )
        return True
    except Exception as e:
        print(f"Failed to send announcement email to {user.email}: {e}")
        return False


def send_time_extension_email(user, exam, extra_minutes, reason):
    """Send email when exam time is extended for a student"""
    subject = f'⏰ Exam Time Extended: {exam.title}'
    html_message = render_to_string('emails/time_extension.html', {
        'user': user,
        'exam': exam,
        'extra_minutes': extra_minutes,
        'reason': reason or 'No reason provided.',
        'frontend_url': settings.FRONTEND_URL,
    })
    plain_message = strip_tags(html_message)
    try:
        send_mail(
            subject=subject,
            message=plain_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            html_message=html_message,
            fail_silently=False,
        )
        return True
    except Exception as e:
        print(f"Failed to send time extension email: {e}")
        return False


def send_issue_report_email(user, report, actor_name):
    """Send email when a student reports an issue about an exam question"""
    subject = f'Issue Report: {report.exam.title} - Question {report.question.order}'
    report_link = (
        f"{settings.FRONTEND_URL}/dashboard/teacher/reports?report={report.id}"
        if user.role == 'instructor'
        else f"{settings.FRONTEND_URL}/dashboard/dean/reports?report={report.id}"
    )
    html_message = f"""
        <div style="font-family: Arial, sans-serif; line-height: 1.6; color: #0f172a;">
          <h2 style="margin-bottom: 8px;">New Exam Issue Report</h2>
          <p>{actor_name} submitted an issue report for <strong>{report.exam.title}</strong>.</p>
          <p><strong>Question:</strong> #{report.question.order}</p>
          <p><strong>Issue Type:</strong> {report.get_issue_type_display()}</p>
          <p><strong>Reported Answer:</strong> {report.reported_answer or 'No answer provided'}</p>
          <p><strong>Description:</strong><br>{report.description}</p>
          <p style="margin-top: 20px;">
            <a href="{report_link}" style="background:#0f172a;color:#ffffff;padding:10px 16px;border-radius:8px;text-decoration:none;">
              Open Issue Report
            </a>
          </p>
        </div>
    """
    plain_message = (
        f"New Exam Issue Report\n\n"
        f"{actor_name} submitted an issue report for {report.exam.title}.\n"
        f"Question: #{report.question.order}\n"
        f"Issue Type: {report.get_issue_type_display()}\n"
        f"Reported Answer: {report.reported_answer or 'No answer provided'}\n"
        f"Description: {report.description}\n\n"
        f"Open report: {report_link}"
    )
    try:
        send_mail(
            subject=subject,
            message=plain_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            html_message=html_message,
            fail_silently=False,
        )
        return True
    except Exception as e:
        print(f"Failed to send issue report email to {user.email}: {e}")
        return False


def send_issue_report_reply_email(user, report, actor_name, message_text):
    """Send email to a student when staff replies to an exam issue report."""
    subject = f'Issue Report Reply: {report.exam.title} - Question {report.question.order}'
    report_link = f"{settings.FRONTEND_URL}/dashboard/student/reports?report={report.id}"
    html_message = f"""
        <div style="font-family: Arial, sans-serif; line-height: 1.6; color: #0f172a;">
          <h2 style="margin-bottom: 8px;">There is an update on your exam issue report</h2>
          <p>{actor_name} replied to your issue report for <strong>{report.exam.title}</strong>.</p>
          <p><strong>Question:</strong> #{report.question.order}</p>
          <p><strong>Status:</strong> {report.get_status_display()}</p>
          <p><strong>Reply:</strong><br>{message_text}</p>
          <p style="margin-top: 20px;">
            <a href="{report_link}" style="background:#0f172a;color:#ffffff;padding:10px 16px;border-radius:8px;text-decoration:none;">
              Open My Exam Issue Report
            </a>
          </p>
        </div>
    """
    plain_message = (
        f"There is an update on your exam issue report\n\n"
        f"{actor_name} replied to your issue report for {report.exam.title}.\n"
        f"Question: #{report.question.order}\n"
        f"Status: {report.get_status_display()}\n"
        f"Reply: {message_text}\n\n"
        f"Open report: {report_link}"
    )
    try:
        send_mail(
            subject=subject,
            message=plain_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            html_message=html_message,
            fail_silently=False,
        )
        return True
    except Exception as e:
        print(f"Failed to send issue report reply email to {user.email}: {e}")
        return False
