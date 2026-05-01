"""MailPlus Intelligence runtime foundations."""

from .runtime import RuntimeProfile, default_runtime_profile
from .schema import apply_schema_v0, current_schema_version
from .sqlite import connect_sqlite

__all__ = [
    "RuntimeProfile",
    "apply_schema_v0",
    "connect_sqlite",
    "current_schema_version",
    "default_runtime_profile",
]
