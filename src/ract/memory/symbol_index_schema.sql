-- Symbol index schema (v0.5.0 memory discipline, module_02).
--
-- Canonical schema per docs/RACT_v0.5.0_MEMORY_DISCIPLINE_SPEC.md
-- section "The three indexes / Symbol index". Loaded by
-- ract.memory.symbol_index.SymbolIndex on connection open. Every
-- CREATE is idempotent so the schema loader is safe to run against
-- an existing store.
--
-- schema_version table carries one row per version the store has
-- ever been at. Fresh stores end at 'v1'; a future migration adds
-- a new row before rewriting the tables.

CREATE TABLE IF NOT EXISTS schema_version (
    version TEXT PRIMARY KEY
);

INSERT OR IGNORE INTO schema_version (version) VALUES ('v1');

CREATE TABLE IF NOT EXISTS symbols (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    kind TEXT NOT NULL,
    file_path TEXT NOT NULL,
    start_line INTEGER,
    end_line INTEGER,
    signature TEXT,
    docstring TEXT,
    visibility TEXT,
    parent_symbol_id INTEGER,
    language TEXT,
    content_hash TEXT,
    token_count INTEGER,
    updated_at INTEGER,
    UNIQUE (file_path, kind, name, start_line)
);

CREATE INDEX IF NOT EXISTS idx_symbols_name ON symbols(name);
CREATE INDEX IF NOT EXISTS idx_symbols_kind ON symbols(kind);
CREATE INDEX IF NOT EXISTS idx_symbols_file ON symbols(file_path);
CREATE INDEX IF NOT EXISTS idx_symbols_hash ON symbols(content_hash);

-- FTS5 external-content index over the symbols table. Uses id as the
-- content rowid so a symbol's FTS entry follows its schema row. Triggers
-- below keep the FTS mirror consistent within the same transaction so a
-- query issued after insert_or_update never hits a stale FTS snapshot
-- (Second Pass Q4).
CREATE VIRTUAL TABLE IF NOT EXISTS symbols_fts USING fts5(
    name,
    docstring,
    content=symbols,
    content_rowid=id
);

CREATE TRIGGER IF NOT EXISTS symbols_ai AFTER INSERT ON symbols BEGIN
    INSERT INTO symbols_fts(rowid, name, docstring)
    VALUES (new.id, new.name, coalesce(new.docstring, ''));
END;

CREATE TRIGGER IF NOT EXISTS symbols_ad AFTER DELETE ON symbols BEGIN
    INSERT INTO symbols_fts(symbols_fts, rowid, name, docstring)
    VALUES ('delete', old.id, old.name, coalesce(old.docstring, ''));
END;

CREATE TRIGGER IF NOT EXISTS symbols_au AFTER UPDATE ON symbols BEGIN
    INSERT INTO symbols_fts(symbols_fts, rowid, name, docstring)
    VALUES ('delete', old.id, old.name, coalesce(old.docstring, ''));
    INSERT INTO symbols_fts(rowid, name, docstring)
    VALUES (new.id, new.name, coalesce(new.docstring, ''));
END;
