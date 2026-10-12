-- Message d'origine d'un objectif (le rappel lui répond) et journal des lectures web.

ALTER TABLE objectives ADD COLUMN origin_message_id INTEGER;

CREATE TABLE objective_fetches (
    id INTEGER PRIMARY KEY,
    at TEXT NOT NULL,
    objective_id INTEGER NOT NULL,
    budget_key TEXT NOT NULL
);

CREATE INDEX idx_objective_fetches ON objective_fetches (budget_key, at);
