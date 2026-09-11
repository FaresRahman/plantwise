"""Shared slowapi Limiter instance.

Defined here (not inline in main.py) so individual module routers can apply
tighter, endpoint-specific `@limiter.limit(...)` decorators (e.g. on
login/signup/invite) without importing back through main.py — main.py is
what imports every module's router at startup, so a router importing
`from app.main import limiter` would be a circular import.
"""
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.config import settings

limiter = Limiter(key_func=get_remote_address, default_limits=[settings.RATE_LIMIT])
