# maria-core

MARIA est un bot Discord. Elle discute dans les salons, réagit selon l'activité du serveur, retient ce qu'on lui demande de retenir, et envoie des rappels, des récaps et des veilles. Un seul processus, une base SQLite, des extensions pour la météo, le foot, les films, la musique, les jeux, YouTube et les transports.

Python 3.13 ou plus récent.

## Installation

```bash
python3.13 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e . --no-deps
cp .env.example .env
```

Sous Windows, `tzdata` est tiré par `requirements.txt`. Les outils de test s'installent avec `pip install -e ".[dev]"`.

Renseigne au minimum `TOKEN`, `APP_ID` et `OPENAI_API_KEY` dans `.env`. Les autres clés activent des capacités : sans clé, l'outil correspondant reste caché. `TYPESAFE_API_KEY` (JEV) sert aux décisions fines : sans elle, MARIA s'en tient aux règles (pas de réaction spontanée, pas de suivi sur une phrase ambiguë). `DATA_DIR` est le dossier de `maria.db`, de l'index Chroma et de `statuses.txt`.

## Lancement

```bash
python -m maria_core --check --env-file .env
python -m maria_core --env-file .env
```

`--check` ouvre la base et charge les extensions, sans se connecter à Discord. Après un premier lancement, `5!sync` publie les commandes slash.

## Ce que fait MARIA

- **Conversation** : mention, réponse à un de ses messages, `@everyone` si le salon l'autorise, son prénom (et en mode greedy, son prénom au milieu d'une phrase). Elle voit les citations de reply, les embeds, les messages transférés, les images. Un message privé ne lance pas de conversation : il ne sert qu'à recevoir un rappel ou une veille.
- **Silence choisi** : quand on ne lui pose pas de vraie question, elle peut se contenter d'un emoji. « Réagis à mon message » pose une réaction.
- **Vocaux** : transcription automatique si le salon l'a activée, ou quand on parle à MARIA ; sinon la réaction de transcription (emoji de MARIA, ou 📝 si le bot n'y a pas accès) transcrit à la demande. La transcription est postée en citation.
- **Vues** : météo, films, jeux, morceaux, matchs, transports et images s'affichent en cartes Discord (Components v2). MARIA peut aussi composer une vue sur mesure (`render_widget`) ou un tableau (`render_table`).
- **Objectifs** : rappels (« dans 10 min », « tous les lundis à 9 h »), récaps rédigés avec ses outils, veilles de page ou de prix, écoute d'un mot, d'un sujet ou d'un vocal. Ce qui ne part pas à coup sûr (condition, écoute, veille) est un brouillon : un « oui » ou le bouton le confirme.
- **Fichiers et liens lus d'office** : texte, code, Word, PDF (avec `pypdf`) et pages web citées dans un message qui lui est adressé. Ce qu'elle ne peut pas lire (vidéo, archive, réseau social fermé, audio non transcrit, page sans texte) est annoncé comme tel : elle le dit au lieu de deviner.
- **Mémoire silencieuse** : un fait clair sur toi (« je suis végétarien ») est retenu sans question, avec une trace « 🧠 Retenu : … » et un bouton Annuler. Un nouveau fait qui contredit un ancien le remplace (l'ancien se retrouve avec Annuler). Santé, religion, orientation, argent, justice : jamais retenu sans demander. Un gag ou une habitude du groupe est proposé aux modérateurs dans `/global`. `/preferences apprentissage` : automatique, « demande-moi d'abord » ou rien. `/moi` montre le résumé, tout ce qu'elle sait, et l'onglet « Appris récemment ».
- **Profil** : ville, équipe de foot, arrêt habituel, et façon de te parler (longueur, ton, emojis). « Météo chez moi », « le match de mon équipe » ou « mon métro » marchent sans question, et la réponse dit ce qui vient du profil. Les champs se règlent dans `/profil` ou à la parole ; le style se déduit de la longueur et du ton de tes messages (jamais de leur contenu).
- **Ce que j'ai raté** : « qu'est-ce que j'ai raté ? » résume depuis ton dernier départ du salon, sans durée à préciser.
- **Vérification discrète** : une réponse qui donne des faits d'actualité sans avoir cherché est revérifiée une fois avec un outil, avec le même ton.
- **Rapidité** : les lectures indépendantes d'un même tour (météo et foot, deux recherches d'images…) partent en parallèle ; les résultats publics sont mis en cache.
- **Spontanéité** : réactions sur les messages de ceux qui lui parlent, emojis appris du serveur, suivi d'un échange qui continue.

## Commandes

Slash (après `5!sync`) :

| Commande | Rôle |
|---|---|
| `/moi`, `/global` | Résumé de ce que MARIA sait, souvenirs, propositions, modifier, oublier, tout effacer |
| `/profil` | Ce que MARIA sait de toi (ville, équipe, arrêt) et comment elle te parle : tout se voit et se change |
| `/programmes` | Rappels, écoutes et surveillances : modifier, pause, reprise, saut, confirmation, suppression, tout supprimer |
| `/info` | Réglages du salon et outils disponibles |
| `/chatbot mode\|forget\|everyone\|autotranscribe\|python\|spontaneite` | Réglages, modérateurs |
| `/preferences apprentissage\|reactions` | Réglages personnels |

Préfixe (`5!` par défaut) : `spontaneite`. Propriétaire : `why <lien>`, `status`, `usage [jours]`, `keys`, `presence`, `plugin load|unload|reload`, `sync`, `update`, `restart`, `shutdown`.

## Import depuis MARIA_R

La commande lit une copie du dossier MARIA_R, en lecture seule, et affiche un rapport avant d'écrire.

```bash
python -m maria_core.legacy /chemin/vers/copie-MARIA_R --database data/maria.db
python -m maria_core.legacy /chemin/vers/copie-MARIA_R --database data/maria.db --write
```

Le second passage ne duplique pas les lignes déjà reprises. Les statuts tournants (`statuses.txt`) et l'index Chroma sont recopiés.

Pour revenir en arrière après la bascule, `python scripts/export_since_cutover.py data/maria.db <date ISO>` liste en JSON les objectifs et souvenirs créés depuis.
