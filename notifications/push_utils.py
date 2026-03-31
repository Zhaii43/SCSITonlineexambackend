import requests


EXPO_PUSH_URL = 'https://exp.host/--/api/v2/push/send'


def send_push_notification(expo_push_token, title, body, data=None):
    """Send a push notification via Expo Push API"""
    if not expo_push_token or not expo_push_token.startswith('ExponentPushToken['):
        return False

    payload = {
        'to': expo_push_token,
        'title': title,
        'body': body,
        'sound': 'default',
        'data': data or {},
    }

    try:
        res = requests.post(
            EXPO_PUSH_URL,
            json=payload,
            headers={'Content-Type': 'application/json'},
            timeout=10,
        )
        return res.status_code == 200
    except Exception as e:
        print(f'Push notification failed: {e}')
        return False


def send_push_to_users(users, title, body, data=None):
    """Send push notification to a list of users"""
    for user in users:
        if user.expo_push_token:
            send_push_notification(user.expo_push_token, title, body, data)
