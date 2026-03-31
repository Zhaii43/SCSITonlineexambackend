from django.urls import path
from .views import get_audit_logs, export_audit_logs, get_audit_count

urlpatterns = [
    path('', get_audit_logs, name='get_audit_logs'),
    path('count/', get_audit_count, name='get_audit_count'),
    path('export/', export_audit_logs, name='export_audit_logs'),
]
