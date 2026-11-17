"""Workflow engine tests — registry, validation, execution, persistence."""

from __future__ import annotations

from autoclip.workflow import (
    NodeExecutionError,
    WorkflowEngine,
    registry,
    validate_workflow,
)
from autoclip.workflow import store as wf_store
from autoclip.workflow.engine import MISSING, NodeContext, NodeSpec

# --------------------------------------------------------------------------
# Registry
# --------------------------------------------------------------------------


def test_all_six_pipeline_stages_are_registered() -> None:
    types = set(registry().keys())
    for stage in ("prepare", "transcribe", "highlights", "reframe", "captions", "export"):
        assert f"stage.{stage}" in types


def test_utility_nodes_are_registered() -> None:
    types = set(registry().keys())
    assert "util.condition" in types
    assert "util.log" in types


def test_node_specs_are_complete() -> None:
    for factory in registry().values():
        spec = factory({})
        assert spec.type and spec.name and spec.category and spec.description
        assert spec.inputs and spec.output
        assert callable(spec.handler)


# --------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------


def _definition(nodes: list[dict], edges: list[dict]) -> dict:
    return {"nodes": nodes, "edges": edges}


def _stage_node(node_id: str, stage: str, **extra) -> dict:
    return {"id": node_id, "type": f"stage.{stage}", **extra}


def test_valid_linear_pipeline_has_no_problems() -> None:
    stages = ["prepare", "transcribe", "highlights", "reframe", "captions", "export"]
    nodes = [_stage_node(f"n{i}", s) for i, s in enumerate(stages)]
    edges = [{"from": f"n{i}", "to": f"n{i + 1}"} for i in range(len(stages) - 1)]
    assert validate_workflow(_definition(nodes, edges)) == []


def test_unknown_node_type_is_rejected() -> None:
    problems = validate_workflow(_definition([{"id": "x", "type": "nope"}], []))
    assert any("Unknown node type" in p for p in problems)


def test_duplicate_ids_are_rejected() -> None:
    nodes = [_stage_node("a", "prepare"), _stage_node("a", "transcribe")]
    assert any("Duplicate" in p for p in validate_workflow(_definition(nodes, [])))


def test_edge_to_unknown_node_is_rejected() -> None:
    nodes = [_stage_node("a", "prepare")]
    edges = [{"from": "a", "to": "ghost"}]
    assert any("unknown node" in p for p in validate_workflow(_definition(nodes, edges)))


def test_cycle_is_rejected() -> None:
    nodes = [_stage_node("a", "prepare"), _stage_node("b", "transcribe")]
    edges = [{"from": "a", "to": "b"}, {"from": "b", "to": "a"}]
    assert any("Cycle" in p for p in validate_workflow(_definition(nodes, edges)))


# --------------------------------------------------------------------------
# Execution
# --------------------------------------------------------------------------


def _engine_with(nodes: dict[str, NodeSpec]) -> WorkflowEngine:
    """Engine over a type-keyed spec map: each type resolves to its own spec."""
    return WorkflowEngine(
        registry_fn=lambda: {s.type: (lambda spec=s: spec) for s in nodes.values()}
    )


def test_linear_execution_runs_in_topological_order() -> None:
    calls: list[str] = []

    def make(node_id: str) -> NodeSpec:
        def handler(ctx: NodeContext) -> str:
            calls.append(ctx.node_id)
            return f"out-{ctx.node_id}"

        return NodeSpec(
            type="util.log",
            name="n",
            category="u",
            description="",
            inputs=["any"],
            output="any",
            handler=handler,
        )

    specs = {"util.log": make("n")}
    engine = WorkflowEngine(registry_fn=lambda: specs)
    definition = _definition(
        [{"id": f"n{i}", "type": "util.log"} for i in range(3)],
        [{"from": "n0", "to": "n1"}, {"from": "n1", "to": "n2"}],
    )
    results = engine.execute(definition, {})
    assert [r.status for r in results] == ["succeeded"] * 3
    assert calls == ["n0", "n1", "n2"]
    assert results[-1].output == "out-n2"


def test_disabled_node_is_skipped_and_passes_data_through() -> None:
    received: list = []

    def make(record: bool) -> NodeSpec:
        def handler(ctx: NodeContext):
            if record and ctx.node_id == "c":
                received.append(ctx.input)
            return f"out-{ctx.node_id}"

        return NodeSpec(
            type="util.log",
            name="n",
            category="u",
            description="",
            inputs=["any"],
            output="any",
            handler=handler,
        )

    # The middle node is disabled via its definition, not the spec.
    specs = {"util.log": make(record=True)}
    engine = WorkflowEngine(registry_fn=lambda: specs)
    definition = _definition(
        [
            {"id": "a", "type": "util.log"},
            {"id": "b", "type": "util.log", "enabled": False},
            {"id": "c", "type": "util.log"},
        ],
        [{"from": "a", "to": "b"}, {"from": "b", "to": "c"}],
    )
    results = engine.execute(definition, {})
    statuses = {r.node_id: r.status for r in results}
    assert statuses == {"a": "succeeded", "b": "skipped", "c": "succeeded"}
    # The disabled node's input (a's output) passed through to c.
    assert received == ["out-a"]


def test_failure_stops_the_run_and_reports_error() -> None:
    calls: list[str] = []

    def make(fail: bool) -> NodeSpec:
        def handler(ctx: NodeContext):
            calls.append(ctx.node_id)
            if ctx.node_id == "b":
                raise RuntimeError("boom")
            return "ok"

        return NodeSpec(
            type="util.log",
            name="n",
            category="u",
            description="",
            inputs=["any"],
            output="any",
            handler=handler,
        )

    specs = {"util.log": make(fail=False)}
    engine = WorkflowEngine(registry_fn=lambda: specs)
    definition = _definition(
        [
            {"id": "a", "type": "util.log"},
            {"id": "b", "type": "util.log"},
            {"id": "c", "type": "util.log"},
        ],
        [{"from": "a", "to": "b"}, {"from": "b", "to": "c"}],
    )
    results = engine.execute(definition, {})
    assert [r.status for r in results] == ["succeeded", "failed"]
    assert "boom" in (results[-1].error or "")


def test_retryable_error_is_retried_then_succeeds() -> None:
    attempts = {"count": 0}

    def handler(ctx: NodeContext) -> str:
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise NodeExecutionError("transient", retryable=True)
        return "finally"

    spec = NodeSpec(
        type="util.log",
        name="n",
        category="u",
        description="",
        inputs=["any"],
        output="any",
        handler=handler,
        max_retries=3,
    )
    engine = WorkflowEngine(registry_fn=lambda: {"util.log": spec})
    results = engine.execute(_definition([{"id": "a", "type": "util.log"}], []), {})
    assert results[0].status == "succeeded"
    assert results[0].output == "finally"
    assert attempts["count"] == 3


def test_non_retryable_error_is_not_retried() -> None:
    attempts = {"count": 0}

    def handler(ctx: NodeContext) -> None:
        attempts["count"] += 1
        raise NodeExecutionError("permanent", retryable=False)

    spec = NodeSpec(
        type="util.log",
        name="n",
        category="u",
        description="",
        inputs=["any"],
        output="any",
        handler=handler,
        max_retries=5,
    )
    engine = WorkflowEngine(registry_fn=lambda: {"util.log": spec})
    results = engine.execute(_definition([{"id": "a", "type": "util.log"}], []), {})
    assert results[0].status == "failed"
    assert attempts["count"] == 1


def test_cancellation_skips_remaining_nodes() -> None:
    def handler(ctx: NodeContext) -> str:
        return "ok"

    spec = NodeSpec(
        type="util.log",
        name="n",
        category="u",
        description="",
        inputs=["any"],
        output="any",
        handler=handler,
    )

    engine = WorkflowEngine(registry_fn=lambda: {"util.log": spec})
    definition = _definition(
        [{"id": f"n{i}", "type": "util.log"} for i in range(3)],
        [{"from": "n0", "to": "n1"}, {"from": "n1", "to": "n2"}],
    )
    state = {"cancelled_after_first": False}

    def on_node_finish(result) -> None:
        if result.node_id == "n0":
            state["cancelled_after_first"] = True

    cancelled = lambda: state["cancelled_after_first"]  # noqa: E731
    results = engine.execute(definition, {}, on_node_finish=on_node_finish, is_cancelled=cancelled)
    assert results[0].status == "succeeded"
    assert all(r.status == "skipped" for r in results[1:])


def test_condition_node_routes_by_config() -> None:
    def handler(ctx: NodeContext) -> dict:
        from autoclip.workflow.engine import _cond_handler

        return _cond_handler(ctx)

    spec = NodeSpec(
        type="util.condition",
        name="c",
        category="u",
        description="",
        inputs=["any"],
        output="branch",
        handler=handler,
        config_schema={"expression": "string"},
    )
    engine = WorkflowEngine(registry_fn=lambda: {"util.condition": spec})
    definition = _definition(
        [{"id": "a", "type": "util.condition", "config": {"expression": "false"}}], []
    )
    results = engine.execute(definition, {})
    assert results[0].output == {"branch": "false", "value": MISSING}


# --------------------------------------------------------------------------
# Persistence (real DB via the autoclip_home fixture)
# --------------------------------------------------------------------------


def test_workflow_crud_and_versioning(initialised_db: int) -> None:
    created = wf_store.create_workflow("demo", {"nodes": [], "edges": []}, "first")
    wid = created["id"]
    assert created["version"] == 1

    saved = wf_store.save_workflow(wid, {"nodes": [{"id": "x"}], "edges": []})
    assert saved is not None
    assert saved["version"] == 2
    assert saved["definition"] == {"nodes": [{"id": "x"}], "edges": []}

    # Both versions are retained.
    all_rows = wf_store.list_workflows()
    assert len(all_rows) == 2
    assert {r["version"] for r in all_rows} == {1, 2}


def test_run_and_node_history(initialised_db: int) -> None:
    wf = wf_store.create_workflow("hist", {"nodes": [], "edges": []})
    run_id = wf_store.start_run(wf["id"], None, trigger="test")
    wf_store.record_node_run(
        run_id,
        "n1",
        "util.log",
        "succeeded",
        input_payload={"k": 1},
        output_payload="done",
    )
    wf_store.finish_run(run_id, "succeeded")

    runs = wf_store.list_runs(wf["id"])
    assert len(runs) == 1
    assert runs[0]["status"] == "succeeded"
    assert runs[0]["workflow_name"] == "hist"

    nodes = wf_store.list_node_runs(run_id)
    assert len(nodes) == 1
    assert nodes[0]["node_id"] == "n1"
    assert nodes[0]["input"] == {"k": 1}
    assert nodes[0]["output"] == "done"


def test_migration_v4_creates_workflow_tables(initialised_db: int) -> None:

    from autoclip.db.store import connection

    with connection() as conn:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        tables = {
            r[0]
            for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
    assert version >= 4
    assert {"workflows", "workflow_runs", "workflow_node_runs"} <= tables
