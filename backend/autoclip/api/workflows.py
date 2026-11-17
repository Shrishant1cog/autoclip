"""Workflow API — CRUD, validation, execution, history, node registry."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..db import store as db_store
from ..db.models import Job, Source, new_id
from ..workflow import engine as wf_engine
from ..workflow import store as wf_store

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/workflows", tags=["workflows"])


class WorkflowIn(BaseModel):
    name: str
    description: str = ""
    definition: dict = Field(default_factory=dict)


class WorkflowSaveIn(BaseModel):
    definition: dict
    name: str | None = None


class RunIn(BaseModel):
    job_id: str | None = None
    source_url: str | None = None


@router.get("/nodes")
async def node_registry() -> list[dict]:
    """Every registered node type with its schema — drives the builder palette."""
    nodes = []
    for factory in wf_engine.registry().values():
        spec = factory({})
        nodes.append(
            {
                "type": spec.type,
                "name": spec.name,
                "category": spec.category,
                "description": spec.description,
                "inputs": spec.inputs,
                "output": spec.output,
                "config_schema": spec.config_schema,
                "optional": spec.optional,
                "max_retries": spec.max_retries,
            }
        )
    return nodes


@router.get("", response_model=None)
async def list_workflows() -> list[dict]:
    return wf_store.list_workflows()


@router.post("", status_code=201)
async def create_workflow(payload: WorkflowIn) -> dict:
    problems = wf_engine.validate_workflow(payload.definition)
    if problems:
        raise HTTPException(status_code=400, detail="; ".join(problems))
    return wf_store.create_workflow(payload.name, payload.definition, payload.description)


@router.get("/{workflow_id}")
async def get_workflow(workflow_id: str) -> dict:
    workflow = wf_store.get_workflow(workflow_id)
    if workflow is None:
        raise HTTPException(status_code=404, detail="Workflow not found.")
    return workflow


@router.put("/{workflow_id}")
async def save_workflow(workflow_id: str, payload: WorkflowSaveIn) -> dict:
    problems = wf_engine.validate_workflow(payload.definition)
    if problems:
        raise HTTPException(status_code=400, detail="; ".join(problems))
    saved = wf_store.save_workflow(workflow_id, payload.definition, name=payload.name)
    if saved is None:
        raise HTTPException(status_code=404, detail="Workflow not found.")
    return saved


@router.post("/{workflow_id}/validate")
async def validate(workflow_id: str, payload: WorkflowSaveIn) -> dict:
    return {"problems": wf_engine.validate_workflow(payload.definition)}


@router.post("/{workflow_id}/run")
async def run_workflow(workflow_id: str, payload: RunIn) -> dict:
    workflow = wf_store.get_workflow(workflow_id)
    if workflow is None:
        raise HTTPException(status_code=404, detail="Workflow not found.")

    job_id = payload.job_id
    if job_id is None and payload.source_url:
        source = Source(
            id=new_id(),
            type="youtube",
            url=payload.source_url,
            path="",
            title=payload.source_url,
        )
        db_store.create_source(source)
        job = Job(id=new_id(), source_id=source.id, provider="")
        db_store.create_job(job)
        job_id = job.id
    if job_id is not None and db_store.get_job(job_id) is None:
        raise HTTPException(status_code=404, detail="Job not found.")

    engine = wf_engine.WorkflowEngine()
    run_id = wf_store.start_run(workflow_id, job_id)

    node_ctx = {"run_id": run_id, "job_id": job_id}

    # A full pipeline run needs the runner; until the runner-binding node
    # handlers are exposed through the API, execution runs utility nodes and
    # records per-node history.
    kwargs: dict = {"runner": None}
    results = engine.execute(
        workflow["definition"],
        {**node_ctx, **kwargs},
        on_node_start=lambda nid, ntype: wf_store.record_node_run(run_id, nid, ntype, "running"),
        on_node_finish=lambda result: wf_store.record_node_run(
            run_id,
            result.node_id,
            next(
                (
                    n["type"]
                    for n in workflow["definition"].get("nodes", [])
                    if n["id"] == result.node_id
                ),
                "",
            ),
            result.status,
            error=result.error,
            output_payload=result.output
            if isinstance(result.output, (dict, list, str, int, float, bool))
            else None,
        ),
    )

    failed = [r for r in results if r.status == "failed"]
    wf_store.finish_run(
        run_id,
        "failed" if failed else "succeeded",
        failed[0].error if failed else None,
    )
    return {
        "run_id": run_id,
        "status": "failed" if failed else "succeeded",
        "nodes": [{"node_id": r.node_id, "status": r.status, "error": r.error} for r in results],
    }


@router.get("/runs")
async def runs(workflow_id: str | None = None, limit: int = 50) -> list[dict]:
    return wf_store.list_runs(workflow_id, limit)


@router.get("/runs/{run_id}")
async def run_detail(run_id: str) -> dict:
    runs = wf_store.list_runs(limit=1000)
    run = next((r for r in runs if r["id"] == run_id), None)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found.")
    run["nodes"] = wf_store.list_node_runs(run_id)
    return run
