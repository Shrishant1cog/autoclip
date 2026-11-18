"""Multi-account / multi-channel YouTube API.

Extends the original single-channel endpoints (which remain untouched and
keep working) with account and channel management.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .. import config
from ..youtube import accounts as accounts_store

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/youtube/accounts", tags=["youtube-accounts"])


class AccountIn(BaseModel):
    label: str = ""
    email: str = ""


class ChannelIn(BaseModel):
    privacy: str = "public"
    category_id: str = "24"
    auto_upload: bool = False
    is_default: bool | None = None


class ChannelUpdateIn(BaseModel):
    privacy: str | None = None
    category_id: str | None = None
    auto_upload: bool | None = None
    is_default: bool | None = None
    title: str | None = None


@router.get("")
async def list_all_accounts() -> list[dict]:
    """Every connected Google account with its channels and token status."""
    result = []
    for account in accounts_store.list_accounts():
        channels = accounts_store.list_channels(account["id"])
        has_token = accounts_store.refresh_token_for(account["id"]) is not None
        result.append(
            {
                **account,
                "has_refresh_token": has_token,
                "channels": channels,
            }
        )
    return result


@router.post("", status_code=201)
async def create_account(payload: AccountIn) -> dict:
    """Register an account slot. The OAuth flow attaches its token later."""
    return accounts_store.create_account(label=payload.label, email=payload.email)


@router.get("/{account_id}")
async def get_account(account_id: str) -> dict:
    account = accounts_store.get_account(account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="Account not found.")
    return {
        **account,
        "has_refresh_token": accounts_store.refresh_token_for(account_id) is not None,
        "channels": accounts_store.list_channels(account_id),
    }


@router.delete("/{account_id}", status_code=204)
async def delete_account(account_id: str) -> None:
    accounts_store.delete_account(account_id)


@router.get("/{account_id}/channels")
async def list_channels(account_id: str) -> list[dict]:
    if accounts_store.get_account(account_id) is None:
        raise HTTPException(status_code=404, detail="Account not found.")
    return accounts_store.list_channels(account_id)


@router.post("/{account_id}/channels", status_code=201)
async def add_channel(account_id: str, payload: ChannelIn) -> dict:
    """Register a channel under an account (manual entry or post-OAuth)."""
    if accounts_store.get_account(account_id) is None:
        raise HTTPException(status_code=404, detail="Account not found.")
    if payload.privacy not in ("private", "unlisted", "public"):
        raise HTTPException(status_code=400, detail="Invalid privacy value.")
    return accounts_store.add_channel(
        account_id,
        {"id": "", "title": "", "url": ""},
        is_default=payload.is_default,
        privacy=payload.privacy,
        category_id=payload.category_id,
        auto_upload=payload.auto_upload,
    )


@router.put("/channels/{channel_row_id}")
async def update_channel(channel_row_id: str, payload: ChannelUpdateIn) -> dict:
    fields = {k: v for k, v in payload.model_dump().items() if v is not None}
    updated = accounts_store.update_channel(channel_row_id, **fields)
    if updated is None:
        raise HTTPException(status_code=404, detail="Channel not found.")
    return updated


@router.delete("/channels/{channel_row_id}", status_code=204)
async def delete_channel(channel_row_id: str) -> None:
    accounts_store.delete_channel(channel_row_id)


@router.get("/channels/{channel_row_id}/routing")
async def channel_routing(channel_row_id: str) -> dict:
    """Effective upload policy for routing decisions."""
    channel = accounts_store.get_channel(channel_row_id)
    if channel is None:
        raise HTTPException(status_code=404, detail="Channel not found.")
    return {
        "channel_id": channel["channel_id"],
        "account_id": channel["account_id"],
        "privacy": channel["privacy"],
        "category_id": channel["category_id"],
        "auto_upload": channel["auto_upload"],
        "is_default": channel["is_default"],
    }


def _load_settings() -> config.Settings:
    return config.load()
