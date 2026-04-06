from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
from django.http import HttpResponse
from .models import AuditLog
from exams.models import Exam
import csv

def get_client_ip(request):
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0]
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip

def log_activity(user, action, description, request=None, metadata=None):
    ip_address = get_client_ip(request) if request else None
    user_agent = request.META.get('HTTP_USER_AGENT', '') if request else ''
    
    AuditLog.objects.create(
        user=user,
        action=action,
        description=description,
        ip_address=ip_address,
        user_agent=user_agent,
        metadata=metadata or {}
    )

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_audit_logs(request):
    user = request.user
    
    if user.role == 'dean':
        logs = AuditLog.objects.filter(user__department=user.department)[:100]
    elif user.role == 'instructor':
        exam_ids = Exam.objects.filter(created_by=user).values_list('id', flat=True)
        logs = AuditLog.objects.filter(metadata__exam_id__in=list(exam_ids))[:100]
    else:
        logs = AuditLog.objects.filter(user=user)[:50]
    
    logs_list = [{
        'id': log.id,
        'user': log.user.username,
        'action': log.action,
        'description': log.description,
        'ip_address': log.ip_address,
        'timestamp': log.timestamp.isoformat(),
    } for log in logs]
    
    return Response({'logs': logs_list})

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_audit_count(request):
    user = request.user

    if user.role == 'dean':
        count = AuditLog.objects.filter(user__department=user.department).count()
    elif user.role == 'instructor':
        exam_ids = Exam.objects.filter(created_by=user).values_list('id', flat=True)
        count = AuditLog.objects.filter(metadata__exam_id__in=list(exam_ids)).count()
    else:
        count = AuditLog.objects.filter(user=user).count()

    return Response({'count': count})

@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def delete_audit_log(request, pk):
    user = request.user
    if user.role != 'dean':
        return Response({'error': 'Only deans can delete audit logs'}, status=status.HTTP_403_FORBIDDEN)
    try:
        log = AuditLog.objects.get(pk=pk, user__department=user.department)
        log.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
    except AuditLog.DoesNotExist:
        return Response({'error': 'Not found'}, status=status.HTTP_404_NOT_FOUND)


@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def bulk_delete_audit_logs(request):
    user = request.user
    if user.role != 'dean':
        return Response({'error': 'Only deans can delete audit logs'}, status=status.HTTP_403_FORBIDDEN)
    ids = request.data.get('ids')  # list of ids, or None to delete all
    qs = AuditLog.objects.filter(user__department=user.department)
    if ids is not None:
        qs = qs.filter(pk__in=ids)
    deleted, _ = qs.delete()
    return Response({'deleted': deleted})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def export_audit_logs(request):
    user = request.user
    
    if user.role != 'dean':
        return Response({'error': 'Only deans can export audit logs'}, status=status.HTTP_403_FORBIDDEN)
    
    logs = AuditLog.objects.filter(user__department=user.department)
    
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="audit_logs.csv"'
    
    writer = csv.writer(response)
    writer.writerow(['Timestamp', 'User', 'Action', 'Description', 'IP Address'])
    
    for log in logs:
        writer.writerow([
            log.timestamp.strftime('%Y-%m-%d %H:%M:%S'),
            log.user.username,
            log.get_action_display(),
            log.description,
            log.ip_address or 'N/A',
        ])
    
    return response
