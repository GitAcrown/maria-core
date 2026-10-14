-- Limite de réponses par serveur. Aucune par défaut ; seuls les suivis restent bridés.

ALTER TABLE guild_settings
    ADD COLUMN reply_limit TEXT NOT NULL DEFAULT 'none'
    CHECK (reply_limit IN ('none', 'normal', 'strict'));
