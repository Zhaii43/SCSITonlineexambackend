"""
email_utils.py — All email sending is handled by the Next.js frontend via Nodemailer.
These are no-op stubs kept for import compatibility only.
"""

import logging
logger = logging.getLogger(__name__)


def send_email_verification_otp(user, otp_code): pass
def send_pre_registration_otp(email, otp_code): pass
def send_student_approval_email(user): pass
def send_staff_approval_email(user): pass
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
