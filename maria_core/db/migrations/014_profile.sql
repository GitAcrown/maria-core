-- Profil d'une personne : champs réglés à la main ou appris, et style déduit de ses messages.

CREATE TABLE user_profile (
    user_id INTEGER NOT NULL,
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'user' CHECK (source IN ('user', 'auto')),
    updated_at TEXT NOT NULL,
    PRIMARY KEY (user_id, key)
);

CREATE TABLE user_style (
    user_id INTEGER PRIMARY KEY,
    samples INTEGER NOT NULL DEFAULT 0,
    avg_words REAL NOT NULL DEFAULT 0,
    lower_rate REAL NOT NULL DEFAULT 0,
    laugh_rate REAL NOT NULL DEFAULT 0,
    polite_rate REAL NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL
);
