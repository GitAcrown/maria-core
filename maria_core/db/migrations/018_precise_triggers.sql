-- Le déclencheur on_message (chaque message jugé par un modèle) est remplacé par des écoutes
-- précises : on_mention, on_post, on_link, on_attachment, on_reaction.

UPDATE objectives
SET status = 'cancelled'
WHERE status IN ('draft', 'active', 'paused')
  AND json_extract(trigger_json, '$.type') = 'on_message';
