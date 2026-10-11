-- Plus de stats de serveur. L'activité horaire sert au seuil de spontanéité.

DROP TABLE IF EXISTS fun_hits;
DROP TABLE IF EXISTS fun_campaigns;

CREATE TABLE guild_hour_activity (
    guild_id INTEGER NOT NULL,
    day TEXT NOT NULL,
    hour INTEGER NOT NULL CHECK (hour BETWEEN 0 AND 23),
    messages INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (guild_id, day, hour)
);
