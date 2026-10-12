-- Mots qui entourent un emoji : MARIA choisit celui qui colle au message.
-- Les onglets de widgets disparaissent au profit des cartes Components v2.

CREATE TABLE emoji_words (
    guild_id INTEGER NOT NULL,
    emoji TEXT NOT NULL,
    word TEXT NOT NULL,
    hits INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (guild_id, emoji, word)
);

DROP INDEX IF EXISTS idx_widget_tabs_recent;
DROP TABLE IF EXISTS widget_tabs;
