-- Capacités : signets, onglets de widgets, sondages, journal d'appels.

CREATE TABLE bookmarks (
    id TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL,
    guild_id INTEGER,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX idx_bookmarks_user ON bookmarks (user_id, created_at);

CREATE TABLE widget_tabs (
    id TEXT PRIMARY KEY,
    channel_id INTEGER NOT NULL,
    message_id INTEGER,
    tabs_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX idx_widget_tabs_recent ON widget_tabs (created_at);

CREATE TABLE polls (
    message_id INTEGER PRIMARY KEY,
    channel_id INTEGER NOT NULL,
    guild_id INTEGER NOT NULL,
    author_id INTEGER NOT NULL,
    question TEXT NOT NULL,
    options_json TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE capability_calls (
    id INTEGER PRIMARY KEY,
    at TEXT NOT NULL,
    name TEXT NOT NULL,
    guild_id INTEGER,
    user_id INTEGER NOT NULL,
    ok INTEGER NOT NULL CHECK (ok IN (0, 1)),
    duration_ms INTEGER NOT NULL,
    error TEXT NOT NULL DEFAULT ''
);

CREATE INDEX idx_capability_calls_name ON capability_calls (name, at);
