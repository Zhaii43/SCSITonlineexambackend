from urllib.parse import urlparse


def _is_remote_url(value: str) -> bool:
    if not value:
        return False
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def safe_delete_field(field) -> bool:
    """
    Delete a FileField/ImageField only if it looks like a local media path.
    Returns True when a delete was attempted and succeeded.
    """
    if not field:
        return False
    name = getattr(field, "name", "") or ""
    if _is_remote_url(name):
        return False
    try:
        field.delete(save=False)
        return True
    except Exception:
        return False
