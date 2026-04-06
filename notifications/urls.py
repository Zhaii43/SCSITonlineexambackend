from django.urls import path
from .views import (
    get_notifications, mark_as_read, mark_all_as_read, clear_all_notifications,
    get_announcements, create_announcement, delete_announcement, get_my_announcements,
    test_email_bridge,
)

urlpatterns = [
    path('', get_notifications, name='get_notifications'),
    path('<int:notification_id>/read/', mark_as_read, name='mark_as_read'),
    path('mark-all-read/', mark_all_as_read, name='mark_all_as_read'),
    path('clear-all/', clear_all_notifications, name='clear_all_notifications'),
    # Announcements
    path('announcements/', get_announcements, name='get_announcements'),
    path('announcements/create/', create_announcement, name='create_announcement'),
    path('announcements/mine/', get_my_announcements, name='get_my_announcements'),
    path('announcements/<int:announcement_id>/delete/', delete_announcement, name='delete_announcement'),
    # Diagnostics
    path('test-email-bridge/', test_email_bridge, name='test_email_bridge'),
]
