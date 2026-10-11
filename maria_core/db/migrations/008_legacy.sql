-- Correspondance avec les identifiants MARIA_R, pour ne pas importer deux fois.

CREATE TABLE legacy_map (
    source TEXT NOT NULL,
    legacy_id TEXT NOT NULL,
    destination TEXT NOT NULL,
    row_id INTEGER NOT NULL,
    PRIMARY KEY (source, legacy_id)
);
