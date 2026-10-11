# maria-core : plan de réécriture et de migration

Objectif : une MARIA aussi intelligente et versatile qu'aujourd'hui, mais
construite sur une base propre. On allège la **structure** (chemins en double,
décisions dispersées, couplage, bricolages), pas les **capacités**.

Ce plan s'appuie sur l'audit du dépôt MARIA_R du 11 octobre 2026.

Principes :

1. **Parité fonctionnelle avant la bascule.** Ce qui rend MARIA intelligente,
   versatile ou spontanée est conservé. Seuls les doublons et le code mort
   disparaissent.
2. **Chaque décision a un propriétaire, un budget et une trace.** MARIA peut
   être spontanée, mais on doit toujours pouvoir dire pourquoi elle a agi.
3. **Le noyau est petit, les fonctionnalités sont des extensions.** Ajouter une
   capacité, un type d'objectif ou un comportement social ne modifie pas le
   noyau.
4. **La mémoire est puissante mais consentie.** MARIA peut repérer et proposer
   ce qui mérite d'être retenu. Elle ne l'enregistre durablement qu'avec
   l'accord de la personne concernée.

---

## 1. Ce que l'audit impose

| Constat dans MARIA_R | Réponse de maria-core |
|---|---|
| ~26 800 lignes, `chat.py` (3 439 lignes) exécute aussi les tâches | Cible **10 000 à 12 000 lignes** à parité. Les cogs Discord ne contiennent aucun métier. |
| Une vingtaine de décisions JEV appelées depuis partout, plus des regex et le LLM | Un module `decisions/` unique : chaque décision est nommée, a un budget, un cache, un repli, et est journalisée. |
| Réactions ambiantes perçues comme aléatoires | Le tirage au hasard est remplacé par un score explicable et un budget par salon. Réglable par serveur. |
| Tâches : `kind`, `schedule_kind`, `trigger_json`, `recipe_json.plan`, chemin legacy | Un **objectif** = déclencheur + condition + action, chacun étant un type enregistré et extensible. |
| Mémoire passive écrite sans consentement, decay automatique | Trois niveaux séparés : contexte, propositions, mémoire durable. Recherche sémantique conservée. |
| 9 bases SQLite, `ALTER TABLE` au démarrage | Une base, migrations versionnées, sauvegarde avant chaque migration. |
| Cogs qui s'appellent par attributs privés | Communication par services injectés et par un bus d'événements interne. |
| 6 fichiers de tests | Tests écrits avec chaque module, critères de sortie testés par phase. |

---

## 2. Périmètre : tout est gardé, rien n'est dupliqué

### Conservé et porté

| Domaine | Fonctionnalités |
|---|---|
| Conversation | Mention, reply, MP, mode greedy avec filtre d'adresse, debounce, fenêtres de suivi, édition de message rejouée, personnalité par serveur, images, transcription vocale (à la demande et automatique) |
| Spontanéité | Réactions ambiantes, réactions apprises, bandwagon, réactions sur demande, silence choisi, fatigue et attention, statistiques d'emojis du serveur, fun-stat |
| Mémoire | Souvenirs par membre, par serveur et sur MARIA elle-même, recherche hybride sémantique + lexicale, profils injectés, mise à jour, fusion, contradiction, `/moi`, `/global`, outils `search_memory`, `remember_fact`, `forget_fact` |
| Objectifs | Rappels ponctuels et récurrents, veilles de prix, écoutes de mots-clés et de sujets, signaux vocaux et arrivées, conditions jugées, récapitulatifs rédigés, brouillons confirmés, pause, reprise, saut, modification |
| Capacités | Web (recherche, lecture, images), météo, transport, football, TMDB, YouTube, Spotify, Steam, infos Discord, statistiques serveur, résumé de salon, sondages, `about_me`, `run_python`, tableaux et widgets |
| Interface | Widgets riches, onglets, signets, `/taches`, `/signets`, `/info`, commandes owner |

### Supprimé parce que dupliqué ou mort

- le chemin d'exécution legacy des tâches et la double taxonomie `kind` / `schedule_kind` ;
- la seconde horloge implicite des events (date sentinelle 2099) ;
- les heuristiques regex sur le français dispersées dans plusieurs modules,
  regroupées dans `decisions/rules/` ;
- l'extraction de la catégorie mémoire `event`, déjà ignorée ;
- `rappels.db` et sa migration, déjà jouée ;
- les accès privés entre cogs (`Web._crawl_page`, `Chat._channel_config`…).

### Modifié en comportement (volontairement)

| Avant | Après |
|---|---|
| Un fait passif est inséré en base, un fait dit à MARIA devient actif sans accord | Le fait devient une **proposition**. Il est retenu après accord explicite, ou immédiatement si la personne a dit « retiens ». |
| Decay automatique qui archive des souvenirs | Pas de suppression silencieuse. Les souvenirs peu utilisés sont signalés dans `/moi` pour révision. |
| Réaction ambiante décidée en partie au hasard | Score déterministe + budget + une décision structurée. La raison est journalisée. |

---

## 3. Architecture

Un seul processus. Un noyau stable, des extensions.

```text
           Discord (messages, réactions, voix, slash, boutons)
                               |
                    discord/  (adaptateurs, rendu)
                               |
                 Event bus interne  <---  scheduler (horloge)
                    /        |         \             \
          conversation    social    objectives      memory
                    \        |         /             /
                     decisions/  (règles, JEV, LLM)
                               |
                  capabilities/  (outils, via registre)
                               |
                 infrastructure (SQLite, vecteurs, OpenAI, HTTP)
```

### Arborescence

```text
maria-core/
  pyproject.toml
  .env.example
  maria_core/
    __main__.py
    app.py                  # assemble services, charge les extensions
    config.py               # réglages typés (.env + réglages par serveur en base)
    logging.py
    events.py               # bus interne : publish / subscribe, événements typés
    plugins.py              # contrat d'extension et chargement

    db/
      database.py           # SQLite unique, exécution hors boucle, sauvegardes
      migrations/
    vectors/
      index.py              # interface VectorIndex
      chroma.py             # implémentation actuelle (données conservées)

    llm/
      client.py             # complétion, vision, transcription, sortie structurée, coût
      conversation.py       # boucle de tour avec outils
      history.py            # contexte de salon + résumé de session
      prompt.py             # assemblage du prompt par sections enregistrées

    decisions/
      registry.py           # décisions nommées : budget, cache, repli, journal
      rules/                # règles déterministes (adresse, bruit, mots-clés…)
      structured.py         # backend JEV, remplaçable par sortie structurée OpenAI
      catalog.py            # liste des décisions et de leur politique

    capabilities/
      base.py               # Capability, Context, Result, Risk
      registry.py
      builtin/              # web, discord_info, memory, objectives, summary, self, polls
    plugins/                # météo, transport, football, tmdb, youtube, spotify, steam,
                            # sandbox python, funstat — chacun autonome

    conversation/
      routing.py            # répondre ? (règles puis décision « adresse »)
      followup.py           # fenêtres de suivi
      service.py            # orchestre un tour : contexte, mémoire, LLM, rendu

    social/
      signals.py            # état : fatigue, attention, activité du salon
      reactions.py          # réactions ambiantes, apprises, bandwagon, sur demande
      emoji_usage.py        # apprentissage des emojis du serveur
      budget.py             # plafonds par salon, par membre, par heure

    objectives/
      model.py              # Objective, statuts, transitions
      types.py              # registre des types de déclencheur, condition, action
      builtin_types.py      # at, daily, interval, on_message, on_topic, on_voice, …
      store.py
      scheduler.py
      matcher.py            # événements -> objectifs concernés
      runner.py             # évalue un objectif pour une activation

    memory/
      model.py              # Memory, Proposal, Revision
      store.py              # SQLite + FTS5
      retrieval.py          # recherche hybride, profils, injection
      proposals.py          # extraction -> propositions
      policy.py             # qui peut écrire quoi, et quand

    ui/
      widgets.py            # registre de rendus par capacité
      tabs.py               # onglets persistants
      bookmarks.py
      render.py             # messages longs, sources, pieds de message

    discord/
      bot.py
      chat_cog.py           # on_message, on_message_edit -> bus
      reactions_cog.py      # on_raw_reaction_add -> bus
      voice_cog.py          # voix, arrivées -> bus
      commands/             # slash et owner, un fichier par groupe
      views/                # objectifs, mémoire, propositions

  scripts/
    import_legacy.py
  tests/
```

### Contrat d'extension

Une extension est un module qui expose `setup(app)`. Elle peut enregistrer, sans
toucher au noyau :

```python
def setup(app: App) -> None:
    app.capabilities.register(TransportCapability(app.http, app.config))
    app.widgets.register("get_transport", render_transport)
    app.objectives.types.register_condition(PriceCondition)
    app.decisions.register(TOPIC_RELEVANCE)
    app.events.subscribe(MessageCreated, my_handler)
    app.prompt.register_section("transport_hint", build_hint)
    app.commands.add(transport_group)
```

Le rechargement à chaud d'une extension retire et réenregistre ses éléments.
C'est ce qui garantit qu'une évolution future reste locale.

### Garde-fous automatiques

Vérifiés par `ruff` et un test d'architecture :

- aucun fichier au-delà de 500 lignes, complexité par fonction plafonnée ;
- `objectives`, `memory`, `decisions`, `llm`, `social` n'importent pas `discord` ;
- aucun appel OpenAI ou JEV hors `llm/client.py` et `decisions/structured.py` ;
- aucune décision probabiliste hors `decisions/` ;
- aucun accès à un attribut privé d'un autre module.

---

## 4. Décisions : centralisées, budgétées, traçables

MARIA_R appelle JEV et le LLM depuis une dizaine d'endroits, avec des seuils
codés en dur. maria-core garde ces décisions, mais les déclare toutes au même
endroit :

```python
@dataclass(frozen=True)
class Decision:
    name: str                       # "ambient_react"
    rules: Callable | None          # tranche sans modèle quand c'est possible
    backend: Literal["structured", "llm"]
    threshold: float
    budget: Budget                  # par salon, serveur, jour
    cache_ttl: timedelta
    fallback: Any                   # si budget épuisé, clé absente ou erreur
```

Chaque appel produit une trace `decision_log(name, input_hash, path, verdict,
confidence, ms, cost)`. `path` vaut `rules`, `cache`, `model` ou `fallback`.

Catalogue initial (repris des usages réels de MARIA_R) :

| Décision | Règles d'abord | Modèle si nécessaire |
|---|---|---|
| `addressed_to_bot` (greedy) | Prénom en bord de phrase, mention, reply | Prénom au milieu d'une phrase |
| `followup` | Délai, profondeur de chaîne, même auteur | Le message prolonge-t-il l'échange ? |
| `ambient_react` | Score + budget (voir §5) | Réagir à ce message ? |
| `pick_reaction` | Emojis appris du serveur | Lequel convient ? |
| `join_reaction` | Nombre d'humains ayant réagi, déjà fait | Rejoindre ? |
| `intent` | Pièces jointes, URL, mots d'outil | Catégorie et besoin d'outil |
| `memory_relevance` | Distance vectorielle | Pertinence d'un souvenir |
| `memory_worth_proposing` | Longueur, bruit, doublon | Fait durable ? |
| `listen_relevance` | Mot-clé exact multi-mots | Le message correspond-il à l'intention ? |
| `topic_match` | — | Sujets d'écoute concernés |
| `condition_judge` | Conditions chiffrées | Condition en texte libre |
| `draft_reply` | « oui », « non », « ok » | Réponse ambiguë à un brouillon |
| `alert_mode` | Texte court sans faits à rédiger | Rédiger ou poster tel quel ? |
| `main_price` | Score de contexte | Candidats de prix ambigus |

Le backend structuré reste JEV. Il est derrière une interface : on peut le
remplacer par la sortie structurée d'OpenAI sans toucher aux appelants.

---

## 5. Spontanéité : garder le charme, retirer l'aléatoire

Les réactions ambiantes restent. Ce qui change, c'est la façon de décider.

### Score explicable

Pour chaque message non adressé à MARIA :

```text
score = activité du salon (humains récents)
      + réactions humaines déjà posées
      + présence d'emojis ou de ton expressif
      + attention envers l'auteur
      - fatigue du salon
      - réaction de MARIA récente dans ce salon
```

- Sous le seuil : rien, sans appel au modèle.
- Au-dessus : décision `ambient_react`, puis `pick_reaction` parmi les emojis
  appris du serveur.

### Budget

- Par salon : au plus N réactions par heure (défaut 3).
- Par membre : pas deux fois de suite sur le même auteur.
- Par serveur : plafond quotidien d'appels de décision sociale.

### Réglage par serveur

`/maria spontaneite niveau:off|discret|normal|bavard` ajuste le seuil, le budget
et l'activation des fenêtres de suivi. Le défaut reproduit le comportement
actuel, sans le hasard.

### Traçabilité

Chaque réaction journalise le score, ses composantes et le verdict. La commande
owner `why <lien du message>` explique pourquoi MARIA a réagi ou non.

---

## 6. Mémoire : puissante, consentie

### Trois niveaux

| Niveau | Stockage | Durée | Injecté dans le prompt |
|---|---|---|---|
| Contexte | Historique de salon + résumé de session | Jusqu'à compaction ou redémarrage | Oui |
| Propositions | Table `memory_proposals` | 14 jours, puis expirées | Non |
| Mémoire durable | Table `memories` + index vectoriel + FTS5 | Jusqu'à suppression | Oui, par pertinence |

### Comment un souvenir naît

1. **Demande explicite** : « retiens que… », « souviens-toi… ».
   `remember_fact` écrit directement, après contrôle du sujet par `policy.py`.
2. **Proposition** : l'extracteur analyse les échanges **adressés à MARIA**
   (et non plus tout le serveur), et crée des propositions.
   - Si la proposition concerne l'auteur de l'échange, MARIA peut le dire à la
     fin de sa réponse : « Je note que tu es végétarien ? » avec un bouton
     Retenir / Ignorer. Fréquence plafonnée, désactivable par membre.
   - Sinon, elle apparaît dans `/moi` sous « Propositions ».
   - Une proposition répétée par la personne elle-même dans un échange avec
     MARIA est acceptée comme confirmation explicite.
3. **Mémoire de serveur** : créée par un modérateur, ou proposée puis validée
   par un modérateur.
4. **Mémoire de MARIA** (ses goûts) : réservée au propriétaire, comme
   aujourd'hui.

### Ce qui reste puissant

- recherche hybride vecteurs + FTS5, filtrée par auteur, mentionnés et serveur ;
- profils injectés pour l'auteur et les personnes citées ;
- mise à jour, fusion et contradiction des souvenirs existants, avec un
  historique (`memory_revisions`) qui permet d'annuler ;
- dédoublonnage textuel et sémantique ;
- `last_used_at` pour classer, et une révision proposée des souvenirs anciens au
  lieu d'un archivage silencieux ;
- l'index vectoriel actuel (`data/chroma`) est conservé et réutilisé.

### Règles testées

- une conversation de 50 messages sans demande ni accord n'ajoute rien à
  `memories` ;
- une proposition ignorée n'est jamais injectée dans un prompt ;
- un membre ne peut pas créer de souvenir sur un autre membre ;
- une suppression est immédiatement invisible, puis purgée après 30 jours ;
- toute modification produit une révision.

---

## 7. Objectifs : un modèle commun, extensible

### Modèle

```python
@dataclass
class Objective:
    id: int
    owner_id: int
    guild_id: int | None
    channel_ids: list[int]
    deliver: Literal["channel", "dm"]
    title: str
    trigger: TriggerSpec      # {"type": "daily", ...}
    condition: ConditionSpec | None
    action: ActionSpec
    status: Status            # draft, active, paused, done, cancelled, failed
    next_run_at: datetime | None
    fires: int
    max_fires: int | None
    cooldown_s: int
    expires_at: datetime | None
    state: dict               # mémoire de travail (dernier prix…)
    version: int              # verrou optimiste
```

Les types sont enregistrés, pas codés en dur :

| Famille | Types intégrés | Exemple d'extension future |
|---|---|---|
| Déclencheur | `at`, `daily`, `weekly`, `interval`, `on_message`, `on_topic`, `on_voice`, `on_member_join`, `on_reply_to` | `on_rss`, `on_stream_live` |
| Condition | `price_below`, `price_above`, `price_drop`, `judge` (texte libre jugé) | `weather_alert`, `stock_level` |
| Action | `remind` (tel quel), `alert` (gabarit), `report` (rédigé par le LLM avec outils), `fetch_then` (lire une page ou chercher, puis condition, puis message) | `post_poll`, `create_event` |

Le pipeline action / condition / suite de `task_plan.py` est conservé dans
`fetch_then`. Le chemin legacy disparaît : un rappel sans plan est un `remind`.

### Fiabilité

- réservation par bail SQLite, un seul exécuteur par objectif ;
- `objective_runs` avec clé unique `(objective_id, activation_key)` : pas de
  double envoi après redémarrage ou événement reçu deux fois ;
- rappel manqué de moins de 6 h envoyé en retard, au-delà marqué « manqué » et
  signalé au propriétaire ;
- 3 tentatives (30 s, 2 min, 10 min), puis `failed` et notification ;
- doublon détecté à la création : le modèle reçoit l'id existant et propose
  une modification ;
- quotas et budget web conservés, désormais dans un seul module.

### Outils exposés au modèle

`objective_create`, `objective_update` (modification, pause, reprise, saut,
annulation, confirmation), `objective_list`, `objective_show`. La compilation
d'un plan est faite par le noyau, pas par chaque outil.

---

## 8. Capacités

```python
class Capability(Protocol):
    name: str
    description: str
    parameters: dict           # schéma JSON strict
    risk: Risk                 # READ, WRITE, EXTERNAL, DANGEROUS
    requires: frozenset[str]   # clés de config nécessaires (ex. "BRAVE_API_KEY")

    async def run(self, ctx: Context, args: dict) -> Result: ...


@dataclass
class Result:
    ok: bool
    data: dict                 # renvoyé au modèle
    error: str = ""
    widget: str | None = None  # nom du rendu enregistré
    sources: list[Source] = field(default_factory=list)
    needs_confirmation: bool = False
```

Le registre applique pour toutes les capacités : validation, permissions selon
le risque, capacités désactivées si une clé manque, délai maximal, plafond
d'appels par tour, journalisation. `run_python` est classé `DANGEROUS` :
activable par serveur, désactivé par défaut.

Toutes les capacités de MARIA_R sont portées. Les plugins médias deviennent des
extensions autonomes avec leur rendu.

---

## 9. Persistance

`data/maria.db`, migrations `PRAGMA user_version`, sauvegarde automatique avant
chaque migration :

- `guild_settings`, `channel_settings`, `member_settings`
- `objectives`, `objective_runs`, `objective_state_vars`
- `memories`, `memories_fts`, `memory_proposals`, `memory_revisions`
- `emoji_usage`, `funstat_*`, `activity`
- `widgets`, `bookmarks`, `polls`
- `decision_log`, `llm_calls`

L'index vectoriel reste dans `data/chroma` derrière l'interface `VectorIndex`.

---

## 10. Phases

Pendant les phases 0 à 7, maria-core tourne avec une **seconde application
Discord** sur un serveur de test. MARIA_R continue de servir les vrais serveurs.

| Phase | Contenu | Sortie testée | Durée |
|---|---|---|---|
| 0. Socle | `pyproject`, config, logging, base + migrations, bus d'événements, contrat d'extension, bot, commandes owner, test d'architecture | Le bot de test se connecte, une extension factice se charge et se décharge proprement | 2 jours |
| 1. Conversation | Routage, historique, résumé de session, client LLM, boucle d'outils, prompt par sections, debounce, édition rejouée, images, transcription | Matrice de routage, bornes d'historique, boucle d'outils avec faux client | 4 jours |
| 2. Décisions | Registre, règles, backend JEV, budgets, cache, `decision_log`, catalogue | Chaque décision : chemin règles, cache, modèle, repli quand le budget est épuisé | 3 jours |
| 3. Capacités | Registre, rendu de widgets, onglets, signets ; portage de toutes les capacités | Chaque capacité avec faux client HTTP ; capacité désactivée sans clé | 6 jours |
| 4. Objectifs | Modèle, types, store, scheduler, matcher, runner, outils, vues | Pas de double envoi, redémarrage, événement dupliqué, modification sans doublon, changement d'heure, rappel manqué, quotas | 7 jours |
| 5. Mémoire | Store, recherche hybride, propositions, révisions, politique, `/moi`, `/global` | Aucune écriture sans accord, proposition non injectée, révision annulable | 5 jours |
| 6. Spontanéité | Signaux, score, budget, réactions ambiantes, apprises, bandwagon, suivi, fun-stat, réglage par serveur, commande `why` | Score reproductible, budget respecté, niveau `off` silencieux | 4 jours |
| 7. Import et essai | Import en lecture seule, une semaine sur le serveur de test, grille de parité | Rapport d'import sans erreur sur une copie réelle, parité complète | 1 semaine |
| 8. Bascule | Arrêt de MARIA_R, archive des données, import réel, token de production, surveillance 48 h | 48 h sans erreur non comprise | 1 jour + 48 h |

Total jusqu'à la bascule : **environ 7 semaines**.

---

## 11. Import depuis MARIA_R

`scripts/import_legacy.py` ouvre les bases de MARIA_R en lecture seule et
produit un rapport avant toute écriture.

| Source MARIA_R | Destination maria-core |
|---|---|
| `tasks` actives (`pending`, `paused`, `armed`, `draft` récent) | `objectives`. Les plans deviennent `fetch_then`, les rappels sans plan deviennent `remind`. Une ligne non convertible est listée, jamais devinée. |
| `tasks` terminales, `task_runs` | Non importées, archivées avec MARIA_R |
| `member_vars` | `objective_state_vars` |
| `memories` `active` | `memories`, avec une révision « importé » |
| `memories` `pending` | `memory_proposals` : jamais consenties, donc proposées à nouveau |
| `memories` `archived` | Non importées |
| `data/chroma` | Réutilisé, réconcilié avec les ids importés |
| `cogs/chat/data` | `guild_settings`, `channel_settings` |
| emojis, fun-stat, activité, signets, sondages, widgets | Tables correspondantes |

**Retour arrière** : arrêter maria-core, relancer MARIA_R. Ses données n'ont
jamais été modifiées. Les objectifs et souvenirs créés entre-temps sont listés
par `scripts/export_since_cutover.py`.

---

## 12. Ce qui est repris de MARIA_R

Repris en adaptant, avec les tests :

- extraction de prix (`task_watch.py`) et pipeline `task_plan.py` ;
- calcul des récurrences en heure de Paris et réservation (`tasks.py`) ;
- recherche et lecture web (`web.py`) ;
- conversion des outils en schéma strict (`llm/tools.py`) ;
- détection d'adresse (`greedy_address.py`), fatigue et attention (`attention.py`) ;
- normalisation et dédoublonnage mémoire (`memory/worker.py`), recherche (`rag.py`) ;
- questions JEV de `typesafe_client.py`, réparties dans le catalogue ;
- statistiques d'emojis, fun-stat, rendus des capacités ;
- le prompt de personnalité, découpé en sections.

---

## 13. Risques

| Risque | Parade |
|---|---|
| Réécriture qui n'atteint jamais la parité | Grille de parité dès la phase 0, bascule interdite tant qu'elle n'est pas complète |
| MARIA perçue comme moins vivante | Niveau de spontanéité par défaut équivalent à l'actuel ; réglage par serveur |
| Moins de souvenirs retenus qu'avant | Propositions visibles et confirmables en un clic ; mesure du taux d'acceptation |
| Coût des décisions et des récapitulatifs | Budgets par décision, `decision_log`, `llm_calls`, plafonds quotidiens |
| Données de production différentes du dossier audité | Import rejoué sur une copie réelle avant la bascule |
| Double réponse pendant le développement | Applications Discord distinctes jusqu'à la bascule |
