from django.urls import path
from .views import get_audit_logs, export_audit_logs, get_audit_count, delete_audit_log, bulk_delete_audit_logs

urlpatterns = [
    path('', get_audit_logs, name='get_audit_logs'),
    path('count/', get_audit_count, name='get_audit_count'),
    path('export/', export_audit_logs, name='export_audit_logs'),
    path('<int:pk>/delete/', delete_audit_log, name='delete_audit_log'),
    path('bulk-delete/', bulk_delete_audit_logs, name='bulk_delete_audit_logs'),
]
