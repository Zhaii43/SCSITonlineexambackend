from django.contrib import admin
from .models import Notification, Announcement

@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ['user', 'title', 'type', 'is_read', 'created_at']
    list_filter = ['type', 'is_read', 'created_at']
    search_fields = ['user__username', 'title', 'message']


@admin.register(Announcement)
class AnnouncementAdmin(admin.ModelAdmin):
    list_display = ['title', 'target_audience', 'department', 'created_by', 'is_active', 'created_at']
    list_filter = ['target_audience', 'is_active', 'department', 'created_at']
    search_fields = ['title', 'message', 'created_by__username']
    readonly_fields = ['created_at', 'updated_at']
    list_editable = ['is_active']
