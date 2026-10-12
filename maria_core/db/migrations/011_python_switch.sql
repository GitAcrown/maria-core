-- run_python est ouvert à tous (sandbox) ; un modérateur peut le couper sur son serveur.

ALTER TABLE guild_settings ADD COLUMN python_blocked INTEGER NOT NULL DEFAULT 0
    CHECK (python_blocked IN (0, 1));
