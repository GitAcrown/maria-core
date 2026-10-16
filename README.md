# maria-core

MARIA est un bot Discord. Elle discute dans les salons, réagit selon l'activité du serveur, retient ce qu'on lui demande de retenir, et envoie des rappels, des récaps et des veilles. Un seul processus, une base SQLite, des extensions pour la météo, le foot, les films, la musique, les jeux, YouTube et les transports.

Python 3.12 ou plus récent.

## Installation

```bash
python3 -m venv .venv
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

`--check` ouvre la base et charge les extensions, sans se connecter à Discord.

**Relance automatique** : `python -m maria_core` surveille le bot. S'il plante, il est relancé après 10 s, puis 30 s, 90 s, 4 min 30, 13 min 30, 40 min, 2 h, 6 h (le maximum). Après 8 relances de suite sans que le bot tienne 10 minutes, il abandonne : c'est probablement un bug à corriger, le message `[supervision]` le dit. Une fois resté en vie 10 min, le compteur repart de zéro. Les arrêts voulus (`5!shutdown`, Ctrl+C) et les réglages à corriger (jeton absent ou refusé par Discord, intents manquants) ne sont pas relancés. `5!restart` et `5!update` continuent de fonctionner. Avec `--no-restart`, le bot ne se relance pas lui-même (utile si systemd s'en charge déjà). Les messages de la supervision sont préfixés `[supervision]` sur la sortie d'erreur. Après un premier lancement, `5!sync` publie les commandes slash.

## Ce que fait MARIA

- **Conversation** : mention, réponse à un de ses messages, `@everyone` si le salon l'autorise, son prénom (et en mode greedy, son prénom au milieu d'une phrase). Elle voit les citations de reply, les embeds, les messages transférés, les images. Un message privé ne lance pas de conversation : il ne sert qu'à recevoir un rappel ou une veille.
- **Aucune limite sur les membres** : MARIA répond chaque fois qu'on l'appelle. Un modérateur peut en poser une pour tout un serveur (`/chatbot limite` : modérée ou stricte). Seuls les suivis, quand elle reprend la parole sans qu'on l'appelle, sont toujours un peu bridés.
- **Silence choisi** : quand on ne lui pose pas de vraie question, elle peut se contenter d'un emoji. « Réagis à mon message » pose une réaction.
- **Vocaux** : transcription automatique si le salon l'a activée, ou quand on parle à MARIA ; sinon la réaction de transcription (emoji de MARIA, ou 📝 si le bot n'y a pas accès) transcrit à la demande. La transcription est postée en citation.
- **Images à la demande** : graphiques (barres, courbes, camembert…), diagrammes (organigramme, séquence, planning, carte mentale, Graphviz, PlantUML), QR codes, formules mathématiques et tracé de fonctions. Rien n'est dessiné sur le serveur : des services gratuits sans clé s'en chargent (QuickChart, mermaid.ink, Kroki, CodeCogs), ce qui veut dire que le contenu du graphique ou du diagramme leur est envoyé. Un diagramme refusé par le service est corrigé et renvoyé. MARIA règle le style à la demande : fond clair, sombre ou transparent (texte clair, pour un Discord sombre), et les couleurs des séries ou des parts.
- **Vues** : météo, films, jeux, morceaux, matchs, transports et images s'affichent en cartes Discord (Components v2). MARIA peut aussi composer une vue sur mesure (`render_widget`) ou un tableau (`render_table`).
- **Objectifs** : rappels (« dans 10 min », « tous les lundis à 9 h »), récaps rédigés avec ses outils, veilles de page ou de prix, écoute d'un mot, d'un sujet ou d'un vocal. Un rappel isolé ou une écoute unique part tout de suite. Ce qui peut devenir pénible (rappel récurrent, écoute répétée, veille de page ou de prix) est un brouillon : un « oui » ou un « non » dans le salon le tranche (MARIA l'attend 5 minutes, sans bouton, puis l'annule d'elle-même).
- **Fichiers et liens lus d'office** : texte, code, Word, PDF (avec `pypdf`) et pages web citées dans un message qui lui est adressé. Ce qu'elle ne peut pas lire (vidéo, archive, réseau social fermé, audio non transcrit, page sans texte) est annoncé comme tel : elle le dit au lieu de deviner.
- **Mémoire silencieuse** : un fait clair sur toi (« je suis végétarien ») est retenu sans question, avec une trace « 🧠 Retenu : … » et un bouton Annuler. Un nouveau fait qui contredit un ancien le remplace (l'ancien se retrouve avec Annuler). Santé, religion, orientation, argent, justice : jamais retenu sans demander. Un gag ou une habitude du groupe est proposé aux modérateurs dans `/global`. `/preferences apprentissage` : automatique, « demande-moi d'abord » ou rien. `/moi` réunit, en onglets : le profil, le résumé et les souvenirs, « Appris récemment » et « À valider ».
- **Où part un rappel** : chaque rappel créé indique « Envoi » (dans le salon, ou en message privé) à l'écran et dans `/programmes`. Un rappel n'est jamais pour quelqu'un d'autre que la personne qui le demande.
- **Message édité** : une simple correction (faute, accent, majuscule, ponctuation) ne relance rien : sa réponse reste. Un vrai changement de demande, lui, corrige sa réponse sur place quand c'est possible, sinon elle efface l'ancienne et en poste une nouvelle. Jamais deux réponses. Une modification pendant qu'elle écrit attend la fin de la première réponse.
- **Suivis** : quand tu enchaînes sur sa réponse sans la mentionner, MARIA répond en une ou deux phrases, ou par une simple réaction si le suivi n'apporte rien. Elle continue d'écouter tant que tu écris (message ou « en train d'écrire »), pendant 2 min au plus après sa réponse. Elle ne donne qu'une réponse de suivi après une première réponse ; pour relancer l'échange, mentionne-la ou réponds à l'un de ses messages.
- **Demander à MARIA** : clic droit sur un message, Applications, « Demander à MARIA » : résumer, traduire ou expliquer ce message. La réponse n'est visible que de toi, sans suite possible, et n'entre ni dans la conversation ni dans la mémoire. Une demande toutes les quelques secondes au plus. Les modérateurs ont aussi « Retenir pour le serveur » : une fenêtre reprend le texte du message, à ajuster avant de l'ajouter à la mémoire du serveur (visible et modifiable dans `/global`).
- **Calculs exacts** : toute opération, tout pourcentage et toute conversion d'unités (km/miles, kg/livres, °C/°F, durées, octets, surfaces) passent par l'outil `calculate`, jamais de tête ; les devises restent à la recherche web.
- **Outil lent** : si un outil met plus de 2 s, MARIA affiche une ligne discrète (« Je cherche sur le web… »), qu'elle modifie à chaque nouvel outil avec une formule différente, puis efface avec la réponse. Jamais pour un simple échange. Elle ne répond au message que si d'autres ont suivi.
- **Profil** : ville, équipe de foot, arrêt habituel, anniversaire, et façon de te parler (longueur, ton, emojis). « Météo chez moi », « le match de mon équipe » ou « mon métro » marchent sans question, et la réponse dit ce qui vient du profil. Les champs se règlent dans l'onglet Profil de `/moi` ou à la parole ; le style se déduit de la longueur et du ton de tes messages (jamais de leur contenu).
- **Ce que j'ai raté** : « qu'est-ce que j'ai raté ? » résume depuis ton dernier départ du salon, sans durée à préciser.
- **Vérification discrète** : une réponse qui donne des faits d'actualité sans avoir cherché est revérifiée une fois avec un outil, avec le même ton.
- **Rapidité** : les lectures indépendantes d'un même tour (météo et foot, deux recherches d'images…) partent en parallèle ; les résultats publics sont mis en cache.
- **Spontanéité** : réactions sur les messages de ceux qui lui parlent, emojis appris du serveur, suivi d'un échange qui continue.

## Commandes

Slash (après `5!sync`) :

| Commande | Rôle |
|---|---|
| `/moi` | Tout ce que MARIA sait de toi : profil (ville, équipe, arrêt, façon de te parler), souvenirs, appris récemment, à valider ; modifier, oublier, tout effacer |
| `/global` | Souvenirs du serveur : résumé, propositions, modifier, oublier |
| `/programmes` | Rappels, écoutes et surveillances : modifier, pause, reprise, saut, confirmation, suppression, tout supprimer |
| `/info` | Réglages du salon et outils disponibles |
| `/chatbot mode\|forget\|everyone\|autotranscribe\|python\|spontaneite\|limite` | Réglages, modérateurs |
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
