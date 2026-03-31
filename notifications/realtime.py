from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.utils import timezone

from .models import Notification


def build_notification_payload(notification):
    return {
        "type": "notification",
        "notification": {
            "id": notification.id,
            "type": notification.type,
            "title": notification.title,
            "message": notification.message,
            "link": notification.link,
            "is_read": notification.is_read,
            "created_at": notification.created_at.isoformat() if notification.created_at else timezone.now().isoformat(),
        },
        "unread_count": Notification.objects.filter(user=notification.user, is_read=False).count(),
    }


def send_notification(notification):
    channel_layer = get_channel_layer()
    if not channel_layer:
        return

    payload = build_notification_payload(notification)
    async_to_sync(channel_layer.group_send)(
        f"user_{notification.user_id}",
        {"type": "notify", "payload": payload},
    )
