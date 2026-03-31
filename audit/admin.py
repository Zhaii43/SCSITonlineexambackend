from django.contrib import admin
from .models import AuditLog

@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ['get_username', 'action', 'description', 'timestamp', 'ip_address']
    list_filter = ['timestamp']
    search_fields = ['user__username', 'description', 'action']
    readonly_fields = ['user', 'action', 'description', 'ip_address', 'user_agent', 'metadata', 'timestamp']
    list_per_page = 25
    show_full_result_count = False

    @admin.display(description='User')
    def get_username(self, obj):
        if obj.user:
            return obj.user.username
        return '(deleted)'

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser
