from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from rest_framework import status
from django.conf import settings
from django.utils import timezone
from datetime import timedelta
from django.db import models
from .models import Exam, ExamResult, PracticeExamResult, Question, CheatingViolation, ExamTermination, ExamPhoto, ExamTimeExtension, QuestionBank, ExamSession, StudentExamSeed, QuestionIssueReport, QuestionIssueMessage
from audit.models import AuditLog
from .utils import safe_delete_field
from user.models import User, SubjectAssignment
from notifications.models import Notification
from notifications.email_utils import send_exam_scheduled_email, send_results_published_email, send_exam_rejected_email, send_time_extension_email, send_issue_report_email, send_dean_exam_created_email, send_issue_report_reply_email
from notifications.push_utils import send_push_notification, send_push_to_users
from notifications.realtime import send_notification
from .realtime import send_exam_update
from audit.views import log_activity
from backend.security import require_role, throttle_request


def _file_url(request, field):
    """Return the correct Cloudinary URL for a file field.
    Handles cases where the DB stored a full URL instead of a relative path.
    """
    if not field or not field.name:
        return None
    name = field.name
    # If DB stored a full URL, return it directly (fix double-URL if present)
    if name.startswith('http://') or name.startswith('https://'):
        if name.count('https://') > 1:
            name = 'https://' + name.split('https://')[-1]
        return name
    # Relative path — let Cloudinary storage build the URL
    try:
        return field.url
    except Exception:
        return None


def _normalize_subject_label(value):
    return ' '.join(str(value or '').strip().lower().split())


def _normalize_year_level_token(value):
    normalized = ''.join(str(value or '').strip().lower().split())
    mapping = {
        '1': '1',
        '1st': '1',
        '1styr': '1',
        '1styear': '1',
        'first': '1',
        'firstyear': '1',
        '2': '2',
        '2nd': '2',
        '2ndyr': '2',
        '2ndyear': '2',
        'second': '2',
        'secondyear': '2',
        '3': '3',
        '3rd': '3',
        '3rdyr': '3',
        '3rdyear': '3',
        'third': '3',
        'thirdyear': '3',
        '4': '4',
        '4th': '4',
        '4thyr': '4',
        '4thyear': '4',
        'fourth': '4',
        'fourthyear': '4',
        'all': 'ALL',
    }
    return mapping.get(normalized, '')


def _normalized_year_level_values(value):
    raw_value = str(value or '').strip()
    if not raw_value:
        return []
    return [
        normalized
        for normalized in (
            _normalize_year_level_token(token)
            for token in raw_value.split(',')
        )
        if normalized
    ]


def _format_expected_year_level(value):
    normalized_values = _normalized_year_level_values(value)
    if normalized_values:
        return ','.join(normalized_values)
    return str(value or '').strip()


def _active_subject_assignments_for_instructor(user, department=None):
    assignments = SubjectAssignment.objects.filter(instructor=user, is_active=True)
    if department:
        assignments = assignments.filter(department=department)
    return list(assignments.order_by('subject_name'))


def _instructor_subject_allowed(user, department, subject_name):
    normalized_subject = _normalize_subject_label(subject_name)
    if not normalized_subject:
        return False
    assignments = _active_subject_assignments_for_instructor(user, department)
    return any(_normalize_subject_label(assignment.subject_name) == normalized_subject for assignment in assignments)


def _student_matches_exam_subject(student, exam_subject):
    subjects = getattr(student, 'enrolled_subjects', None) or []
    if not subjects:
        return True

    normalized_exam_subject = _normalize_subject_label(exam_subject)
    if not normalized_exam_subject:
        return True

    for subject in subjects:
        normalized_subject = _normalize_subject_label(subject)
        if not normalized_subject:
            continue
        if normalized_subject == normalized_exam_subject:
            return True
        if normalized_exam_subject in normalized_subject or normalized_subject in normalized_exam_subject:
            return True
    return False


def _exam_access_error(user, exam):
    if not user.is_approved:
        return 'Your account is not approved yet'
    if exam.department != user.department:
        return 'This exam is not for your department'
    if exam.year_level != 'ALL':
        user_level = user.year_level or ''
        if user_level not in exam.year_level.split(','):
            return 'This exam is not for your year level'
    if not _student_matches_exam_subject(user, exam.subject):
        return 'This exam is not part of your approved subject load'
    if (getattr(user, 'is_transferee', False) or getattr(user, 'is_irregular', False)) and not getattr(user, 'extra_approved', False):
        return 'Transferee/irregular students require additional dean approval to take this exam'
    return None


def _normalized_exam_year_levels(exam):
    if exam.year_level == 'ALL':
        return None
    return [level.strip() for level in str(exam.year_level).split(',') if level.strip()]


def _eligible_students_for_exam(exam):
    students = User.objects.filter(
        department=exam.department,
        role='student',
        is_approved=True,
    )

    year_levels = _normalized_exam_year_levels(exam)
    if year_levels:
        students = students.filter(year_level__in=year_levels)

    return [student for student in students if _student_matches_exam_subject(student, exam.subject)]


def _extract_exam_session_token(request):
    token = request.headers.get('X-Exam-Session')
    if token:
        return str(token).strip()
    if hasattr(request, 'data'):
        body_token = request.data.get('session_token')
        if body_token:
            return str(body_token).strip()
    return str(request.query_params.get('session_token', '')).strip()


def _is_staff_exam_owner(user, exam):
    return user.role in ('instructor', 'dean') and exam.created_by_id == user.id


def _get_staff_exam_or_404(user, exam_id):
    if user.role not in ('instructor', 'dean'):
        raise Exam.DoesNotExist
    return Exam.objects.get(id=exam_id, created_by=user)


def _can_modify_exam_questions(user, exam):
    if not exam.is_approved:
        return True
    if exam.created_by_id != user.id:
        return False
    return not exam.results.exists()


def _can_modify_exam_definition(user, exam):
    if not exam.is_approved:
        return True
    if exam.created_by_id != user.id:
        return False
    return not exam.results.exists()


def _validate_question_total_points(exam, questions_data):
    total_question_points = sum(int(q.get('points', 0)) for q in questions_data)
    if total_question_points != exam.total_points:
        return Response(
            {
                'error': (
                    f'Total question points ({total_question_points}) do not match '
                    f'the exam total points ({exam.total_points}).'
                )
            },
            status=status.HTTP_400_BAD_REQUEST,
        )
    return None


def _validate_question_types(exam, questions_data):
    allowed_types = {'multiple_choice', 'identification', 'enumeration', 'essay'}
    exam_type = exam.question_type

    for index, question in enumerate(questions_data, start=1):
        question_type = str(question.get('type', '')).strip()
        if question_type not in allowed_types:
            return Response(
                {'error': f'Question {index} has an invalid type "{question_type}".'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if exam_type != 'mixed' and question_type != exam_type:
            return Response(
                {
                    'error': (
                        f'Question {index} type "{question_type}" does not match the exam '
                        f'question type "{exam_type}".'
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

    return None


def _notify_exam_approved(exam, approver, notify_creator=True):
    if notify_creator and exam.created_by_id != approver.id:
        try:
            Notification.objects.create(
                user=exam.created_by,
                type='exam_approved',
                title='Exam Approved',
                message=f'Your exam "{exam.title}" has been approved by {approver.get_full_name() or approver.username}.',
                link=f'/exam/{exam.id}/edit'
            )
        except Exception as exc:
            print(f"Warning: failed to notify exam creator about approval: {exc}")

    student_list = list(_eligible_students_for_exam(exam))

    for student in student_list:
        should_send_email = False
        try:
            notification_link = f'/exam/{exam.id}/instructions'
            notification_exists = Notification.objects.filter(
                user=student,
                type='exam_scheduled',
                link=notification_link,
            ).exists()
            if not notification_exists:
                Notification.objects.create(
                    user=student,
                    type='exam_scheduled',
                    title='New Exam Scheduled',
                    message=f'A new {exam.exam_type} exam "{exam.title}" has been scheduled for {exam.scheduled_date.strftime("%B %d, %Y")}.',
                    link=notification_link
                )
                should_send_email = True
        except Exception as exc:
            print(f"Warning: failed to create exam notification for student {student.id}: {exc}")
        try:
            if should_send_email and student.email:
                send_exam_scheduled_email(student, exam)
        except Exception as exc:
            print(f"Warning: failed to send exam scheduled email to student {student.id}: {exc}")

    try:
        send_push_to_users(
            student_list,
            'New Exam Scheduled',
            f'{exam.exam_type.capitalize()} exam "{exam.title}" scheduled for {exam.scheduled_date.strftime("%b %d, %Y")}.',
        )
    except Exception as exc:
        print(f"Warning: failed to send exam scheduled push notifications: {exc}")

    try:
        send_exam_update(f"exams_user_{exam.created_by_id}", "approved", exam.id)
        send_exam_update(f"exams_dean_{exam.department}", "approved", exam.id)
        send_exam_update(f"exams_students_{exam.department}", "available", exam.id)
    except Exception as exc:
        print(f"Warning: failed to send exam realtime updates: {exc}")


def _publish_staff_exam_if_ready(exam, user):
    if user.role not in ('instructor', 'dean') or exam.created_by_id != user.id or not exam.is_approved:
        return
    if exam.questions.count() == 0:
        return
    try:
        fresh_exam = Exam.objects.get(id=exam.id)
        _notify_exam_approved(fresh_exam, user, notify_creator=False)
    except Exception as exc:
        print(f"Warning: failed to publish staff exam {exam.id}: {exc}")


def _require_active_exam_session(request, exam, user):
    session_token = _extract_exam_session_token(request)
    if not session_token:
        return None, Response({'error': 'Active exam session token is required'}, status=status.HTTP_403_FORBIDDEN)

    try:
        session = ExamSession.objects.get(
            exam=exam,
            student=user,
            is_active=True,
            session_token=session_token,
        )
    except ExamSession.DoesNotExist:
        return None, Response({'error': 'Invalid or expired exam session'}, status=status.HTTP_403_FORBIDDEN)

    stale_threshold = timezone.now() - timedelta(seconds=90)
    if session.last_heartbeat < stale_threshold:
        session.delete()
        return None, Response({'error': 'Exam session expired. Please restart the exam.'}, status=status.HTTP_403_FORBIDDEN)

    return session, None


def _get_issue_report_queryset(user):
    qs = QuestionIssueReport.objects.select_related(
        'exam', 'question', 'student', 'exam_result', 'exam__created_by'
    ).prefetch_related('messages__sender')

    if user.role == 'student':
        return qs.filter(student=user)
    if user.role == 'instructor':
        return qs.filter(exam__created_by=user)
    if user.role == 'dean':
        return qs.filter(exam__department=user.department)
    return QuestionIssueReport.objects.none()


def _serialize_issue_report_summary(report):
    latest_message = report.messages.all().last()
    return {
        'id': report.id,
        'exam_id': report.exam_id,
        'exam_title': report.exam.title,
        'question_id': report.question_id,
        'question_order': report.question.order,
        'question_preview': report.question.question[:160],
        'student_id': report.student_id,
        'student_name': report.student.get_full_name() or report.student.username,
        'student_school_id': report.student.school_id,
        'issue_type': report.issue_type,
        'issue_type_label': report.get_issue_type_display(),
        'status': report.status,
        'status_label': report.get_status_display(),
        'reported_answer': report.reported_answer,
        'created_at': report.created_at.isoformat(),
        'updated_at': report.updated_at.isoformat(),
        'message_count': report.messages.count(),
        'latest_message': latest_message.message if latest_message else report.description,
        'latest_message_at': latest_message.created_at.isoformat() if latest_message else report.created_at.isoformat(),
    }


def _serialize_issue_report_detail(report, user):
    return {
        **_serialize_issue_report_summary(report),
        'description': report.description,
        'exam_result_id': report.exam_result_id,
        'messages': [{
            'id': message.id,
            'sender_id': message.sender_id,
            'sender_name': message.sender.get_full_name() or message.sender.username,
            'sender_role': message.sender.role,
            'message': message.message,
            'created_at': message.created_at.isoformat(),
            'is_mine': message.sender_id == user.id,
        } for message in report.messages.all()],
    }


def _notify_issue_report_users(report, actor, title, message, student_link=True, staff_link=True):
    recipients = []
    student_link_path = f'/dashboard/student/reports?report={report.id}'
    instructor_link_path = f'/dashboard/teacher/reports?report={report.id}'
    dean_link_path = f'/dashboard/dean/reports?report={report.id}'

    if student_link and report.student_id != actor.id:
        recipients.append((report.student, student_link_path))

    instructor = report.exam.created_by
    if staff_link and instructor.id != actor.id:
        recipients.append((instructor, instructor_link_path))

    deans = User.objects.filter(role='dean', department=report.exam.department, is_active=True, is_approved=True).exclude(id=actor.id)
    for dean in deans:
        recipients.append((dean, dean_link_path))

    seen = set()
    for recipient, link in recipients:
        if recipient.id in seen:
            continue
        seen.add(recipient.id)
        Notification.objects.create(
            user=recipient,
            type='issue_report',
            title=title,
            message=message,
            link=link,
        )


@api_view(['GET'])
@permission_classes([AllowAny])
def get_public_stats(request):
    '''Public stats for the landing page hero card — no auth required'''
    from datetime import datetime, timedelta

    now = datetime.now()

    # Active exams: approved, non-practice, scheduled_date <= now <= scheduled_date + duration
    all_approved = Exam.objects.filter(is_approved=True, is_practice=False)
    active_exams = [e for e in all_approved if e.get_status() == 'ongoing']
    active_count = len(active_exams)
    total_exams = all_approved.count()

    # Total registered students (exclude superusers/admins)
    total_users = User.objects.filter(role='student', is_superuser=False).count()

    # Violations today
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    violations_today = CheatingViolation.objects.filter(timestamp__gte=today_start).count()

    # Most recent live exam with submission progress
    live_exam_data = None
    if active_exams:
        exam = active_exams[0]
        submitted = ExamResult.objects.filter(exam=exam).count()
        # Eligible students
        total_eligible = len(_eligible_students_for_exam(exam))
        elapsed = (now - exam.scheduled_date).total_seconds() / 60
        remaining = max(0, exam.duration_minutes - elapsed)
        progress = round((submitted / total_eligible * 100), 1) if total_eligible > 0 else 0
        live_exam_data = {
            'title': exam.title,
            'subject': exam.subject,
            'submitted': submitted,
            'total': total_eligible,
            'progress': progress,
            'remaining_minutes': round(remaining),
        }

    # Recent activity — announcements only
    from notifications.models import Announcement
    recent_announcements = Announcement.objects.filter(is_active=True).order_by('-created_at')[:3]
    activity = []
    for ann in recent_announcements:
        from django.utils.timesince import timesince
        activity.append({
            'dot': 'bg-sky-500',
            'msg': ann.title,
            'time': timesince(ann.created_at) + ' ago',
        })

    return Response({
        'active_exams': active_count,
        'total_exams': total_exams,
        'total_users': total_users,
        'violations_today': violations_today,
        'live_exam': live_exam_data,
        'activity': activity,
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_available_exams(request):
    '''Get exams available for the authenticated student'''
    user = request.user
    
    if user.role != 'student':
        return Response({'error': 'Only students can access this endpoint'}, 
                       status=status.HTTP_403_FORBIDDEN)
    
    if not user.is_approved:
        return Response({'error': 'Your account is not approved yet'}, 
                       status=status.HTTP_403_FORBIDDEN)
    
    exams = Exam.objects.filter(
        department=user.department,
        is_draft=False,
        is_approved=True,
        questions__isnull=False,
        is_practice=False,
    ).distinct()
    
    exam_list = []
    for exam in exams:
        access_error = _exam_access_error(user, exam)
        if access_error:
            continue
        # Check attempts for this student
        attempts = ExamResult.objects.filter(exam=exam, student=user)
        attempt_count = attempts.count()
        can_take = attempt_count < exam.max_attempts
        
        # Only show if student can still take the exam
        if can_take:
            exam_list.append({
                'id': exam.id,
                'title': exam.title,
                'subject': exam.subject,
                'department': exam.department,
                'exam_type': exam.exam_type,
                'scheduled_date': exam.scheduled_date.isoformat(),
                'expiration_time': exam.expiration_time.isoformat() if exam.expiration_time else None,
                'duration_minutes': exam.duration_minutes,
                'total_points': exam.total_points,
                'passing_score': exam.passing_score,
                'instructions': exam.instructions,
                'status': exam.get_status(),
                'year_level': exam.year_level,
                'is_expired': exam.is_expired(),
                'max_attempts': exam.max_attempts,
                'retake_policy': exam.retake_policy,
                'attempts_used': attempt_count,
                'attempts_remaining': exam.max_attempts - attempt_count,
                'is_retake': attempt_count > 0,
            })
    
    return Response(exam_list)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_exam_results(request):
    '''Get exam results for the authenticated student'''
    user = request.user
    
    if user.role != 'student':
        return Response({'error': 'Only students can access this endpoint'}, 
                       status=status.HTTP_403_FORBIDDEN)
    
    results = ExamResult.objects.filter(student=user, is_graded=True)
    
    result_list = []
    for result in results:
        result_list.append({
            'id': result.id,
            'exam_id': result.exam.id,
            'exam_title': result.exam.title,
            'score': result.score,
            'total_points': result.total_points,
            'percentage': result.percentage,
            'grade': result.grade,
            'remarks': result.remarks,
            'submitted_at': result.submitted_at.isoformat(),
        })
    
    return Response(result_list)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_exam_detail(request, exam_id):
    '''Get detailed information about a specific exam'''
    user = request.user
    
    if user.role != 'student':
        return Response({'error': 'Only students can access this endpoint'}, 
                       status=status.HTTP_403_FORBIDDEN)
    
    try:
        exam = Exam.objects.get(id=exam_id)
        
        access_error = _exam_access_error(user, exam)
        if access_error:
            return Response({'error': access_error}, status=status.HTTP_403_FORBIDDEN)
        
        # Check if student has already taken this exam
        attempts = ExamResult.objects.filter(exam=exam, student=user)
        attempt_count = attempts.count()
        
        return Response({
            'id': exam.id,
            'title': exam.title,
            'subject': exam.subject,
            'department': exam.department,
            'exam_type': exam.exam_type,
            'question_type': exam.question_type,
            'scheduled_date': exam.scheduled_date.isoformat(),
            'expiration_time': exam.expiration_time.isoformat() if exam.expiration_time else None,
            'duration_minutes': exam.duration_minutes,
            'total_points': exam.total_points,
            'passing_score': exam.passing_score,
            'instructions': exam.instructions,
            'preview_rules': exam.preview_rules,
            'sample_questions': exam.sample_questions or [],
            'question_count': exam.questions.count(),
            'question_types': list(
                exam.questions.values('type').annotate(count=models.Count('id')).order_by('type')
            ),
            'status': exam.get_status(),
            'max_attempts': exam.max_attempts,
            'retake_policy': exam.retake_policy,
            'attempts_used': attempt_count,
            'attempts_remaining': max(0, exam.max_attempts - attempt_count),
            'can_take': attempt_count < exam.max_attempts,
            'is_retake': attempt_count > 0,
            'has_taken': attempt_count > 0,
            'is_expired': exam.is_expired(),
        })
    
    except Exam.DoesNotExist:
        return Response({'error': 'Exam not found'}, status=status.HTTP_404_NOT_FOUND)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_instructor_exams(request):
    '''Get all exams created by the authenticated instructor'''
    user = request.user
    
    if user.role != 'instructor':
        return Response({'error': 'Only instructors can access this endpoint'}, 
                       status=status.HTTP_403_FORBIDDEN)
    
    exams = Exam.objects.filter(created_by=user, is_draft=False)
    
    exam_list = []
    for exam in exams:
        submitted_count = ExamResult.objects.filter(exam=exam).count()
        total_students = len(_eligible_students_for_exam(exam))
        exam_list.append({
            'id': exam.id,
            'title': exam.title,
            'subject': exam.subject,
            'department': exam.department,
            'exam_type': exam.exam_type,
            'scheduled_date': exam.scheduled_date.isoformat(),
            'expiration_time': exam.expiration_time.isoformat() if exam.expiration_time else None,
            'duration_minutes': exam.duration_minutes,
            'total_points': exam.total_points,
            'status': exam.get_status(),
            'is_approved': exam.is_approved,
            'submitted_count': submitted_count,
            'total_students': total_students,
        })
    
    return Response(exam_list)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_exam_detail_for_instructor(request, exam_id):
    '''Get exam details for editing'''
    user = request.user
    
    if user.role not in ('instructor', 'dean'):
        return Response({'error': 'Only instructors or deans can access this endpoint'}, 
                       status=status.HTTP_403_FORBIDDEN)
    
    try:
        exam = _get_staff_exam_or_404(user, exam_id)
        eligible_students = _eligible_students_for_exam(exam)
        return Response({
            'id': exam.id,
            'title': exam.title,
            'subject': exam.subject,
            'department': exam.department,
            'exam_type': exam.exam_type,
            'question_type': exam.question_type,
            'scheduled_date': exam.scheduled_date.isoformat(),
            'expiration_time': exam.expiration_time.isoformat() if exam.expiration_time else None,
            'duration_minutes': exam.duration_minutes,
            'total_points': exam.total_points,
            'passing_score': exam.passing_score,
            'instructions': exam.instructions,
            'preview_rules': exam.preview_rules,
            'sample_questions': exam.sample_questions or [],
            'year_level': exam.year_level,
            'max_attempts': exam.max_attempts,
            'retake_policy': exam.retake_policy,
            'question_pool_size': exam.question_pool_size,
            'shuffle_options': exam.shuffle_options,
            'is_approved': exam.is_approved,
            'eligible_students': [{
                'id': student.id,
                'username': student.username,
                'email': student.email,
                'first_name': student.first_name,
                'last_name': student.last_name,
                'school_id': student.school_id,
                'year_level': student.year_level,
                'course': student.course,
                'contact_number': student.contact_number,
            } for student in eligible_students],
            'total_eligible_students': len(eligible_students),
            'questions': [{
                'id': q.id,
                'question': q.question,
                'type': q.type,
                'options': q.options,
                'correct_answer': q.correct_answer,
                'points': q.points,
                'order': q.order,
            } for q in exam.questions.all()],
        })
    except Exam.DoesNotExist:
        return Response({'error': 'Exam not found'}, status=status.HTTP_404_NOT_FOUND)


@api_view(['PUT'])
@permission_classes([IsAuthenticated])
def update_exam(request, exam_id):
    '''Update exam details for an exam owner before results exist.'''
    user = request.user
    
    if user.role not in ('instructor', 'dean'):
        return Response({'error': 'Only instructors or deans can update exams'}, 
                       status=status.HTTP_403_FORBIDDEN)
    
    try:
        from datetime import datetime
        
        exam = _get_staff_exam_or_404(user, exam_id)
        
        if not _can_modify_exam_definition(user, exam):
            return Response({'error': 'Cannot edit exams after students have submitted results'},
                           status=status.HTTP_403_FORBIDDEN)
        
        import json
        next_title = request.data.get('title', exam.title)
        next_subject = request.data.get('subject', exam.subject)
        next_department = exam.department if user.role == 'dean' else request.data.get('department', exam.department)

        if user.role == 'instructor' and not _instructor_subject_allowed(user, next_department, next_subject):
            return Response(
                {'error': 'You can only save exams for your dean-assigned active subjects.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        exam.title = next_title
        exam.subject = next_subject
        if user.role != 'dean':
            exam.department = next_department
        exam.exam_type = request.data.get('exam_type', exam.exam_type)
        exam.question_type = request.data.get('question_type', exam.question_type)
        
        # Handle scheduled_date as naive datetime
        if 'scheduled_date' in request.data:
            scheduled_date_str = request.data.get('scheduled_date')
            naive_dt = datetime.fromisoformat(scheduled_date_str.replace('Z', ''))
            exam.scheduled_date = naive_dt
        
        # Handle expiration_time
        if 'expiration_time' in request.data:
            expiration_time_str = request.data.get('expiration_time')
            if expiration_time_str:
                naive_exp = datetime.fromisoformat(expiration_time_str.replace('Z', ''))
                exam.expiration_time = naive_exp
            else:
                exam.expiration_time = None
        
        exam.duration_minutes = request.data.get('duration_minutes', exam.duration_minutes)
        exam.total_points = request.data.get('total_points', exam.total_points)
        exam.passing_score = request.data.get('passing_score', exam.passing_score)
        exam.instructions = request.data.get('instructions', exam.instructions)
        exam.preview_rules = request.data.get('preview_rules', exam.preview_rules)
        sample_questions = request.data.get('sample_questions', exam.sample_questions)
        if isinstance(sample_questions, str):
            try:
                sample_questions = json.loads(sample_questions)
            except Exception:
                sample_questions = [q.strip() for q in sample_questions.splitlines() if q.strip()]
        exam.sample_questions = sample_questions
        exam.year_level = request.data.get('year_level', exam.year_level)
        exam.max_attempts = int(request.data.get('max_attempts', exam.max_attempts))
        exam.retake_policy = request.data.get('retake_policy', exam.retake_policy)
        exam.question_pool_size = int(request.data.get('question_pool_size', exam.question_pool_size))
        exam.shuffle_options = request.data.get('shuffle_options', exam.shuffle_options)
        
        # Update questions if provided
        if 'questions' in request.data:
            # Delete existing questions
            exam.questions.all().delete()
            
            # Add new questions
            questions_data = request.data.get('questions', [])
            for idx, q_data in enumerate(questions_data):
                Question.objects.create(
                    exam=exam,
                    question=q_data['question'],
                    type=q_data['type'],
                    options=q_data.get('options'),
                    correct_answer=q_data['correct_answer'],
                    points=q_data['points'],
                    order=idx + 1,
                )
        
        exam.save()

        # Clear all student seeds so the updated question set takes effect
        StudentExamSeed.objects.filter(exam=exam).delete()

        send_exam_update(f"exams_user_{user.id}", "updated", exam.id)
        send_exam_update(f"exams_dean_{exam.department}", "updated", exam.id)

        return Response({'message': 'Exam updated successfully'})
    except Exam.DoesNotExist:
        return Response({'error': 'Exam not found'}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_department_exam_stats(request):
    '''Get pass/fail stats per exam for dean — strictly filtered to dean's own department'''
    user = request.user

    if user.role != 'dean':
        return Response({'error': 'Only deans can access this endpoint'},
                       status=status.HTTP_403_FORBIDDEN)

    exams = Exam.objects.filter(department=user.department, is_draft=False, is_approved=True)

    stats = []
    for exam in exams:
        results = ExamResult.objects.filter(exam=exam, is_graded=True)
        total = results.count()
        passed = results.filter(remarks='Passed').count()
        failed = results.filter(remarks='Failed').count()
        pending = ExamResult.objects.filter(exam=exam, is_graded=False).count()
        pass_rate = round((passed / total * 100), 1) if total > 0 else 0

        from django.db.models import Avg
        avg = results.aggregate(avg=Avg('percentage'))['avg']

        stats.append({
            'exam_id': exam.id,
            'title': exam.title,
            'subject': exam.subject,
            'exam_type': exam.exam_type,
            'scheduled_date': exam.scheduled_date.isoformat(),
            'year_level': exam.year_level,
            'created_by': exam.created_by.get_full_name() or exam.created_by.username,
            'total_submissions': total,
            'passed': passed,
            'failed': failed,
            'pending': pending,
            'pass_rate': pass_rate,
            'avg_percentage': round(avg, 1) if avg is not None else 0,
            'status': exam.get_status(),
        })

    return Response({
        'department': user.department,
        'exams': stats,
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_pending_exams(request):
    '''Get pending exams for dean approval (filtered by department)'''
    user = request.user
    
    if user.role != 'dean':
        return Response({'error': 'Only deans can access this endpoint'}, 
                       status=status.HTTP_403_FORBIDDEN)
    
    # Filter exams by dean's department and only show exams with questions
    exams = Exam.objects.filter(
        department=user.department,
        is_draft=False,
        is_approved=False
    ).annotate(
        question_count=models.Count('questions')
    ).filter(question_count__gt=0)
    
    exam_list = []
    for exam in exams:
        exam_list.append({
            'id': exam.id,
            'title': exam.title,
            'subject': exam.subject,
            'department': exam.department,
            'exam_type': exam.exam_type,
            'scheduled_date': exam.scheduled_date.isoformat(),
            'duration_minutes': exam.duration_minutes,
            'total_points': exam.total_points,
            'year_level': exam.year_level,
            'created_by_id': exam.created_by_id,
            'created_by': exam.created_by.get_full_name() or exam.created_by.username,
        })
    
    return Response(exam_list)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_exam_detail_for_dean(request, exam_id):
    '''Get detailed exam information for dean including eligible students'''
    user = request.user
    
    if user.role != 'dean':
        return Response({'error': 'Only deans can access this endpoint'}, 
                       status=status.HTTP_403_FORBIDDEN)
    
    try:
        exam = Exam.objects.get(id=exam_id, department=user.department)
        
        # Get eligible students based on year level
        from django.db.models import Q
        eligible_students = _eligible_students_for_exam(exam)
        
        students_data = []
        for student in eligible_students:
            students_data.append({
                'id': student.id,
                'username': student.username,
                'email': student.email,
                'first_name': student.first_name,
                'last_name': student.last_name,
                'school_id': student.school_id,
                'year_level': student.year_level,
                'contact_number': student.contact_number,
                'profile_picture': _file_url(request, student.profile_picture),
                'id_photo': _file_url(request, student.id_photo),
                'id_verified': student.id_verified,
                'study_load': _file_url(request, student.study_load),
                'approved_by': student.approved_by.get_full_name() or student.approved_by.username if student.approved_by else None,
                'approved_at': student.approved_at.isoformat() if student.approved_at else None,
            })
        
        return Response({
            'exam': {
                'id': exam.id,
                'title': exam.title,
                'subject': exam.subject,
                'department': exam.department,
                'exam_type': exam.exam_type,
                'question_type': exam.question_type,
                'scheduled_date': exam.scheduled_date.isoformat(),
                'expiration_time': exam.expiration_time.isoformat() if exam.expiration_time else None,
                'duration_minutes': exam.duration_minutes,
                'total_points': exam.total_points,
                'passing_score': exam.passing_score,
                'instructions': exam.instructions,
                'year_level': exam.year_level,
                'is_approved': exam.is_approved,
                'created_by': exam.created_by.get_full_name() or exam.created_by.username,
                'created_at': exam.created_at.isoformat(),
                'question_count': exam.questions.count(),
            },
            'eligible_students': students_data,
            'total_eligible_students': len(students_data),
        })
    except Exam.DoesNotExist:
        return Response({'error': 'Exam not found'}, status=status.HTTP_404_NOT_FOUND)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def approve_exam(request, exam_id):
    '''Approve an exam'''
    user = request.user
    
    if user.role != 'dean':
        return Response({'error': 'Only deans can approve exams'}, 
                       status=status.HTTP_403_FORBIDDEN)
    
    try:
        exam = Exam.objects.get(id=exam_id, department=user.department)
        exam.is_approved = True
        exam.approved_by = user
        exam.approved_at = timezone.now()
        exam.save()
        
        log_activity(user, 'exam_approved', f'Approved exam: {exam.title}', request, {'exam_id': exam.id})
        _notify_exam_approved(Exam.objects.get(id=exam.id), user, notify_creator=True)
        return Response({'message': 'Exam approved successfully'})
        
        # Create notification for instructor
        Notification.objects.create(
            user=exam.created_by,
            type='exam_approved',
            title='Exam Approved',
            message=f'Your exam "{exam.title}" has been approved by {user.get_full_name() or user.username}.',
            link=f'/exam/{exam.id}/edit'
        )
        
        # Create notifications for students
        students = User.objects.filter(
            department=exam.department,
            role='student',
            is_approved=True
        )
        
        if exam.year_level != 'ALL':
            year_levels = exam.year_level.split(',')
            students = students.filter(year_level__in=year_levels)
        
        for student in students:
            Notification.objects.create(
                user=student,
                type='exam_scheduled',
                title='New Exam Scheduled',
                message=f'A new {exam.exam_type} exam "{exam.title}" has been scheduled for {exam.scheduled_date.strftime("%B %d, %Y")}.',
                link=f'/exam/{exam.id}/instructions'
            )
            # Send email notification
            send_exam_scheduled_email(student, exam)
        
        # Send push notifications to all eligible students
        student_list = list(students)
        send_push_to_users(
            student_list,
            '📝 New Exam Scheduled',
            f'{exam.exam_type.capitalize()} exam "{exam.title}" scheduled for {exam.scheduled_date.strftime("%b %d, %Y")}.',
        )

        send_exam_update(f"exams_user_{exam.created_by_id}", "approved", exam.id)
        send_exam_update(f"exams_dean_{exam.department}", "approved", exam.id)
        send_exam_update(f"exams_students_{exam.department}", "available", exam.id)

        # Note: 1-hour reminder push notifications should be handled via a scheduled task (e.g. Celery beat) in production.
        
        return Response({'message': 'Exam approved successfully'})
    except Exam.DoesNotExist:
        return Response({'error': 'Exam not found'}, status=status.HTTP_404_NOT_FOUND)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def reject_exam(request, exam_id):
    '''Reject an exam'''
    user = request.user
    
    if user.role != 'dean':
        return Response({'error': 'Only deans can reject exams'}, 
                       status=status.HTTP_403_FORBIDDEN)
    
    try:
        exam = Exam.objects.get(id=exam_id, department=user.department)
        exam_title = exam.title
        exam_creator = exam.created_by

        Notification.objects.create(
            user=exam_creator,
            type='exam_approved',
            title='Exam Rejected',
            message=f'Your exam "{exam_title}" was rejected by {user.get_full_name() or user.username}.',
            link='/dashboard/instructor'
        )

        send_exam_rejected_email(exam_creator, exam_title, user.get_full_name() or user.username)
        exam.delete()

        send_exam_update(f"exams_user_{exam_creator.id}", "rejected", exam_id)
        send_exam_update(f"exams_dean_{user.department}", "rejected", exam_id)
        
        log_activity(user, 'exam_rejected', f'Rejected exam: {exam_title}', request, {'exam_id': exam_id})
        
        return Response({'message': 'Exam rejected successfully', 'exam_title': exam_title, 'creator_email': exam_creator.email, 'creator_first_name': exam_creator.first_name})
    except Exam.DoesNotExist:
        return Response({'error': 'Exam not found'}, status=status.HTTP_404_NOT_FOUND)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_approved_exams(request):
    '''Get approved exams for dean's department'''
    user = request.user
    
    if user.role != 'dean':
        return Response({'error': 'Only deans can access this endpoint'}, 
                       status=status.HTTP_403_FORBIDDEN)
    
    exams = Exam.objects.filter(department=user.department, is_draft=False, is_approved=True)
    
    exam_list = []
    for exam in exams:
        exam_list.append({
            'id': exam.id,
            'title': exam.title,
            'subject': exam.subject,
            'department': exam.department,
            'exam_type': exam.exam_type,
            'scheduled_date': exam.scheduled_date.isoformat(),
            'duration_minutes': exam.duration_minutes,
            'total_points': exam.total_points,
            'year_level': exam.year_level,
            'created_by_id': exam.created_by_id,
            'created_by': exam.created_by.get_full_name() or exam.created_by.username,
            'approved_by': exam.approved_by.get_full_name() or exam.approved_by.username if exam.approved_by else 'N/A',
            'approved_at': exam.approved_at.isoformat() if exam.approved_at else None,
        })
    
    return Response(exam_list)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def create_exam(request):
    '''Create a new exam for instructors or deans'''
    user = request.user
    
    if user.role not in ('instructor', 'dean'):
        return Response({'error': 'Only instructors or deans can create exams'}, 
                       status=status.HTTP_403_FORBIDDEN)
    
    try:
        from datetime import datetime, timedelta
        
        # Parse the datetime string as naive datetime (no timezone conversion)
        scheduled_date_str = request.data.get('scheduled_date')
        naive_dt = datetime.fromisoformat(scheduled_date_str.replace('Z', ''))
        requested_department = request.data.get('department')
        department = user.department if user.role == 'dean' else requested_department
        subject_name = request.data.get('subject')

        if user.role == 'instructor':
            if not department:
                return Response({'error': 'Department is required'}, status=status.HTTP_400_BAD_REQUEST)
            if not _instructor_subject_allowed(user, department, subject_name):
                return Response(
                    {'error': 'You can only create exams for your dean-assigned active subjects.'},
                    status=status.HTTP_400_BAD_REQUEST
                )
        
        exam_type = request.data.get('exam_type')

        # Check for duplicate exam at same date/hour in same department
        # Round down to the hour to prevent exams within the same hour
        scheduled_hour = naive_dt.replace(minute=0, second=0, microsecond=0)
        next_hour = scheduled_hour + timedelta(hours=1)
        
        if exam_type not in ('quiz', 'practice'):
            existing_exam = Exam.objects.filter(
                department=department,
                scheduled_date__gte=scheduled_hour,
                scheduled_date__lt=next_hour
            ).exclude(exam_type__in=['quiz', 'practice']).exists()

            if existing_exam:
                return Response({
                    'error': 'Failed to create exam: A duplicate exam already exists for this department at the selected date and time. Please choose a different schedule.'
                }, status=status.HTTP_400_BAD_REQUEST)
        
        # Parse expiration_time if provided
        expiration_time = None
        if 'expiration_time' in request.data and request.data.get('expiration_time'):
            expiration_time_str = request.data.get('expiration_time')
            expiration_time = datetime.fromisoformat(expiration_time_str.replace('Z', ''))
        
        is_practice = exam_type == 'practice'
        
        auto_approve = user.role in ('dean', 'instructor')
        exam_title = request.data.get('title')
        import json
        sample_questions = request.data.get('sample_questions')
        if isinstance(sample_questions, str):
            try:
                sample_questions = json.loads(sample_questions)
            except Exception:
                sample_questions = [q.strip() for q in sample_questions.splitlines() if q.strip()]
        
        exam = Exam.objects.create(
              title=exam_title,
              subject=subject_name,
              department=department,
              exam_type=exam_type,
              question_type=request.data.get('question_type', 'multiple_choice'),
              scheduled_date=naive_dt,
              expiration_time=expiration_time,
              duration_minutes=request.data.get('duration_minutes'),
              total_points=request.data.get('total_points'),
              passing_score=request.data.get('passing_score'),
              instructions=request.data.get('instructions', ''),
              preview_rules=request.data.get('preview_rules', ''),
              sample_questions=sample_questions,
              year_level=request.data.get('year_level'),
              max_attempts=int(request.data.get('max_attempts', 1)),
              retake_policy=request.data.get('retake_policy', 'none'),
              question_pool_size=int(request.data.get('question_pool_size', 0)),
              shuffle_options=request.data.get('shuffle_options', True),
              created_by=user,
              is_approved=auto_approve,
              approved_by=user if auto_approve else None,
              approved_at=timezone.now() if auto_approve else None,
              is_practice=is_practice,
          )

        send_exam_update(f"exams_user_{user.id}", "created", exam.id)
        if department and not auto_approve:
            send_exam_update(f"exams_dean_{department}", "pending_created", exam.id)

        if auto_approve:
            try:
                send_dean_exam_created_email(user, exam)
            except Exception as exc:
                print(f"Warning: failed to send exam created email for exam {exam.id}: {exc}")
            log_activity(user, 'exam_approved', f'Auto-approved own exam: {exam_title}', request, {'exam_id': exam.id})

        log_activity(user, 'exam_created', f'Created exam: {exam_title}', request, {'exam_id': exam.id})
        
        dean_email_data = None
        if auto_approve:
            dean_email_data = {
                'to': user.email,
                'fullName': (user.first_name + ' ' + user.last_name).strip() or user.username,
                'examId': exam.id,
                'examTitle': exam.title,
                'subject': exam.subject,
                'department': exam.department,
                'examType': exam.exam_type,
                'scheduledDate': exam.scheduled_date.strftime('%B %d, %Y %I:%M %p'),
                'yearLevel': exam.year_level,
            }
        return Response({
            'message': 'Exam created successfully and approved automatically' if auto_approve else 'Exam created successfully and sent for dean approval',
            'exam_id': exam.id,
            'is_approved': exam.is_approved,
            'dean_email_data': dean_email_data,
        }, status=status.HTTP_201_CREATED)
    
    except Exception as e:
        return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def save_questions(request, exam_id):
    '''Save questions for an exam'''
    user = request.user
    
    if user.role not in ('instructor', 'dean'):
        return Response({'error': 'Only instructors or deans can add questions'}, 
                       status=status.HTTP_403_FORBIDDEN)
    
    try:
        exam = _get_staff_exam_or_404(user, exam_id)
        
        if not _can_modify_exam_questions(user, exam):
            return Response({'error': 'Cannot change exam questions after students have submitted results'},
                           status=status.HTTP_403_FORBIDDEN)
        
        questions_data = request.data.get('questions', [])
        question_type_error = _validate_question_types(exam, questions_data)
        if question_type_error:
            return question_type_error
        total_points_error = _validate_question_total_points(exam, questions_data)
        if total_points_error:
            return total_points_error
        from django.db import transaction
        with transaction.atomic():
            # Delete existing questions
            exam.questions.all().delete()
            
            # Add new questions
            for idx, q_data in enumerate(questions_data):
                Question.objects.create(
                    exam=exam,
                    question=q_data['question'],
                    type=q_data['type'],
                    options=q_data.get('options'),
                    correct_answer=q_data['correct_answer'],
                    points=q_data['points'],
                    order=idx + 1,
                )
            # Mark exam as no longer a draft — questions saved successfully
            if exam.is_draft:
                exam.is_draft = False
                exam.save(update_fields=['is_draft'])
            if exam.is_approved and questions_data:
                _publish_staff_exam_if_ready(exam, user)

        return Response({'message': 'Questions saved successfully'}, status=status.HTTP_201_CREATED)
    
    except Exam.DoesNotExist:
        return Response({'error': 'Exam not found'}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def import_questions_csv(request, exam_id):
    '''Import questions from CSV file'''
    user = request.user
    
    if user.role not in ('instructor', 'dean'):
        return Response({'error': 'Only instructors or deans can import questions'}, 
                       status=status.HTTP_403_FORBIDDEN)
    
    try:
        import csv
        import io
        
        exam = _get_staff_exam_or_404(user, exam_id)
        
        if not _can_modify_exam_questions(user, exam):
            return Response({'error': 'Cannot import questions after students have submitted results'},
                           status=status.HTTP_403_FORBIDDEN)
        
        if 'file' not in request.FILES:
            return Response({'error': 'No file uploaded'}, status=status.HTTP_400_BAD_REQUEST)
        
        csv_file = request.FILES['file']
        
        if not csv_file.name.endswith('.csv'):
            return Response({'error': 'File must be CSV format'}, status=status.HTTP_400_BAD_REQUEST)
        
        # Read CSV
        decoded_file = csv_file.read().decode('utf-8-sig')
        io_string = io.StringIO(decoded_file)
        reader = csv.DictReader(io_string)
        required_columns = {'question', 'type', 'correct_answer', 'points', 'subject', 'year_level'}
        csv_columns = {str(field or '').strip() for field in (reader.fieldnames or []) if str(field or '').strip()}
        missing_columns = sorted(required_columns - csv_columns)
        if missing_columns:
            return Response(
                {'error': f'Missing required column(s): {", ".join(missing_columns)}'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        
        questions_data = []
        mismatched_rows = []
        expected_subject = exam.subject.strip()
        expected_subject_normalized = _normalize_subject_label(expected_subject)
        expected_year_level = _format_expected_year_level(exam.year_level)
        expected_year_level_values = _normalized_year_level_values(exam.year_level)
        for row_num, row in enumerate(reader, start=2):
            row_mismatches = []

            row_subject = (row.get('subject') or '').strip()
            if _normalize_subject_label(row_subject) != expected_subject_normalized:
                row_mismatches.append({
                    'field': 'subject',
                    'actual': row_subject or '[blank]',
                    'expected': expected_subject,
                })

            row_year_level = (row.get('year_level') or '').strip()
            row_year_level_values = _normalized_year_level_values(row_year_level)
            if sorted(row_year_level_values) != sorted(expected_year_level_values):
                row_mismatches.append({
                    'field': 'year_level',
                    'actual': row_year_level or '[blank]',
                    'expected': expected_year_level,
                })
            # Validate department column if present — must match exam department
            row_dept = (row.get('department') or '').strip().upper()
            if row_dept and row_dept != exam.department.upper():
                row_mismatches.append({
                    'field': 'department',
                    'actual': row_dept,
                    'expected': exam.department,
                })

            if row_mismatches:
                mismatched_rows.append({
                    'row': row_num,
                    'question': (row.get('question') or '')[:60],
                    'mismatches': row_mismatches,
                })
                continue

            # Parse options for multiple choice
            options = None
            if row.get('type') == 'multiple_choice' and row.get('options'):
                options = [opt.strip() for opt in row['options'].split('|')]

            questions_data.append({
                'question': row['question'],
                'type': row['type'],
                'options': options,
                'correct_answer': row['correct_answer'],
                'points': int(row['points'])
            })

        if mismatched_rows:
            return Response({
                'error': (
                    f'CSV is invalid for this exam. Every row must match subject "{exam.subject}" '
                    f'and year level "{expected_year_level}".'
                ),
                'mismatched_rows': mismatched_rows,
            }, status=status.HTTP_400_BAD_REQUEST)

        if not questions_data:
            return Response({'error': 'No valid questions found in CSV'}, status=status.HTTP_400_BAD_REQUEST)

        question_type_error = _validate_question_types(exam, questions_data)
        if question_type_error:
            return question_type_error

        total_points_error = _validate_question_total_points(exam, questions_data)
        if total_points_error:
            return total_points_error
        # Delete existing questions
        exam.questions.all().delete()
        
        # Add imported questions
        for idx, q_data in enumerate(questions_data):
            Question.objects.create(
                exam=exam,
                question=q_data['question'],
                type=q_data['type'],
                options=q_data['options'],
                correct_answer=q_data['correct_answer'],
                points=q_data['points'],
                order=idx + 1,
            )
        # Mark exam as no longer a draft — questions imported successfully
        if exam.is_draft:
            exam.is_draft = False
            exam.save(update_fields=['is_draft'])
        if exam.is_approved:
            _publish_staff_exam_if_ready(exam, user)
        
        return Response({
            'message': f'{len(questions_data)} questions imported successfully',
            'count': len(questions_data)
        }, status=status.HTTP_201_CREATED)
    
    except Exam.DoesNotExist:
        return Response({'error': 'Exam not found'}, status=status.HTTP_404_NOT_FOUND)
    except KeyError as e:
        return Response({'error': f'Missing required column: {str(e)}'}, status=status.HTTP_400_BAD_REQUEST)
    except Exception as e:
        return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_exam_results_for_instructor(request, exam_id):
    '''Get all results for a specific exam owned by the current instructor or dean'''
    user = request.user
    
    if user.role not in ('instructor', 'dean'):
        return Response({'error': 'Only instructors or deans can access this endpoint'}, 
                       status=status.HTTP_403_FORBIDDEN)
    
    try:
        exam = _get_staff_exam_or_404(user, exam_id)
        results = ExamResult.objects.filter(exam=exam).select_related('student')
        
        result_list = []
        for result in results:
            # Get questions with student answers
            questions_with_answers = []
            for question in exam.questions.all():
                student_answer = result.answers.get(str(question.id), '')
                questions_with_answers.append({
                    'id': question.id,
                    'question': question.question,
                    'type': question.type,
                    'correct_answer': question.correct_answer,
                    'student_answer': student_answer,
                    'points': question.points,
                })
            
            result_list.append({
                'id': result.id,
                'student_name': result.student.get_full_name() or result.student.username,
                'student_id': result.student.school_id,
                'score': result.score,
                'total_points': result.total_points,
                'percentage': result.percentage,
                'grade': result.grade,
                'remarks': result.remarks,
                'submitted_at': result.submitted_at.isoformat(),
                'is_graded': result.is_graded,
                'score_before_penalty': result.score_before_penalty,
                'penalty_percent': result.penalty_percent,
                'questions_with_answers': questions_with_answers,
            })
        
        return Response({
            'exam': {
                'id': exam.id,
                'title': exam.title,
                'subject': exam.subject,
                'total_points': exam.total_points,
                'passing_score': exam.passing_score,
            },
            'results': result_list,
            'total_students': len(result_list),
            'passed': len([r for r in result_list if r['remarks'] == 'Passed' and r['is_graded']]),
            'failed': len([r for r in result_list if r['remarks'] == 'Failed' and r['is_graded']]),
            'pending': len([r for r in result_list if not r['is_graded']]),
        })
    
    except Exam.DoesNotExist:
        return Response({'error': 'Exam not found'}, status=status.HTTP_404_NOT_FOUND)



@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_exam_for_taking(request, exam_id):
    '''Get exam with questions for student to take'''
    user = request.user
    
    role_response = require_role(user, 'student', message='Only students can take exams')
    if role_response:
        return role_response
    
    try:
        from django.db.models import Q
        exam = Exam.objects.get(id=exam_id)
        
        if not exam.is_approved:
            return Response({'error': 'This exam is not yet approved'}, 
                           status=status.HTTP_403_FORBIDDEN)

        access_error = _exam_access_error(user, exam)
        if access_error:
            return Response({'error': access_error}, status=status.HTTP_403_FORBIDDEN)
        
        # Check if exam has an expiration time and if it's passed
        from datetime import datetime
        if exam.expiration_time and datetime.now() > exam.expiration_time:
            return Response({'error': 'This exam has expired and is no longer available'}, 
                           status=status.HTTP_403_FORBIDDEN)
        
        # Check if student is blocked due to multiple terminations
        try:
            termination = ExamTermination.objects.get(exam=exam, student=user)
            if termination.is_blocked:
                return Response({
                    'error': f'You have been permanently blocked from this exam after {termination.termination_count} terminations due to violations'
                }, status=status.HTTP_403_FORBIDDEN)
        except ExamTermination.DoesNotExist:
            pass
        
        # Check for cheating violations
        violation_count = CheatingViolation.objects.filter(exam=exam, student=user).count()
        if violation_count >= 5:
            return Response({'error': 'You have been blocked from this exam due to multiple cheating violations'}, 
                           status=status.HTTP_403_FORBIDDEN)
        
        # Check if student has already taken this exam and if retakes are allowed
        existing_results = ExamResult.objects.filter(exam=exam, student=user)
        attempt_count = existing_results.count()
        
        if attempt_count >= exam.max_attempts:
            return Response({'error': f'You have reached the maximum number of attempts ({exam.max_attempts}) for this exam'}, 
                           status=status.HTTP_403_FORBIDDEN)
        
        # For retakes, check if exam allows them
        if attempt_count > 0 and exam.retake_policy == 'none':
            return Response({'error': 'Retakes are not allowed for this exam'}, 
                           status=status.HTTP_403_FORBIDDEN)

        # Check for active session on another device
        from django.utils import timezone as tz
        from datetime import timedelta
        active_session = ExamSession.objects.filter(exam=exam, student=user, is_active=True).first()
        if active_session:
            supplied_session_token = _extract_exam_session_token(request)
            if supplied_session_token and supplied_session_token == active_session.session_token:
                active_session.last_heartbeat = tz.now()
                active_session.save(update_fields=['last_heartbeat'])
            else:
                # Stale if no heartbeat for 90 seconds (3 missed heartbeats at 30s interval)
                stale_threshold = tz.now() - timedelta(seconds=90)
                if active_session.last_heartbeat > stale_threshold:
                    return Response({
                        'error': 'You already have an active exam session on another device. Please finish or close that session first.'
                    }, status=status.HTTP_403_FORBIDDEN)
            # Stale session — clear it and allow
                active_session.delete()

        # --- Question pool + shuffle ---
        import random
        all_questions = list(exam.questions.all().order_by('order'))

        seed_obj, created = StudentExamSeed.objects.get_or_create(
            exam=exam,
            student=user,
            defaults={'question_ids': []},
        )

        if created or not seed_obj.question_ids:
            # First time: pick pool and shuffle order, then persist
            pool_size = exam.question_pool_size
            if pool_size and 0 < pool_size < len(all_questions):
                selected = random.sample(all_questions, pool_size)
            else:
                selected = all_questions[:]
            random.shuffle(selected)
            seed_obj.question_ids = [q.id for q in selected]
            seed_obj.save()

        # Restore the persisted order (consistent on reload)
        id_to_q = {q.id: q for q in all_questions}
        ordered_questions = [id_to_q[qid] for qid in seed_obj.question_ids if qid in id_to_q]

        def shuffled_options(q):
            if q.type == 'multiple_choice' and q.options and exam.shuffle_options:
                opts = q.options[:]
                random.shuffle(opts)
                return opts
            return q.options if q.type == 'multiple_choice' else None

        questions_data = [{
            'id': q.id,
            'question': q.question,
            'type': q.type,
            'options': shuffled_options(q),
            'points': q.points,
        } for q in ordered_questions]

        pool_total = sum(q.points for q in ordered_questions)

        return Response({
            'id': exam.id,
            'title': exam.title,
            'subject': exam.subject,
            'instructions': exam.instructions,
            'duration_minutes': exam.duration_minutes,
            'total_points': pool_total,
            'pool_total_points': pool_total,
            'questions': questions_data,
        })

    except Exam.DoesNotExist:
        return Response({'error': 'Exam not found'}, status=status.HTTP_404_NOT_FOUND)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def record_exam_termination(request, exam_id):
    '''Record when a student's exam is terminated due to violations'''
    user = request.user

    role_response = require_role(user, 'student', message='Only students can have terminations')
    if role_response:
        return role_response
    
    try:
        exam = Exam.objects.get(id=exam_id)
        _, session_response = _require_active_exam_session(request, exam, user)
        if session_response:
            return session_response
        block_threshold = getattr(settings, 'EXAM_TERMINATION_BLOCK_THRESHOLD', 3)
        final_warning_at = getattr(settings, 'EXAM_TERMINATION_FINAL_WARNING_AT', block_threshold - 1)
        first_penalty_percent = getattr(settings, 'EXAM_TERMINATION_FIRST_PENALTY_PERCENT', 10)
        
        # Get or create termination record
        termination, created = ExamTermination.objects.get_or_create(
            exam=exam,
            student=user,
            defaults={'termination_count': 1}
        )
        
        if not created:
            # Increment termination count
            termination.termination_count += 1
            
            # Final warning on the second termination (configurable)
            if termination.termination_count == final_warning_at:
                Notification.objects.create(
                    user=user,
                    type='exam_warning',
                    title='Final Warning: Exam Violation',
                    message=f'Your exam was terminated due to violations. This is your final warning for "{exam.title}". One last attempt will be allowed, but another violation will permanently block you from this exam.',
                    link='/dashboard/student'
                )

            # Block after the configured threshold
            if termination.termination_count >= block_threshold:
                termination.is_blocked = True
                
                # Create notification for permanent block
                Notification.objects.create(
                    user=user,
                    type='exam_blocked',
                    title='Permanently Blocked from Exam',
                    message=f'You have been permanently blocked from "{exam.title}" after {termination.termination_count} terminations due to multiple violations. Please contact your instructor if you believe this is an error.',
                    link='/dashboard/student'
                )
            
            termination.save()

        log_activity(
            user,
            'exam_terminated',
            f'Exam terminated: {exam.title}',
            request,
            {'exam_id': exam.id, 'student_id': user.id, 'termination_count': termination.termination_count}
        )
        
        message = 'Termination recorded'
        if termination.termination_count == 1:
            message = (
                'Suspicious behavior detected. Your exam was terminated. '
                f'You may retry, but a -{first_penalty_percent}% penalty will be applied.'
            )
        elif termination.termination_count == final_warning_at and not termination.is_blocked:
            message = (
                'Final warning: your exam was terminated due to violations. '
                'You may take one last attempt, but another violation will permanently block you.'
            )
        elif termination.is_blocked:
            message = (
                'Your exam was terminated due to violations and you are now permanently blocked '
                'from this exam. No further attempts are allowed.'
            )

        return Response({
            'message': message,
            'termination_count': termination.termination_count,
            'is_blocked': termination.is_blocked,
            'can_retry': not termination.is_blocked,
            'is_final_attempt': termination.termination_count == final_warning_at and not termination.is_blocked,
            'penalty_percent': first_penalty_percent if termination.termination_count == 1 else 0,
            'final_chance_used': termination.is_blocked
        })
    
    except Exam.DoesNotExist:
        return Response({'error': 'Exam not found'}, status=status.HTTP_404_NOT_FOUND)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def submit_exam(request, exam_id):
    '''Submit exam answers and calculate score'''
    user = request.user

    role_response = require_role(user, 'student', message='Only students can submit exams')
    if role_response:
        return role_response
    
    try:
        exam = Exam.objects.get(id=exam_id)
        _, session_response = _require_active_exam_session(request, exam, user)
        if session_response:
            return session_response
        access_error = _exam_access_error(user, exam)
        if access_error:
            return Response({'error': access_error}, status=status.HTTP_403_FORBIDDEN)
        
        # Check if student has already taken this exam and if retakes are allowed
        existing_results = ExamResult.objects.filter(exam=exam, student=user)
        attempt_count = existing_results.count()
        
        if attempt_count >= exam.max_attempts:
            return Response({'error': f'You have reached the maximum number of attempts ({exam.max_attempts}) for this exam'}, 
                           status=status.HTTP_403_FORBIDDEN)
        
        # For retakes, check if exam allows them
        if attempt_count > 0 and exam.retake_policy == 'none':
            return Response({'error': 'Retakes are not allowed for this exam'}, 
                           status=status.HTTP_403_FORBIDDEN)
        
        next_attempt = attempt_count + 1

        # Clear seed on retakes so student gets a fresh shuffle/pool
        if attempt_count > 0 and exam.retake_policy in ('average_score', 'best_score', 'latest_score'):
            StudentExamSeed.objects.filter(exam=exam, student=user).delete()
        
        answers = request.data.get('answers', {})
        all_questions = list(exam.questions.all())

        # Use seeded questions if available (question pool per student)
        pool_questions = all_questions
        pool_total = exam.total_points
        try:
            seed_obj = StudentExamSeed.objects.get(exam=exam, student=user)
            id_to_q = {q.id: q for q in all_questions}
            pool_questions = [id_to_q[qid] for qid in seed_obj.question_ids if qid in id_to_q]
            if not pool_questions:
                pool_questions = all_questions
            pool_total = sum(q.points for q in pool_questions) if pool_questions else exam.total_points
        except StudentExamSeed.DoesNotExist:
            pass

        score = 0
        debug_info = []
        
        for question in pool_questions:
            question_id_str = str(question.id)
            student_answer = str(answers.get(question_id_str, '')).strip()
            correct_answer = str(question.correct_answer).strip()
            
            debug_info.append({
                'question_id': question.id,
                'question_text': question.question[:50],
                'student_answer': student_answer,
                'correct_answer': correct_answer,
                'type': question.type,
                'points': question.points,
            })
            
            # Auto-grade multiple choice and identification
            if question.type in ['multiple_choice', 'identification']:
                if student_answer.lower() == correct_answer.lower():
                    score += question.points
                    debug_info[-1]['matched'] = True
                else:
                    debug_info[-1]['matched'] = False
            else:
                # Essay and enumeration require manual grading
                debug_info[-1]['matched'] = 'Manual grading required'
        
        # Log debug info
        print("\n=== EXAM SUBMISSION DEBUG ===")
        print(f"Exam ID: {exam_id}")
        print(f"Student: {user.username}")
        print(f"Total Score: {score}/{pool_total}")
        print("\nAnswers received:")
        for key, value in answers.items():
            print(f"  Question {key}: {value}")
        print("\nGrading details:")
        for info in debug_info:
            print(f"  Q{info['question_id']} ({info['type']}): Student='{info['student_answer']}' vs Correct='{info['correct_answer']}' -> Match={info.get('matched', 'N/A')}")
        print("=== END DEBUG ===\n")
        
        # Check if exam has essay/enumeration questions (within student's pool)
        has_manual_grading = any(q.type in ['essay', 'enumeration'] for q in pool_questions)

        # Apply penalty based on prior terminations
        penalty_percent = 0
        try:
            termination = ExamTermination.objects.get(exam=exam, student=user)
            if termination.termination_count >= 2:
                penalty_percent = getattr(settings, 'EXAM_TERMINATION_SECOND_PENALTY_PERCENT', 30)
            elif termination.termination_count >= 1:
                penalty_percent = getattr(settings, 'EXAM_TERMINATION_FIRST_PENALTY_PERCENT', 10)
        except ExamTermination.DoesNotExist:
            pass

        penalty_points = round(pool_total * (penalty_percent / 100)) if penalty_percent > 0 else 0
        adjusted_score = max(score - penalty_points, 0)

        result = ExamResult.objects.create(
            exam=exam,
            student=user,
            score_before_penalty=score,
            score=adjusted_score,
            total_points=pool_total,
            answers=answers,
            attempt_number=next_attempt,
            is_graded=not has_manual_grading,
            graded_at=timezone.now() if not has_manual_grading else None,
            penalty_percent=penalty_percent,
        )
        
        # If auto-graded (no essay/enumeration), send email immediately
        # If auto-graded (no essay/enumeration), send email immediately
        if not has_manual_grading:
            try:
                Notification.objects.create(
                    user=user,
                    type='result_published',
                    title='Exam Result Published',
                    message=f'Your result for "{exam.title}" is now available. Grade: {result.grade}',
                    link=f'/dashboard/student'
                )
                send_results_published_email(user, result)
                send_push_notification(
                    user.expo_push_token,
                    'Result Published',
                    f'Your result for "{exam.title}" is ready. Grade: {result.grade}',
                )
            except Exception as notify_err:
                print(f"Warning: failed to send result notifications: {notify_err}")

        log_activity(user, 'exam_submitted', f'Submitted exam: {exam.title}', request, {'exam_id': exam.id, 'score': score})

        # Apply retake policies across graded attempts
        if next_attempt > 1 and result.is_graded:
            graded_results = list(ExamResult.objects.filter(exam=exam, student=user, is_graded=True))
            if graded_results:
                if exam.retake_policy == 'average_score':
                    avg_pct = sum(r.percentage for r in graded_results) / len(graded_results)
                    result.score = round((avg_pct / 100) * result.total_points)
                    result.save(update_fields=['score', 'percentage', 'grade', 'remarks'])
                elif exam.retake_policy == 'best_score':
                    best = max(graded_results, key=lambda r: r.score)
                    if best.id != result.id:
                        result.score = best.score
                        result.score_before_penalty = best.score_before_penalty
                        result.penalty_percent = best.penalty_percent
                        result.save(update_fields=['score', 'percentage', 'grade', 'remarks', 'score_before_penalty', 'penalty_percent'])

        # End the exam session
        ExamSession.objects.filter(exam=exam, student=user).delete()

        email_data = None
        if not has_manual_grading:
            email_data = {
                'to': user.email,
                'firstName': user.first_name or 'there',
                'examTitle': exam.title,
                'subject': exam.subject,
                'score': adjusted_score,
                'totalItems': pool_total,
                'percentage': round(result.percentage, 1),
                'passed': result.remarks == 'Passed',
                'dateTaken': result.submitted_at.strftime('%B %d, %Y %I:%M %p'),
            }
        return Response({
            'message': 'Exam submitted successfully',
            'score': adjusted_score if not has_manual_grading else None,
            'score_before_penalty': score if not has_manual_grading else None,
            'penalty_percent': penalty_percent if not has_manual_grading else None,
            'total_points': pool_total,
            'percentage': result.percentage if not has_manual_grading else None,
            'grade': result.grade if not has_manual_grading else None,
            'is_graded': not has_manual_grading,
            'needs_manual_grading': has_manual_grading,
            'email_data': email_data,
        }, status=status.HTTP_201_CREATED)
    
    except Exam.DoesNotExist:
        return Response({'error': 'Exam not found'}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        print(f"ERROR in submit_exam: {str(e)}")
        import traceback
        traceback.print_exc()
        return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)



@api_view(['POST'])
@permission_classes([IsAuthenticated])
def grade_exam_result(request, result_id):
    '''Grade essay/enumeration questions for a specific exam result'''
    user = request.user
    
    if user.role not in ('instructor', 'dean'):
        return Response({'error': 'Only instructors or deans can grade exams'}, 
                       status=status.HTTP_403_FORBIDDEN)
    
    try:
        result = ExamResult.objects.get(id=result_id)
        exam = result.exam
        
        # Verify current staff user owns this exam
        if not _is_staff_exam_owner(user, exam):
            return Response({'error': 'You can only grade your own exams'}, 
                           status=status.HTTP_403_FORBIDDEN)
        
        # Get manual scores from request
        manual_scores = request.data.get('manual_scores', {})
        
        # Recalculate total score using answered question IDs as the pool
        # (avoids relying on a seed that may have been deleted on retake)
        total_score = 0
        all_questions = list(exam.questions.all())
        answered_ids = set(result.answers.keys())
        pool_questions = [q for q in all_questions if str(q.id) in answered_ids] or all_questions
        
        for question in pool_questions:
            question_id_str = str(question.id)
            student_answer = str(result.answers.get(question_id_str, '')).strip()
            correct_answer = str(question.correct_answer).strip()
            
            if question.type in ['multiple_choice', 'identification']:
                # Auto-graded questions
                if student_answer.lower() == correct_answer.lower():
                    total_score += question.points
            elif question.type in ['essay', 'enumeration']:
                # Manually graded questions
                awarded_points = manual_scores.get(question_id_str, 0)
                total_score += int(awarded_points)
        
        # Update result
        penalty_percent = result.penalty_percent or 0
        penalty_points = round(result.total_points * (penalty_percent / 100)) if penalty_percent > 0 else 0
        adjusted_score = max(total_score - penalty_points, 0)
        result.score_before_penalty = total_score
        result.score = adjusted_score
        result.is_graded = True
        result.graded_at = timezone.now()
        result.save()
        
        # Create notification for student
        try:
            Notification.objects.create(
                user=result.student,
                type='result_published',
                title='Exam Result Published',
                message=f'Your result for "{exam.title}" has been published. Grade: {result.grade}',
                link=f'/dashboard/student'
            )
            send_results_published_email(result.student, result)
            send_push_notification(
                result.student.expo_push_token,
                'Result Published',
                f'Your result for "{exam.title}" has been published. Grade: {result.grade}',
            )
        except Exception as notify_err:
            print(f"Warning: failed to send result notifications: {notify_err}")

        return Response({
            'message': 'Exam graded successfully',
            'score': result.score,
            'total_points': result.total_points,
            'percentage': result.percentage,
            'grade': result.grade,
            'remarks': result.remarks,
            'email_data': {
                'to': result.student.email,
                'firstName': result.student.first_name or 'there',
                'examTitle': exam.title,
                'subject': exam.subject,
                'score': result.score,
                'totalItems': result.total_points,
                'percentage': round(result.percentage, 1),
                'passed': result.remarks == 'Passed',
                'dateTaken': result.submitted_at.strftime('%B %d, %Y %I:%M %p'),
            },
        })
    
    except ExamResult.DoesNotExist:
        return Response({'error': 'Result not found'}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)



@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_pending_results(request):
    '''Get pending exam results (submitted but not graded) for student'''
    user = request.user
    
    if user.role != 'student':
        return Response({'error': 'Only students can access this endpoint'}, 
                       status=status.HTTP_403_FORBIDDEN)
    
    results = ExamResult.objects.filter(student=user, is_graded=False)
    
    result_list = []
    for result in results:
        result_list.append({
            'id': result.id,
            'exam_id': result.exam.id,
            'exam_title': result.exam.title,
            'exam_subject': result.exam.subject,
            'submitted_at': result.submitted_at.isoformat(),
            'status': 'Pending Grading',
        })
    
    return Response(result_list)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def list_question_issue_reports(request):
    '''List issue reports visible to the current user'''
    user = request.user

    if user.role not in ['student', 'instructor', 'dean']:
        return Response({'error': 'Forbidden'}, status=status.HTTP_403_FORBIDDEN)

    status_filter = request.GET.get('status', '').strip()
    qs = _get_issue_report_queryset(user)
    if status_filter:
        qs = qs.filter(status=status_filter)

    reports = [_serialize_issue_report_summary(report) for report in qs]
    return Response({'reports': reports})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def create_question_issue_report(request, exam_id):
    '''Allow a student to report an issue about a specific exam question'''
    user = request.user

    role_response = require_role(user, 'student', message='Only students can report exam issues')
    if role_response:
        return role_response

    throttle_response = throttle_request(
        request,
        'question_issue_report_create',
        limit=6,
        window_seconds=600,
        identifiers=[user.id, exam_id],
        message='Too many issue reports submitted. Please wait before sending another one.',
    )
    if throttle_response:
        return throttle_response

    try:
        exam = Exam.objects.get(id=exam_id)
        access_error = _exam_access_error(user, exam)
        if access_error:
            return Response({'error': access_error}, status=status.HTTP_403_FORBIDDEN)
        question = Question.objects.get(id=request.data.get('question_id'), exam=exam)
    except Exam.DoesNotExist:
        return Response({'error': 'Exam not found'}, status=status.HTTP_404_NOT_FOUND)
    except Question.DoesNotExist:
        return Response({'error': 'Question not found'}, status=status.HTTP_404_NOT_FOUND)

    result = ExamResult.objects.filter(exam=exam, student=user).order_by('-submitted_at').first()
    if not result:
        access_error = _exam_access_error(user, exam)
        if access_error:
            return Response({'error': access_error}, status=status.HTTP_403_FORBIDDEN)

    issue_type = request.data.get('issue_type', '').strip()
    description = request.data.get('description', '').strip()
    reported_answer = request.data.get('reported_answer', '').strip()

    valid_issue_types = {choice[0] for choice in QuestionIssueReport.ISSUE_TYPE_CHOICES}
    if issue_type not in valid_issue_types:
        return Response({'error': 'Invalid issue type'}, status=status.HTTP_400_BAD_REQUEST)
    if not description:
        return Response({'error': 'Description is required'}, status=status.HTTP_400_BAD_REQUEST)

    report = QuestionIssueReport.objects.create(
        exam=exam,
        question=question,
        student=user,
        exam_result=result,
        issue_type=issue_type,
        description=description,
        reported_answer=reported_answer,
        status='under_review',
    )
    QuestionIssueMessage.objects.create(
        report=report,
        sender=user,
        message=description,
    )

    _notify_issue_report_users(
        report,
        actor=user,
        title='New Exam Issue Report',
        message=f'{user.get_full_name() or user.username} reported an issue in "{exam.title}" (Question {question.order}).',
        student_link=False,
        staff_link=True,
    )
    actor_name = user.get_full_name() or user.username
    instructor = exam.created_by
    if instructor.email:
        send_issue_report_email(instructor, report, actor_name)
    log_activity(
        user,
        'exam_issue_reported',
        f'Reported an issue for question {question.order} in {exam.title}',
        request,
        {'exam_id': exam.id, 'question_id': question.id, 'report_id': report.id}
    )

    return Response({'report': _serialize_issue_report_detail(report, user), 'instructor_email_data': {'to': instructor.email, 'firstName': instructor.first_name or 'there', 'reportId': report.id, 'examTitle': exam.title, 'questionOrder': question.order, 'issueType': report.get_issue_type_display(), 'reportedAnswer': report.reported_answer or None, 'description': report.description, 'actorName': actor_name, 'role': instructor.role}}, status=status.HTTP_201_CREATED)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_question_issue_report_detail(request, report_id):
    '''Get a single issue report and its thread'''
    report = _get_issue_report_queryset(request.user).filter(id=report_id).first()
    if not report:
        return Response({'error': 'Report not found'}, status=status.HTTP_404_NOT_FOUND)
    return Response({'report': _serialize_issue_report_detail(report, request.user)})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def add_question_issue_message(request, report_id):
    '''Add a reply to an issue report thread'''
    user = request.user
    report = _get_issue_report_queryset(user).filter(id=report_id).first()
    if not report:
        return Response({'error': 'Report not found'}, status=status.HTTP_404_NOT_FOUND)

    throttle_response = throttle_request(
        request,
        'question_issue_report_message',
        limit=12,
        window_seconds=600,
        identifiers=[user.id, report_id],
        message='Too many issue report replies submitted. Please wait before sending another one.',
    )
    if throttle_response:
        return throttle_response

    message_text = request.data.get('message', '').strip()
    if not message_text:
        return Response({'error': 'Message is required'}, status=status.HTTP_400_BAD_REQUEST)

    QuestionIssueMessage.objects.create(
        report=report,
        sender=user,
        message=message_text,
    )
    next_status = report.status
    if user.role == 'student':
        if report.status != 'rejected':
            next_status = 'under_review'
    elif user.role in ['instructor', 'dean']:
        if report.status != 'rejected':
            next_status = 'resolved'

    if next_status != report.status:
        report.status = next_status
        report.save(update_fields=['status', 'updated_at'])

    if user.role == 'student':
        title = 'Student Replied to Issue Report'
        body = f'{user.get_full_name() or user.username} replied on "{report.exam.title}" issue report.'
        _notify_issue_report_users(report, actor=user, title=title, message=body, student_link=False, staff_link=True)
    else:
        title = 'Issue Report Update'
        body = f'{user.get_full_name() or user.username} replied to your report for "{report.exam.title}".'
        _notify_issue_report_users(report, actor=user, title=title, message=body, student_link=True, staff_link=False)
        if report.student.email:
            send_issue_report_reply_email(report.student, report, user.get_full_name() or user.username, message_text)

    return Response({'report': _serialize_issue_report_detail(report, user)})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def update_question_issue_status(request, report_id):
    '''Allow instructors and deans to change the report status'''
    user = request.user
    if user.role not in ['instructor', 'dean']:
        return Response({'error': 'Only instructors or deans can update report status'}, status=status.HTTP_403_FORBIDDEN)

    report = _get_issue_report_queryset(user).filter(id=report_id).first()
    if not report:
        return Response({'error': 'Report not found'}, status=status.HTTP_404_NOT_FOUND)

    new_status = request.data.get('status', '').strip()
    valid_statuses = {choice[0] for choice in QuestionIssueReport.STATUS_CHOICES}
    if new_status not in valid_statuses:
        return Response({'error': 'Invalid status'}, status=status.HTTP_400_BAD_REQUEST)

    note = request.data.get('message', '').strip()
    report.status = new_status
    report.save(update_fields=['status', 'updated_at'])

    if note:
        QuestionIssueMessage.objects.create(report=report, sender=user, message=note)

    _notify_issue_report_users(
        report,
        actor=user,
        title='Issue Report Status Updated',
        message=f'Your report for "{report.exam.title}" is now marked as {report.get_status_display().lower()}.',
        student_link=True,
        staff_link=False,
    )
    return Response({'report': _serialize_issue_report_detail(report, user)})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def report_cheating(request, exam_id):
    '''Report a cheating violation for a student'''
    user = request.user

    role_response = require_role(user, 'instructor', message='Only instructors can report cheating')
    if role_response:
        return role_response

    throttle_response = throttle_request(
        request,
        'report_cheating',
        limit=20,
        window_seconds=600,
        identifiers=[user.id, exam_id],
        message='Too many cheating reports submitted. Please wait before creating more.',
    )
    if throttle_response:
        return throttle_response
    
    try:
        exam = Exam.objects.get(id=exam_id, created_by=user)
        student_id = request.data.get('student_id')
        violation_type = request.data.get('violation_type', 'cheating')
        
        student = User.objects.get(id=student_id)
        
        CheatingViolation.objects.create(
            exam=exam,
            student=student,
            violation_type=violation_type
        )
        
        violation_count = CheatingViolation.objects.filter(exam=exam, student=student).count()
        
        return Response({
            'message': 'Cheating violation reported',
            'violation_count': violation_count,
            'blocked': violation_count >= 5
        })
    
    except Exam.DoesNotExist:
        return Response({'error': 'Exam not found'}, status=status.HTTP_404_NOT_FOUND)
    except User.DoesNotExist:
        return Response({'error': 'Student not found'}, status=status.HTTP_404_NOT_FOUND)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_exam_analytics(request, exam_id):
    '''Get detailed analytics for a specific exam (instructors only)'''
    user = request.user
    
    if user.role != 'instructor':
        return Response({'error': 'Only instructors can access analytics'}, 
                       status=status.HTTP_403_FORBIDDEN)
    
    try:
        from django.db.models import Avg, Max, Min, Count
        
        exam = Exam.objects.get(id=exam_id, created_by=user)
        results = ExamResult.objects.filter(exam=exam, is_graded=True)
        
        if not results.exists():
            return Response({
                'exam': {
                    'id': exam.id,
                    'title': exam.title,
                    'subject': exam.subject,
                    'total_points': exam.total_points,
                    'passing_score': exam.passing_score,
                },
                'statistics': {
                    'total_students': 0,
                    'passed': 0,
                    'failed': 0,
                    'pass_rate': 0,
                    'average_score': 0,
                    'highest_score': 0,
                    'lowest_score': 0,
                    'average_percentage': 0,
                },
                'grade_distribution': [],
                'score_distribution': [],
                'question_analysis': [],
            })
        
        # Basic statistics
        total_students = results.count()
        passed = results.filter(remarks='Passed').count()
        failed = results.filter(remarks='Failed').count()
        pass_rate = (passed / total_students * 100) if total_students > 0 else 0
        
        stats = results.aggregate(
            avg_score=Avg('score'),
            max_score=Max('score'),
            min_score=Min('score'),
            avg_percentage=Avg('percentage')
        )
        
        # Grade distribution
        grade_counts = {}
        for result in results:
            grade = result.grade
            grade_counts[grade] = grade_counts.get(grade, 0) + 1
        
        grade_distribution = [
            {'grade': grade, 'count': count, 'percentage': (count / total_students * 100)}
            for grade, count in sorted(grade_counts.items())
        ]
        
        # Score distribution (grouped by ranges)
        score_ranges = {
            '0-20': 0, '21-40': 0, '41-60': 0, '61-80': 0, '81-100': 0
        }
        for result in results:
            percentage = result.percentage
            if percentage <= 20:
                score_ranges['0-20'] += 1
            elif percentage <= 40:
                score_ranges['21-40'] += 1
            elif percentage <= 60:
                score_ranges['41-60'] += 1
            elif percentage <= 80:
                score_ranges['61-80'] += 1
            else:
                score_ranges['81-100'] += 1
        
        score_distribution = [
            {'range': range_name, 'count': count}
            for range_name, count in score_ranges.items()
        ]
        
        # Question analysis (difficulty)
        questions = exam.questions.all()
        question_analysis = []
        
        for question in questions:
            correct_count = 0
            total_answered = 0
            
            for result in results:
                student_answer = str(result.answers.get(str(question.id), '')).strip()
                if student_answer:
                    total_answered += 1
                    if question.type in ['multiple_choice', 'identification']:
                        if student_answer.lower() == str(question.correct_answer).strip().lower():
                            correct_count += 1
            
            difficulty_rate = (correct_count / total_answered * 100) if total_answered > 0 else 0
            
            if difficulty_rate >= 80:
                difficulty = 'Easy'
            elif difficulty_rate >= 50:
                difficulty = 'Medium'
            else:
                difficulty = 'Hard'
            
            question_analysis.append({
                'question_number': question.order,
                'question_text': question.question[:100],
                'type': question.type,
                'points': question.points,
                'correct_count': correct_count,
                'total_answered': total_answered,
                'success_rate': round(difficulty_rate, 2),
                'difficulty': difficulty,
            })
        
        # Top performers
        top_performers = results.order_by('-score')[:5]
        top_performers_list = [{
            'student_name': r.student.get_full_name() or r.student.username,
            'student_id': r.student.school_id,
            'score': r.score,
            'percentage': round(r.percentage, 2),
            'grade': r.grade,
        } for r in top_performers]
        
        return Response({
            'exam': {
                'id': exam.id,
                'title': exam.title,
                'subject': exam.subject,
                'total_points': exam.total_points,
                'passing_score': exam.passing_score,
                'scheduled_date': exam.scheduled_date.isoformat(),
            },
            'statistics': {
                'total_students': total_students,
                'passed': passed,
                'failed': failed,
                'pass_rate': round(pass_rate, 2),
                'average_score': round(stats['avg_score'], 2),
                'highest_score': stats['max_score'],
                'lowest_score': stats['min_score'],
                'average_percentage': round(stats['avg_percentage'], 2),
            },
            'grade_distribution': grade_distribution,
            'score_distribution': score_distribution,
            'question_analysis': question_analysis,
            'top_performers': top_performers_list,
        })
    
    except Exam.DoesNotExist:
        return Response({'error': 'Exam not found'}, status=status.HTTP_404_NOT_FOUND)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def export_exam_results_csv(request, exam_id):
    '''Export exam results to CSV'''
    import csv
    from django.http import HttpResponse
    
    user = request.user
    
    if user.role != 'instructor':
        return Response({'error': 'Only instructors can export results'}, 
                       status=status.HTTP_403_FORBIDDEN)
    
    try:
        exam = Exam.objects.get(id=exam_id, created_by=user)
        results = ExamResult.objects.filter(exam=exam).select_related('student')
        
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename="{exam.title.replace(" ", "_")}_results.csv"'
        
        writer = csv.writer(response)
        writer.writerow(['Student ID', 'Student Name', 'Email', 'Score', 'Total Points', 'Percentage', 'Grade', 'Remarks', 'Submitted At', 'Graded'])
        
        for result in results:
            writer.writerow([
                result.student.school_id,
                result.student.get_full_name() or result.student.username,
                result.student.email,
                result.score,
                result.total_points,
                f"{result.percentage:.2f}%",
                result.grade,
                result.remarks,
                result.submitted_at.strftime('%Y-%m-%d %H:%M:%S'),
                'Yes' if result.is_graded else 'Pending'
            ])
        
        return response
    
    except Exam.DoesNotExist:
        return Response({'error': 'Exam not found'}, status=status.HTTP_404_NOT_FOUND)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_exam_review(request, result_id):
    '''Get exam review with answers for student'''
    user = request.user
    
    if user.role != 'student':
        return Response({'error': 'Only students can access this endpoint'}, 
                       status=status.HTTP_403_FORBIDDEN)
    
    try:
        result = ExamResult.objects.get(id=result_id, student=user)
        exam = result.exam
        
        if not result.is_graded:
            return Response({'error': 'Exam is not yet graded'}, 
                           status=status.HTTP_403_FORBIDDEN)
        
        # Only show the questions the student actually received (their seeded pool)
        try:
            seed_obj = StudentExamSeed.objects.get(exam=exam, student=user)
            id_to_q = {q.id: q for q in exam.questions.all()}
            review_questions = [id_to_q[qid] for qid in seed_obj.question_ids if qid in id_to_q]
        except StudentExamSeed.DoesNotExist:
            review_questions = list(exam.questions.all())

        questions_review = []
        for question in review_questions:
            student_answer = result.answers.get(str(question.id), '')
            is_correct = False
            if question.type in ['multiple_choice', 'identification']:
                is_correct = str(student_answer).strip().lower() == str(question.correct_answer).strip().lower()
            questions_review.append({
                'id': question.id,
                'question': question.question,
                'type': question.type,
                'options': question.options if question.type == 'multiple_choice' else None,
                'student_answer': student_answer,
                'correct_answer': question.correct_answer,
                'is_correct': is_correct,
                'points': question.points,
            })
        
        return Response({
            'exam': {
                'id': exam.id,
                'title': exam.title,
                'subject': exam.subject,
                'total_points': exam.total_points,
            },
            'result': {
                'score': result.score,
                'score_before_penalty': result.score_before_penalty,
                'penalty_percent': result.penalty_percent,
                'total_points': result.total_points,
                'percentage': result.percentage,
                'grade': result.grade,
                'remarks': result.remarks,
                'submitted_at': result.submitted_at.isoformat(),
            },
            'questions': questions_review,
        })
    
    except ExamResult.DoesNotExist:
        return Response({'error': 'Result not found'}, status=status.HTTP_404_NOT_FOUND)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_practice_exams(request):
    '''Get practice exams for students'''
    user = request.user
    
    if user.role != 'student':
        return Response({'error': 'Only students can access practice exams'}, 
                       status=status.HTTP_403_FORBIDDEN)
    
    from django.db.models import Q
    practice_exams = Exam.objects.filter(
        Q(department=user.department) &
        Q(is_practice=True) &
        Q(is_approved=True) &
        (Q(year_level__contains=user.year_level) | Q(year_level='ALL'))
    )
    
    exam_list = []
    for exam in practice_exams:
        access_error = _exam_access_error(user, exam)
        if access_error:
            continue
        exam_list.append({
            'id': exam.id,
            'title': exam.title,
            'subject': exam.subject,
            'department': exam.department,
            'exam_type': exam.exam_type,
            'total_points': exam.total_points,
            'instructions': exam.instructions,
            'question_count': exam.questions.count(),
        })
    
    return Response(exam_list)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def take_practice_exam(request, exam_id):
    '''Get practice exam questions'''
    user = request.user
    
    if user.role != 'student':
        return Response({'error': 'Only students can take practice exams'}, 
                       status=status.HTTP_403_FORBIDDEN)
    
    try:
        exam = Exam.objects.get(id=exam_id, is_practice=True, is_approved=True)
        access_error = _exam_access_error(user, exam)
        if access_error:
            return Response({'error': access_error}, status=status.HTTP_403_FORBIDDEN)
        
        import random
        all_questions = list(exam.questions.all().order_by('order'))
        pool_size = exam.question_pool_size
        if pool_size and 0 < pool_size < len(all_questions):
            selected = random.sample(all_questions, pool_size)
        else:
            selected = all_questions[:]
        random.shuffle(selected)
        def shuffled_opts(q):
            if q.type == 'multiple_choice' and q.options and exam.shuffle_options:
                opts = q.options[:]
                random.shuffle(opts)
                return opts
            return q.options if q.type == 'multiple_choice' else None
        questions_data = [{
            'id': q.id,
            'question': q.question,
            'type': q.type,
            'options': shuffled_opts(q),
            'points': q.points,
        } for q in selected]
        pool_total = sum(q.points for q in selected)
        
        return Response({
            'id': exam.id,
            'title': exam.title,
            'subject': exam.subject,
            'instructions': exam.instructions,
            'total_points': pool_total,
            'questions': questions_data,
        })
    
    except Exam.DoesNotExist:
        return Response({'error': 'Practice exam not found'}, status=status.HTTP_404_NOT_FOUND)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def check_practice_answers(request, exam_id):
    '''Check practice exam answers without saving'''
    user = request.user
    
    if user.role != 'student':
        return Response({'error': 'Only students can check practice answers'}, 
                       status=status.HTTP_403_FORBIDDEN)
    
    try:
        exam = Exam.objects.get(id=exam_id, is_practice=True)
        answers = request.data.get('answers', {})
        return Response(_evaluate_practice_answers(exam, answers))
    except Exam.DoesNotExist:
        return Response({'error': 'Practice exam not found'}, status=status.HTTP_404_NOT_FOUND)


def _evaluate_practice_answers(exam, answers):
    questions = exam.questions.all()
    results = []
    score = 0

    for question in questions:
        student_answer = str(answers.get(str(question.id), '')).strip()
        correct_answer = str(question.correct_answer).strip()
        is_correct = False

        if question.type in ['multiple_choice', 'identification']:
            is_correct = student_answer.lower() == correct_answer.lower()
            if is_correct:
                score += question.points

        results.append({
            'question_id': question.id,
            'question': question.question,
            'type': question.type,
            'options': question.options if question.type == 'multiple_choice' else None,
            'student_answer': student_answer,
            'correct_answer': correct_answer,
            'is_correct': is_correct,
            'points': question.points,
        })

    percentage = (score / exam.total_points * 100) if exam.total_points > 0 else 0

    return {
        'score': score,
        'total_points': exam.total_points,
        'percentage': round(percentage, 2),
        'results': results,
    }


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def submit_practice_exam(request, exam_id):
    '''Check practice exam answers and save result history'''
    user = request.user

    if user.role != 'student':
        return Response({'error': 'Only students can submit practice exams'},
                       status=status.HTTP_403_FORBIDDEN)

    try:
        exam = Exam.objects.get(id=exam_id, is_practice=True)
        answers = request.data.get('answers', {})
        payload = _evaluate_practice_answers(exam, answers)

        PracticeExamResult.objects.create(
            exam=exam,
            student=user,
            score=payload['score'],
            total_points=payload['total_points'],
            percentage=payload['percentage'],
            answers=answers,
            results=payload['results'],
        )

        payload['saved'] = True
        return Response(payload)
    except Exam.DoesNotExist:
        return Response({'error': 'Practice exam not found'}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_practice_results(request):
    '''Get practice exam history for the authenticated student'''
    user = request.user

    if user.role != 'student':
        return Response({'error': 'Only students can access practice results'},
                       status=status.HTTP_403_FORBIDDEN)

    results = PracticeExamResult.objects.filter(student=user).select_related('exam')
    result_list = []
    for result in results:
        result_list.append({
            'id': result.id,
            'exam_id': result.exam.id,
            'exam_title': result.exam.title,
            'exam_subject': result.exam.subject,
            'score': result.score,
            'total_points': result.total_points,
            'percentage': result.percentage,
            'submitted_at': result.submitted_at.isoformat(),
        })

    return Response(result_list)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def capture_exam_photo(request, exam_id):
    '''Capture and save student photo during exam'''
    user = request.user

    role_response = require_role(user, 'student', message='Only students can capture photos')
    if role_response:
        return role_response
    
    try:
        import base64
        from django.core.files.base import ContentFile
        
        exam = Exam.objects.get(id=exam_id)
        _, session_response = _require_active_exam_session(request, exam, user)
        if session_response:
            return session_response
        photo_data = request.data.get('photo')
        capture_type = request.data.get('capture_type', 'periodic')
        violation_reason = request.data.get('violation_reason')

        MAX_PHOTOS_PER_EXAM = 10
        photo_count = ExamPhoto.objects.filter(
            exam=exam,
            student=user,
            photo__isnull=False,
        ).count()

        def build_text_summary(capture_type_value, reason):
            label_map = {
                'start': 'Exam start',
                'periodic': 'Periodic check',
                'violation': 'Violation detected',
                'suspicious': 'Suspicious activity',
            }
            label = label_map.get(capture_type_value, 'Exam activity')
            if capture_type_value == 'start':
                base = f"{label}: student presence recorded."
            elif capture_type_value == 'periodic':
                base = f"{label}: student continuing the exam."
            elif capture_type_value == 'violation':
                base = f"{label}."
            elif capture_type_value == 'suspicious':
                base = f"{label} flagged."
            else:
                base = f"{label} noted."
            if reason:
                base = f"{base} Reason: {reason}."
            else:
                if capture_type_value in ['violation', 'suspicious']:
                    base = f"{base} Reason not specified."
            return base

        if photo_count >= MAX_PHOTOS_PER_EXAM:
            summary = build_text_summary(capture_type, violation_reason)
            ExamPhoto.objects.create(
                exam=exam,
                student=user,
                capture_type=capture_type,
                violation_reason=violation_reason,
                text_summary=summary,
                is_text_only=True,
            )
            return Response({
                'message': 'Photo limit reached. Stored text summary instead.',
                'text_summary': summary,
                'photo_limit_reached': True,
            })
        
        if not photo_data:
            return Response({'error': 'No photo data provided'}, status=status.HTTP_400_BAD_REQUEST)
        
        # Decode base64 image
        format, imgstr = photo_data.split(';base64,')
        ext = format.split('/')[-1]
        if ext not in {'jpeg', 'jpg', 'png', 'webp'}:
            return Response({'error': 'Unsupported image format'}, status=status.HTTP_400_BAD_REQUEST)
        raw_bytes = base64.b64decode(imgstr)
        if len(raw_bytes) > 3 * 1024 * 1024:
            return Response({'error': 'Captured image is too large'}, status=status.HTTP_400_BAD_REQUEST)
        photo_file = ContentFile(raw_bytes, name=f'{user.id}_{exam.id}_{capture_type}_{timezone.now().timestamp()}.{ext}')
        
        # Save photo
        ExamPhoto.objects.create(
            exam=exam,
            student=user,
            photo=photo_file,
            capture_type=capture_type,
            violation_reason=violation_reason,
            text_summary=None,
            is_text_only=False,
        )

        # Cleanup: keep only the most recent periodic photos per student/exam
        try:
            MAX_PERIODIC_PHOTOS = 50
            MAX_PERIODIC_DAYS = 7
            periodic = ExamPhoto.objects.filter(
                exam=exam,
                student=user,
                capture_type='periodic',
                photo__isnull=False,
            ).order_by('-timestamp')
            cutoff = timezone.now() - timedelta(days=MAX_PERIODIC_DAYS)
            old_by_age = periodic.filter(timestamp__lt=cutoff)
            for old in old_by_age:
                try:
                    safe_delete_field(old.photo)
                finally:
                    old.delete()
            for old in periodic[MAX_PERIODIC_PHOTOS:]:
                try:
                    safe_delete_field(old.photo)
                finally:
                    old.delete()
        except Exception:
            # Cleanup failure should not block photo capture
            pass
        
        return Response({'message': 'Photo captured successfully'})
    
    except Exam.DoesNotExist:
        return Response({'error': 'Exam not found'}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_exam_photos(request, exam_id):
    '''Get all photos captured during an exam (for dean/instructor review)'''
    user = request.user
    
    if user.role not in ['dean', 'instructor']:
        return Response({'error': 'Only deans and instructors can access exam photos'}, 
                       status=status.HTTP_403_FORBIDDEN)
    
    try:
        # Dean can view any exam in their department, instructor only their own exams
        if user.role == 'dean':
            exam = Exam.objects.get(id=exam_id, department=user.department)
        else:
            exam = Exam.objects.get(id=exam_id, created_by=user)
        
        student_id = request.GET.get('student_id')
        
        photos = ExamPhoto.objects.filter(exam=exam)
        if student_id:
            photos = photos.filter(student_id=student_id)
        
        photos_data = []
        total_images = 0
        total_text = 0
        for photo in photos:
            if photo.photo:
                total_images += 1
            if photo.is_text_only:
                total_text += 1
            photos_data.append({
                'id': photo.id,
                'student_name': photo.student.get_full_name() or photo.student.username,
                'student_id': photo.student.school_id,
                'student_id_photo': _file_url(request, photo.student.id_photo),
                'student_id_verified': photo.student.id_verified or photo.student.is_approved,
                'photo_url': _file_url(request, photo.photo) if photo.photo else None,
                'capture_type': photo.capture_type,
                'violation_reason': photo.violation_reason,
                'text_summary': photo.text_summary,
                'is_text_only': photo.is_text_only,
                'timestamp': photo.timestamp.isoformat(),
            })
        
        return Response({
            'exam_title': exam.title,
            'photos': photos_data,
            'total_photos': len(photos_data),
            'total_images': total_images,
            'total_text': total_text,
        })
    
    except Exam.DoesNotExist:
        return Response({'error': 'Exam not found'}, status=status.HTTP_404_NOT_FOUND)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def extend_exam_time(request, exam_id):
    '''Grant extra time for a specific student or all students in an exam'''
    user = request.user

    if user.role != 'instructor':
        return Response({'error': 'Only instructors can extend exam time'},
                       status=status.HTTP_403_FORBIDDEN)

    try:
        exam = Exam.objects.get(id=exam_id, created_by=user)

        extra_minutes = int(request.data.get('extra_minutes', 0))
        reason = request.data.get('reason', '')
        student_id = request.data.get('student_id')  # None = bulk (all students)

        if extra_minutes <= 0:
            return Response({'error': 'Extra minutes must be greater than 0'},
                           status=status.HTTP_400_BAD_REQUEST)

        if student_id:
            # Per-student extension
            student = User.objects.get(id=student_id, role='student')
            ExamTimeExtension.objects.create(
                exam=exam,
                student=student,
                extra_minutes=extra_minutes,
                reason=reason,
                granted_by=user,
            )
            Notification.objects.create(
                user=student,
                type='time_extended',
                title='Exam Time Extended',
                message=f'Your time for "{exam.title}" has been extended by {extra_minutes} minute(s). Reason: {reason or "No reason provided."}',
                link=f'/exam/{exam.id}/take',
            )
            send_time_extension_email(student, exam, extra_minutes, reason)
            log_activity(user, 'exam_time_extended', f'Extended time for {student.username} in {exam.title} by {extra_minutes}m', request)
            return Response({'message': f'Time extended by {extra_minutes} minute(s) for {student.get_full_name() or student.username}', 'email_data': [{'to': student.email, 'firstName': student.first_name or 'there', 'examTitle': exam.title, 'examSubject': exam.subject, 'scheduledDate': exam.scheduled_date.strftime('%B %d, %Y %I:%M %p'), 'extraMinutes': extra_minutes, 'reason': reason or 'No reason provided.'}]})

        else:
            # Bulk extension — all eligible students
            students = User.objects.filter(
                department=exam.department,
                role='student',
                is_approved=True,
            )
            if exam.year_level != 'ALL':
                year_levels = exam.year_level.split(',')
                students = students.filter(year_level__in=year_levels)

            extensions = []
            notifications = []
            for student in students:
                extensions.append(ExamTimeExtension(
                    exam=exam,
                    student=student,
                    extra_minutes=extra_minutes,
                    reason=reason,
                    granted_by=user,
                ))
                notifications.append(Notification(
                    user=student,
                    type='time_extended',
                    title='Exam Time Extended',
                    message=f'Your time for "{exam.title}" has been extended by {extra_minutes} minute(s). Reason: {reason or "No reason provided."}',
                    link=f'/exam/{exam.id}/take',
                ))

            ExamTimeExtension.objects.bulk_create(extensions)
            created = Notification.objects.bulk_create(notifications)
            for n in created:
                send_notification(n)
            for student in students:
                send_time_extension_email(student, exam, extra_minutes, reason)
            log_activity(user, 'exam_time_extended_bulk', f'Bulk extended time in {exam.title} by {extra_minutes}m for {len(extensions)} students', request)
            email_data = [{'to': s.email, 'firstName': s.first_name or 'there', 'examTitle': exam.title, 'examSubject': exam.subject, 'scheduledDate': exam.scheduled_date.strftime('%B %d, %Y %I:%M %p'), 'extraMinutes': extra_minutes, 'reason': reason or 'No reason provided.'} for s in students if s.email]
            return Response({'message': f'Time extended by {extra_minutes} minute(s) for {len(extensions)} student(s)', 'email_data': email_data})

    except Exam.DoesNotExist:
        return Response({'error': 'Exam not found'}, status=status.HTTP_404_NOT_FOUND)
    except User.DoesNotExist:
        return Response({'error': 'Student not found'}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_question_bank(request):
    '''Get all questions in the instructor's question bank'''
    user = request.user
    if user.role != 'instructor':
        return Response({'error': 'Only instructors can access the question bank'},
                       status=status.HTTP_403_FORBIDDEN)

    search = request.GET.get('search', '').strip()
    qs = QuestionBank.objects.filter(created_by=user)
    if search:
        qs = qs.filter(
            models.Q(question__icontains=search) |
            models.Q(subject__icontains=search) |
            models.Q(tags__icontains=search)
        )

    return Response([{
        'id': q.id,
        'question': q.question,
        'type': q.type,
        'options': q.options,
        'correct_answer': q.correct_answer,
        'points': q.points,
        'subject': q.subject,
        'tags': q.tags,
        'created_at': q.created_at.isoformat(),
    } for q in qs])


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def save_to_question_bank(request):
    '''Save a question to the instructor's question bank'''
    user = request.user
    if user.role != 'instructor':
        return Response({'error': 'Only instructors can save to the question bank'},
                       status=status.HTTP_403_FORBIDDEN)

    q = QuestionBank.objects.create(
        created_by=user,
        question=request.data.get('question', ''),
        type=request.data.get('type', 'multiple_choice'),
        options=request.data.get('options'),
        correct_answer=request.data.get('correct_answer', ''),
        points=int(request.data.get('points', 1)),
        subject=request.data.get('subject', ''),
        tags=request.data.get('tags', ''),
    )
    return Response({'id': q.id, 'message': 'Question saved to bank'}, status=status.HTTP_201_CREATED)


@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def delete_from_question_bank(request, bank_id):
    '''Delete a question from the instructor's question bank'''
    user = request.user
    if user.role != 'instructor':
        return Response({'error': 'Only instructors can delete from the question bank'},
                       status=status.HTTP_403_FORBIDDEN)
    try:
        q = QuestionBank.objects.get(id=bank_id, created_by=user)
        q.delete()
        return Response({'message': 'Question deleted from bank'})
    except QuestionBank.DoesNotExist:
        return Response({'error': 'Question not found'}, status=status.HTTP_404_NOT_FOUND)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def import_from_question_bank(request, exam_id):
    '''Import selected questions from the bank into an exam'''
    user = request.user
    if user.role != 'instructor':
        return Response({'error': 'Only instructors can import questions'},
                       status=status.HTTP_403_FORBIDDEN)
    try:
        exam = Exam.objects.get(id=exam_id, created_by=user)
        if not _can_modify_exam_questions(user, exam):
            return Response({'error': 'Cannot change exam questions after students have submitted results'},
                           status=status.HTTP_403_FORBIDDEN)

        bank_ids = request.data.get('bank_ids', [])
        if not bank_ids:
            return Response({'error': 'No questions selected'}, status=status.HTTP_400_BAD_REQUEST)

        bank_questions = QuestionBank.objects.filter(id__in=bank_ids, created_by=user)
        current_order = exam.questions.count()

        for bq in bank_questions:
            current_order += 1
            Question.objects.create(
                exam=exam,
                question=bq.question,
                type=bq.type,
                options=bq.options,
                correct_answer=bq.correct_answer,
                points=bq.points,
                order=current_order,
            )

        return Response({'message': f'{bank_questions.count()} question(s) imported into exam'})
    except Exam.DoesNotExist:
        return Response({'error': 'Exam not found'}, status=status.HTTP_404_NOT_FOUND)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_exam_attempts(request, exam_id):
    '''Get attempt information for a student'''
    user = request.user
    if user.role != 'student':
        return Response({'error': 'Only students can access this endpoint'},
                       status=status.HTTP_403_FORBIDDEN)
    try:
        exam = Exam.objects.get(id=exam_id)
        attempts = ExamResult.objects.filter(exam=exam, student=user).order_by('attempt_number')
        
        return Response({
            'max_attempts': exam.max_attempts,
            'retake_policy': exam.retake_policy,
            'attempts_used': attempts.count(),
            'attempts_remaining': max(0, exam.max_attempts - attempts.count()),
            'can_retake': attempts.count() < exam.max_attempts and exam.retake_policy != 'none',
            'attempts': [{
                'attempt_number': a.attempt_number,
                'score': a.score,
                'percentage': a.percentage,
                'grade': a.grade,
                'remarks': a.remarks,
                'submitted_at': a.submitted_at.isoformat(),
                'is_graded': a.is_graded,
            } for a in attempts],
        })
    except Exam.DoesNotExist:
        return Response({'error': 'Exam not found'}, status=status.HTTP_404_NOT_FOUND)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def check_exam_conflicts(request):
    '''Return IDs of exams that have scheduling conflicts for the current student'''
    user = request.user

    if user.role != 'student':
        return Response({'error': 'Only students can access this endpoint'},
                       status=status.HTTP_403_FORBIDDEN)

    from django.db.models import Q
    from datetime import timedelta

    exams = Exam.objects.filter(
        Q(department=user.department) &
        Q(is_approved=True) &
        Q(is_practice=False) &
        (Q(year_level__contains=user.year_level) | Q(year_level='ALL'))
    ).exclude(
        id__in=ExamResult.objects.filter(student=user).values_list('exam_id', flat=True)
    )

    # Only check upcoming/ongoing exams
    active = [e for e in exams if e.get_status() in ('upcoming', 'ongoing')]

    conflict_ids = set()
    for i, a in enumerate(active):
        a_start = a.scheduled_date
        a_end = a_start + timedelta(minutes=a.duration_minutes)
        for b in active[i + 1:]:
            b_start = b.scheduled_date
            b_end = b_start + timedelta(minutes=b.duration_minutes)
            # Overlap: a starts before b ends AND b starts before a ends
            if a_start < b_end and b_start < a_end:
                conflict_ids.add(a.id)
                conflict_ids.add(b.id)

    return Response({'conflict_ids': list(conflict_ids)})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def start_exam_session(request, exam_id):
    '''Create an active session when student starts the exam'''
    user = request.user
    role_response = require_role(user, 'student', message='Only students can start exam sessions')
    if role_response:
        return role_response
    try:
        from datetime import timedelta
        from django.utils import timezone as tz
        exam = Exam.objects.get(id=exam_id)
        access_error = _exam_access_error(user, exam)
        if access_error:
            return Response({'error': access_error}, status=status.HTTP_403_FORBIDDEN)
        existing = ExamSession.objects.filter(exam=exam, student=user, is_active=True).first()
        if existing:
            supplied_session_token = _extract_exam_session_token(request)
            stale_threshold = tz.now() - timedelta(seconds=90)
            if supplied_session_token and supplied_session_token == existing.session_token:
                existing.last_heartbeat = tz.now()
                existing.save(update_fields=['last_heartbeat'])
                return Response({'session_token': existing.session_token})
            if existing.last_heartbeat > stale_threshold:
                return Response(
                    {'error': 'You already have an active exam session on another device. Please finish or close that session first.'},
                    status=status.HTTP_403_FORBIDDEN
                )
            # Stale session — clear it and allow
            existing.delete()
        # Also clear any inactive/leftover sessions
        ExamSession.objects.filter(exam=exam, student=user).delete()
        session = ExamSession.objects.create(exam=exam, student=user)
        log_activity(
            user,
            'exam_started',
            f'Started exam: {exam.title}',
            request,
            {'exam_id': exam.id, 'student_id': user.id}
        )
        return Response({'session_token': session.session_token})
    except Exam.DoesNotExist:
        return Response({'error': 'Exam not found'}, status=status.HTTP_404_NOT_FOUND)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def heartbeat_exam_session(request, exam_id):
    '''Keep session alive with periodic heartbeat'''
    user = request.user
    try:
        from django.utils import timezone as tz
        exam = Exam.objects.get(id=exam_id)
        session, session_response = _require_active_exam_session(request, exam, user)
        if session_response:
            return session_response
        session.last_heartbeat = tz.now()
        session.save(update_fields=['last_heartbeat'])
        return Response({'status': 'ok'})
    except Exam.DoesNotExist:
        return Response({'error': 'Exam not found'}, status=status.HTTP_404_NOT_FOUND)
    except ExamSession.DoesNotExist:
        return Response({'error': 'No active session'}, status=status.HTTP_404_NOT_FOUND)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def end_exam_session(request, exam_id):
    '''End the active session when exam is submitted or terminated'''
    user = request.user
    try:
        exam = Exam.objects.get(id=exam_id)
    except Exam.DoesNotExist:
        return Response({'error': 'Exam not found'}, status=status.HTTP_404_NOT_FOUND)
    session, session_response = _require_active_exam_session(request, exam, user)
    if session_response:
        return session_response
    session.delete()
    return Response({'status': 'session ended'})


@api_view(['POST'])
@permission_classes([AllowAny])
def end_exam_session_beacon(request, exam_id):
    '''End session via sendBeacon (no auth header, token in body)'''
    from rest_framework_simplejwt.tokens import AccessToken
    from rest_framework_simplejwt.exceptions import TokenError
    try:
        import json
        body = json.loads(request.body)
        token_str = body.get('token')
        session_token = str(body.get('session_token', '')).strip()
        token = AccessToken(token_str)
        user = User.objects.get(id=token['user_id'])
        session_qs = ExamSession.objects.filter(exam_id=exam_id, student=user)
        if session_token:
            session_qs = session_qs.filter(session_token=session_token)
        session_qs.delete()
    except Exception:
        pass
    return Response({'status': 'ok'})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_my_time_extensions(request, exam_id):
    '''Get time extensions granted to the current student for an exam'''
    user = request.user

    if user.role != 'student':
        return Response({'error': 'Only students can access this endpoint'},
                       status=status.HTTP_403_FORBIDDEN)

    try:
        exam = Exam.objects.get(id=exam_id)
        extensions = ExamTimeExtension.objects.filter(exam=exam, student=user)
        total_extra = sum(e.extra_minutes for e in extensions)
        return Response({
            'total_extra_minutes': total_extra,
            'extensions': [{'extra_minutes': e.extra_minutes, 'reason': e.reason, 'granted_at': e.created_at.isoformat()} for e in extensions],
        })
    except Exam.DoesNotExist:
        return Response({'error': 'Exam not found'}, status=status.HTTP_404_NOT_FOUND)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_instructor_monitoring(request):
    '''Instructor/dean monitoring: active sessions + latest terminations + activity logs'''
    user = request.user
    if user.role not in ['instructor', 'dean']:
        return Response({'error': 'Only instructors or deans can access this endpoint'}, status=status.HTTP_403_FORBIDDEN)

    if user.role == 'dean':
        exams = Exam.objects.filter(department=user.department)
    else:
        exams = Exam.objects.filter(created_by=user, is_draft=False)

    exam_ids = list(exams.values_list('id', flat=True))
    if not exam_ids:
        return Response({'active_sessions': [], 'latest_terminations': [], 'activity_logs': [], 'today_schedule': []})

    from django.utils import timezone as tz
    now = tz.now()
    today_schedule = []
    if user.role == 'dean':
        from datetime import datetime
        today = datetime.now().date()
        today_exams = exams.filter(scheduled_date__date=today).select_related('created_by').order_by('scheduled_date')[:100]
        for exam in today_exams:
            instructor = exam.created_by
            full_name = f"{instructor.first_name} {instructor.last_name}".strip()
            today_schedule.append({
                'exam_id': exam.id,
                'exam_title': exam.title,
                'subject': exam.subject,
                'year_level': exam.year_level,
                'scheduled_date': exam.scheduled_date.isoformat(),
                'instructor_id': instructor.id,
                'instructor_name': full_name if full_name else instructor.username,
            })

    active_sessions = ExamSession.objects.filter(
        exam_id__in=exam_ids,
        is_active=True
    ).select_related('exam', 'student').order_by('-last_heartbeat')[:200]

    session_list = [{
        'exam_id': s.exam_id,
        'exam_title': s.exam.title,
        'student_id': s.student_id,
        'student_username': s.student.username,
        'started_at': s.started_at.isoformat(),
        'last_heartbeat': s.last_heartbeat.isoformat(),
        'seconds_since_heartbeat': int((now - s.last_heartbeat).total_seconds()),
    } for s in active_sessions]

    latest_terminations = AuditLog.objects.filter(
        action='exam_terminated',
        metadata__exam_id__in=exam_ids
    ).order_by('-timestamp')[:50]

    termination_student_ids = list({
        log.metadata.get('student_id')
        for log in latest_terminations
        if log.metadata.get('student_id') is not None
    })
    student_name_map = {}
    if termination_student_ids:
        students = User.objects.filter(id__in=termination_student_ids).only('id', 'first_name', 'last_name', 'username')
        for s in students:
            full = f"{s.first_name} {s.last_name}".strip()
            student_name_map[s.id] = full if full else s.username

    termination_list = [{
        'id': log.id,
        'exam_id': log.metadata.get('exam_id'),
        'student_id': log.metadata.get('student_id'),
        'student_name': student_name_map.get(log.metadata.get('student_id'), 'Unknown Student'),
        'termination_count': log.metadata.get('termination_count'),
        'description': log.description,
        'timestamp': log.timestamp.isoformat(),
    } for log in latest_terminations]

    activity_logs = AuditLog.objects.filter(
        metadata__exam_id__in=exam_ids
    ).order_by('-timestamp')[:100]

    activity_list = [{
        'id': log.id,
        'action': log.action,
        'description': log.description,
        'exam_id': log.metadata.get('exam_id'),
        'student_id': log.metadata.get('student_id'),
        'timestamp': log.timestamp.isoformat(),
    } for log in activity_logs]

    return Response({
        'active_sessions': session_list,
        'latest_terminations': termination_list,
        'activity_logs': activity_list,
        'today_schedule': today_schedule,
    })



@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_draft_exams(request):
    '''Return all draft (incomplete) exams created by the requesting instructor or dean.'''
    user = request.user
    if user.role not in ('instructor', 'dean'):
        return Response({'error': 'Only instructors or deans can access drafts'}, status=status.HTTP_403_FORBIDDEN)
    drafts = Exam.objects.filter(created_by=user, is_draft=True).order_by('-created_at')
    return Response([{
        'id': d.id,
        'title': d.title,
        'subject': d.subject,
        'exam_type': d.exam_type,
        'question_type': d.question_type,
        'scheduled_date': d.scheduled_date.isoformat(),
        'total_points': d.total_points,
        'created_at': d.created_at.isoformat(),
    } for d in drafts])


@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def discard_draft_exam(request, exam_id):
    '''Delete a draft exam that was never completed with questions.'''
    user = request.user
    if user.role not in ('instructor', 'dean'):
        return Response({'error': 'Only instructors or deans can discard exams'}, status=status.HTTP_403_FORBIDDEN)
    try:
        exam = Exam.objects.get(id=exam_id, created_by=user, is_draft=True)
        exam.delete()
        return Response({'message': 'Draft exam discarded'}, status=status.HTTP_204_NO_CONTENT)
    except Exam.DoesNotExist:
        return Response({'error': 'Draft exam not found'}, status=status.HTTP_404_NOT_FOUND)
