# Retrait de l'événement Halloween 2026

> Note pour Claude (et pour le propriétaire). À faire **à partir du 2 novembre 2026**, quand
> l'utilisateur demande de retirer Halloween, ou si tu tombes sur ce fichier après cette date :
> propose-lui le retrait. L'outil `trick_or_treat` s'éteint déjà seul après le 1er novembre
> (il disparaît de la liste du modèle), donc rien n'est urgent : c'est du ménage.

## Ce qui a été ajouté (tout est listé ici)

| Élément | Où |
|---|---|
| L'extension (outil `trick_or_treat`, carte, tirage, table) | `maria_core/plugins/halloween.py` |
| Ses tests | `tests/test_halloween.py` |
| Son chargement par défaut | `maria_core/config.py`, tuple `DEFAULT_PLUGINS` : ligne `"maria_core.plugins.halloween"` + les 2 lignes de commentaire au-dessus |
| La table SQLite des bonbons | `halloween_bag`, créée par `setup()` du plugin (`CREATE TABLE IF NOT EXISTS`). **Pas de migration** : rien à défaire dans `maria_core/db/migrations/` |

Dates de l'événement : du 2026-10-15 au 2026-11-01 inclus, heure de Paris
(`FIRST_DAY` et `LAST_DAY` dans le plugin).

## Étapes du retrait

1. Créer une branche : `git checkout -b retrait-halloween`.
2. Supprimer `maria_core/plugins/halloween.py` et `tests/test_halloween.py`.
3. Dans `maria_core/config.py`, retirer de `DEFAULT_PLUGINS` la ligne
   `"maria_core.plugins.halloween",` et le commentaire qui la précède.
4. Supprimer ce fichier (`RETRAIT_HALLOWEEN.md`).
5. Vérifier qu'il ne reste rien : `grep -rni "halloween\|trick_or_treat" maria_core tests README.md`
   (aucun résultat attendu, hormis l'historique git).
6. `python -m ruff format . && python -m ruff check . && python -m pytest -q` : tout doit passer.
7. Commit (trailer `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`), merge dans `main`
   avec `--no-ff`, push. Dire à l'utilisateur de faire `git pull` sur le Raspberry Pi puis de
   relancer le bot. Pas de `5!sync` : aucune slash command n'est concernée.

## À propos de la base de données (facultatif)

La table `halloween_bag` reste dans `data/*.db` si on ne fait rien : elle est inoffensive et
permet de relancer un événement identique l'an prochain avec les mêmes bonbons. Pour la supprimer
(à faire sur la machine qui héberge la base, bot arrêté ou non) :

```sql
DROP TABLE IF EXISTS halloween_bag;
```

Ne jamais ajouter de migration pour ça : les migrations déjà appliquées ne se suppriment pas.

## Ce qu'on garde volontairement

- `Capability.active` (`maria_core/capabilities/base.py`) et `_in_season` / `_unavailable`
  (`maria_core/capabilities/runner.py`) : mécanisme générique d'outil saisonnier, réutilisable pour
  un prochain événement (Noël, etc.). Ne pas les retirer.
- `database` dans le protocole `PluginHost` (`maria_core/plugins/manager.py`) : utile aux futures
  extensions qui stockent des données.

## Rejouer l'événement une autre année

Changer `FIRST_DAY` et `LAST_DAY` dans le plugin, rajouter la ligne dans `DEFAULT_PLUGINS`
(ou partir de l'historique git : le commit « Halloween : outil trick_or_treat »), et refaire un
test de la période dans `tests/test_halloween.py`.
