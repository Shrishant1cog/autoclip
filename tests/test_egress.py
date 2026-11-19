"""Tests for the egress gateway and the consent layer.

The gateway is the seam every outbound request passes through, so these tests
are about behaviour a user can observe: a transfer is refused without consent,
allowed with it, recorded afterwards, and never silently rerouted to a
different provider.
"""

from __future__ import annotations

import pytest
from autoclip.providers.base import ProviderConsentRequired
from autoclip.security import consent
from autoclip.security.egress import (
    EgressGateway,
    MemoryLogSink,
    Transfer,
    redact,
)
from autoclip.security.urlpolicy import ConsentRequired, UrlRejected


def _resolver(mapping: dict[str, list[str]]):
    def resolve(host: str) -> list[str]:
        if host not in mapping:
            raise OSError(f"no such host: {host}")
        return mapping[host]

    return resolve


@pytest.fixture
def gateway() -> EgressGateway:
    """A gateway with in-memory consent and log stores."""
    sink = MemoryLogSink()
    gw = EgressGateway(store=consent.MemoryConsentStore(), log_sink=sink)
    gw.sink = sink  # type: ignore[attr-defined]
    return gw


# --------------------------------------------------------------------------
# Classification and consent
# --------------------------------------------------------------------------


def test_loopback_is_allowed_without_consent(gateway: EgressGateway):
    transfer = Transfer(
        operation=consent.Operation.HIGHLIGHTS,
        url="http://localhost:11434/v1",
        data_summary="Transcript text.",
    )
    permit = gateway.authorize(transfer)
    assert permit.allowed
    assert permit.destination_class == "loopback"


def test_public_transfer_is_refused_without_consent(gateway: EgressGateway):
    transfer = Transfer(
        operation=consent.Operation.HIGHLIGHTS,
        url="https://api.example.com/v1",
        data_summary="Transcript text.",
    )
    gateway.resolver = _resolver({"api.example.com": ["93.184.216.34"]})
    permit = gateway.authorize(transfer)
    assert not permit.allowed
    with pytest.raises(ConsentRequired):
        gateway.require(transfer)


def test_public_transfer_is_allowed_after_consent(gateway: EgressGateway):
    gateway.store.set(
        consent.ConsentDecision(
            operation=consent.Operation.HIGHLIGHTS,
            destination_class="public",
            granted=True,
            source="user",
        )
    )
    transfer = Transfer(
        operation=consent.Operation.HIGHLIGHTS,
        url="https://api.example.com/v1",
        data_summary="Transcript text.",
    )
    gateway.resolver = _resolver({"api.example.com": ["93.184.216.34"]})
    assert gateway.require(transfer).allowed


def test_withdrawn_consent_blocks_even_a_configured_transfer(gateway: EgressGateway):
    gateway.store.set(
        consent.ConsentDecision(
            operation=consent.Operation.HIGHLIGHTS,
            destination_class="public",
            granted=False,
            source="user",
        )
    )
    transfer = Transfer(
        operation=consent.Operation.HIGHLIGHTS,
        url="https://api.example.com/v1",
        data_summary="Transcript text.",
        configured=True,
    )
    gateway.resolver = _resolver({"api.example.com": ["93.184.216.34"]})
    assert not gateway.authorize(transfer).allowed


def test_configured_public_transfer_is_allowed_and_recorded(gateway: EgressGateway):
    """A destination the user configured keeps working, and the decision shows up."""
    transfer = Transfer(
        operation=consent.Operation.HIGHLIGHTS,
        url="https://api.example.com/v1",
        data_summary="Transcript text.",
        configured=True,
    )
    gateway.resolver = _resolver({"api.example.com": ["93.184.216.34"]})
    permit = gateway.authorize(transfer)
    assert permit.allowed
    assert permit.implied
    stored = gateway.store.get(consent.Operation.HIGHLIGHTS, "public")
    assert stored is not None
    assert stored.granted
    assert stored.source == "configured"


def test_private_transfer_is_never_allowed_implicitly(gateway: EgressGateway):
    """A private address has to be granted, even when the user configured it."""
    transfer = Transfer(
        operation=consent.Operation.HIGHLIGHTS,
        url="http://10.0.0.5/v1",
        data_summary="Transcript text.",
        configured=True,
    )
    permit = gateway.authorize(transfer)
    assert not permit.allowed
    assert permit.destination_class == "private"


def test_changing_the_destination_reclassifies(gateway: EgressGateway):
    """Consent is for a class, so a base_url that moves to a private host stops."""
    gateway.store.set(
        consent.ConsentDecision(
            operation=consent.Operation.HIGHLIGHTS,
            destination_class="public",
            granted=True,
            source="user",
        )
    )
    gateway.resolver = _resolver({"api.example.com": ["93.184.216.34"]})
    public = Transfer(
        operation=consent.Operation.HIGHLIGHTS,
        url="https://api.example.com/v1",
        data_summary="Transcript text.",
    )
    private = Transfer(
        operation=consent.Operation.HIGHLIGHTS,
        url="http://10.0.0.9/v1",
        data_summary="Transcript text.",
    )
    assert gateway.authorize(public).allowed
    assert not gateway.authorize(private).allowed


def test_a_refused_url_is_rejected_outright(gateway: EgressGateway):
    transfer = Transfer(
        operation=consent.Operation.MEDIA_DOWNLOAD,
        url="http://169.254.169.254/latest/meta-data/",
        data_summary="A page.",
        requires_consent=False,
    )
    with pytest.raises(UrlRejected):
        gateway.authorize(transfer)


# --------------------------------------------------------------------------
# Logging
# --------------------------------------------------------------------------


def test_a_successful_transfer_is_recorded(gateway: EgressGateway):
    transfer = Transfer(
        operation=consent.Operation.HIGHLIGHTS,
        url="https://api.example.com/v1",
        data_summary="Transcript text.",
        configured=True,
    )
    gateway.resolver = _resolver({"api.example.com": ["93.184.216.34"]})
    gateway.record(transfer, "ok")
    assert len(gateway.sink.records) == 1  # type: ignore[attr-defined]
    record = gateway.sink.records[0]  # type: ignore[attr-defined]
    assert record.outcome == "ok"
    assert record.destination_class == "public"
    assert record.data_summary == "Transcript text."


def test_the_log_never_stores_a_credential(gateway: EgressGateway):
    transfer = Transfer(
        operation=consent.Operation.HIGHLIGHTS,
        url="https://api.example.com/v1?api_key=sk-secret-value",
        data_summary="Transcript text.",
        configured=True,
    )
    gateway.resolver = _resolver({"api.example.com": ["93.184.216.34"]})
    gateway.record(transfer, "ok", detail="Authorization: Bearer sk-secret-value")
    record = gateway.sink.records[0]  # type: ignore[attr-defined]
    assert "sk-secret-value" not in record.destination
    assert "sk-secret-value" not in record.detail


def test_redact_masks_credential_shaped_text():
    assert "sk-secret" not in redact("api_key=sk-secret")
    assert "hunter2" not in redact("password: hunter2")
    assert "abc123" not in redact("Authorization: Bearer abc123")


# --------------------------------------------------------------------------
# The provider seam
# --------------------------------------------------------------------------


def test_provider_refuses_an_unconsented_destination():
    from autoclip.providers.openai_provider import OpenAIProvider

    provider = OpenAIProvider("gpt-4o", api_key="k", base_url="http://10.0.0.7/v1")
    with pytest.raises(ProviderConsentRequired):
        provider._authorize("Transcript text.")


def test_provider_knows_its_sdk_default_endpoint():
    from autoclip.providers.anthropic_provider import AnthropicProvider
    from autoclip.providers.gemini_provider import GeminiProvider
    from autoclip.providers.openai_provider import OpenAIProvider

    assert OpenAIProvider("m").endpoint == "https://api.openai.com/v1"
    assert AnthropicProvider("m").endpoint == "https://api.anthropic.com"
    assert GeminiProvider("m").endpoint == "https://generativelanguage.googleapis.com"


def test_a_refused_external_provider_does_not_fall_back_to_another_external_one(
    monkeypatch: pytest.MonkeyPatch,
):
    """The consent refusal must not be answered by trying the next vendor."""
    import asyncio

    from autoclip.config import Settings
    from autoclip.providers import resolver
    from autoclip.providers.base import ProviderConsentRequired
    from autoclip.providers.presets import ProviderPreset

    attempted: list[str] = []

    def fake_build(preset, settings, **kwargs):  # noqa: ANN001, ANN003
        attempted.append(preset.key)

        class _Refusing:
            name = preset.key
            endpoint = "http://10.0.0.7/v1"

            async def generate_text(self, system, user, *, temperature=0.4):  # noqa: ANN001
                raise ProviderConsentRequired(
                    "refused", provider=preset.key, hint="allow it in Settings"
                )

        return _Refusing()

    monkeypatch.setattr(resolver, "build_preset_provider", fake_build)

    first = ProviderPreset(
        key="first",
        label="First",
        adapter="openai",
        default_model="m",
        capabilities=("text",),
    )
    second = ProviderPreset(
        key="second",
        label="Second",
        adapter="openai",
        default_model="m",
        capabilities=("text",),
    )
    monkeypatch.setattr(
        resolver, "resolve_chain", lambda task, settings, override_chain=None: [first, second]
    )

    settings = Settings()
    with pytest.raises(resolver.AllProvidersFailedError):
        asyncio.run(resolver.run_with_fallback("highlights", "sys", "user", settings))

    # The second external provider was never contacted.
    assert attempted == ["first"]


def test_a_refused_external_provider_may_fall_back_to_a_local_one(
    monkeypatch: pytest.MonkeyPatch,
):
    """Local inference sends nothing anywhere, so it is an acceptable answer."""
    import asyncio

    from autoclip.config import Settings
    from autoclip.providers import resolver
    from autoclip.providers.base import ProviderConsentRequired
    from autoclip.providers.presets import ProviderPreset

    attempted: list[str] = []

    class _Local:
        name = "local"

        async def generate_text(self, system, user, *, temperature=0.4):  # noqa: ANN001
            return '{"clips": []}'

    def fake_build(preset, settings, **kwargs):  # noqa: ANN001, ANN003
        attempted.append(preset.key)
        if preset.is_local:
            return _Local()

        class _Refusing:
            name = preset.key

            async def generate_text(self, system, user, *, temperature=0.4):  # noqa: ANN001
                raise ProviderConsentRequired("refused", provider=preset.key)

        return _Refusing()

    monkeypatch.setattr(resolver, "build_preset_provider", fake_build)

    hosted = ProviderPreset(
        key="hosted",
        label="Hosted",
        adapter="openai",
        default_model="m",
        capabilities=("text",),
    )
    local = ProviderPreset(
        key="local",
        label="Local",
        adapter="ollama",
        default_model="m",
        capabilities=("text",),
        is_local=True,
    )
    monkeypatch.setattr(
        resolver, "resolve_chain", lambda task, settings, override_chain=None: [hosted, local]
    )

    settings = Settings()
    output, label = asyncio.run(resolver.run_with_fallback("highlights", "sys", "user", settings))
    assert output == '{"clips": []}'
    assert label == "Local"
    assert attempted == ["hosted", "local"]


# --------------------------------------------------------------------------
# The consent store
# --------------------------------------------------------------------------


def test_consent_decisions_survive_a_round_trip(initialised_db: int):
    consent.grant(consent.Operation.TRANSCRIPTION, "public", note="ok")
    decisions = {(d.operation, d.destination_class): d for d in consent.list_decisions()}
    decision = decisions[(consent.Operation.TRANSCRIPTION, "public")]
    assert decision.granted
    assert decision.note == "ok"


def test_revoking_consent_is_recorded(initialised_db: int):
    consent.grant(consent.Operation.VOICEOVER, "public")
    consent.revoke(consent.Operation.VOICEOVER, "public")
    assert not consent.has_consent(consent.Operation.VOICEOVER, "public")


def test_the_transfer_log_is_append_only(initialised_db: int):
    from autoclip.db import connection

    consent.log_transfer(
        consent.TransferRecord(
            operation=consent.Operation.HIGHLIGHTS,
            destination="https://api.example.com/v1",
            destination_class="public",
            outcome="ok",
            data_summary="Transcript text.",
        )
    )
    with connection() as conn:
        rows = conn.execute("SELECT outcome, data_summary FROM egress_log").fetchall()
    assert len(rows) == 1
    assert rows[0]["outcome"] == "ok"
    assert rows[0]["data_summary"] == "Transcript text."


# --------------------------------------------------------------------------
# The API
# --------------------------------------------------------------------------


def test_the_consent_api_lists_every_operation(initialised_db: int):
    from autoclip.app import create_app
    from fastapi.testclient import TestClient

    with TestClient(create_app()) as client:
        response = client.get("/api/privacy/consents")
    assert response.status_code == 200
    operations = response.json()
    names = {operation["operation"] for operation in operations}
    assert "transcription" in names
    assert "highlights" in names
    for operation in operations:
        assert operation["data"]
        assert operation["why"]
        classes = {decision["destination_class"] for decision in operation["decisions"]}
        assert classes == {"public", "private"}


def test_the_consent_api_records_a_decision(initialised_db: int):
    from autoclip.app import create_app
    from fastapi.testclient import TestClient

    with TestClient(create_app()) as client:
        response = client.put(
            "/api/privacy/consents",
            json={
                "operation": "transcription",
                "destination_class": "public",
                "granted": True,
            },
        )
    assert response.status_code == 200
    operations = {operation["operation"]: operation for operation in response.json()}
    decisions = {
        decision["destination_class"]: decision
        for decision in operations["transcription"]["decisions"]
    }
    assert decisions["public"]["granted"] is True
    assert decisions["public"]["source"] == "user"


def test_the_consent_api_refuses_a_loopback_decision(initialised_db: int):
    """Loopback is not a choice — offering it would suggest it can be denied."""
    from autoclip.app import create_app
    from fastapi.testclient import TestClient

    with TestClient(create_app()) as client:
        response = client.put(
            "/api/privacy/consents",
            json={"operation": "transcription", "destination_class": "loopback", "granted": True},
        )
    assert response.status_code == 400


def test_the_consent_api_refuses_an_unknown_operation(initialised_db: int):
    from autoclip.app import create_app
    from fastapi.testclient import TestClient

    with TestClient(create_app()) as client:
        response = client.put(
            "/api/privacy/consents",
            json={"operation": "exfiltrate", "destination_class": "public", "granted": True},
        )
    assert response.status_code == 400


def test_the_transfer_api_returns_the_log(initialised_db: int):
    from autoclip.app import create_app
    from fastapi.testclient import TestClient

    consent.log_transfer(
        consent.TransferRecord(
            operation=consent.Operation.HIGHLIGHTS,
            destination="https://api.example.com/v1",
            destination_class="public",
            outcome="ok",
            data_summary="Transcript text.",
        )
    )
    with TestClient(create_app()) as client:
        response = client.get("/api/privacy/transfers")
    assert response.status_code == 200
    transfers = response.json()
    assert len(transfers) == 1
    assert transfers[0]["data_summary"] == "Transcript text."
    assert transfers[0]["destination_class"] == "public"
