-- Morphism SRS: proposed SQLite schema, version 1
-- Target: SQLite >= 3.38 (JSON functions and STRICT tables).
-- Design: a note groups ordered cards; each card owns title/front/back.
-- A note may appear in multiple courses; graph position belongs to course membership.
-- Review logs are historical facts, not part of the mutable FSRS state.

-- Run these when opening EVERY connection (foreign_keys, busy_timeout).
PRAGMA foreign_keys = ON;
PRAGMA busy_timeout = 5000;
-- Set once on the database file, outside an explicit transaction.
PRAGMA journal_mode = WAL;

BEGIN;

-- Import provenance is optional. A single import can create many notes and cards.
CREATE TABLE import_batches (
    id                  INTEGER PRIMARY KEY,
    source              TEXT NOT NULL DEFAULT 'manual', -- manual, ai, json, ...
    label               TEXT NOT NULL DEFAULT '',
    model_name          TEXT,
    metadata_json       TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(metadata_json)),
    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
) STRICT;

-- Course folders are purely organizational, NOT themselves courses.
CREATE TABLE course_folders (
    id                  INTEGER PRIMARY KEY,
    parent_id           INTEGER REFERENCES course_folders(id) ON DELETE RESTRICT,
    name                TEXT NOT NULL CHECK (length(trim(name)) > 0),
    sort_order          INTEGER NOT NULL DEFAULT 0,
    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    CHECK (parent_id IS NULL OR parent_id <> id)
) STRICT;
CREATE UNIQUE INDEX uq_folder_siblings
    ON course_folders(coalesce(parent_id, -1), name COLLATE NOCASE);

CREATE TABLE courses (
    id                  INTEGER PRIMARY KEY,
    folder_id           INTEGER REFERENCES course_folders(id) ON DELETE SET NULL,
    title               TEXT NOT NULL CHECK (length(trim(title)) > 0),
    description         TEXT NOT NULL DEFAULT '',
    sort_order          INTEGER NOT NULL DEFAULT 0,
    archived_at         TEXT,
    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
) STRICT;
CREATE UNIQUE INDEX uq_course_names_in_folder
    ON courses(coalesce(folder_id, -1), title COLLATE NOCASE);

-- The note is an organizational/review object. It has NO shared front/back.
-- Keep mode independent of card format and of mathematics-content classification.
CREATE TABLE notes (
    id                  INTEGER PRIMARY KEY,    -- can preserve existing 64-bit note IDs
    title               TEXT NOT NULL CHECK (length(trim(title)) > 0),
    review_mode         TEXT NOT NULL DEFAULT 'standard'
                        CHECK (review_mode IN ('standard','serial_sequence','serial_sequence_single')),
    content_kind        TEXT,                   -- optional: theorem, definition, example, ...
    desired_retention   REAL NOT NULL DEFAULT 0.85
                        CHECK (desired_retention > 0 AND desired_retention <= 1),
    import_batch_id     INTEGER REFERENCES import_batches(id) ON DELETE SET NULL,
    archived_at         TEXT,
    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
) STRICT;

-- Notes are reusable across courses. X/Y live HERE, not in the note itself.
CREATE TABLE course_notes (
    course_id           INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    note_id             INTEGER NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
    x                   REAL NOT NULL DEFAULT 0,
    y                   REAL NOT NULL DEFAULT 0,
    sort_order          INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (course_id, note_id)
) STRICT;
CREATE INDEX ix_course_notes_by_note ON course_notes(note_id);
CREATE INDEX ix_course_notes_order ON course_notes(course_id, sort_order, note_id);

-- All ordinary cards preserve title/front/back. 'proof_sequence' is an
-- OPTIONAL presentation mode with finer-grained child steps in card_steps.
-- 'position' determines note-level Serial Sequence order as well as UI order.
CREATE TABLE cards (
    id                  INTEGER PRIMARY KEY,    -- can preserve existing item_id
    note_id             INTEGER NOT NULL REFERENCES notes(id) ON DELETE RESTRICT,
    position            INTEGER NOT NULL DEFAULT 0 CHECK (position >= 0),
    card_type           TEXT NOT NULL DEFAULT 'flashcard'
                        CHECK (card_type IN ('flashcard','proof_sequence')),
    content_version     INTEGER NOT NULL DEFAULT 1 CHECK (content_version >= 1),
    title               TEXT NOT NULL DEFAULT '',
    front               TEXT NOT NULL DEFAULT '',
    back                TEXT NOT NULL DEFAULT '',
    import_batch_id     INTEGER REFERENCES import_batches(id) ON DELETE SET NULL,
    archived_at         TEXT,
    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
) STRICT;
CREATE INDEX ix_cards_note_position ON cards(note_id, position, id);
CREATE INDEX ix_cards_import_batch ON cards(import_batch_id);

-- Optional append-only snapshots when a card's content changes. Increments
-- cards.content_version and allows old reviews to be matched to old prompts.
CREATE TABLE card_revisions (
    card_id             INTEGER NOT NULL REFERENCES cards(id) ON DELETE CASCADE,
    version             INTEGER NOT NULL CHECK (version >= 1),
    card_type           TEXT NOT NULL,
    title               TEXT NOT NULL,
    front               TEXT NOT NULL,
    back                TEXT NOT NULL,
    steps_json          TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(steps_json)),
    recorded_at         TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    PRIMARY KEY (card_id, version)
) STRICT;

-- Steps INSIDE a ProofSequenceCard are distinct from multiple cards in a
-- serial note. Normal cards simply have no card_steps rows.
CREATE TABLE card_steps (
    card_id             INTEGER NOT NULL REFERENCES cards(id) ON DELETE CASCADE,
    step_number         INTEGER NOT NULL CHECK (step_number >= 1),
    body                TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (card_id, step_number)
) STRICT;

-- Graph edges. A NULL scope_course_id means GLOBAL; a non-NULL value means
-- specific to one course (which preserves the current per-course edges).
-- Whether endpoints belong to that course must be validated by app logic.
CREATE TABLE note_links (
    id                  INTEGER PRIMARY KEY,
    source_note_id      INTEGER NOT NULL REFERENCES notes(id) ON DELETE RESTRICT,
    target_note_id      INTEGER NOT NULL REFERENCES notes(id) ON DELETE RESTRICT,
    scope_course_id     INTEGER REFERENCES courses(id) ON DELETE CASCADE,
    relation_type       TEXT NOT NULL DEFAULT 'prerequisite', -- or related, uses, interferes
    label               TEXT NOT NULL DEFAULT '',
    strength            REAL CHECK (strength IS NULL OR (strength >= 0 AND strength <= 1)),
    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    CHECK (source_note_id <> target_note_id),
    -- Nullable scope bypasses these composite FKs for global links.
    -- Scoped links require both endpoints to belong to that course.
    FOREIGN KEY (scope_course_id, source_note_id)
        REFERENCES course_notes(course_id, note_id) ON DELETE CASCADE,
    FOREIGN KEY (scope_course_id, target_note_id)
        REFERENCES course_notes(course_id, note_id) ON DELETE CASCADE
) STRICT;
CREATE UNIQUE INDEX uq_note_links_scope_relation
    ON note_links(source_note_id, target_note_id, relation_type,
                  coalesce(scope_course_id,-1));
CREATE INDEX ix_links_target ON note_links(target_note_id);
CREATE INDEX ix_links_by_course ON note_links(scope_course_id);

CREATE TABLE tags (
    id                  INTEGER PRIMARY KEY,
    name                TEXT NOT NULL COLLATE NOCASE UNIQUE
                        CHECK (length(trim(name)) > 0)
) STRICT;
CREATE TABLE note_tags (
    note_id             INTEGER NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
    tag_id              INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    PRIMARY KEY (note_id, tag_id)
) STRICT;
CREATE INDEX ix_note_tags_tag ON note_tags(tag_id);

-- Mutable CURRENT scheduling state: one row per card.
-- Keep library-specific scheduler serialization losslessly in JSON so
-- future FSRS versions or alternative schedulers need not rewrite tables.
CREATE TABLE card_schedules (
    card_id             INTEGER PRIMARY KEY REFERENCES cards(id) ON DELETE CASCADE,
    scheduler_name      TEXT NOT NULL DEFAULT 'fsrs',
    scheduler_version   TEXT,
    due_at              TEXT,                   -- UTC ISO-8601 sortable string
    last_review_at      TEXT,
    stability           REAL,
    difficulty          REAL,
    scheduler_state_json TEXT NOT NULL DEFAULT '{}'
                         CHECK (json_valid(scheduler_state_json)),
    updated_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
) STRICT;
CREATE INDEX ix_card_schedules_due ON card_schedules(due_at);

-- A session groups step reviews from one serial note (or a global review).
CREATE TABLE review_sessions (
    id                  INTEGER PRIMARY KEY,
    course_id           INTEGER REFERENCES courses(id) ON DELETE SET NULL,
    note_id             INTEGER REFERENCES notes(id) ON DELETE SET NULL,
    mode                TEXT NOT NULL DEFAULT 'standard',
    started_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    ended_at            TEXT
) STRICT;
CREATE INDEX ix_sessions_note_time ON review_sessions(note_id, started_at);

-- APPEND-ONLY FACTS. Never replace these when recomputing FSRS schedules.
-- Preserve all fields in current ReviewLogRecord, plus optional context
-- for research on conditional recall and later scheduler comparisons.
CREATE TABLE review_logs (
    id                  INTEGER PRIMARY KEY,
    card_id             INTEGER NOT NULL REFERENCES cards(id) ON DELETE RESTRICT,
    session_id          INTEGER REFERENCES review_sessions(id) ON DELETE SET NULL,
    reviewed_at         TEXT NOT NULL,           -- UTC ISO-8601
    rating              INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 4),
    elapsed_days        INTEGER,
    scheduled_days      INTEGER,
    fsrs_state          INTEGER,
    stability           REAL,
    difficulty          REAL,
    scheduler_name      TEXT NOT NULL DEFAULT 'fsrs',
    scheduler_version   TEXT,
    card_content_version INTEGER NOT NULL DEFAULT 1 CHECK (card_content_version >= 1),
    sequence_position   INTEGER CHECK (sequence_position IS NULL OR sequence_position >= 0),
    hint_count          INTEGER CHECK (hint_count IS NULL OR hint_count >= 0),
    response_time_ms    INTEGER CHECK (response_time_ms IS NULL OR response_time_ms >= 0),
    prompt_context_json TEXT CHECK (prompt_context_json IS NULL OR json_valid(prompt_context_json)),
    state_before_json   TEXT CHECK (state_before_json IS NULL OR json_valid(state_before_json)),
    state_after_json    TEXT CHECK (state_after_json IS NULL OR json_valid(state_after_json))
) STRICT;
CREATE INDEX ix_logs_card_time ON review_logs(card_id, reviewed_at);
CREATE INDEX ix_logs_session ON review_logs(session_id);
CREATE INDEX ix_logs_time ON review_logs(reviewed_at);

-- Track schema version for forward migrations.
PRAGMA user_version = 1;
COMMIT;

-- Recommended application invariants (not enforced above):
-- 1. course_folders must be acyclic (not just non-self-parenting).
-- 2. course-scoped link endpoints are enforced by composite foreign keys.
-- 3. insert/update card + card_schedules + review_logs atomically per review.
-- 4. prefer archival over hard delete when cards have review logs.
-- 5. render note-level serials using ORDER BY cards.position, cards.id.
-- 6. maintain timestamps in a single canonical UTC format.
-- 7. record the old card content in card_revisions BEFORE modifying it.
-- 8. never store or execute untrusted AI-generated HTML as privileged app code.
