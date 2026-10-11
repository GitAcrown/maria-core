-- Réactions apprises, journal du score, budget horaire.

CREATE TABLE emoji_usage (
    guild_id INTEGER NOT NULL,
    emoji TEXT NOT NULL,
    uses INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (guild_id, emoji)
);

CREATE TABLE spontaneity_log (
    id INTEGER PRIMARY KEY,
    at TEXT NOT NULL,
    guild_id INTEGER,
    channel_id INTEGER NOT NULL,
    message_id INTEGER NOT NULL,
    author_id INTEGER NOT NULL,
    score REAL NOT NULL,
    parts_json TEXT NOT NULL,
    verdict TEXT NOT NULL,
    emoji TEXT NOT NULL DEFAULT ''
);

CREATE INDEX idx_spontaneity_message ON spontaneity_log (message_id);

CREATE TABLE social_budget (
    channel_id INTEGER NOT NULL,
    hour_key TEXT NOT NULL,
    reactions INTEGER NOT NULL DEFAULT 0,
    last_author_id INTEGER,
    PRIMARY KEY (channel_id, hour_key)
);
