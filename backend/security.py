import hashlib
import os
from pathlib import Path

from django.core.cache import cache
from django.utils.text import get_valid_filename
from rest_framework import status
from rest_framework.response import Response


def get_client_ip(request):
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        return x_forwarded_for.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR', '')


def require_role(user, *roles, message=None):
    if getattr(user, 'role', None) in roles:
        return None
    allowed = ', '.join(roles)
    return Response(
        {'error': message or f'Access restricted to: {allowed}'},
        status=status.HTTP_403_FORBIDDEN,
    )


def throttle_request(request, scope, limit, window_seconds, identifiers=None, message=None):
    values = [get_client_ip(request) or 'unknown-ip']
    for identifier in identifiers or []:
        normalized = str(identifier or '').strip().lower()
        if normalized:
            values.append(normalized)

    for raw_value in values:
        hashed = hashlib.sha256(raw_value.encode('utf-8')).hexdigest()[:24]
        cache_key = f'security:{scope}:{hashed}'
        if cache.add(cache_key, 1, timeout=window_seconds):
            current = 1
        else:
            try:
                current = cache.incr(cache_key)
            except ValueError:
                cache.set(cache_key, 1, timeout=window_seconds)
                current = 1

        if current > limit:
            response = Response(
                {
                    'error': message or 'Too many requests. Please try again later.',
                    'retry_after': window_seconds,
                },
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )
            response['Retry-After'] = str(window_seconds)
            return response

    return None


def validate_uploaded_file(
    upload,
    *,
    allowed_extensions,
    allowed_content_types=None,
    max_size_bytes,
):
    if not upload:
        return 'No file uploaded.'

    original_name = os.path.basename(getattr(upload, 'name', '') or '')
    sanitized_name = get_valid_filename(original_name)
    if not sanitized_name:
        return 'Invalid file name.'
    upload.name = sanitized_name

    extension = Path(sanitized_name).suffix.lower()
    normalized_extensions = {ext.lower() if ext.startswith('.') else f'.{ext.lower()}' for ext in allowed_extensions}
    if extension not in normalized_extensions:
        return f'Unsupported file type: {extension or "unknown"}.'

    if max_size_bytes and getattr(upload, 'size', 0) > max_size_bytes:
        max_mb = round(max_size_bytes / (1024 * 1024), 1)
        return f'File is too large. Maximum allowed size is {max_mb} MB.'

    if allowed_content_types:
        content_type = (getattr(upload, 'content_type', '') or '').lower()
        normalized_types = {item.lower() for item in allowed_content_types}
        if content_type and content_type not in normalized_types:
            return f'Unsupported content type: {content_type}.'

    return None
