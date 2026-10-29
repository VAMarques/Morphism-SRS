-- ============================================================================
-- Morphism SRS Prototype 2 — Canonical SQLite Schema (Version 2)
-- Target: SQLite >= 3.38 (STRICT tables, FTS5, Recursive CTEs, WAL)
-- ============================================================================

CREATE TABLE IF NOT EXISTS app_meta (
    key         TEXT PRIMARY KEY,
    value_json  TEXT NOT NULL
) STRICT;

CREATE TABLE IF NOT EXISTS course_folders (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid                TEXT NOT NULL UNIQUE,
    name                TEXT NOT NULL CHECK (length(trim(name)) > 0),
    parent_id           INTEGER REFERENCES course_folders(id) ON DELETE SET NULL,
    display_order       INTEGER NOT NULL DEFAULT 0,
    is_expanded         INTEGER NOT NULL DEFAULT 1 CHECK (is_expanded IN (0, 1)),
    fsrs_weights_json   TEXT,
    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    CHECK (parent_id IS NULL OR parent_id <> id)
) STRICT;

CREATE TRIGGER IF NOT EXISTS trg_course_folders_prevent_cycles
BEFORE UPDATE OF parent_id ON course_folders
WHEN NEW.parent_id IS NOT NULL
BEGIN
    SELECT RAISE(ABORT, 'Cycle detected in course_folders hierarchy')
    WHERE EXISTS (
        WITH RECURSIVE ancestors(fid) AS (
            SELECT NEW.parent_id
            UNION ALL
            SELECT cf.parent_id FROM course_folders cf
            JOIN ancestors a ON cf.id = a.fid
            WHERE cf.parent_id IS NOT NULL
        )
        SELECT 1 FROM ancestors WHERE fid = OLD.id
    );
END;

CREATE TABLE IF NOT EXISTS courses (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid                TEXT NOT NULL UNIQUE,
    name                TEXT NOT NULL UNIQUE CHECK (length(trim(name)) > 0),
    folder_id           INTEGER REFERENCES course_folders(id) ON DELETE SET NULL,
    description         TEXT NOT NULL DEFAULT '',
    color_hex           TEXT NOT NULL DEFAULT '#89b4fa',
    desired_retention   REAL NOT NULL DEFAULT 0.80 CHECK (desired_retention >= 0.70 AND desired_retention <= 0.99),
    display_order       INTEGER NOT NULL DEFAULT 0,
    is_archived         INTEGER NOT NULL DEFAULT 0 CHECK (is_archived IN (0, 1)),
    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
) STRICT;

CREATE INDEX IF NOT EXISTS idx_courses_folder ON courses(folder_id, display_order);

CREATE TABLE IF NOT EXISTS notes (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid                TEXT NOT NULL UNIQUE,
    course_id           INTEGER REFERENCES courses(id) ON DELETE SET NULL,
    external_key        TEXT,
    title               TEXT NOT NULL CHECK (length(trim(title)) > 0),
    premise_html        TEXT NOT NULL DEFAULT '',
    pos_x               REAL NOT NULL DEFAULT 0.0,
    pos_y               REAL NOT NULL DEFAULT 0.0,
    review_mode         TEXT NOT NULL DEFAULT 'standard' CHECK (review_mode IN ('standard', 'serial', 'cloze')),
    desired_retention   REAL CHECK (desired_retention IS NULL OR (desired_retention >= 0.70 AND desired_retention <= 0.99)),
    is_pinned           INTEGER NOT NULL DEFAULT 0 CHECK (is_pinned IN (0, 1)),
    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE (course_id, external_key)
) STRICT;

CREATE INDEX IF NOT EXISTS idx_notes_course ON notes(course_id);
CREATE INDEX IF NOT EXISTS idx_notes_mode ON notes(review_mode);

CREATE TABLE IF NOT EXISTS course_notes (
    course_id           INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    note_id             INTEGER NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
    pos_x               REAL NOT NULL DEFAULT 0.0,
    pos_y               REAL NOT NULL DEFAULT 0.0,
    is_pinned           INTEGER NOT NULL DEFAULT 0 CHECK (is_pinned IN (0, 1)),
    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    PRIMARY KEY (course_id, note_id)
) STRICT;

CREATE INDEX IF NOT EXISTS idx_course_notes_course ON course_notes(course_id);
CREATE INDEX IF NOT EXISTS idx_course_notes_note ON course_notes(note_id);

CREATE TABLE IF NOT EXISTS cards (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid                TEXT NOT NULL UNIQUE,
    note_id             INTEGER NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
    step_order          INTEGER NOT NULL DEFAULT 0 CHECK (step_order >= 0),
    title               TEXT NOT NULL DEFAULT '',
    front_html          TEXT NOT NULL DEFAULT '',
    back_html           TEXT NOT NULL DEFAULT '',
    hint_html           TEXT NOT NULL DEFAULT '',
    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
) STRICT;

CREATE INDEX IF NOT EXISTS idx_cards_note_step ON cards(note_id, step_order);

CREATE TABLE IF NOT EXISTS card_schedules (
    card_id             INTEGER PRIMARY KEY REFERENCES cards(id) ON DELETE CASCADE,
    state               INTEGER NOT NULL DEFAULT 0 CHECK (state IN (0, 1, 2, 3)),
    step                INTEGER DEFAULT 0,
    stability           REAL,
    difficulty          REAL,
    due_at              TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    last_review_at      TEXT,
    reps                INTEGER NOT NULL DEFAULT 0,
    lapses              INTEGER NOT NULL DEFAULT 0,
    scheduled_days      INTEGER NOT NULL DEFAULT 0,
    elapsed_days        INTEGER NOT NULL DEFAULT 0,
    is_suspended        INTEGER NOT NULL DEFAULT 0 CHECK (is_suspended IN (0, 1)),
    is_buried           INTEGER NOT NULL DEFAULT 0 CHECK (is_buried IN (0, 1))
) STRICT;

CREATE INDEX IF NOT EXISTS idx_schedules_due ON card_schedules(is_suspended, is_buried, state, due_at);

CREATE TRIGGER IF NOT EXISTS trg_cards_auto_schedule
AFTER INSERT ON cards
BEGIN
    INSERT OR IGNORE INTO card_schedules (card_id, state, step, due_at)
    VALUES (NEW.id, 0, 0, NEW.created_at);
END;

CREATE TABLE IF NOT EXISTS edges (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid                TEXT NOT NULL UNIQUE,
    course_id           INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    source_note_id      INTEGER NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
    target_note_id      INTEGER NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
    label               TEXT NOT NULL DEFAULT '',
    weight              REAL NOT NULL DEFAULT 1.0,
    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    CHECK (source_note_id <> target_note_id),
    UNIQUE (source_note_id, target_note_id)
) STRICT;

CREATE INDEX IF NOT EXISTS idx_edges_course ON edges(course_id);
CREATE INDEX IF NOT EXISTS idx_edges_source ON edges(source_note_id);
CREATE INDEX IF NOT EXISTS idx_edges_target ON edges(target_note_id);

CREATE TABLE IF NOT EXISTS tags (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    name                TEXT NOT NULL COLLATE NOCASE UNIQUE CHECK (length(trim(name)) > 0),
    category            TEXT NOT NULL DEFAULT 'general',
    scope               TEXT NOT NULL DEFAULT 'standard',
    color_hex           TEXT NOT NULL DEFAULT '#cba6f7'
) STRICT;

CREATE TABLE IF NOT EXISTS note_tags (
    note_id             INTEGER NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
    tag_id              INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    PRIMARY KEY (note_id, tag_id)
) STRICT;

CREATE INDEX IF NOT EXISTS idx_note_tags_tag ON note_tags(tag_id);

CREATE TABLE IF NOT EXISTS review_logs (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid                TEXT NOT NULL UNIQUE,
    card_id             INTEGER NOT NULL REFERENCES cards(id) ON DELETE CASCADE,
    rating              INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 4),
    reviewed_at         TEXT NOT NULL,
    duration_ms         INTEGER NOT NULL DEFAULT 0,
    prev_state          INTEGER NOT NULL DEFAULT 0,
    prev_step           INTEGER,
    prev_stability      REAL,
    prev_difficulty     REAL,
    prev_due_at         TEXT,
    prev_last_review_at TEXT,
    new_state           INTEGER NOT NULL DEFAULT 1,
    new_step            INTEGER,
    new_stability       REAL,
    new_difficulty      REAL,
    new_due_at          TEXT NOT NULL,
    elapsed_days        REAL NOT NULL DEFAULT 0.0,
    scheduled_days      REAL NOT NULL DEFAULT 0.0
) STRICT;

CREATE INDEX IF NOT EXISTS idx_review_logs_card ON review_logs(card_id, reviewed_at);
CREATE INDEX IF NOT EXISTS idx_review_logs_date ON review_logs(reviewed_at);

CREATE TABLE IF NOT EXISTS media_assets (
    sha256_hash         TEXT PRIMARY KEY CHECK (length(sha256_hash) = 64),
    original_name       TEXT NOT NULL DEFAULT '',
    mime_type           TEXT NOT NULL DEFAULT 'image/png',
    byte_size           INTEGER NOT NULL DEFAULT 0,
    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
) STRICT;

CREATE TABLE IF NOT EXISTS scratchbook_pages (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid                TEXT NOT NULL UNIQUE,
    title               TEXT NOT NULL DEFAULT 'Scratchpad',
    content_text        TEXT NOT NULL DEFAULT '',
    display_order       INTEGER NOT NULL DEFAULT 0,
    updated_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
) STRICT;

CREATE TABLE IF NOT EXISTS gamification_stats (
    id                  INTEGER PRIMARY KEY CHECK (id = 1),
    streak_count        INTEGER NOT NULL DEFAULT 0,
    total_xp            REAL NOT NULL DEFAULT 0.0,
    last_login_at       TEXT,
    updated_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
) STRICT;

CREATE TABLE IF NOT EXISTS sync_oplog (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_table        TEXT NOT NULL,
    entity_uuid         TEXT NOT NULL,
    operation           TEXT NOT NULL,
    payload_json        TEXT NOT NULL DEFAULT '{}',
    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    device_id           TEXT NOT NULL DEFAULT 'desktop-local'
) STRICT;

CREATE VIRTUAL TABLE IF NOT EXISTS cards_fts USING fts5(
    title,
    front_html,
    back_html,
    hint_html,
    content='cards',
    content_rowid='id',
    tokenize='unicode61 remove_diacritics 2'
);

CREATE TRIGGER IF NOT EXISTS trg_cards_fts_insert AFTER INSERT ON cards BEGIN
    INSERT INTO cards_fts(rowid, title, front_html, back_html, hint_html)
    VALUES (NEW.id, NEW.title, NEW.front_html, NEW.back_html, NEW.hint_html);
END;

CREATE TRIGGER IF NOT EXISTS trg_cards_fts_delete AFTER DELETE ON cards BEGIN
    INSERT INTO cards_fts(cards_fts, rowid, title, front_html, back_html, hint_html)
    VALUES ('delete', OLD.id, OLD.title, OLD.front_html, OLD.back_html, OLD.hint_html);
END;

CREATE TRIGGER IF NOT EXISTS trg_cards_fts_update AFTER UPDATE OF title, front_html, back_html, hint_html ON cards BEGIN
    INSERT INTO cards_fts(cards_fts, rowid, title, front_html, back_html, hint_html)
    VALUES ('delete', OLD.id, OLD.title, OLD.front_html, OLD.back_html, OLD.hint_html);
    INSERT INTO cards_fts(rowid, title, front_html, back_html, hint_html)
    VALUES (NEW.id, NEW.title, NEW.front_html, NEW.back_html, NEW.hint_html);
END;

CREATE TRIGGER IF NOT EXISTS trg_sync_course_folders_insert AFTER INSERT ON course_folders
BEGIN
 INSERT INTO sync_oplog(entity_table,entity_uuid,operation,payload_json)
 VALUES ('course_folders',coalesce(CAST(NEW.uuid AS TEXT),''),'UPSERT',json_object('id',NEW.id));
END;

CREATE TRIGGER IF NOT EXISTS trg_sync_course_folders_update AFTER UPDATE ON course_folders
BEGIN
 INSERT INTO sync_oplog(entity_table,entity_uuid,operation,payload_json)
 VALUES ('course_folders',coalesce(CAST(NEW.uuid AS TEXT),''),'UPSERT',json_object('id',NEW.id));
END;

CREATE TRIGGER IF NOT EXISTS trg_sync_course_folders_delete AFTER DELETE ON course_folders
BEGIN
 INSERT INTO sync_oplog(entity_table,entity_uuid,operation,payload_json)
 VALUES ('course_folders',coalesce(CAST(OLD.uuid AS TEXT),''),'DELETE',json_object('id',OLD.id));
END;

CREATE TRIGGER IF NOT EXISTS trg_sync_courses_insert AFTER INSERT ON courses
BEGIN
 INSERT INTO sync_oplog(entity_table,entity_uuid,operation,payload_json)
 VALUES ('courses',coalesce(CAST(NEW.uuid AS TEXT),''),'UPSERT',json_object('id',NEW.id));
END;

CREATE TRIGGER IF NOT EXISTS trg_sync_courses_update AFTER UPDATE ON courses
BEGIN
 INSERT INTO sync_oplog(entity_table,entity_uuid,operation,payload_json)
 VALUES ('courses',coalesce(CAST(NEW.uuid AS TEXT),''),'UPSERT',json_object('id',NEW.id));
END;

CREATE TRIGGER IF NOT EXISTS trg_sync_courses_delete AFTER DELETE ON courses
BEGIN
 INSERT INTO sync_oplog(entity_table,entity_uuid,operation,payload_json)
 VALUES ('courses',coalesce(CAST(OLD.uuid AS TEXT),''),'DELETE',json_object('id',OLD.id));
END;

CREATE TRIGGER IF NOT EXISTS trg_sync_notes_insert AFTER INSERT ON notes
BEGIN
 INSERT INTO sync_oplog(entity_table,entity_uuid,operation,payload_json)
 VALUES ('notes',coalesce(CAST(NEW.uuid AS TEXT),''),'UPSERT',json_object('id',NEW.id));
END;

CREATE TRIGGER IF NOT EXISTS trg_sync_notes_update AFTER UPDATE ON notes
BEGIN
 INSERT INTO sync_oplog(entity_table,entity_uuid,operation,payload_json)
 VALUES ('notes',coalesce(CAST(NEW.uuid AS TEXT),''),'UPSERT',json_object('id',NEW.id));
END;

CREATE TRIGGER IF NOT EXISTS trg_sync_notes_delete AFTER DELETE ON notes
BEGIN
 INSERT INTO sync_oplog(entity_table,entity_uuid,operation,payload_json)
 VALUES ('notes',coalesce(CAST(OLD.uuid AS TEXT),''),'DELETE',json_object('id',OLD.id));
END;

CREATE TRIGGER IF NOT EXISTS trg_sync_course_notes_insert AFTER INSERT ON course_notes
BEGIN
 INSERT INTO sync_oplog(entity_table,entity_uuid,operation,payload_json)
 VALUES ('course_notes',coalesce(CAST(NEW.course_id || ':' || NEW.note_id AS TEXT),''),'UPSERT',json_object('course_id',NEW.course_id,'note_id',NEW.note_id));
END;

CREATE TRIGGER IF NOT EXISTS trg_sync_course_notes_update AFTER UPDATE ON course_notes
BEGIN
 INSERT INTO sync_oplog(entity_table,entity_uuid,operation,payload_json)
 VALUES ('course_notes',coalesce(CAST(NEW.course_id || ':' || NEW.note_id AS TEXT),''),'UPSERT',json_object('course_id',NEW.course_id,'note_id',NEW.note_id));
END;

CREATE TRIGGER IF NOT EXISTS trg_sync_course_notes_delete AFTER DELETE ON course_notes
BEGIN
 INSERT INTO sync_oplog(entity_table,entity_uuid,operation,payload_json)
 VALUES ('course_notes',coalesce(CAST(OLD.course_id || ':' || OLD.note_id AS TEXT),''),'DELETE',json_object('course_id',OLD.course_id,'note_id',OLD.note_id));
END;

CREATE TRIGGER IF NOT EXISTS trg_sync_cards_insert AFTER INSERT ON cards
BEGIN
 INSERT INTO sync_oplog(entity_table,entity_uuid,operation,payload_json)
 VALUES ('cards',coalesce(CAST(NEW.uuid AS TEXT),''),'UPSERT',json_object('id',NEW.id));
END;

CREATE TRIGGER IF NOT EXISTS trg_sync_cards_update AFTER UPDATE ON cards
BEGIN
 INSERT INTO sync_oplog(entity_table,entity_uuid,operation,payload_json)
 VALUES ('cards',coalesce(CAST(NEW.uuid AS TEXT),''),'UPSERT',json_object('id',NEW.id));
END;

CREATE TRIGGER IF NOT EXISTS trg_sync_cards_delete AFTER DELETE ON cards
BEGIN
 INSERT INTO sync_oplog(entity_table,entity_uuid,operation,payload_json)
 VALUES ('cards',coalesce(CAST(OLD.uuid AS TEXT),''),'DELETE',json_object('id',OLD.id));
END;

CREATE TRIGGER IF NOT EXISTS trg_sync_card_schedules_insert AFTER INSERT ON card_schedules
BEGIN
 INSERT INTO sync_oplog(entity_table,entity_uuid,operation,payload_json)
 VALUES ('card_schedules',coalesce(CAST(NEW.card_id AS TEXT),''),'UPSERT',json_object('card_id',NEW.card_id));
END;

CREATE TRIGGER IF NOT EXISTS trg_sync_card_schedules_update AFTER UPDATE ON card_schedules
BEGIN
 INSERT INTO sync_oplog(entity_table,entity_uuid,operation,payload_json)
 VALUES ('card_schedules',coalesce(CAST(NEW.card_id AS TEXT),''),'UPSERT',json_object('card_id',NEW.card_id));
END;

CREATE TRIGGER IF NOT EXISTS trg_sync_card_schedules_delete AFTER DELETE ON card_schedules
BEGIN
 INSERT INTO sync_oplog(entity_table,entity_uuid,operation,payload_json)
 VALUES ('card_schedules',coalesce(CAST(OLD.card_id AS TEXT),''),'DELETE',json_object('card_id',OLD.card_id));
END;

CREATE TRIGGER IF NOT EXISTS trg_sync_edges_insert AFTER INSERT ON edges
BEGIN
 INSERT INTO sync_oplog(entity_table,entity_uuid,operation,payload_json)
 VALUES ('edges',coalesce(CAST(NEW.uuid AS TEXT),''),'UPSERT',json_object('id',NEW.id));
END;

CREATE TRIGGER IF NOT EXISTS trg_sync_edges_update AFTER UPDATE ON edges
BEGIN
 INSERT INTO sync_oplog(entity_table,entity_uuid,operation,payload_json)
 VALUES ('edges',coalesce(CAST(NEW.uuid AS TEXT),''),'UPSERT',json_object('id',NEW.id));
END;

CREATE TRIGGER IF NOT EXISTS trg_sync_edges_delete AFTER DELETE ON edges
BEGIN
 INSERT INTO sync_oplog(entity_table,entity_uuid,operation,payload_json)
 VALUES ('edges',coalesce(CAST(OLD.uuid AS TEXT),''),'DELETE',json_object('id',OLD.id));
END;

CREATE TRIGGER IF NOT EXISTS trg_sync_tags_insert AFTER INSERT ON tags
BEGIN
 INSERT INTO sync_oplog(entity_table,entity_uuid,operation,payload_json)
 VALUES ('tags',coalesce(CAST(NEW.name AS TEXT),''),'UPSERT',json_object('id',NEW.id));
END;

CREATE TRIGGER IF NOT EXISTS trg_sync_tags_update AFTER UPDATE ON tags
BEGIN
 INSERT INTO sync_oplog(entity_table,entity_uuid,operation,payload_json)
 VALUES ('tags',coalesce(CAST(NEW.name AS TEXT),''),'UPSERT',json_object('id',NEW.id));
END;

CREATE TRIGGER IF NOT EXISTS trg_sync_tags_delete AFTER DELETE ON tags
BEGIN
 INSERT INTO sync_oplog(entity_table,entity_uuid,operation,payload_json)
 VALUES ('tags',coalesce(CAST(OLD.name AS TEXT),''),'DELETE',json_object('id',OLD.id));
END;

CREATE TRIGGER IF NOT EXISTS trg_sync_note_tags_insert AFTER INSERT ON note_tags
BEGIN
 INSERT INTO sync_oplog(entity_table,entity_uuid,operation,payload_json)
 VALUES ('note_tags',coalesce(CAST(NEW.note_id || ':' || NEW.tag_id AS TEXT),''),'UPSERT',json_object('note_id',NEW.note_id,'tag_id',NEW.tag_id));
END;

CREATE TRIGGER IF NOT EXISTS trg_sync_note_tags_update AFTER UPDATE ON note_tags
BEGIN
 INSERT INTO sync_oplog(entity_table,entity_uuid,operation,payload_json)
 VALUES ('note_tags',coalesce(CAST(NEW.note_id || ':' || NEW.tag_id AS TEXT),''),'UPSERT',json_object('note_id',NEW.note_id,'tag_id',NEW.tag_id));
END;

CREATE TRIGGER IF NOT EXISTS trg_sync_note_tags_delete AFTER DELETE ON note_tags
BEGIN
 INSERT INTO sync_oplog(entity_table,entity_uuid,operation,payload_json)
 VALUES ('note_tags',coalesce(CAST(OLD.note_id || ':' || OLD.tag_id AS TEXT),''),'DELETE',json_object('note_id',OLD.note_id,'tag_id',OLD.tag_id));
END;

CREATE TRIGGER IF NOT EXISTS trg_sync_review_logs_insert AFTER INSERT ON review_logs
BEGIN
 INSERT INTO sync_oplog(entity_table,entity_uuid,operation,payload_json)
 VALUES ('review_logs',coalesce(CAST(NEW.uuid AS TEXT),''),'UPSERT',json_object('id',NEW.id));
END;

CREATE TRIGGER IF NOT EXISTS trg_sync_review_logs_update AFTER UPDATE ON review_logs
BEGIN
 INSERT INTO sync_oplog(entity_table,entity_uuid,operation,payload_json)
 VALUES ('review_logs',coalesce(CAST(NEW.uuid AS TEXT),''),'UPSERT',json_object('id',NEW.id));
END;

CREATE TRIGGER IF NOT EXISTS trg_sync_review_logs_delete AFTER DELETE ON review_logs
BEGIN
 INSERT INTO sync_oplog(entity_table,entity_uuid,operation,payload_json)
 VALUES ('review_logs',coalesce(CAST(OLD.uuid AS TEXT),''),'DELETE',json_object('id',OLD.id));
END;

CREATE TRIGGER IF NOT EXISTS trg_sync_media_assets_insert AFTER INSERT ON media_assets
BEGIN
 INSERT INTO sync_oplog(entity_table,entity_uuid,operation,payload_json)
 VALUES ('media_assets',coalesce(CAST(NEW.sha256_hash AS TEXT),''),'UPSERT',json_object('sha256_hash',NEW.sha256_hash));
END;

CREATE TRIGGER IF NOT EXISTS trg_sync_media_assets_update AFTER UPDATE ON media_assets
BEGIN
 INSERT INTO sync_oplog(entity_table,entity_uuid,operation,payload_json)
 VALUES ('media_assets',coalesce(CAST(NEW.sha256_hash AS TEXT),''),'UPSERT',json_object('sha256_hash',NEW.sha256_hash));
END;

CREATE TRIGGER IF NOT EXISTS trg_sync_media_assets_delete AFTER DELETE ON media_assets
BEGIN
 INSERT INTO sync_oplog(entity_table,entity_uuid,operation,payload_json)
 VALUES ('media_assets',coalesce(CAST(OLD.sha256_hash AS TEXT),''),'DELETE',json_object('sha256_hash',OLD.sha256_hash));
END;

CREATE TRIGGER IF NOT EXISTS trg_sync_scratchbook_pages_insert AFTER INSERT ON scratchbook_pages
BEGIN
 INSERT INTO sync_oplog(entity_table,entity_uuid,operation,payload_json)
 VALUES ('scratchbook_pages',coalesce(CAST(NEW.uuid AS TEXT),''),'UPSERT',json_object('id',NEW.id));
END;

CREATE TRIGGER IF NOT EXISTS trg_sync_scratchbook_pages_update AFTER UPDATE ON scratchbook_pages
BEGIN
 INSERT INTO sync_oplog(entity_table,entity_uuid,operation,payload_json)
 VALUES ('scratchbook_pages',coalesce(CAST(NEW.uuid AS TEXT),''),'UPSERT',json_object('id',NEW.id));
END;

CREATE TRIGGER IF NOT EXISTS trg_sync_scratchbook_pages_delete AFTER DELETE ON scratchbook_pages
BEGIN
 INSERT INTO sync_oplog(entity_table,entity_uuid,operation,payload_json)
 VALUES ('scratchbook_pages',coalesce(CAST(OLD.uuid AS TEXT),''),'DELETE',json_object('id',OLD.id));
END;
