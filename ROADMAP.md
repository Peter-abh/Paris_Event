# Roadmap — App d'événements culturels à Paris (MVP 4h)

> Ce document sert de brief de reprise pour une IA ou un développeur qui
> continue ce projet dans une nouvelle session. Il résume l'objectif, les
> décisions déjà prises, ce qui est déjà construit, et les étapes restantes.

## 1. Objectif du projet

Application web permettant aux utilisateurs de trouver facilement des
événements culturels et ludiques à Paris : concerts, spectacles, théâtre,
sport, expositions, etc.

**Contrainte principale : obtenir un MVP fonctionnel en 4h de développement.**
Toute décision d'architecture ci-dessous a été prise pour tenir ce délai —
ne pas réintroduire de complexité (comptes utilisateurs, favoris, reviews,
etc.) sans que ce soit explicitement demandé.

## 2. Stack technique retenue

- **Backend** : FastAPI
- **Templates** : Jinja2 (rendu HTML côté serveur, pas de frontend séparé)
- **Base de données** : SQLite (fichier local `events.db`)
- **ORM** : SQLAlchemy
- **Déploiement cible** : Render

**Pourquoi ce choix** : l'app n'a besoin d'aucune interactivité riche côté
client (pas de drag-and-drop, pas de mise à jour temps réel) — une page qui
se recharge avec les filtres en query params suffit. FastAPI + Jinja2 évite
toute la complexité d'une API JSON séparée + build frontend + CORS. React a
été explicitement écarté pour ce MVP (voir section 7, décisions rejetées).

### ⚠️ Point de vigilance déploiement (Render)

Le filesystem de Render est **éphémère** sur le plan gratuit : un fichier
SQLite est perdu à chaque redémarrage/redéploiement, sauf à payer pour un
disque persistant. Pour le MVP, c'est acceptable (on relance le script de
sync avant chaque démo). Si le projet doit vivre au-delà du MVP, prévoir une
migration vers PostgreSQL (Render propose un tier gratuit managé et
persistant pour ça) — le code SQLAlchemy actuel est compatible avec les deux
via `DATABASE_URL`, donc pas de refactor lourd à prévoir.

## 3. Source de données

**Dataset retenu** : Open Data Île-de-France, dataset `evenements-publics-cibul`
(alimenté par OpenAgenda), couvrant toute l'Île-de-France — filtré côté
requête sur `location_city="Paris"`.

- Portail : `https://data.iledefrance.fr`
- Endpoint (API Explore v2.1) :
  `https://data.iledefrance.fr/api/explore/v2.1/catalog/datasets/evenements-publics-cibul/records`
- Accès **ouvert**, pas de clé API ni de compte nécessaire.
- ⚠️ La syntaxe exacte du paramètre `where` (ODSQL) n'a pas été validée en
  conditions réelles (testée uniquement en environnement sandbox sans accès
  réseau au domaine). À vérifier en premier avec un `curl` avant de debug
  quoi que ce soit d'autre si le sync échoue.

### Structure JSON réelle confirmée (champs clés)

```
uid, slug, canonicalurl
title_fr, description_fr, longdescription_fr, conditions_fr, keywords_fr[]
image, imagecredits
firstdate_begin, firstdate_end, lastdate_begin, lastdate_end, timings (string JSON)
location_uid, location_name, location_address, location_postalcode,
location_city, location_coordinates {lat, lon}
age_min, age_max
```

Points importants qui ont guidé le schéma de BDD (section 4) :
- Pas de prix structuré : `conditions_fr` est du texte libre
  (ex. "Gratuit", "16€ / 13€ tarif réduit") → parsing best-effort en Python.
- `location_postalcode` et `location_city` existent déjà nativement → pas
  besoin de regex sur l'adresse pour ça.
- `firstdate_begin`/`firstdate_end` donnent directement le premier créneau
  à venir → pas besoin de parser le champ `timings` (liste brute) pour le MVP.
- Alternative écartée : API OpenAgenda directe et `opendata.paris.fr`
  (dataset "Que Faire à Paris") — abandonnés respectivement pour schéma
  moins pratique et pour un problème d'accès non résolu en session
  précédente. Ne pas y revenir sans raison explicite.
- Ticketmaster Discovery API évaluée et **écartée pour le MVP** (nécessite
  un compte, couvre mal les événements gratuits/municipaux qui sont le cœur
  de cible de l'app). À reconsidérer seulement en V2 pour enrichir avec de
  gros événements commerciaux.

## 4. Schéma de base de données

3 tables (`categories`, `venues`, `events`), volontairement dénormalisées
pour le MVP (pas de many-to-many catégories/tags, pas de comptes
utilisateurs, pas de récurrence d'événements).

Le schéma DBML de référence (à jour, corrigé pour matcher la vraie
structure de l'API) est dans les scripts `database.py` et `models.py` — voir
section 5. Points
clés du schéma :

- `venues` et `events` ont chacun un couple `(external_id, external_source)`
  avec contrainte `UNIQUE`, utilisé pour l'upsert (dédup lors des sync
  répétés).
- `events.price_conditions` (texte brut) + `events.price_min` /
  `events.is_free` (dérivés best-effort par parsing regex) — ne pas
  supposer que `price_min` est fiable à 100%.
- `events.raw_keywords` (texte brut des keywords API) sert à mapper vers
  `category_id` via un dictionnaire Python (voir `KEYWORD_TO_CATEGORY` dans
  `sync_events.py`) — pas de relation many-to-many.
- `venues.arrondissement` n'est renseigné que si `city = 'Paris'`, sinon
  NULL (le dataset couvre toute l'Île-de-France).

## 5. Ce qui est déjà construit et testé

Fichiers livrés à la racine du projet :

- **`database.py`** — configuration SQLAlchemy centralisée (`engine`,
  `SessionLocal`, `Base`, `get_db()`, `get_session()`) avec une URL
  `DATABASE_URL` configurable et `events.db` par défaut.
- **`models.py`** — modèles SQLAlchemy (`Category`, `Venue`, `Event`) utilisant
  la `Base` centralisée.
- **`sync_events.py`** — script de synchronisation complet :
  - `fetch_from_api()` : pagination + filtre `where` sur ville/date
  - `fetch_fallback()` : charge `fallback_events.json` si l'API échoue
  - `transform()` : aplatissement JSON, parsing prix, mapping catégorie,
    dérivation arrondissement
  - `upsert_venue()` / `upsert_event()` : upsert basé sur
    `(external_id, external_source)`
  - `main()` : orchestration avec `try/except` autour de l'appel API
- **`fallback_events.json`** — 3 événements de secours réalistes, déjà
  au format transformé.

**Testé et validé en sandbox** :
- Le script tourne sans erreur (bascule automatique sur le fallback quand
  l'API est injoignable).
- L'upsert est idempotent (relancer le script 2x ne duplique rien — vérifié :
  3 events / 3 venues après 2 exécutions).
- Bug corrigé : les dates ISO string doivent être converties en objets
  `datetime` Python avant insertion SQLite (`_parse_datetime()` dans
  `sync_events.py`).

**Validé en conditions réelles** : l'appel API a permis de récupérer 1 062
événements parisiens, avec 471 lieux, 7 catégories et aucun doublon sur les
identifiants externes.

## 6. Prochaines étapes (dans l'ordre)

1. **Application FastAPI** :
   - Route `GET /` : page unique avec liste paginée et filtres
     (`?q=concert&category=musique&period=weekend`)
   - Route `GET /events` : redirection de compatibilité vers `/`
   - Route `POST /admin/sync` protégée par l'en-tête `X-Admin-Token` et la
     variable d'environnement `ADMIN_SYNC_TOKEN`
2. **Interface Jinja2** : page d'accueil unique avec cartes d'événements,
   pagination classique et formulaire de filtre en GET (pas de JS requis).
   Le menu mobile conserve les raccourcis Agenda, Lieux et Coups de cœur vers
   la liste générale `/events`.
3. **Styles** : Tailwind est compilé localement dans
   `static/css/tailwind.css` à partir de `static/src/input.css`.
4. **Tests** : les tests essentiels se trouvent dans `tests/test_app.py` et
   couvrent les routes, filtres, pagination, assets, sync admin et
   l'idempotence du fallback.
5. **(Optionnel, si temps restant)** : ajouter HTMX pour un filtrage
   dynamique sans reload complet — reste dans l'esprit "zéro complexité
   frontend", à ne considérer qu'une fois le MVP de base fonctionnel.
6. **Déploiement sur Render** en gardant à l'esprit la contrainte filesystem
   éphémère (section 2) — relancer le sync manuellement avant toute démo.

## 7. Décisions explicitement écartées pour le MVP (ne pas réintroduire sans le demander)

- Comptes utilisateurs, authentification, favoris, reviews/notes
- Relation many-to-many catégories/tags (une seule catégorie par événement)
- Gestion de la récurrence d'événements (RRULE) — on ne garde que le premier
  créneau à venir par événement
- Recherche géospatiale indexée (un simple filtre par `arrondissement`
  suffit à cette échelle)
- React / frontend séparé — Jinja2 uniquement
- Intégration Ticketmaster (évaluée, écartée — voir section 3)
- Cron/scheduler automatique pour le sync — déclenchement manuel via route
  `/admin/sync` suffit pour le MVP

## 8. Comment relancer le script de sync

```bash
python -m sync_events
```

Crée/met à jour `events.db` à la racine du dossier. Peut être relancé sans
risque (upsert idempotent). Pour reconstruire le CSS et lancer les tests :

```bash
npm install
npm run build:css
pytest
```

Pour utiliser la synchronisation administrateur, définir `ADMIN_SYNC_TOKEN`
dans l'environnement du serveur et envoyer ce token dans l'en-tête
`X-Admin-Token` lors d'un appel `POST /admin/sync`.
