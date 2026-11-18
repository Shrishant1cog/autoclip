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


#: Ordered migrations. Index + 1 is the resulting ``user_version``.
#: Append only — never edit a migration that has shipped.
MIGRATIONS: list[Callable[[sqlite3.Connection], None]] = [
    _migration_v1,
    _migration_v2,
    _migration_v3,
    _migration_v4,
    _migration_v5,
    _migration_v6,
    _migration_v7,
    _migration_v8,
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
