# app/core/limiter.py
from slowapi import Limiter
from slowapi.util import get_remote_address
from app.core.config import settings

def get_user_id_key(request) -> str:
    """
    Returns the user ID from the request header, falling back to the remote address.
    This ensures that even if the header is missing, we can still apply a limit.
    """
    user_id = request.headers.get("x-user-id")
    return user_id or get_remote_address(request)

limiter = Limiter(
    key_func=get_user_id_key,
    storage_uri=settings.REDIS_URL,
    strategy="fixed-window"
)