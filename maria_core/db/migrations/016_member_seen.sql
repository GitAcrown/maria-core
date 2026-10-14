-- Dernier passage d'une personne dans un salon, pour « ce que j'ai raté ».
-- away_since : fin de sa visite précédente, la dernière fois qu'elle a laissé le salon plus de
-- 30 minutes. Rien du contenu des messages n'est gardé.

CREATE TABLE member_seen (
    user_id INTEGER NOT NULL,
    channel_id INTEGER NOT NULL,
    last_at TEXT NOT NULL,
    away_since TEXT,
    PRIMARY KEY (user_id, channel_id)
);

CREATE INDEX idx_member_seen_last ON member_seen (last_at);
