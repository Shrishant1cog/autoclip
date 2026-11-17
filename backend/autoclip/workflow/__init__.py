"""Workflow engine — native automation for AutoClip.

Wraps the existing six-stage pipeline as executable nodes; never replaces it.
"""

from __future__ import annotations

from .engine import (
    NodeContext,
    NodeExecutionError,
    NodeResult,
    NodeSpec,
    WorkflowEngine,
    WorkflowValidationError,
    registry,
    validate_workflow,
)

__all__ = [
    "NodeContext",
    "NodeExecutionError",
    "NodeResult",
    "NodeSpec",
    "WorkflowEngine",
    "WorkflowValidationError",
    "registry",
    "validate_workflow",
]
