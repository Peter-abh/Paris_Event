# ParisEvent

Application FastAPI/Jinja2 + Tailwindcss + SQLite permettant de découvrir les événements culturels à Paris.

## Conception & Architecture

- Modèle Logique de Données : Visible dans `docs/MLP.png`. Version condensée et épurée (centrée sur les tables `Event`, `Category` et `Venue`) conçue pour répondre aux contraintes de rapidité du MVP.
- Parcours utilisateur (UI/UX) : Maquette de référence disponibles dans `docs/maquette`.
- Documentation API : Swagger UI interactif intégré nativement via FastAPI (`/docs`).

## Fonctionnalités

- Synchronisation depuis l'API Open Data Île-de-France.
- Fallback local dans `fallback_events.json`.
- Recherche par titre.
- Filtres par catégorie et période.
- Pagination classique.
- Date, lieu et tarif affichés sur les cartes.
- Synchronisation manuelle protégée par token avec `POST /admin/sync`.

## Installation

```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
npm install
npm run build:css
```

## Développement

Initialiser ou actualiser la base :

```bash
python -m sync_events
```

Lancer l'application :

```bash
uvicorn main:app --reload
```

Pendant le développement frontend, utiliser :

```bash
npm run watch:css
```

## Tests

```bash
pytest
```

Les tests de `tests/test_app.py` utilisent une base SQLite temporaire et
couvrent les routes principales, les filtres, la pagination, les assets
statiques, la route d'administration et l'idempotence de la synchronisation
fallback.

## Synchronisation administrateur

Définir le token dans l'environnement du serveur :

```powershell
$env:ADMIN_SYNC_TOKEN = "un-token-long-et-secret"
```

Puis appeler la route avec l'en-tête `X-Admin-Token` :

```powershell
Invoke-WebRequest `
  -Method Post `
  -Uri http://127.0.0.1:8000/admin/sync `
  -Headers @{ "X-Admin-Token" = "un-token-long-et-secret" }
```

La route renvoie `503` si aucun token n'est configuré, `401` si le token est
incorrect et un résultat JSON avec la source (`api` ou `fallback`) et le
nombre d'événements traités en cas de succès.

## Structure utile

```text
docs/                      Schéma MLP/MCD et maquette UI du projet
main.py                    Application FastAPI et routes
database.py                Configuration SQLAlchemy
models.py                  Modèles Category, Venue et Event
sync_events.py             Synchronisation et fallback
fallback_events.json       Données de secours locales
templates/index.html       Interface Jinja2
templates/src/logo.png     Logo
static/src/input.css       Source Tailwind
static/css/tailwind.css    CSS compilé
tests/test_app.py          Tests automatisés essentiels
```

## Déploiement Render

Commande de build :

```text
npm install && npm run build:css && pip install -r requirements.txt
```

Commande de démarrage :

```text
uvicorn main:app --host 0.0.0.0 --port $PORT
```

Configurer `ADMIN_SYNC_TOKEN` dans les variables d'environnement Render.
Le fichier SQLite du plan gratuit étant éphémère, une base PostgreSQL
managée devra être prévue pour une conservation durable des données.
