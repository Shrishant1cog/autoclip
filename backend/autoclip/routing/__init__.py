"""Content classification and channel routing (Phase 5)."""

from .classifier import (
    CATEGORIES,
    add_rule,
    classification_for,
    classify_transcript_sync,
    delete_rule,
    get_rule,
    list_rules,
    resolve_target_channel,
    resolve_target_channels,
    save_classification,
    update_rule,
)

__all__ = [
    "CATEGORIES",
    "add_rule",
    "classification_for",
    "classify_transcript_sync",
    "delete_rule",
    "get_rule",
    "list_rules",
    "resolve_target_channel",
    "resolve_target_channels",
    "save_classification",
    "update_rule",
]
