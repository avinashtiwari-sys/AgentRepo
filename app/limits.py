"""Shared rate-limiter instance.

Imported by both app/main.py and app/webhook.py to avoid circular imports.
Rate limiting is only enforced in production mode.
"""
from slowapi import Limiter
from slowapi.util import get_remote_address
from config import MODE

limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["30/minute"],
    enabled=MODE == "prod",
)
