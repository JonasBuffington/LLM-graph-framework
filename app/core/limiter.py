# app/core/limiter.py
from slowapi import Limiter
from slowapi.util import get_remote_address
from app.core.config import settings

def get_user_id_key(request) -> str:
    """
    Returns the user ID from the request header, falling back to the remote address.
    """
    user_id = request.headers.get("x-user-id")
    return user_id or get_remote_address(request)

# Configure the limiter directly. If LIMITER_STORAGE_URI is not set,
# slowapi defaults to in-memory storage, which is perfect for our needs.
limiter = Limiter(
    key_func=get_user_id_key,
    storage_uri=settings.LIMITER_STORAGE_URI,
    strategy="fixed-window"
)