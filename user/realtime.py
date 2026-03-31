from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer


def _send_dean_event(department, payload):
    channel_layer = get_channel_layer()
    if not channel_layer or not department:
        return

    async_to_sync(channel_layer.group_send)(
        f"exams_dean_{department}",
        {"type": "notify", "payload": payload},
    )


def send_enrollment_records_update(department, action, extra=None):
    payload = {
        "type": "enrollment_records_update",
        "action": action,
        "department": department,
    }
    if extra:
        payload.update(extra)

    _send_dean_event(department, payload)


def send_student_verification_update(department, action, student_id=None, extra=None):
    payload = {
        "type": "student_verification_update",
        "action": action,
        "department": department,
    }
    if student_id is not None:
        payload["student_id"] = student_id
    if extra:
        payload.update(extra)

    _send_dean_event(department, payload)
