"""Phase 17 — the API behind the four new frontend pages.

Each of the pages (Providers, Channels, Routing, Batches) was written against
a live endpoint. These tests pin the shapes those pages read, so a backend
change that breaks a page fails here rather than in the browser.

They exercise the real app through its lifespan, so the responses are the
ones the frontend actually receives.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from autoclip import app as app_module
from autoclip.app import create_app
from autoclip.db.models import Clip, Job, Source, new_id
from fastapi.testclient import TestClient


@pytest.fixture
def client(
    autoclip_home: Path,
    monkeypatch: pytest.MonkeyPatch,
    fake_keyring,
) -> Iterator[TestClient]:
    monkeypatch.setenv(app_module.ENV_NO_WORKER, "1")
    with TestClient(create_app()) as test_client:
        yield test_client


@pytest.fixture
def source() -> Source:
    from autoclip.db import store

    return store.create_source(
        Source(id=new_id(), type="upload", path="C:/media/video.mp4", title="Test source")
    )


# --------------------------------------------------------------------------
# Providers
# --------------------------------------------------------------------------


def test_the_provider_list_covers_every_preset(client: TestClient) -> None:
    response = client.get("/api/ai/providers")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 16
    for provider in body:
        assert set(provider) >= {
            "key",
            "label",
            "adapter",
            "requires_key",
            "default_model",
            "suggested_models",
            "capabilities",
            "is_local",
            "keys_total",
            "keys_healthy",
            "active",
        }


def test_the_presets_endpoint_returns_every_provider(client: TestClient) -> None:
    response = client.get("/api/ai/presets")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 16
    assert body["openai"]["adapter"] == "openai"
    assert "gpt-4o" in body["openai"]["suggested_models"]


def test_a_provider_without_a_key_has_an_empty_pool(client: TestClient) -> None:
    response = client.get("/api/ai/providers/openai/keys")

    assert response.status_code == 200
    assert response.json() == []


def test_an_unknown_provider_has_no_keys(client: TestClient) -> None:
    response = client.get("/api/ai/providers/not-a-provider/keys")

    assert response.status_code == 404


def test_a_key_can_be_added_and_removed(client: TestClient, fake_keyring) -> None:
    response = client.post(
        "/api/ai/providers/openai/keys",
        json={"label": "primary", "value": "sk-test-value"},
    )

    assert response.status_code == 201
    assert response.json()["stored"] in ("keyring", "insecure-fallback")

    keys = client.get("/api/ai/providers/openai/keys").json()
    assert [k["label"] for k in keys] == ["primary"]
    assert keys[0]["enabled"] is True
    # The key value itself is never sent to the browser.
    assert "value" not in keys[0]

    removed = client.delete("/api/ai/providers/openai/keys/primary")
    assert removed.status_code == 204
    assert client.get("/api/ai/providers/openai/keys").json() == []


def test_an_empty_key_is_refused(client: TestClient) -> None:
    response = client.post(
        "/api/ai/providers/openai/keys",
        json={"label": "primary", "value": "   "},
    )

    assert response.status_code == 400


def test_a_key_can_be_disabled_and_enabled_again(client: TestClient) -> None:
    client.post("/api/ai/providers/openai/keys", json={"label": "primary", "value": "sk-test"})

    disabled = client.put("/api/ai/providers/openai/keys/primary/state", json={"enabled": False})
    assert disabled.status_code == 204
    assert client.get("/api/ai/providers/openai/keys").json()[0]["enabled"] is False

    client.put("/api/ai/providers/openai/keys/primary/state", json={"enabled": True})
    assert client.get("/api/ai/providers/openai/keys").json()[0]["enabled"] is True


# --------------------------------------------------------------------------
# Accounts and channels
# --------------------------------------------------------------------------


def test_the_account_list_is_readable_when_empty(client: TestClient) -> None:
    response = client.get("/api/youtube/accounts")

    assert response.status_code == 200
    assert response.json() == []


def test_an_account_slot_can_be_registered(client: TestClient) -> None:
    response = client.post(
        "/api/youtube/accounts",
        json={"label": "Work", "email": "me@example.com"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["label"] == "Work"
    assert body["email"] == "me@example.com"

    accounts = client.get("/api/youtube/accounts").json()
    assert len(accounts) == 1
    assert accounts[0]["channels"] == []
    assert accounts[0]["has_refresh_token"] is False


def test_an_account_slot_can_be_removed(client: TestClient) -> None:
    account = client.post("/api/youtube/accounts", json={"label": "Work"}).json()

    removed = client.delete(f"/api/youtube/accounts/{account['id']}")

    assert removed.status_code == 204
    assert client.get("/api/youtube/accounts").json() == []


def test_a_channel_can_be_registered_and_updated(client: TestClient) -> None:
    account = client.post("/api/youtube/accounts", json={"label": "Work"}).json()

    created = client.post(
        f"/api/youtube/accounts/{account['id']}/channels",
        json={"privacy": "unlisted", "category_id": "22", "auto_upload": True},
    )

    assert created.status_code == 201
    channel = created.json()
    assert channel["privacy"] == "unlisted"
    assert channel["category_id"] == "22"
    assert channel["auto_upload"] is True

    updated = client.put(
        f"/api/youtube/accounts/channels/{channel['id']}",
        json={"privacy": "public", "title_suffix": "shorts"},
    )
    assert updated.status_code == 200
    assert updated.json()["privacy"] == "public"
    assert updated.json()["title_suffix"] == "shorts"


def test_an_invalid_privacy_is_refused(client: TestClient) -> None:
    account = client.post("/api/youtube/accounts", json={"label": "Work"}).json()

    response = client.post(
        f"/api/youtube/accounts/{account['id']}/channels",
        json={"privacy": "secret"},
    )

    assert response.status_code == 400


def test_a_channel_can_be_removed(client: TestClient) -> None:
    account = client.post("/api/youtube/accounts", json={"label": "Work"}).json()
    channel = client.post(f"/api/youtube/accounts/{account['id']}/channels", json={}).json()

    removed = client.delete(f"/api/youtube/accounts/channels/{channel['id']}")

    assert removed.status_code == 204
    assert client.get(f"/api/youtube/accounts/{account['id']}/channels").json() == []


def test_a_channel_on_a_missing_account_is_a_404(client: TestClient) -> None:
    response = client.get("/api/youtube/accounts/nope/channels")

    assert response.status_code == 404


# --------------------------------------------------------------------------
# Routing
# --------------------------------------------------------------------------


def test_the_routing_categories_are_readable(client: TestClient) -> None:
    response = client.get("/api/routing/categories")

    assert response.status_code == 200
    body = response.json()
    assert "gaming" in body
    assert len(body) == 10


def test_the_rule_list_is_empty_to_begin_with(client: TestClient) -> None:
    response = client.get("/api/routing/rules")

    assert response.status_code == 200
    assert response.json() == []


def test_a_rule_needs_a_real_target_channel(client: TestClient) -> None:
    response = client.post(
        "/api/routing/rules",
        json={"match_keyword": "gaming", "target_channel_id": "nope"},
    )

    assert response.status_code == 404


def test_a_rule_needs_a_keyword(client: TestClient) -> None:
    account = client.post("/api/youtube/accounts", json={"label": "Work"}).json()
    channel = client.post(f"/api/youtube/accounts/{account['id']}/channels", json={}).json()

    response = client.post(
        "/api/routing/rules",
        json={"match_keyword": "   ", "target_channel_id": channel["id"]},
    )

    assert response.status_code == 400


def test_a_rule_can_be_created_updated_and_deleted(client: TestClient) -> None:
    account = client.post("/api/youtube/accounts", json={"label": "Work"}).json()
    channel = client.post(f"/api/youtube/accounts/{account['id']}/channels", json={}).json()

    created = client.post(
        "/api/routing/rules",
        json={
            "name": "Gaming clips",
            "match_keyword": "gaming",
            "target_channel_id": channel["id"],
            "priority": 10,
        },
    )

    assert created.status_code == 201
    rule = created.json()
    assert rule["match_keyword"] == "gaming"
    assert rule["target_channel_id"] == channel["id"]
    assert rule["priority"] == 10
    assert rule["enabled"] is True

    updated = client.put(
        f"/api/routing/rules/{rule['id']}", json={"enabled": False, "priority": 20}
    )
    assert updated.status_code == 200
    assert updated.json()["enabled"] is False
    assert updated.json()["priority"] == 20

    listed = client.get("/api/routing/rules").json()
    assert len(listed) == 1
    assert listed[0]["id"] == rule["id"]

    removed = client.delete(f"/api/routing/rules/{rule['id']}")
    assert removed.status_code == 204
    assert client.get("/api/routing/rules").json() == []


def test_a_missing_rule_is_a_404(client: TestClient) -> None:
    assert client.put("/api/routing/rules/nope", json={"priority": 1}).status_code == 404
    assert client.delete("/api/routing/rules/nope").status_code == 204

def test_an_unclassified_clip_has_no_classification(
    client: TestClient, source: Source
) -> None:
    from autoclip.db import store

    job = store.create_job(Job(id=new_id(), source_id=source.id, status="done"))
    clip = Clip(id=new_id(), job_id=job.id, start_s=0, end_s=10)
    store.replace_clips(job.id, [clip])

    response = client.get(f"/api/routing/clips/{clip.id}/classification")

    assert response.status_code == 404


# --------------------------------------------------------------------------
# Batches
# --------------------------------------------------------------------------


def test_the_batch_list_is_empty_to_begin_with(client: TestClient) -> None:
    response = client.get("/api/batches")

    assert response.status_code == 200
    assert response.json() == []


def test_a_batch_can_be_created_with_its_progress(client: TestClient) -> None:
    response = client.post("/api/batches", json={"name": "A run", "settings": {"max_clips": 2}})

    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "A run"
    assert body["settings"] == {"max_clips": 2}
    assert body["progress"]["total"] == 0
    assert body["progress"]["done"] == 0


def test_sources_can_be_added_to_a_batch(client: TestClient, source: Source) -> None:
    batch = client.post("/api/batches", json={"name": "A run"}).json()

    response = client.post(f"/api/batches/{batch['id']}/sources", json={"source_ids": [source.id]})

    assert response.status_code == 201
    assert response.json()["added"] == 1

    detail = client.get(f"/api/batches/{batch['id']}").json()
    assert detail["progress"]["total"] == 1
    assert detail["items"][0]["source_title"] == source.title


def test_an_unknown_source_is_refused(client: TestClient) -> None:
    batch = client.post("/api/batches", json={"name": "A run"}).json()

    response = client.post(f"/api/batches/{batch['id']}/sources", json={"source_ids": ["nope"]})

    assert response.status_code == 400


def test_a_batch_can_be_paused_and_cancelled(client: TestClient) -> None:
    batch = client.post("/api/batches", json={"name": "A run"}).json()

    launched = client.post(f"/api/batches/{batch['id']}/launch")
    assert launched.status_code == 200

    paused = client.post(f"/api/batches/{batch['id']}/pause")
    assert paused.status_code == 200

    cancelled = client.post(f"/api/batches/{batch['id']}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"


def test_a_batch_can_be_deleted(client: TestClient) -> None:
    batch = client.post("/api/batches", json={"name": "A run"}).json()

    removed = client.delete(f"/api/batches/{batch['id']}")

    assert removed.status_code == 204
    assert client.get("/api/batches").json() == []


def test_a_missing_batch_is_a_404(client: TestClient) -> None:
    assert client.get("/api/batches/nope").status_code == 404
    assert client.post("/api/batches/nope/launch").status_code == 404


# --------------------------------------------------------------------------
# Restarts
# --------------------------------------------------------------------------


def test_the_restart_endpoint_is_registered(client: TestClient) -> None:
    response = client.get("/api/restarts")

    assert response.status_code == 200
    body = response.json()
    assert "restarts" in body
    assert "latest" in body
    assert "restarts_with_work" in body
