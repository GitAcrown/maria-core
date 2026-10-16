-- Un rappel peut s'adresser à quelqu'un d'autre que son auteur. NULL : l'auteur lui-même.

ALTER TABLE objectives ADD COLUMN target_id INTEGER;
