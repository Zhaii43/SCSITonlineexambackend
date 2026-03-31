from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Notification
from .realtime import send_notification


@receiver(post_save, sender=Notification)
def push_notification_realtime(sender, instance, created, **kwargs):
    if created:
        send_notification(instance)
