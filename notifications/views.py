from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from rest_framework import status
from .models import Notification, Announcement
from .email_utils import send_announcement_email, _build_announcement_message
from .realtime import send_notification
from user.models import User


def _get_announcement_recipients(target_audience, department=None, year_level=None):
    from django.db.models import Q
    qs = User.objects.filter(is_active=True).filter(
        Q(is_approved=True) | Q(role__in=['instructor', 'dean'])
    )
    if target_audience != 'all':
        qs = qs.filter(role=target_audience)
    if department:
        qs = qs.filter(department=department)
    if year_level and target_audience in ['student', 'all']:
        qs = qs.filter(Q(role='student', year_level=year_level) | ~Q(role='student'))
    return qs.exclude(email='').filter(email__isnull=False)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_notifications(request):
    '''Get all notifications for authenticated user'''
    notifications = Notification.objects.filter(user=request.user)[:20]
    
    notification_list = [{
        'id': n.id,
        'type': n.type,
        'title': n.title,
        'message': n.message,
        'link': n.link,
        'is_read': n.is_read,
        'created_at': n.created_at.isoformat(),
    } for n in notifications]
    
    unread_count = Notification.objects.filter(user=request.user, is_read=False).count()
    
    return Response({
        'notifications': notification_list,
        'unread_count': unread_count,
    })

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def mark_as_read(request, notification_id):
    '''Mark a notification as read'''
    try:
        notification = Notification.objects.get(id=notification_id, user=request.user)
        notification.is_read = True
        notification.save()
        return Response({'message': 'Notification marked as read'})
    except Notification.DoesNotExist:
        return Response({'error': 'Notification not found'}, status=status.HTTP_404_NOT_FOUND)

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def mark_all_as_read(request):
    '''Mark all notifications as read'''
    Notification.objects.filter(user=request.user, is_read=False).update(is_read=True)
    return Response({'message': 'All notifications marked as read'})

@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def clear_all_notifications(request):
    '''Delete all notifications for the user'''
    count = Notification.objects.filter(user=request.user).count()
    Notification.objects.filter(user=request.user).delete()
    return Response({'message': f'{count} notification(s) cleared'})


# ── Announcements ──────────────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_announcements(request):
    '''Get active announcements visible to the current user'''
    user = request.user
    qs = Announcement.objects.filter(
        is_active=True,
        target_audience__in=['all', user.role],
    )

    from django.db.models import Q
    qs = qs.filter(
        Q(department=user.department) | Q(department__isnull=True) | Q(department='')
    )
    # Filter by year_level: only hide if announcement targets a specific year and user is a student with a different year
    if user.role == 'student':
        qs = qs.filter(
            Q(year_level__isnull=True) | Q(year_level='') | Q(year_level=user.year_level)
        )
    qs = qs.order_by('-created_at')[:50]

    data = [{
        'id': a.id,
        'title': a.title,
        'message': a.message,
        'target_audience': a.target_audience,
        'department': a.department,
        'year_level': a.year_level,
        'created_by': f"{a.created_by.first_name} {a.created_by.last_name}".strip() or a.created_by.username,
        'created_by_role': a.created_by.role,
        'created_at': a.created_at.isoformat(),
    } for a in qs]

    return Response({'announcements': data})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def create_announcement(request):
    '''Dean or instructor creates a new announcement'''
    if request.user.role not in ['dean', 'instructor']:
        return Response({'error': 'Only deans and instructors can create announcements'}, status=status.HTTP_403_FORBIDDEN)

    title = request.data.get('title', '').strip()
    message = request.data.get('message', '').strip()

    if not title or not message:
        return Response({'error': 'Title and message are required'}, status=status.HTTP_400_BAD_REQUEST)

    # Instructor-specific subject-based targeting
    if request.user.role == 'instructor':
        from user.models import SubjectAssignment
        apply_to_all_raw = request.data.get('apply_to_all', False)
        if isinstance(apply_to_all_raw, str):
            apply_to_all = apply_to_all_raw.strip().lower() in ['1', 'true', 'yes', 'on']
        else:
            apply_to_all = bool(apply_to_all_raw)

        subject_name_raw = request.data.get('subject_name', '')
        if isinstance(subject_name_raw, str):
            subject_name = subject_name_raw.strip() or None
        else:
            subject_name = None

        if apply_to_all:
            subject_name = None
            active_assignments = SubjectAssignment.objects.filter(instructor=request.user, is_active=True)
            subject_names = list(active_assignments.values_list('subject_name', flat=True))
        elif subject_name:
            subject_names = [subject_name]
        else:
            return Response({'error': 'Select a subject or apply to all subjects.'}, status=status.HTTP_400_BAD_REQUEST)

        # Target students enrolled in those subjects
        from django.db.models import Q
        if subject_names:
            recipients_qs = User.objects.filter(is_active=True, is_approved=True, role='student')
            subject_filter = Q()
            for sn in subject_names:
                subject_filter |= Q(enrolled_subjects__contains=[sn])
            recipients_qs = recipients_qs.filter(subject_filter)
        else:
            recipients_qs = User.objects.filter(is_active=True, is_approved=True, role='student')

        announcement = Announcement.objects.create(
            title=title,
            message=message,
            target_audience='student',
            department=None,
            year_level=None,
            subject_name=subject_name,
            created_by=request.user,
        )
        recipients = list(recipients_qs.exclude(email='').filter(email__isnull=False))
    else:
        # Dean flow: always announce to everyone within the dean's own department.
        target_audience = 'all'
        department = (request.user.department or '').strip() or None
        year_level_raw = request.data.get('year_level', '')
        year_level = year_level_raw.strip() if isinstance(year_level_raw, str) else None
        year_level = year_level or None

        if not department:
            return Response({'error': 'Dean account has no department assigned.'}, status=status.HTTP_400_BAD_REQUEST)
        if year_level and year_level not in ['1', '2', '3', '4']:
            return Response({'error': 'Invalid year level'}, status=status.HTTP_400_BAD_REQUEST)

        announcement = Announcement.objects.create(
            title=title,
            message=message,
            target_audience=target_audience,
            department=department,
            year_level=year_level,
            subject_name=None,
            created_by=request.user,
        )
        recipients = list(_get_announcement_recipients(target_audience, department, year_level))

    created_by_name = f"{request.user.first_name} {request.user.last_name}".strip() or request.user.username

    # Build all messages then send in one SMTP session
    from .email_utils import send_bulk_emails
    messages = []
    for recipient in recipients:
        try:
            msg = _build_announcement_message(recipient, announcement, created_by_name)
            if msg:
                messages.append(msg)
        except Exception:
            pass
    if messages:
        import threading
        threading.Thread(target=send_bulk_emails, args=(messages,), daemon=False).start()

    link = '/dashboard/student' if announcement.target_audience in ['all', 'student'] else '/dashboard'
    notifications = Notification.objects.bulk_create([
        Notification(
            user=user,
            type='announcement',
            title=announcement.title,
            message=announcement.message,
            link=link,
        )
        for user in recipients
    ])
    for notification in notifications:
        send_notification(notification)

    return Response({
        'id': announcement.id,
        'title': announcement.title,
        'message': announcement.message,
        'target_audience': announcement.target_audience,
        'subject_name': announcement.subject_name,
        'created_at': announcement.created_at.isoformat(),
    }, status=status.HTTP_201_CREATED)


@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def delete_announcement(request, announcement_id):
    '''Dean or instructor deletes their own announcement'''
    if request.user.role not in ['dean', 'instructor']:
        return Response({'error': 'Only deans and instructors can delete announcements'}, status=status.HTTP_403_FORBIDDEN)

    try:
        announcement = Announcement.objects.get(id=announcement_id, created_by=request.user)
        announcement.delete()
        return Response({'message': 'Announcement deleted'})
    except Announcement.DoesNotExist:
        return Response({'error': 'Announcement not found'}, status=status.HTTP_404_NOT_FOUND)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_my_announcements(request):
    '''Dean or instructor gets their own announcements to manage'''
    if request.user.role not in ['dean', 'instructor']:
        return Response({'error': 'Forbidden'}, status=status.HTTP_403_FORBIDDEN)

    announcements = Announcement.objects.filter(created_by=request.user).order_by('-created_at')

    from user.models import SubjectAssignment

    # For instructor announcements, resolve subject_names from assignment or stored subject_name
    def _resolve_subject_names(a):
        if a.created_by.role != 'instructor':
            return []
        if a.subject_name:
            return [a.subject_name]
        # apply_to_all — return all active subjects at time of query
        return list(SubjectAssignment.objects.filter(instructor=a.created_by, is_active=True).values_list('subject_name', flat=True))

    data = [{
        'id': a.id,
        'title': a.title,
        'message': a.message,
        'target_audience': a.target_audience,
        'department': a.department,
        'year_level': a.year_level,
        'subject_names': _resolve_subject_names(a),
        'is_active': a.is_active,
        'created_at': a.created_at.isoformat(),
    } for a in announcements]

    return Response({'announcements': data})


@api_view(['POST'])
@permission_classes([AllowAny])
def test_email_bridge(request):
    """Diagnostic — sends a real test email through the bridge. POST {"to": "you@example.com"}"""
    import requests as req
    from django.conf import settings as s
    to = request.data.get('to', '').strip()
    if not to:
        return Response({'error': 'to is required'}, status=400)
    secret = getattr(s, 'EMAIL_BRIDGE_SECRET', '')
    frontend_url = getattr(s, 'FRONTEND_URL', '').rstrip('/')
    bridge_url = f"{frontend_url}/api/email-bridge"
    if not secret:
        return Response({'error': 'EMAIL_BRIDGE_SECRET not set on Django side', 'bridge_url': bridge_url})
    try:
        resp = req.post(
            bridge_url,
            json={"emailType": "student_approval", "to": to, "firstName": "Test", "frontendUrl": frontend_url},
            headers={"x-email-bridge-secret": secret, "Content-Type": "application/json"},
            timeout=20,
        )
        return Response({
            'bridge_url': bridge_url,
            'secret_length': len(secret),
            'status_code': resp.status_code,
            'response': resp.text[:500],
        })
    except Exception as exc:
        return Response({'bridge_url': bridge_url, 'error': str(exc)}, status=500)

