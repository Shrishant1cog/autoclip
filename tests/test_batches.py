"""Phase 6 — persistent batch queue tests."""

from __future__ import annotations

import pytest
from autoclip.db import store
from autoclip.db.models import Source, new_id
from autoclip.jobs import batch_runner, batches


@pytest.fixture
def sources(initialised_db: int) -> list:
    made = []
    for i in range(3):
        made.append(
            store.create_source(
                Source(
                    id=new_id(), type="youtube",
                    url=f"https://youtu.be/v{i}", path=f"/tmp/v{i}.mp4",
                    title=f"Video {i}",
                )
            )
        )
    return made


# --------------------------------------------------------------------------
# CRUD & progress
# --------------------------------------------------------------------------


def test_batch_crud(initialised_db: int) -> None:
    batch = batches.create_batch("my batch", {"max_clips": 3})
    assert batch["status"] == "queued"
    assert batch["settings"] == {"max_clips": 3}

    batches.set_batch_status(batch["id"], "paused")
    assert batches.get_batch(batch["id"])["status"] == "paused"  # type: ignore[index]

    batches.delete_batch(batch["id"])
    assert batches.get_batch(batch["id"]) is None


def test_items_ordered_by_position(initialised_db: int, sources: list) -> None:
    batch = batches.create_batch("ordered")
    i0 = batches.add_item(batch["id"], sources[0].id)
    i1 = batches.add_item(batch["id"], sources[1].id)
    i2 = batches.add_item(batch["id"], sources[2].id)
    items = batches.list_items(batch["id"])
    assert [it["id"] for it in items] == [i0["id"], i1["id"], i2["id"]]
    assert [it["position"] for it in items] == [0, 1, 2]


def test_next_pending_and_progress(initialised_db: int, sources: list) -> None:
    batch = batches.create_batch()
    a = batches.add_item(batch["id"], sources[0].id)
    b = batches.add_item(batch["id"], sources[1].id)
    batches.update_item(a["id"], status="done")
    assert batches.next_pending_item(batch["id"])["id"] == b["id"]  # type: ignore[union-attr]

    progress = batches.batch_progress(batch["id"])
    assert progress == {
        "total": 2, "pending": 1, "processing": 0, "done": 1,
        "failed": 0, "skipped": 0, "cancelled": 0,
    }


def test_recover_interrupted(initialised_db: int, sources: list) -> None:
    batch = batches.create_batch()
    item = batches.add_item(batch["id"], sources[0].id)
    batches.update_item(item["id"], status="processing")
    # The recovered ids come back so the restart can be recorded (Phase 17).
    recovered = batches.recover_interrupted()
    assert item["id"] in recovered
    assert batches.get_item(item["id"])["status"] == "pending"  # type: ignore[index]


def test_deleting_source_cascades_item(initialised_db: int, sources: list) -> None:
    from autoclip.db.store import connection

    batch = batches.create_batch()
    batches.add_item(batch["id"], sources[0].id)
    with connection() as conn:
        conn.execute("DELETE FROM sources WHERE id = ?", (sources[0].id,))
    assert batches.list_items(batch["id"]) == []


# --------------------------------------------------------------------------
# Runner
# --------------------------------------------------------------------------


def test_runner_enqueues_next_job(initialised_db: int, sources: list) -> None:
    batch = batches.create_batch()
    i0 = batches.add_item(batch["id"], sources[0].id)
    i1 = batches.add_item(batch["id"], sources[1].id)

    runner = batch_runner.BatchRunner()
    assert runner._advance_one(batch["id"]) is True

    item0 = batches.get_item(i0["id"])
    assert item0["status"] == "processing"
    assert item0["job_id"] is not None
    job = store.get_job(item0["job_id"])
    assert job is not None and job.status == "queued"

    # The batch is 'running' but item1 is still pending (one at a time).
    assert batches.next_pending_item(batch["id"])["id"] == i1["id"]  # type: ignore[union-attr]


def test_runner_completes_items_sequentially(initialised_db: int, sources: list) -> None:
    batch = batches.create_batch()
    i0 = batches.add_item(batch["id"], sources[0].id)
    i1 = batches.add_item(batch["id"], sources[1].id)

    runner = batch_runner.BatchRunner()
    runner._advance_one(batch["id"])
    item0 = batches.get_item(i0["id"])
    assert item0["job_id"] is not None

    # Simulate the job finishing.
    store.update_job(item0["job_id"], status="done")
    runner._advance_one(batch["id"])
    assert batches.get_item(i0["id"])["status"] == "done"  # type: ignore[index]
    # Second item now processing.
    item1 = batches.get_item(i1["id"])
    assert item1["status"] == "processing"


def test_runner_marks_batch_done(initialised_db: int, sources: list) -> None:
    batch = batches.create_batch()
    i0 = batches.add_item(batch["id"], sources[0].id)

    runner = batch_runner.BatchRunner()
    runner._advance_one(batch["id"])
    item0 = batches.get_item(i0["id"])
    store.update_job(item0["job_id"], status="done")
    runner._advance_one(batch["id"])   # finish item0; no pending left
    runner._advance_one(batch["id"])   # complete the batch

    assert batches.get_batch(batch["id"])["status"] == "done"  # type: ignore[index]


def test_runner_records_failures(initialised_db: int, sources: list) -> None:
    batch = batches.create_batch()
    i0 = batches.add_item(batch["id"], sources[0].id)
    i1 = batches.add_item(batch["id"], sources[1].id)

    runner = batch_runner.BatchRunner()
    runner._advance_one(batch["id"])
    item0 = batches.get_item(i0["id"])
    store.update_job(item0["job_id"], status="failed", error="stage boom")
    runner._advance_one(batch["id"])

    assert batches.get_item(i0["id"])["status"] == "failed"  # type: ignore[index]
    assert "boom" in (batches.get_item(i0["id"])["error"] or "")  # type: ignore[index]
    # The batch moved on to item1 despite the failure.
    assert batches.get_item(i1["id"])["status"] == "processing"  # type: ignore[index]
    # Batch status reflects failure at completion.
    runner._advance_one(batch["id"])
    store.update_job(batches.get_item(i1["id"])["job_id"], status="done")  # type: ignore[index]
    runner._advance_one(batch["id"])
    runner._advance_one(batch["id"])
    assert batches.get_batch(batch["id"])["status"] == "failed"  # type: ignore[index]


def test_retry_failed_requeues(initialised_db: int, sources: list) -> None:
    batch = batches.create_batch()
    i0 = batches.add_item(batch["id"], sources[0].id)
    batches.update_item(i0["id"], status="failed", error="x")

    runner = batch_runner.BatchRunner()
    count = runner.retry_failed(batch["id"])
    assert count == 1
    assert batches.get_item(i0["id"])["status"] == "pending"  # type: ignore[index]


def test_cancel_marks_pending_cancelled(initialised_db: int, sources: list) -> None:
    batch = batches.create_batch()
    i0 = batches.add_item(batch["id"], sources[0].id)
    i1 = batches.add_item(batch["id"], sources[1].id)

    runner = batch_runner.BatchRunner()
    runner._advance_one(batch["id"])
    runner.cancel(batch["id"])

    items = {it["id"]: it["status"] for it in batches.list_items(batch["id"])}
    assert items[i0["id"]] == "cancelled"
    assert items[i1["id"]] == "cancelled"
    assert batches.get_batch(batch["id"])["status"] == "cancelled"  # type: ignore[index]


def test_pause_blocks_advance(initialised_db: int, sources: list) -> None:
    batch = batches.create_batch()
    i0 = batches.add_item(batch["id"], sources[0].id)

    runner = batch_runner.BatchRunner()
    batches.set_batch_status(batch["id"], "paused")
    # _advance_all only touches running batches.
    assert runner._advance_all() is False
    assert batches.get_item(i0["id"])["status"] == "pending"  # type: ignore[index]
