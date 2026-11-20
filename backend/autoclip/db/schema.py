"""SQLite schema and migrations.

Migrations are driven by SQLite's ``user_version`` pragma: each entry in
:data:`MIGRATIONS` moves the database forward one version. Applying them is
idempotent, so :func:`migrate` runs safely on every startup.

We use raw ``sqlite3`` rather than an ORM. The schema is six small tables read
by one local process, so an ORM would add a dependency and a layer of
indirection without buying anything.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable

_V1 = """
CREATE TABLE sources (
    id          TEXT PRIMARY KEY,
    type        TEXT NOT NULL CHECK (type IN ('youtube', 'upload')),
    url         TEXT,
    filename    TEXT,
    path        TEXT NOT NULL,
    title       TEXT NOT NULL DEFAULT '',
    channel     TEXT,
    duration_s  REAL NOT NULL DEFAULT 0,
    width       INTEGER,
    height      INTEGER,
    fps         REAL,
    has_audio   INTEGER NOT NULL DEFAULT 1,
    has_video   INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT NOT NULL
);

CREATE TABLE jobs (
    id            TEXT PRIMARY KEY,
    source_id     TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    status        TEXT NOT NULL CHECK (status IN ('queued','running','failed','done','cancelled')),
    current_stage TEXT NOT NULL DEFAULT '',
    progress      REAL NOT NULL DEFAULT 0,
    error         TEXT,
    provider      TEXT NOT NULL DEFAULT '',
    settings_json TEXT NOT NULL DEFAULT '{}',
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL,
    started_at    TEXT,
    finished_at   TEXT
);
CREATE INDEX idx_jobs_source ON jobs(source_id);
CREATE INDEX idx_jobs_status ON jobs(status);

CREATE TABLE transcripts (
    job_id          TEXT PRIMARY KEY REFERENCES jobs(id) ON DELETE CASCADE,
    json_path       TEXT NOT NULL,
    language        TEXT NOT NULL DEFAULT '',
    model           TEXT NOT NULL DEFAULT '',
    has_diarization INTEGER NOT NULL DEFAULT 0,
    word_count      INTEGER NOT NULL DEFAULT 0,
    source          TEXT NOT NULL DEFAULT 'whisper',
    created_at      TEXT NOT NULL
);

CREATE TABLE clips (
    id           TEXT PRIMARY KEY,
    job_id       TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    rank         INTEGER NOT NULL DEFAULT 0,
    start_s      REAL NOT NULL,
    end_s        REAL NOT NULL,
    start_word   INTEGER NOT NULL DEFAULT 0,
    end_word     INTEGER NOT NULL DEFAULT 0,
    title        TEXT NOT NULL DEFAULT '',
    hook         TEXT NOT NULL DEFAULT '',
    score        INTEGER NOT NULL DEFAULT 0,
    reason       TEXT NOT NULL DEFAULT '',
    status       TEXT NOT NULL DEFAULT 'candidate'
                 CHECK (status IN ('candidate','kept','discarded','exported')),
    user_trimmed INTEGER NOT NULL DEFAULT 0,
    created_at   TEXT NOT NULL
);
CREATE INDEX idx_clips_job ON clips(job_id, rank);

CREATE TABLE clip_edits (
    clip_id           TEXT PRIMARY KEY REFERENCES clips(id) ON DELETE CASCADE,
    edited_words_json TEXT,
    caption_style     TEXT NOT NULL DEFAULT 'bold_pop',
    ratio             TEXT NOT NULL DEFAULT '9:16',
    updated_at        TEXT NOT NULL
);

CREATE TABLE exports (
    id         TEXT PRIMARY KEY,
    clip_id    TEXT NOT NULL REFERENCES clips(id) ON DELETE CASCADE,
    path       TEXT NOT NULL,
    ratio      TEXT NOT NULL DEFAULT '9:16',
    style      TEXT NOT NULL DEFAULT 'bold_pop',
    size_bytes INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE INDEX idx_exports_clip ON exports(clip_id);
"""


def _migration_v1(conn: sqlite3.Connection) -> None:
    conn.executescript(_V1)


_V2 = """
CREATE TABLE youtube_uploads (
    id          TEXT PRIMARY KEY,
    export_id   TEXT NOT NULL REFERENCES exports(id) ON DELETE CASCADE,
    clip_id     TEXT NOT NULL REFERENCES clips(id) ON DELETE CASCADE,
    status      TEXT NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending','uploading','done','failed')),
    video_id    TEXT,
    title       TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    tags_json   TEXT NOT NULL DEFAULT '[]',
    privacy     TEXT NOT NULL DEFAULT 'public',
    error       TEXT,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE UNIQUE INDEX idx_youtube_uploads_export ON youtube_uploads(export_id);
CREATE INDEX idx_youtube_uploads_status ON youtube_uploads(status);
"""


def _migration_v2(conn: sqlite3.Connection) -> None:
    conn.executescript(_V2)


#: SQLite cannot widen a CHECK constraint in place, so the table is rebuilt.
#: ``skipped`` is a deliberate end state: the worker found this row would
#: duplicate an existing upload and stopped before touching YouTube.
_V3 = """
CREATE TABLE youtube_uploads_v3 (
    id          TEXT PRIMARY KEY,
    export_id   TEXT NOT NULL REFERENCES exports(id) ON DELETE CASCADE,
    clip_id     TEXT NOT NULL REFERENCES clips(id) ON DELETE CASCADE,
    status      TEXT NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending','uploading','done','failed','skipped')),
    video_id    TEXT,
    title       TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    tags_json   TEXT NOT NULL DEFAULT '[]',
    privacy     TEXT NOT NULL DEFAULT 'public',
    error       TEXT,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
INSERT INTO youtube_uploads_v3 (
    id, export_id, clip_id, status, video_id, title, description,
    tags_json, privacy, error, created_at, updated_at
)
SELECT id, export_id, clip_id, status, video_id, title, description,
       tags_json, privacy, error, created_at, updated_at
FROM youtube_uploads;
DROP TABLE youtube_uploads;
ALTER TABLE youtube_uploads_v3 RENAME TO youtube_uploads;
CREATE UNIQUE INDEX idx_youtube_uploads_export ON youtube_uploads(export_id);
CREATE INDEX idx_youtube_uploads_status ON youtube_uploads(status);
"""


def _migration_v3(conn: sqlite3.Connection) -> None:
    conn.executescript(_V3)


# --------------------------------------------------------------------------
# V4 — workflow engine (Phase 2, autonomous-platform)
# --------------------------------------------------------------------------

_V4 = """
-- Persisted workflow definitions. A workflow is a graph of nodes; the
-- existing six-stage pipeline is exposed as the built-in "autoclip_job"
-- workflow. Versioning: a new row with the same key and version+1.
CREATE TABLE workflows (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    definition  TEXT NOT NULL DEFAULT '{}',
    version     INTEGER NOT NULL DEFAULT 1,
    active      INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE UNIQUE INDEX idx_workflows_active ON workflows(name, active) WHERE active = 1;

-- One row per workflow run. job_id links to the production jobs table when
-- the execution drives a video job; NULL for utility workflows.
CREATE TABLE workflow_runs (
    id           TEXT PRIMARY KEY,
    workflow_id  TEXT NOT NULL REFERENCES workflows(id) ON DELETE CASCADE,
    job_id       TEXT REFERENCES jobs(id) ON DELETE SET NULL,
    status       TEXT NOT NULL DEFAULT 'running'
                 CHECK (status IN ('running','succeeded','failed','cancelled')),
    trigger      TEXT NOT NULL DEFAULT 'manual',
    started_at   TEXT NOT NULL,
    finished_at  TEXT,
    error        TEXT
);
CREATE INDEX idx_workflow_runs_workflow ON workflow_runs(workflow_id, started_at);
CREATE INDEX idx_workflow_runs_status ON workflow_runs(status);

-- Node-level execution record: real timing, state and payload inspection.
CREATE TABLE workflow_node_runs (
    id          TEXT PRIMARY KEY,
    run_id      TEXT NOT NULL REFERENCES workflow_runs(id) ON DELETE CASCADE,
    node_id     TEXT NOT NULL,
    node_type   TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending','running','succeeded','failed','skipped')),
    attempt     INTEGER NOT NULL DEFAULT 1,
    input_json  TEXT,
    output_json TEXT,
    error       TEXT,
    started_at  TEXT,
    finished_at TEXT
);
CREATE INDEX idx_workflow_node_runs_run ON workflow_node_runs(run_id, started_at);
"""


def _migration_v4(conn: sqlite3.Connection) -> None:
    conn.executescript(_V4)


# --------------------------------------------------------------------------
# V5 — multi Google-account / multi YouTube-channel (Phase 4)
# --------------------------------------------------------------------------

_V5 = """
-- One row per connected Google account. The refresh token lives in the OS
-- keyring under ``youtube_refresh#<account_id>``; the legacy bare entry maps
-- to whichever account migrated first.
CREATE TABLE google_accounts (
    id           TEXT PRIMARY KEY,
    label        TEXT NOT NULL DEFAULT '',
    email        TEXT NOT NULL DEFAULT '',
    client_id    TEXT NOT NULL DEFAULT '',
    connected_at TEXT NOT NULL DEFAULT '',
    created_at   TEXT NOT NULL
);

-- One row per YouTube channel, bound to a Google account. Channel-specific
-- defaults ride along so routing can apply per-channel policies.
CREATE TABLE youtube_channels (
    id             TEXT PRIMARY KEY,
    account_id     TEXT NOT NULL REFERENCES google_accounts(id) ON DELETE CASCADE,
    channel_id     TEXT NOT NULL,
    title          TEXT NOT NULL DEFAULT '',
    url            TEXT NOT NULL DEFAULT '',
    is_default     INTEGER NOT NULL DEFAULT 0,
    -- Channel profile: defaults applied when routing uploads here.
    privacy        TEXT NOT NULL DEFAULT 'public'
                   CHECK (privacy IN ('private','unlisted','public')),
    category_id    TEXT NOT NULL DEFAULT '24',
    auto_upload    INTEGER NOT NULL DEFAULT 0,
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL
);
CREATE UNIQUE INDEX idx_youtube_channels_channel ON youtube_channels(account_id, channel_id);
CREATE INDEX idx_youtube_channels_default ON youtube_channels(is_default);
"""

# The old single-account refresh token keyring entry. Imported on connect.
LEGACY_REFRESH_KEY = "youtube_refresh_token"


def _migration_v5(conn: sqlite3.Connection) -> None:
    conn.executescript(_V5)


# --------------------------------------------------------------------------
# V6 — content classification & routing rules (Phase 5)
# --------------------------------------------------------------------------

_V6 = """
-- AI classification of a clip's content: which audience/category it fits.
CREATE TABLE content_classifications (
    id          TEXT PRIMARY KEY,
    clip_id     TEXT NOT NULL REFERENCES clips(id) ON DELETE CASCADE,
    category    TEXT NOT NULL DEFAULT '',
    confidence  REAL NOT NULL DEFAULT 0,
    provider    TEXT NOT NULL DEFAULT '',
    reason      TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL
);
CREATE INDEX idx_classifications_clip ON content_classifications(clip_id, created_at);

-- User-defined routing: classification keyword -> target channel profile.
-- Evaluated in priority order (lower number = earlier); first enabled match wins.
CREATE TABLE routing_rules (
    id            TEXT PRIMARY KEY,
    name          TEXT NOT NULL DEFAULT '',
    match_keyword TEXT NOT NULL,
    target_channel_id TEXT NOT NULL REFERENCES youtube_channels(id) ON DELETE CASCADE,
    priority      INTEGER NOT NULL DEFAULT 100,
    enabled       INTEGER NOT NULL DEFAULT 1,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);
CREATE INDEX idx_routing_rules_priority ON routing_rules(enabled, priority);
"""


def _migration_v6(conn: sqlite3.Connection) -> None:
    conn.executescript(_V6)


# --------------------------------------------------------------------------
# V7 — persistent batch queues (Phase 6)
# --------------------------------------------------------------------------

_V7 = """
CREATE TABLE batches (
    id           TEXT PRIMARY KEY,
    name         TEXT NOT NULL DEFAULT '',
    status       TEXT NOT NULL DEFAULT 'queued'
                 CHECK (status IN ('queued','running','paused','done','failed','cancelled')),
    settings_json TEXT NOT NULL DEFAULT '{}',
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);

CREATE TABLE batch_items (
    id          TEXT PRIMARY KEY,
    batch_id    TEXT NOT NULL REFERENCES batches(id) ON DELETE CASCADE,
    source_id   TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    job_id      TEXT REFERENCES jobs(id) ON DELETE SET NULL,
    position    INTEGER NOT NULL DEFAULT 0,
    status      TEXT NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending','processing','done','failed','skipped','cancelled')),
    error       TEXT,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE INDEX idx_batch_items_batch ON batch_items(batch_id, position);
"""


def _migration_v7(conn: sqlite3.Connection) -> None:
    conn.executescript(_V7)


# --- v8: clip validation reports -------------------------------------------

_V8 = """
PRAGMA foreign_keys = OFF;
CREATE TABLE clips_new (
    id              TEXT PRIMARY KEY,
    job_id          TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    rank            INTEGER NOT NULL DEFAULT 0,
    start_s         REAL NOT NULL,
    end_s           REAL NOT NULL,
    start_word      INTEGER NOT NULL DEFAULT 0,
    end_word        INTEGER NOT NULL DEFAULT 0,
    title           TEXT NOT NULL DEFAULT '',
    hook            TEXT NOT NULL DEFAULT '',
    score           INTEGER NOT NULL DEFAULT 0,
    reason          TEXT NOT NULL DEFAULT '',
    status          TEXT NOT NULL DEFAULT 'candidate'
                    CHECK (status IN ('candidate','kept','discarded','exported','invalid')),
    user_trimmed    INTEGER NOT NULL DEFAULT 0,
    validation_json TEXT NOT NULL DEFAULT '',
    created_at      TEXT NOT NULL
);
INSERT INTO clips_new (id, job_id, rank, start_s, end_s, start_word, end_word,
                       title, hook, score, reason, status, user_trimmed, created_at)
SELECT id, job_id, rank, start_s, end_s, start_word, end_word,
       title, hook, score, reason, status, user_trimmed, created_at
FROM clips;
DROP TABLE clips;
ALTER TABLE clips_new RENAME TO clips;
CREATE INDEX idx_clips_job ON clips(job_id, rank);
PRAGMA foreign_keys = ON;
"""


def _migration_v8(conn: sqlite3.Connection) -> None:
    conn.executescript(_V8)


# --- v9: multi-channel publishing fan-out (Phase 10) -----------------------

_V9 = """
PRAGMA foreign_keys = OFF;
-- One upload row per (export, channel). Channel '' means the legacy default.
CREATE TABLE youtube_uploads_v9 (
    id             TEXT PRIMARY KEY,
    export_id      TEXT NOT NULL REFERENCES exports(id) ON DELETE CASCADE,
    clip_id        TEXT NOT NULL REFERENCES clips(id) ON DELETE CASCADE,
    channel_row_id TEXT NOT NULL DEFAULT '',
    status         TEXT NOT NULL DEFAULT 'pending'
                   CHECK (status IN ('pending','uploading','done','failed','skipped')),
    video_id       TEXT,
    title          TEXT NOT NULL DEFAULT '',
    description    TEXT NOT NULL DEFAULT '',
    tags_json      TEXT NOT NULL DEFAULT '[]',
    privacy        TEXT NOT NULL DEFAULT 'public',
    error          TEXT,
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL
);
INSERT INTO youtube_uploads_v9 (
    id, export_id, clip_id, channel_row_id, status, video_id, title, description,
    tags_json, privacy, error, created_at, updated_at
)
SELECT id, export_id, clip_id, '', status, video_id, title, description,
       tags_json, privacy, error, created_at, updated_at
FROM youtube_uploads;
DROP TABLE youtube_uploads;
ALTER TABLE youtube_uploads_v9 RENAME TO youtube_uploads;
CREATE UNIQUE INDEX idx_youtube_uploads_export_channel
    ON youtube_uploads(export_id, channel_row_id);
CREATE INDEX idx_youtube_uploads_status ON youtube_uploads(status);

-- Per-channel publishing profile additions.
ALTER TABLE youtube_channels ADD COLUMN title_suffix TEXT NOT NULL DEFAULT '';

-- A rule may fan a clip out to additional channels besides its primary target.
ALTER TABLE routing_rules ADD COLUMN extra_channel_ids_json TEXT NOT NULL DEFAULT '[]';
PRAGMA foreign_keys = ON;
"""


def _migration_v9(conn: sqlite3.Connection) -> None:
    conn.executescript(_V9)


# --- v10: notification centre (Phase 14) ------------------------------------

_V10 = """
-- One row per user-visible event. The notification centre is local-first:
-- nothing is pushed anywhere; the rows are the inbox.
CREATE TABLE notifications (
    id         TEXT PRIMARY KEY,
    kind       TEXT NOT NULL DEFAULT '',
    severity   TEXT NOT NULL DEFAULT 'info'
               CHECK (severity IN ('info','success','warning','error')),
    title      TEXT NOT NULL DEFAULT '',
    body       TEXT NOT NULL DEFAULT '',
    link       TEXT NOT NULL DEFAULT '',
    entity_id  TEXT NOT NULL DEFAULT '',
    read       INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE INDEX idx_notifications_created ON notifications(created_at);
CREATE INDEX idx_notifications_unread ON notifications(read, created_at);
"""


def _migration_v10(conn: sqlite3.Connection) -> None:
    conn.executescript(_V10)


# --- v11: per-job resource usage (Phase 16) --------------------------------

_V11 = """
-- What each job actually consumed (Phase 16).
--
-- Every number here is measured, not estimated: the token counts are what the
-- provider reported, the ffmpeg seconds are the wall clock around the real
-- process. A cost control that cannot be measured is a cost control nobody
-- trusts.
CREATE TABLE job_resources (
    job_id           TEXT PRIMARY KEY REFERENCES jobs(id) ON DELETE CASCADE,
    llm_calls        INTEGER NOT NULL DEFAULT 0,
    llm_input_tokens INTEGER NOT NULL DEFAULT 0,
    llm_output_tokens INTEGER NOT NULL DEFAULT 0,
    ffmpeg_runs      INTEGER NOT NULL DEFAULT 0,
    ffmpeg_seconds   REAL NOT NULL DEFAULT 0,
    export_bytes     INTEGER NOT NULL DEFAULT 0,
    windows_skipped  INTEGER NOT NULL DEFAULT 0,
    updated_at       TEXT NOT NULL
);
"""


def _migration_v11(conn: sqlite3.Connection) -> None:
    conn.executescript(_V11)


# --- v12: restart recovery (Phase 17) ---------------------------------------

_V12 = """
-- When AutoClip restarts, work that was in flight is resumed automatically.
--
-- That is the right behaviour, but it used to be invisible: the job simply
-- carried on as if nothing had happened, and the user had no way to learn
-- that a restart had interrupted it (or that it had to start a stage again
-- because the interruption happened mid-stage).
--
-- These columns and table make the restart visible. The counts are the real
-- numbers of rows that were recovered, not a summary of an estimate.
ALTER TABLE jobs ADD COLUMN last_resumed_at TEXT;
ALTER TABLE youtube_uploads ADD COLUMN last_resumed_at TEXT;

CREATE TABLE app_restarts (
    id                  TEXT PRIMARY KEY,
    started_at          TEXT NOT NULL,
    jobs_resumed        INTEGER NOT NULL DEFAULT 0,
    uploads_resumed     INTEGER NOT NULL DEFAULT 0,
    batch_items_resumed INTEGER NOT NULL DEFAULT 0,
    job_ids_json        TEXT NOT NULL DEFAULT '[]',
    upload_ids_json     TEXT NOT NULL DEFAULT '[]',
    details             TEXT NOT NULL DEFAULT ''
);
CREATE INDEX idx_app_restarts_started ON app_restarts(started_at);
"""


def _migration_v12(conn: sqlite3.Connection) -> None:
    conn.executescript(_V12)


# --- v13: repair the job timestamps (Phase 17 audit) ------------------------

_V13 = """
-- Repair the job finish times an older build could leave wrong.
--
-- Three ways it went wrong, all in the job state machine:
--
--   * cancelling a job that was still queued never stamped a finish time,
--     so a finished job looked like one still in flight;
--   * retrying a job kept the previous attempt's finish time, so the row
--     claimed it had finished before the retry even started;
--   * a job whose source had gone missing was marked failed without one.
--
-- For a job in a terminal state the last write *is* the transition into
-- that state — nothing updates a finished job afterwards — so the row's own
-- updated_at is the moment it finished. And a job that is queued or running
-- has not finished at all, so any finish time on it is a leftover.
UPDATE jobs
SET finished_at = updated_at
WHERE status IN ('done', 'failed', 'cancelled')
  AND (finished_at IS NULL OR finished_at < updated_at);

UPDATE jobs
SET finished_at = NULL
WHERE status IN ('queued', 'running')
  AND finished_at IS NOT NULL;
"""


def _migration_v13(conn: sqlite3.Connection) -> None:
    conn.executescript(_V13)


# --- v14: a cancelled transcription was reported as a failure ----------------

_V14 = """
-- An older build reported a cancelled transcription as a failed job.
--
-- The speech layer raised its cancellation as an ordinary engine error, so
-- the runner recorded the job as failed and — worse — fell back to another
-- engine, which would have started a second transcription for a job the
-- user had asked to stop.
--
-- The error text is the fingerprint: only the cancellation path produces it.
-- A job that failed for any other reason keeps its status.
UPDATE jobs
SET status = 'cancelled'
WHERE status = 'failed'
  AND error = 'Transcription cancelled.';
"""


def _migration_v14(conn: sqlite3.Connection) -> None:
    conn.executescript(_V14)


# --- v15: external-transfer consent and the egress log ---------------------

_V15 = """
-- Two tables for the M0.5 governance layer.
--
-- egress_consents records the user's answer to "may this operation reach a
-- host of this class?". The key is (operation, destination_class) rather
-- than a hostname on purpose: a consent decision is about the *kind* of
-- destination, and a base_url that changes from a public host to a private
-- one must stop matching the public decision.
--
-- egress_log records what actually happened. It is append-only and holds no
-- content - only a description of what left, where it went, and whether the
-- call succeeded.
CREATE TABLE IF NOT EXISTS egress_consents (
    operation         TEXT NOT NULL,
    destination_class TEXT NOT NULL,
    granted           INTEGER NOT NULL DEFAULT 0,
    source            TEXT NOT NULL DEFAULT '',
    decided_at        TEXT NOT NULL,
    note              TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (operation, destination_class)
);

CREATE TABLE IF NOT EXISTS egress_log (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    occurred_at       TEXT NOT NULL,
    operation         TEXT NOT NULL,
    provider          TEXT NOT NULL DEFAULT '',
    destination       TEXT NOT NULL DEFAULT '',
    destination_class TEXT NOT NULL DEFAULT '',
    data_summary      TEXT NOT NULL DEFAULT '',
    outcome           TEXT NOT NULL,
    detail            TEXT NOT NULL DEFAULT '',
    duration_ms       INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_egress_log_occurred_at ON egress_log(occurred_at);
"""


def _migration_v15(conn: sqlite3.Connection) -> None:
    conn.executescript(_V15)


# --- v16: the music library -------------------------------------------------

_V16 = """
-- The music library is an index of files the user already owns. AutoClip never
-- copies them and never uploads them: the path is the identity, and the file
-- stays where the user put it.
--
-- music_folders records the folders the user pointed AutoClip at.
CREATE TABLE IF NOT EXISTS music_folders (
    id       TEXT PRIMARY KEY,
    path     TEXT NOT NULL UNIQUE,
    added_at TEXT NOT NULL
);

-- music_tracks is one row per audio file found in those folders. The analysis
-- column holds the measured metadata as JSON; it is empty until the track has
-- been analysed, and it is keyed by the file's size and mtime so an unchanged
-- file is never analysed twice.
CREATE TABLE IF NOT EXISTS music_tracks (
    id          TEXT PRIMARY KEY,
    path        TEXT NOT NULL UNIQUE,
    folder_id   TEXT NOT NULL DEFAULT '',
    name        TEXT NOT NULL,
    title       TEXT NOT NULL DEFAULT '',
    artist      TEXT NOT NULL DEFAULT '',
    tags        TEXT NOT NULL DEFAULT '',
    format      TEXT NOT NULL DEFAULT '',
    size_bytes  INTEGER NOT NULL DEFAULT 0,
    mtime       REAL NOT NULL DEFAULT 0,
    duration_s  REAL NOT NULL DEFAULT 0,
    analysis_at TEXT NOT NULL DEFAULT '',
    analysis    TEXT NOT NULL DEFAULT '{}',
    excluded    INTEGER NOT NULL DEFAULT 0,
    favourite   INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_music_tracks_name ON music_tracks(name);
CREATE INDEX IF NOT EXISTS idx_music_tracks_folder ON music_tracks(folder_id);

-- music_licenses records what the user knows about a track's rights.
--
-- The state vocabulary is deliberately narrow, and 'verified' cannot be set
-- from the UI: independent verification is not something a user can assert
-- about themselves. A user's own confirmation is 'user_confirmed', which is
-- weaker, and the export gate treats the two differently.
CREATE TABLE IF NOT EXISTS music_licenses (
    track_id       TEXT PRIMARY KEY,
    state          TEXT NOT NULL DEFAULT 'unknown',
    source         TEXT NOT NULL DEFAULT '',
    evidence       TEXT NOT NULL DEFAULT '',
    attribution    TEXT NOT NULL DEFAULT '',
    commercial_use INTEGER NOT NULL DEFAULT 0,
    non_commercial INTEGER NOT NULL DEFAULT 0,
    derivative     INTEGER NOT NULL DEFAULT 0,
    share_alike    INTEGER NOT NULL DEFAULT 0,
    expires_at     TEXT NOT NULL DEFAULT '',
    verified_by    TEXT NOT NULL DEFAULT '',
    verified_at    TEXT NOT NULL DEFAULT '',
    updated_at     TEXT NOT NULL
);
"""


def _migration_v16(conn: sqlite3.Connection) -> None:
    conn.executescript(_V16)


# --- v17: per-source layouts ------------------------------------------------

_V17 = """
-- One row per source video: what the detector found, and what the user chose.
--
-- The detected columns are a record of the last detection run. They are kept
-- so the settings page can say what was found and why, and so a re-render
-- does not have to run detection again to show the user the region.
--
-- The override columns are the user's own choice. An empty variant means
-- 'no override': the automatic planner decides. A manual layout always
-- wins over the automatic one, so it is stored separately rather than
-- overwriting what the detector found.
--
-- Nothing here identifies anybody. The rectangle is a region of pixels and
-- the confidence is a number; there is no face template and no name.
CREATE TABLE IF NOT EXISTS source_layouts (
    source_id           TEXT PRIMARY KEY,
    variant             TEXT NOT NULL DEFAULT '',
    rect_x              REAL NOT NULL DEFAULT 0,
    rect_y              REAL NOT NULL DEFAULT 0,
    rect_width          REAL NOT NULL DEFAULT 0,
    rect_height         REAL NOT NULL DEFAULT 0,
    position            TEXT NOT NULL DEFAULT '',
    scale               REAL NOT NULL DEFAULT 0,
    detected_x          REAL NOT NULL DEFAULT 0,
    detected_y          REAL NOT NULL DEFAULT 0,
    detected_width      REAL NOT NULL DEFAULT 0,
    detected_height     REAL NOT NULL DEFAULT 0,
    detected_confidence REAL NOT NULL DEFAULT 0,
    detected_face_width REAL NOT NULL DEFAULT 0,
    detected_reason     TEXT NOT NULL DEFAULT '',
    detected_at         TEXT NOT NULL DEFAULT '',
    updated_at          TEXT NOT NULL
);
"""


def _migration_v17(conn: sqlite3.Connection) -> None:
    conn.executescript(_V17)


# --- v18: the AI call budget ---------------------------------------------------

_V18 = """
-- job_ai_budget records how many AI calls one job made and how many it was
-- allowed.
--
-- The approved budget is one creative-planning call, one repair retry, and
-- up to one music-selection call per eligible clip. With the default of ten
-- clips that is twelve calls.
--
-- The counters are in the database rather than in memory so that retrying a
-- failed job does not hand it a fresh allowance.
--
-- 'overruns' holds the refusals as JSON: a list of {category, reason}. A
-- silently capped budget reads exactly like a budget that was never
-- needed, so the refusals are written down.
CREATE TABLE IF NOT EXISTS job_ai_budget (
    job_id                 TEXT PRIMARY KEY,
    plan_limit            INTEGER NOT NULL DEFAULT 1,
    plan_used             INTEGER NOT NULL DEFAULT 0,
    repair_limit          INTEGER NOT NULL DEFAULT 1,
    repair_used           INTEGER NOT NULL DEFAULT 0,
    music_limit           INTEGER NOT NULL DEFAULT 0,
    music_used            INTEGER NOT NULL DEFAULT 0,
    overruns              TEXT NOT NULL DEFAULT '[]',
    user_approved_overrides INTEGER NOT NULL DEFAULT 0,
    updated_at            TEXT NOT NULL
);
"""


def _migration_v18(conn: sqlite3.Connection) -> None:
    conn.executescript(_V18)


MIGRATIONS: list[Callable[[sqlite3.Connection], None]] = [
    _migration_v1,
    _migration_v2,
    _migration_v3,
    _migration_v4,
    _migration_v5,
    _migration_v6,
    _migration_v7,
    _migration_v8,
    _migration_v9,
    _migration_v10,
    _migration_v11,
    _migration_v12,
    _migration_v13,
    _migration_v14,
    _migration_v15,
    _migration_v16,
    _migration_v17,
    _migration_v18,
]

SCHEMA_VERSION = len(MIGRATIONS)


def migrate(conn: sqlite3.Connection) -> int:
    """Apply any outstanding migrations. Returns the resulting schema version."""
    current: int = conn.execute("PRAGMA user_version").fetchone()[0]

    if current > SCHEMA_VERSION:
        raise RuntimeError(
            f"Database schema version {current} is newer than this AutoClip "
            f"build supports ({SCHEMA_VERSION}). Upgrade AutoClip."
        )

    for version in range(current, SCHEMA_VERSION):
        migration = MIGRATIONS[version]
        with conn:
            migration(conn)
            # PRAGMA doesn't accept bound parameters; version is loop-controlled.
            conn.execute(f"PRAGMA user_version = {version + 1}")

    return SCHEMA_VERSION
