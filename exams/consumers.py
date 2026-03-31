from urllib.parse import parse_qs

from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.contrib.auth import get_user_model
from rest_framework_simplejwt.tokens import AccessToken
from rest_framework_simplejwt.exceptions import TokenError


class ExamUpdatesConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        token = self._get_token()
        if not token:
            await self.close()
            return

        user = await self._get_user_from_token(token)
        if not user:
            await self.close()
            return

        self.user = user
        self.groups_to_join = [f"exams_user_{user.id}"]

        if user.role == "dean" and user.department:
            self.groups_to_join.append(f"exams_dean_{user.department}")
        if user.role == "student" and user.department:
            self.groups_to_join.append(f"exams_students_{user.department}")

        for group in self.groups_to_join:
            await self.channel_layer.group_add(group, self.channel_name)

        await self.accept()
        await self.send_json({"type": "connected"})

    async def disconnect(self, close_code):
        if hasattr(self, "groups_to_join"):
            for group in self.groups_to_join:
                await self.channel_layer.group_discard(group, self.channel_name)

    async def notify(self, event):
        await self.send_json(event.get("payload", {}))

    def _get_token(self):
        qs = parse_qs(self.scope.get("query_string", b"").decode())
        token_list = qs.get("token", [])
        return token_list[0] if token_list else None

    async def _get_user_from_token(self, token):
        try:
            access = AccessToken(token)
            user_id = access.get("user_id")
            if not user_id:
                return None
            User = get_user_model()
            return await User.objects.filter(id=user_id).afirst()
        except TokenError:
            return None
