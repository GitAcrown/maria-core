-- Apprentissage silencieux : MARIA retient seule, la personne voit et annule après coup.
-- learned_at marque un souvenir appris sans question ; learned_reply_id le message qui porte
-- le bouton Annuler. member_settings.learning remplace l'ancien interrupteur des questions.

ALTER TABLE memories ADD COLUMN learned_at TEXT;
ALTER TABLE memories ADD COLUMN learned_reply_id INTEGER;

CREATE INDEX idx_memories_learned
    ON memories (subject_id, learned_at)
    WHERE learned_at IS NOT NULL AND deleted_at IS NULL;

ALTER TABLE member_settings
    ADD COLUMN learning TEXT NOT NULL DEFAULT 'auto' CHECK (learning IN ('auto', 'ask', 'off'));

UPDATE member_settings SET learning = CASE memory_prompts WHEN 1 THEN 'auto' ELSE 'off' END;
