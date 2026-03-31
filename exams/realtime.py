from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer


def send_exam_update(group, action, exam_id=None, extra=None):
    channel_layer = get_channel_layer()
    if not channel_layer:
        return

    payload = {
        "type": "exam_update",
        "action": action,
    }
    if exam_id is not None:
        payload["exam_id"] = exam_id
    if extra:
        payload.update(extra)

    async_to_sync(channel_layer.group_send)(
        group,
        {"type": "notify", "payload": payload},
    )
