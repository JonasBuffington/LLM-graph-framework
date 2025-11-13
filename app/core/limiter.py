# app/core/limiter.py
from slowapi import Limiter
from slowapi.util import get_remote_address

def get_user_id_key(request) -> str:
    """
    Returns the user ID from the request header, falling back to the remote address.
    This ensures that even if the header is missing, we can still apply a limit.
    """
    user_id = request.headers.get("x-user-id")
    return user_id or get_remote_address(request)

# Create a limiter instance without storage.
# The storage will be injected during the application's startup lifespan.
# This prevents the library from making a faulty connection probe on import.
limiter = Limiter(key_func=get_user_id_key)