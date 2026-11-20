"""Content classification and channel routing (Phase 5)."""

from . import decision
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
from .decision import RoutingDecision

__all__ = [
    "CATEGORIES",
    "RoutingDecision",
    "add_rule",
    "classification_for",
    "classify_transcript_sync",
    "decision",
    "delete_rule",
    "get_rule",
    "list_rules",
    "resolve_target_channel",
    "resolve_target_channels",
    "save_classification",
    "update_rule",
]
