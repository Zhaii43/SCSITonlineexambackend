from django.db.models.signals import pre_save, post_save
from django.dispatch import receiver

from notifications.email_utils import send_staff_approval_email
from .models import User


@receiver(pre_save, sender=User)
def _capture_previous_approval_state(sender, instance, **kwargs):
    if instance.pk:
        instance._pre_is_approved = (
            User.objects.filter(pk=instance.pk)
            .values_list('is_approved', flat=True)
            .first()
        )
    else:
        instance._pre_is_approved = None


@receiver(post_save, sender=User)
def _send_staff_approval_email(sender, instance, created, **kwargs):
    if instance.role not in ['instructor', 'dean']:
        return
    if not instance.is_approved:
        return

    previously_approved = getattr(instance, '_pre_is_approved', None)
    if created or previously_approved is False:
        send_staff_approval_email(instance)
