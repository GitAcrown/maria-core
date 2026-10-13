-- MARIA_R exécutait toujours la consigne d'une tâche avec le modèle. Les tâches importées
-- en « remind » postaient la consigne telle quelle : elles deviennent des « report ».

UPDATE objectives
SET action_json = json_set(action_json, '$.type', 'report'),
    version = version + 1
WHERE json_extract(action_json, '$.type') = 'remind'
  AND id IN (
      SELECT row_id FROM legacy_map WHERE source = 'task' AND destination = 'objectives'
  );
