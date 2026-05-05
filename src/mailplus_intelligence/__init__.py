"""MailPlus Intelligence runtime foundations."""

from .fixtures import MetadataFixtureCorpus, load_metadata_fixture_corpus
from .runtime import RuntimeProfile, default_runtime_profile
from .schema import apply_schema_v0, current_schema_version
from .sqlite import connect_sqlite
from .suppression import SUPPRESSION_FAMILIES, SuppressionDecision, classify_noise_suppression

__all__ = [
    "MetadataFixtureCorpus",
    "RuntimeProfile",
    "SUPPRESSION_FAMILIES",
    "SuppressionDecision",
    "apply_schema_v0",
    "classify_noise_suppression",
    "connect_sqlite",
    "current_schema_version",
    "default_runtime_profile",
    "load_metadata_fixture_corpus",
]
