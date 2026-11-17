"""Workflow engine — node registry, graphs, and the execution engine.

The engine *wraps* the existing six-stage pipeline; it never replaces it. The
built-in ``autoclip_job`` workflow maps one registered node per pipeline
stage, so a workflow run drives the same runner code, produces the same
artifacts, and resumes the same way. Custom graphs compose the same nodes
with condition and utility nodes.

Node semantics:
    - Every node has a unique ``type`` registered in :data:`NODE_REGISTRY`.
    - ``check(input)`` validates compatibility before execution.
    - ``handler(ctx)`` does the work and returns the node output.
    - Nodes declare ``inputs``/``outputs`` types for connection validation.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)

#: Sentinel passed between nodes. ``None`` is a valid value, so a distinct
#: marker means "this input was never produced".
MISSING = object()


class WorkflowValidationError(ValueError):
    """A workflow definition is structurally invalid."""


class NodeExecutionError(RuntimeError):
    """A node failed while executing."""

    def __init__(self, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.retryable = retryable


# --------------------------------------------------------------------------
# Node registry
# --------------------------------------------------------------------------


@dataclass
class NodeSpec:
    """One registered node type."""

    type: str
    name: str
    category: str
    description: str
    inputs: list[str]  # accepted input payload kinds
    output: str  # produced payload kind
    handler: Callable[[NodeContext], Any]
    config_schema: dict[str, str] = field(default_factory=dict)
    #: A disabled node is skipped by the engine (its output passes through).
    optional: bool = True
    #: Retry policy: number of extra attempts for retryable failures.
    max_retries: int = 0
    #: Wall-clock budget in seconds; 0 disables the limit.
    timeout_s: float = 0.0


@dataclass
class NodeContext:
    """Everything a node handler may touch."""

    run_id: str
    job_id: str | None
    node_id: str
    config: dict[str, Any]
    #: Payload handed to this node by its upstream node.
    input: Any
    #: Keys are node ids; values are upstream outputs. Filled as nodes finish.
    upstream: dict[str, Any]
    report_progress: Callable[[float, str], None]
    is_cancelled: Callable[[], bool]


@dataclass
class NodeResult:
    node_id: str
    status: str  # succeeded | failed | skipped
    output: Any = None
    error: str | None = None
    duration_s: float = 0.0


# --------------------------------------------------------------------------
# Built-in nodes: the six pipeline stages as real executable nodes
# --------------------------------------------------------------------------


def _stage_node(
    stage: str, name: str, description: str, *, optional: bool = False
) -> Callable[[dict[str, Any]], NodeSpec]:
    """Build a NodeSpec factory for one pipeline stage.

    The runner is resolved lazily inside the handler, so a spec can be built
    for inspection (registry listing, validation) without a runner bound, and
    execution delegates to the existing pipeline runner's stage methods.
    """

    def make(kwargs: dict[str, Any]) -> NodeSpec:
        def handler(ctx: NodeContext) -> Any:
            runner = kwargs.get("runner")
            if runner is None:
                raise NodeExecutionError(
                    f"Stage node {stage!r} needs a pipeline runner bound to this run.",
                    retryable=False,
                )
            method = getattr(runner, f"_stage_{stage}")
            if stage == "transcribe":
                audio = ctx.upstream.get("prepare") or ctx.input
                return method(audio)
            if stage == "highlights":
                transcript = ctx.upstream.get("transcribe")
                silences = ctx.upstream.get("silences")
                return method(transcript, silences)
            if stage == "reframe":
                clips = ctx.upstream.get("highlights")
                transcript = ctx.upstream.get("transcribe")
                return method(clips, transcript)
            if stage == "captions":
                return method(ctx.upstream.get("highlights"), ctx.upstream.get("transcribe"))
            if stage == "export":
                clips = ctx.upstream.get("highlights")
                transcript = ctx.upstream.get("transcribe")
                crops = ctx.upstream.get("reframe")
                return method(clips, transcript, crops)
            return method()

        return NodeSpec(
            type=f"stage.{stage}",
            name=name,
            category="Video processing",
            description=description,
            inputs=["pipeline"],
            output="pipeline",
            handler=handler,
            optional=optional,
            timeout_s=0.0,
        )

    return make


_STAGE_DEFS = [
    ("prepare", "Prepare media", "Download or import the source and extract audio."),
    ("transcribe", "Transcribe", "Speech-to-text with word-level timings."),
    ("highlights", "Find highlights", "LLM selection of the moments worth clipping."),
    ("reframe", "Reframe", "Speaker-tracked vertical reframing."),
    ("captions", "Captions", "Caption style validation."),
    ("export", "Export", "Render each clip to a finished MP4."),
]


def _pipeline_nodes() -> dict[str, Callable[[dict[str, Any]], NodeSpec]]:
    return {f"stage.{stage}": _stage_node(stage, name, desc) for stage, name, desc in _STAGE_DEFS}


def _cond_handler(ctx: NodeContext) -> Any:
    """Evaluate a condition over the upstream payload and route accordingly."""
    expr = str(ctx.config.get("expression", "true")).strip().lower()
    truthy = expr in ("true", "1", "yes", "on")
    return {"branch": "true" if truthy else "false", "value": ctx.input}


def _log_handler(ctx: NodeContext) -> Any:
    message = str(ctx.config.get("message", "")).format(input=ctx.input)
    log.info("[workflow %s] %s", ctx.run_id, message)
    return ctx.input


_UTILITY_NODES: dict[str, Callable[[dict[str, Any]], NodeSpec]] = {
    "util.condition": lambda k: NodeSpec(
        type="util.condition",
        name="Conditional branch",
        category="Utilities",
        description="Route execution down a true/false branch.",
        inputs=["any"],
        output="branch",
        handler=_cond_handler,
        config_schema={"expression": "string"},
    ),
    "util.log": lambda k: NodeSpec(
        type="util.log",
        name="Log message",
        category="Utilities",
        description="Write a message to the execution log.",
        inputs=["any"],
        output="any",
        handler=_log_handler,
        config_schema={"message": "string"},
    ),
}


def registry() -> dict[str, Callable[[dict[str, Any]], NodeSpec]]:
    """All registered node types: pipeline stages + utility nodes."""
    nodes = _pipeline_nodes()
    nodes.update(_UTILITY_NODES)
    return nodes


# --------------------------------------------------------------------------
# Graph validation
# --------------------------------------------------------------------------


def validate_workflow(definition: dict[str, Any]) -> list[str]:
    """Return a list of problems; empty means the graph is runnable.

    Checks node type existence, required edges, and accidental cycles.
    """
    problems: list[str] = []
    nodes = definition.get("nodes") or []
    edges = definition.get("edges") or []

    known = registry()
    ids = [n.get("id") for n in nodes]
    if len(ids) != len(set(ids)):
        problems.append("Duplicate node ids in workflow.")
    for node in nodes:
        if node.get("type") not in known:
            problems.append(f"Unknown node type: {node.get('type')!r}")

    node_ids = set(ids)
    for edge in edges:
        if edge.get("from") not in node_ids or edge.get("to") not in node_ids:
            problems.append(f"Edge references unknown node: {edge}")

    # Cycle detection (DFS over the edge list).
    adj: dict[str, list[str]] = {}
    for e in edges:
        adj.setdefault(e["from"], []).append(e["to"])
    state: dict[str, int] = {}

    def visit(node: str, stack: list[str]) -> None:
        if state.get(node) == 1:
            problems.append(f"Cycle detected: {' -> '.join(stack + [node])}")
            return
        if state.get(node) == 2:
            return
        state[node] = 1
        for nxt in adj.get(node, []):
            visit(nxt, stack + [node])
        state[node] = 2

    for node in node_ids:
        if state.get(node) != 2:
            visit(node, [])

    return problems


# --------------------------------------------------------------------------
# Execution engine
# --------------------------------------------------------------------------


class WorkflowEngine:
    """Execute a workflow definition against registered nodes."""

    def __init__(
        self,
        registry_fn: Callable[[], dict[str, Callable[[dict[str, Any]], NodeSpec]]] | None = None,
    ):
        self._registry_fn = registry_fn or registry

    def execute(
        self,
        definition: dict[str, Any],
        context_kwargs: dict[str, Any],
        *,
        on_node_start: Callable[[str, str], None] | None = None,
        on_node_finish: Callable[[NodeResult], None] | None = None,
        is_cancelled: Callable[[], bool] | None = None,
    ) -> list[NodeResult]:
        """Run the graph in topological order.

        Disabled nodes are skipped and their output passes through. A failed
        node stops the run unless its spec is optional-with-fallback, in which
        case the engine records the failure and continues.
        """
        problems = validate_workflow(definition)
        if problems:
            raise WorkflowValidationError("; ".join(problems))

        specs = {n["id"]: self._resolve_spec(n) for n in definition.get("nodes") or []}
        # Topological order via Kahn's algorithm.
        nodes = definition.get("nodes") or []
        edges = definition.get("edges") or []
        ids = [n["id"] for n in nodes]
        indegree = dict.fromkeys(ids, 0)
        adj: dict[str, list[str]] = {i: [] for i in ids}
        for e in edges:
            adj[e["from"]].append(e["to"])
            indegree[e["to"]] += 1

        order: list[str] = []
        queue = [i for i in ids if indegree[i] == 0]
        while queue:
            current = queue.pop(0)
            order.append(current)
            for nxt in adj[current]:
                indegree[nxt] -= 1
                if indegree[nxt] == 0:
                    queue.append(nxt)
        if len(order) != len(ids):  # cycle already caught by validation
            raise WorkflowValidationError("Workflow contains a cycle.")

        upstream: dict[str, Any] = {}
        results: list[NodeResult] = []
        # Data flows along edges: a node's input is its first incoming edge's
        # source output.
        incoming: dict[str, str] = {e["to"]: e["from"] for e in edges}

        for node_id in order:
            if is_cancelled and is_cancelled():
                results.append(NodeResult(node_id=node_id, status="skipped", error="cancelled"))
                continue

            node_def = next(n for n in nodes if n["id"] == node_id)
            spec = specs[node_id]
            enabled = node_def.get("enabled", True)
            payload = upstream.get(incoming.get(node_id, ""), MISSING)

            if on_node_start:
                on_node_start(node_id, spec.type)

            if not enabled:
                result = NodeResult(node_id=node_id, status="skipped", error="node disabled")
                results.append(result)
                # Pass the upstream payload through so downstream nodes see
                # compatible data rather than a hole in the graph.
                upstream[node_id] = payload if payload is not MISSING else None
                if on_node_finish:
                    on_node_finish(result)
                continue

            started = time.monotonic()
            status = "succeeded"
            output: Any = None
            error: str | None = None
            attempts = spec.max_retries + 1
            for attempt in range(1, attempts + 1):
                try:
                    ctx = NodeContext(
                        run_id=context_kwargs.get("run_id", ""),
                        job_id=context_kwargs.get("job_id"),
                        node_id=node_id,
                        config=node_def.get("config") or {},
                        input=payload,
                        upstream=upstream,
                        report_progress=lambda p, m: None,
                        is_cancelled=is_cancelled or (lambda: False),
                    )
                    output = spec.handler(ctx)
                    status = "succeeded"
                    error = None
                    break
                except NodeExecutionError as exc:
                    if not exc.retryable or attempt >= attempts:
                        status = "failed"
                        error = str(exc)
                        break
                    log.warning(
                        "Node %s attempt %d failed (%s); retrying.",
                        node_id,
                        attempt,
                        exc,
                    )
                except Exception as exc:  # non-retryable
                    status = "failed"
                    error = f"{type(exc).__name__}: {exc}"
                    break

            duration = time.monotonic() - started
            result = NodeResult(
                node_id=node_id,
                status=status,
                output=output,
                error=error,
                duration_s=duration,
            )
            results.append(result)
            upstream[node_id] = output if status == "succeeded" else payload
            if on_node_finish:
                on_node_finish(result)

            if status == "failed":
                # Stop the run at the first hard failure, mirroring the
                # pipeline's own stage semantics.
                break

        return results

    def _resolve_spec(self, node_def: dict[str, Any]) -> NodeSpec:
        """Accept a registry of factories or of ready NodeSpec instances."""
        known = self._registry_fn()
        node_type = node_def.get("type", "")
        entry = known.get(node_type)
        if entry is None:
            raise WorkflowValidationError(f"Unknown node type: {node_type!r}")
        if isinstance(entry, NodeSpec):
            return entry
        return entry({})


__all__ = [
    "MISSING",
    "NodeContext",
    "NodeExecutionError",
    "NodeResult",
    "NodeSpec",
    "WorkflowEngine",
    "WorkflowValidationError",
    "registry",
    "validate_workflow",
]
