"""Background music library API (Phase 8)."""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile

from ..pipeline import music

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/music", tags=["music"])


@router.get("/tracks")
async def tracks() -> list[dict]:
    """Every track in ~/.autoclip/music/."""
    return music.list_tracks()


@router.post("/tracks", status_code=201)
async def upload_track(file: UploadFile) -> dict:
    """Add a track to the library."""
    if file.filename is None:
        raise HTTPException(status_code=400, detail="A filename is required.")
    suffix = Path(file.filename).suffix.lower()
    if suffix not in music.AUDIO_EXTENSIONS:
        allowed = ", ".join(sorted(music.AUDIO_EXTENSIONS))
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported audio type {suffix!r}. Allowed: {allowed}",
        )
    directory = music.music_dir()
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / Path(file.filename).name
    with target.open("wb") as out:
        shutil.copyfileobj(file.file, out)
    return {"name": target.name, "path": str(target)}


@router.delete("/tracks/{name}", status_code=204)
async def delete_track(name: str) -> None:
    target = (music.music_dir() / Path(name).name).resolve()
    if target.parent != music.music_dir().resolve() or not target.is_file():
        raise HTTPException(status_code=404, detail="Track not found.")
    target.unlink()
