-- Schéma initial. Les tables des phases suivantes (emojis, widgets, sondages)
-- arriveront dans leurs propres migrations, quand le code qui les écrit existera.

CREATE TABLE guild_settings (
    guild_id INTEGER PRIMARY KEY,
    mode TEXT NOT NULL DEFAULT 'strict' CHECK (mode IN ('off', 'strict', 'greedy')),
    personality TEXT NOT NULL DEFAULT '',
    spontaneity TEXT NOT NULL DEFAULT 'normal'
        CHECK (spontaneity IN ('off', 'quiet', 'normal', 'chatty')),
    python_enabled INTEGER NOT NULL DEFAULT 0 CHECK (python_enabled IN (0, 1)),
    updated_at TEXT NOT NULL
);

CREATE TABLE channel_settings (
    channel_id INTEGER PRIMARY KEY,
    guild_id INTEGER NOT NULL,
    respond_everyone INTEGER NOT NULL DEFAULT 0 CHECK (respond_everyone IN (0, 1)),
    auto_transcribe INTEGER NOT NULL DEFAULT 0 CHECK (auto_transcribe IN (0, 1))
);

CREATE TABLE member_settings (
    user_id INTEGER NOT NULL,
    guild_id INTEGER NOT NULL,
    spontaneity TEXT,
    memory_prompts INTEGER NOT NULL DEFAULT 1 CHECK (memory_prompts IN (0, 1)),
    PRIMARY KEY (user_id, guild_id)
);

CREATE TABLE objectives (
    id INTEGER PRIMARY KEY,
    owner_id INTEGER NOT NULL,
    guild_id INTEGER,
    channel_ids TEXT NOT NULL,
    deliver TEXT NOT NULL CHECK (deliver IN ('channel', 'dm')),
    title TEXT NOT NULL,
    trigger_json TEXT NOT NULL,
    condition_json TEXT,
    action_json TEXT NOT NULL,
    status TEXT NOT NULL CHECK (
        status IN ('draft', 'active', 'paused', 'done', 'cancelled', 'failed')
    ),
    next_run_at TEXT,
    fires INTEGER NOT NULL DEFAULT 0,
    max_fires INTEGER,
    cooldown_s INTEGER NOT NULL DEFAULT 0,
    expires_at TEXT,
    state_json TEXT NOT NULL DEFAULT '{}',
    version INTEGER NOT NULL DEFAULT 1,
    lease_until TEXT,
    last_error TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX idx_objectives_due ON objectives (status, next_run_at);
CREATE INDEX idx_objectives_owner ON objectives (owner_id, status);

CREATE TABLE objective_runs (
    id INTEGER PRIMARY KEY,
    objective_id INTEGER NOT NULL REFERENCES objectives (id),
    activation_key TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    outcome TEXT,
    summary TEXT NOT NULL DEFAULT '',
    error TEXT NOT NULL DEFAULT '',
    UNIQUE (objective_id, activation_key)
);

CREATE TABLE memories (
    id INTEGER PRIMARY KEY,
    scope TEXT NOT NULL CHECK (scope IN ('user', 'guild', 'self')),
    subject_id INTEGER NOT NULL,
    guild_id INTEGER,
    content TEXT NOT NULL,
    source TEXT NOT NULL CHECK (source IN ('explicit', 'confirmed', 'imported')),
    created_by INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_used_at TEXT,
    deleted_at TEXT,
    chroma_id TEXT
);

CREATE INDEX idx_memories_subject
    ON memories (scope, subject_id)
    WHERE deleted_at IS NULL;
CREATE INDEX idx_memories_guild
    ON memories (guild_id)
    WHERE deleted_at IS NULL;

CREATE VIRTUAL TABLE memories_fts USING fts5(
    content,
    content = 'memories',
    content_rowid = 'id',
    tokenize = 'unicode61'
);

CREATE TRIGGER memories_ai AFTER INSERT ON memories BEGIN
    INSERT INTO memories_fts (rowid, content)
    SELECT new.id, new.content
    WHERE new.deleted_at IS NULL;
END;

CREATE TRIGGER memories_ad AFTER DELETE ON memories BEGIN
    INSERT INTO memories_fts (memories_fts, rowid, content)
    VALUES ('delete', old.id, old.content);
END;

CREATE TRIGGER memories_au AFTER UPDATE ON memories BEGIN
    INSERT INTO memories_fts (memories_fts, rowid, content)
    VALUES ('delete', old.id, old.content);
    INSERT INTO memories_fts (rowid, content)
    SELECT new.id, new.content
    WHERE new.deleted_at IS NULL;
END;

CREATE TABLE memory_proposals (
    id INTEGER PRIMARY KEY,
    guild_id INTEGER,
    channel_id INTEGER,
    subject_user_id INTEGER,
    scope TEXT NOT NULL CHECK (scope IN ('user', 'guild', 'self')),
    content TEXT NOT NULL,
    confidence REAL,
    status TEXT NOT NULL CHECK (status IN ('open', 'accepted', 'ignored', 'expired')),
    source_message_id INTEGER,
    created_at TEXT NOT NULL,
    resolved_at TEXT,
    memory_id INTEGER REFERENCES memories (id)
);

CREATE INDEX idx_memory_proposals_status ON memory_proposals (status, created_at);

CREATE TABLE memory_revisions (
    id INTEGER PRIMARY KEY,
    memory_id INTEGER NOT NULL REFERENCES memories (id),
    content TEXT NOT NULL,
    editor_id INTEGER NOT NULL,
    reason TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE decision_log (
    id INTEGER PRIMARY KEY,
    at TEXT NOT NULL,
    name TEXT NOT NULL,
    input_hash TEXT NOT NULL,
    path TEXT NOT NULL CHECK (path IN ('rules', 'cache', 'model', 'fallback')),
    verdict TEXT NOT NULL,
    confidence REAL,
    duration_ms INTEGER NOT NULL,
    cost_micro_usd INTEGER
);

CREATE INDEX idx_decision_log_name_at ON decision_log (name, at);

CREATE TABLE llm_calls (
    id INTEGER PRIMARY KEY,
    at TEXT NOT NULL,
    purpose TEXT NOT NULL,
    model TEXT NOT NULL,
    input_tokens INTEGER NOT NULL,
    output_tokens INTEGER NOT NULL,
    duration_ms INTEGER NOT NULL,
    ok INTEGER NOT NULL CHECK (ok IN (0, 1))
);

CREATE INDEX idx_llm_calls_at ON llm_calls (at);
