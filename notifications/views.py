from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from rest_framework import status
from .models import Notification, Announcement
from .email_utils import send_announcement_email
from .realtime import send_notification
from user.models import User


def _get_announcement_recipients(target_audience, department=None):
    recipients = User.objects.filter(is_approved=True, is_active=True)
    if target_audience != 'all':
        recipients = recipients.filter(role=target_audience)
    if department:
        recipients = recipients.filter(department=department)
    return recipients

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

    # Filter by department (show dept-specific + global ones)
    from django.db.models import Q
    qs = qs.filter(
        Q(department=user.department) | Q(department__isnull=True) | Q(department='')
    ).order_by('-created_at')[:50]

    data = [{
        'id': a.id,
        'title': a.title,
        'message': a.message,
        'target_audience': a.target_audience,
        'department': a.department,
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
    target_audience = request.data.get('target_audience', 'all')
    department = request.data.get('department', '').strip() or None

    if not title or not message:
        return Response({'error': 'Title and message are required'}, status=status.HTTP_400_BAD_REQUEST)

    if target_audience not in ['all', 'student', 'instructor']:
        return Response({'error': 'Invalid target audience'}, status=status.HTTP_400_BAD_REQUEST)

    announcement = Announcement.objects.create(
        title=title,
        message=message,
        target_audience=target_audience,
        department=department,
        created_by=request.user,
    )

    created_by_name = f"{request.user.first_name} {request.user.last_name}".strip() or request.user.username
    recipients = list(_get_announcement_recipients(target_audience, department))
    for user in recipients:
        send_announcement_email(user, announcement, created_by_name)

    link = '/dashboard/student' if target_audience in ['all', 'student'] else '/dashboard'
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
        'department': announcement.department,
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

    data = [{
        'id': a.id,
        'title': a.title,
        'message': a.message,
        'target_audience': a.target_audience,
        'department': a.department,
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
