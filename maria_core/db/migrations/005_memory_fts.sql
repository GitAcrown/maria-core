-- Un souvenir effacé reste dans l'index jusqu'à la purge, pour ne pas le retirer deux fois.

DROP TRIGGER IF EXISTS memories_au;

CREATE TRIGGER memories_au AFTER UPDATE ON memories BEGIN
    INSERT INTO memories_fts (memories_fts, rowid, content)
    VALUES ('delete', old.id, old.content);
    INSERT INTO memories_fts (rowid, content) VALUES (new.id, new.content);
END;
