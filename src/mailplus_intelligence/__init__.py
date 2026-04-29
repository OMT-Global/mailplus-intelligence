"""MailPlus Intelligence runtime foundations."""

from .runtime import RuntimeProfile, default_runtime_profile
from .sqlite import connect_sqlite

__all__ = [
    "RuntimeProfile",
    "connect_sqlite",
    "default_runtime_profile",
]
