-- Graph index schema (v0.5.0 memory discipline, module_03).
--
-- Canonical schema per docs/RACT_v0.5.0_MEMORY_DISCIPLINE_SPEC.md
-- section "The three indexes / Graph index". Loaded by
-- ract.memory.graph_index.GraphIndex on connection open. Every
-- CREATE is idempotent so the schema loader is safe to run against
-- an existing store.
--
-- Edges reference symbol ids from the module_02 symbol_index.symbols
-- table. The graph store lives at .rack/index/graph.db in a real
-- repo; tests open a temp path (or ATTACH the symbol store to run
-- foreign-key checks in-memory).
--
-- schema_version table carries one row per version the store has
-- ever been at. Fresh stores end at 'v1'; a future migration adds
-- a new row before rewriting the tables.

CREATE TABLE IF NOT EXISTS schema_version (
    version TEXT PRIMARY KEY
);

INSERT OR IGNORE INTO schema_version (version) VALUES ('v1');

-- Edge rows record call / import / inherit / implement / reference
-- relationships between two symbols. Both source and target ids are
-- symbol ids from the module_02 symbols table; because the two
-- tables live in different SQLite databases at production time
-- (graph.db vs symbols.db), foreign keys are NOT declared here.
-- Referential integrity is maintained by the graph_populator's
-- source-file-scoped delete + re-insert path.
--
-- ``strength`` is a caller-supplied integer that lets the hotspots
-- query rank edges by weight; the LSP-driven populator sets it to
-- the reference count so a symbol called twenty times ranks above
-- a symbol called once.
--
-- ``neighborhood_source`` marks the provenance of the edge: 'lsp'
-- when the LSP driver produced it, 'symbol_only' when the fallback
-- populated a self-referential edge because the LSP was
-- unavailable. Downstream (module_05 retrieve / research) reads
-- this so a "no neighborhood" degradation is never rendered as a
-- misleading "the symbol calls itself" claim.
--
-- The (source_symbol_id, target_symbol_id, edge_type, location_file,
-- location_line) UNIQUE constraint stops the populator from
-- inserting duplicate edges on re-run; ON CONFLICT DO UPDATE bumps
-- ``strength`` instead.

CREATE TABLE IF NOT EXISTS edges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_symbol_id INTEGER NOT NULL,
    target_symbol_id INTEGER NOT NULL,
    edge_type TEXT NOT NULL,
    location_file TEXT,
    location_line INTEGER,
    strength INTEGER DEFAULT 1,
    neighborhood_source TEXT DEFAULT 'lsp',
    UNIQUE (source_symbol_id, target_symbol_id, edge_type,
            location_file, location_line)
);

CREATE INDEX IF NOT EXISTS idx_edges_source ON edges(source_symbol_id);
CREATE INDEX IF NOT EXISTS idx_edges_target ON edges(target_symbol_id);
CREATE INDEX IF NOT EXISTS idx_edges_type ON edges(edge_type);
CREATE INDEX IF NOT EXISTS idx_edges_location_file ON edges(location_file);
