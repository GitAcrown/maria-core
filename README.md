# maria-core

MARIA est un bot Discord. Elle discute dans les salons, réagit selon l'activité du serveur, retient ce qu'on lui demande de retenir, et envoie des rappels ou des veilles. Un seul processus, une base SQLite, des extensions pour la météo, le foot, les films, la musique et les transports.

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

Renseigne au minimum `TOKEN`, `APP_ID` et `OPENAI_API_KEY` dans `.env`. Les autres clés activent des extensions. Sans clé, l'outil correspondant reste caché. `DATA_DIR` est le dossier de `maria.db` et de l'index Chroma.

## Lancement

```bash
python -m maria_core --check --env-file .env
python -m maria_core --env-file .env
```

`--check` ouvre la base et charge les extensions, sans se connecter à Discord.

Le préfixe par défaut est `5!`. `5!spontaneite` règle le niveau (`off`, `quiet`, `normal`, `chatty`). `5!moi` montre les souvenirs de la personne. `5!why` explique une réaction, réservé au propriétaire du bot.

MARIA répond dans les salons quand on s'adresse à elle. Un message privé ne lance pas de conversation : il ne sert qu'à recevoir un rappel ou une veille programmés.

Si Chroma ne s'installe pas, le bot démarre quand même. La recherche des souvenirs reste lexicale.

## Import depuis MARIA_R

La commande lit une copie du dossier MARIA_R, en lecture seule, et affiche un rapport avant d'écrire.

```bash
python -m maria_core.legacy /chemin/vers/copie-MARIA_R --database data/maria.db
python -m maria_core.legacy /chemin/vers/copie-MARIA_R --database data/maria.db --write
```

Le second passage ne duplique pas les lignes déjà reprises.
