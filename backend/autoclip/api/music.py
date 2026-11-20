"""The music library API.

Four things live here:

* the **library** — folders the user pointed AutoClip at, and the tracks in
  them, with their measurements and their licence;
* the **analysis** — a track measured locally, once;
* the **licence** — what the user knows about a track's rights, which gates
  the export;
* the **preview** — streaming a track in the browser, and the ducking
  envelope the Settings screen draws.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, Response

from ..music import library as music_library
from ..music import store as music_store
from ..music.licensing import USER_SETTABLE_STATES, LicenseRecord, LicenseState
from ..pipeline import music

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/music", tags=["music"])

#: The legacy library directory is small; the preview is read from disk.
CHUNK_SIZE = 64 * 1024


# --------------------------------------------------------------------------
# The existing upload/list/delete surface
# --------------------------------------------------------------------------


@router.get("/tracks")
async def tracks() -> list[dict]:
    """Every track in the library.

    The legacy ``~/.autoclip/music/`` directory is indexed on the way out, so
    a file dropped there shows up without a separate scan.
    """
    music_library.scan(folder=music.music_dir())
    return [entry.to_dict() for entry in music_library.list_tracks()]


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
    music_store.upsert_track(target)
    return {"name": target.name, "path": str(target)}


@router.delete("/tracks/{name}", status_code=204)
async def delete_track(name: str) -> None:
    """Remove an uploaded track from AutoClip's own music directory."""
    target = (music.music_dir() / Path(name).name).resolve()
    if target.parent != music.music_dir().resolve() or not target.is_file():
        raise HTTPException(status_code=404, detail="Track not found.")
    target.unlink()
    music_store.delete_track(music_store.track_id_for(target))


# --------------------------------------------------------------------------
# The library
# --------------------------------------------------------------------------


@router.get("/library")
async def library_listing(
    q: str = "",
    mood: str = "",
    min_bpm: float | None = None,
    max_bpm: float | None = None,
    licence: str = "",
    favourite: bool = False,
    tag: str = "",
) -> list[dict]:
    """The library, filtered server-side."""
    music_library.scan(folder=music.music_dir())
    entries = music_library.search(
        query=q,
        mood=mood,
        min_bpm=min_bpm,
        max_bpm=max_bpm,
        licence_state=licence,
        favourite_only=favourite,
        tag=tag,
    )
    return [entry.to_dict() for entry in entries]


@router.get("/folders")
async def folders() -> list[dict]:
    """The folders the library reads from."""
    return [folder.to_dict() for folder in music_store.list_folders()]


@router.post("/folders", status_code=201)
async def add_folder(payload: dict) -> dict:
    """Point AutoClip at a local folder of music.

    The files are not copied and not moved: the folder is indexed where it
    stands.
    """
    raw = str(payload.get("path", "")).strip()
    if not raw:
        raise HTTPException(status_code=400, detail="A folder path is required.")
    path = Path(raw).expanduser()
    if not path.is_dir():
        raise HTTPException(status_code=400, detail=f"{path} is not a folder.")
    folder = music_store.add_folder(path)
    report = music_library.scan(folder=path)
    return {"folder": folder.to_dict(), "scan": report.to_dict()}


@router.delete("/folders/{folder_id}", status_code=204)
async def remove_folder(folder_id: str) -> None:
    """Stop reading a folder. The tracks stay in the library."""
    music_store.remove_folder(folder_id)


@router.post("/scan")
async def scan() -> dict:
    """Re-scan the library."""
    report = music_library.scan()
    return report.to_dict()


@router.delete("/library/{track_id}", status_code=204)
async def remove_from_library(track_id: str) -> None:
    """Remove a track from the library.

    The file itself is untouched — AutoClip does not delete the user's music.
    """
    if music_store.get_track(track_id) is None:
        raise HTTPException(status_code=404, detail="Track not found.")
    music_store.delete_track(track_id)


@router.post("/library/{track_id}/flags")
async def set_flags(track_id: str, payload: dict) -> dict:
    """Favourite, exclude, tag or rename a track."""
    track = music_store.get_track(track_id)
    if track is None:
        raise HTTPException(status_code=404, detail="Track not found.")

    favourite = payload.get("favourite")
    excluded = payload.get("excluded")
    tags = payload.get("tags")
    title = payload.get("title")
    artist = payload.get("artist")

    updated = music_store.set_track_flags(
        track_id,
        favourite=bool(favourite) if isinstance(favourite, bool) else None,
        excluded=bool(excluded) if isinstance(excluded, bool) else None,
        tags=str(tags) if isinstance(tags, str) else None,
        title=str(title) if isinstance(title, str) else None,
        artist=str(artist) if isinstance(artist, str) else None,
    )
    assert updated is not None
    return updated.to_dict()


@router.post("/library/{track_id}/analyse")
async def analyse(track_id: str, force: bool = False) -> dict:
    """Measure a track locally."""
    if music_store.get_track(track_id) is None:
        raise HTTPException(status_code=404, detail="Track not found.")
    try:
        track = music_library.analyse(track_id, force=force)
    except Exception as exc:  # noqa: BLE001 - an unreadable file is a 400, not a 500
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return track.to_dict()


# --------------------------------------------------------------------------
# Licensing
# --------------------------------------------------------------------------


@router.put("/library/{track_id}/licence")
async def set_licence(track_id: str, payload: dict) -> dict:
    """Record what the user knows about a track's rights.

    The 'verified' state is not accepted here. Independent verification is
    not something a user can assert about their own files, and letting them
    set it would turn an attestation into a certification.
    """
    if music_store.get_track(track_id) is None:
        raise HTTPException(status_code=404, detail="Track not found.")

    state = str(payload.get("state", LicenseState.UNKNOWN)).strip()
    if state not in USER_SETTABLE_STATES:
        allowed = ", ".join(USER_SETTABLE_STATES)
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unknown licence state {state!r}. Use one of: {allowed}. "
                "'verified' is set by an independent check, not from here."
            ),
        )

    record = LicenseRecord(
        track_id=track_id,
        state=state,
        source=str(payload.get("source", ""))[:200],
        evidence=str(payload.get("evidence", ""))[:1000],
        attribution=str(payload.get("attribution", ""))[:500],
        commercial_use=bool(payload.get("commercial_use", False)),
        non_commercial=bool(payload.get("non_commercial", False)),
        derivative=bool(payload.get("derivative", False)),
        share_alike=bool(payload.get("share_alike", False)),
        expires_at=str(payload.get("expires_at", ""))[:10],
    )
    music_store.set_license(record)
    return record.to_dict()


@router.get("/library/{track_id}/licence")
async def get_licence(track_id: str) -> dict:
    """What is known about a track's rights."""
    return music_store.get_license(track_id).to_dict()


# --------------------------------------------------------------------------
# Preview
# --------------------------------------------------------------------------


@router.get("/library/{track_id}/audio")
async def preview(track_id: str, request: Request) -> Response:
    """Stream a track for preview.

    Range requests are answered, so the browser can seek without downloading
    the whole file.
    """
    track = music_store.get_track(track_id)
    if track is None:
        raise HTTPException(status_code=404, detail="Track not found.")
    path = Path(track.path)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="The file is no longer there.")

    size = path.stat().st_size
    headers = {"Accept-Ranges": "bytes"}
    range_header = request.headers.get("range")
    if range_header:
        start, end = _parse_range(range_header, size)
        if start is None:
            raise HTTPException(status_code=416, detail="Bad range.")
        headers["Content-Range"] = f"bytes {start}-{end}/{size}"
        headers["Content-Length"] = str(end - start + 1)
        return Response(
            content=_read_range(path, start, end),
            media_type="application/octet-stream",
            status_code=206,
            headers=headers,
        )

    return FileResponse(path, media_type="application/octet-stream", headers=headers)


def _parse_range(header: str, size: int) -> tuple[int | None, int]:
    """Parse a single-range ``Range`` header."""
    try:
        raw = header.split("=", 1)[1].split(",")[0].strip()
        if raw.startswith("-"):
            length = int(raw[1:])
            if length <= 0:
                return (None, 0)
            start = max(0, size - length)
            end = size - 1
        else:
            start_text, _, end_text = raw.partition("-")
            start = int(start_text)
            end = int(end_text) if end_text else size - 1
    except (IndexError, ValueError):
        return (None, 0)
    if start >= size or start > end:
        return (None, 0)
    return (start, min(end, size - 1))


def _read_range(path: Path, start: int, end: int) -> bytes:
    with path.open("rb") as handle:
        handle.seek(start)
        return handle.read(end - start + 1)


# --------------------------------------------------------------------------
# The ducking envelope
# --------------------------------------------------------------------------


@router.get("/envelope")
async def envelope(job_id: str = "", start_s: float = 0.0, end_s: float = 0.0) -> dict:
    """The music-ducking envelope for a job's source.

    This is what the Settings screen draws: where the bed drops, by how much,
    and when it comes back up.
    """
    from ..config import load as load_settings
    from ..db import store
    from ..paths import job_work_dir
    from ..pipeline.speech_timeline import SpeechTimeline, envelope_points

    if not job_id:
        raise HTTPException(status_code=400, detail="A job id is required.")

    job = store.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")

    timeline_path = job_work_dir(job_id) / "speech_timeline.json"
    if not timeline_path.is_file():
        raise HTTPException(
            status_code=404,
            detail="This job has no speech timeline yet. Process the video first.",
        )
    timeline = SpeechTimeline.load(timeline_path)

    settings = load_settings()
    export_settings = settings.export
    if end_s <= start_s:
        end_s = timeline.duration_s

    points = envelope_points(
        timeline,
        start_s=start_s,
        end_s=end_s,
        duck_db=export_settings.ducking_amount_db,
        attack_ms=export_settings.ducking_attack_ms,
        release_ms=export_settings.ducking_release_ms,
    )
    return {
        "job_id": job_id,
        "start_s": start_s,
        "end_s": end_s,
        "duck_db": export_settings.ducking_amount_db,
        "points": [{"t": t, "gain": gain} for t, gain in points],
        "intervals": [interval.to_dict() for interval in timeline.slice(start_s, end_s)],
    }
