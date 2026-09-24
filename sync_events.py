import json
import re
from datetime import datetime, timezone
from pathlib import Path

import requests
from sqlalchemy.exc import SQLAlchemyError

from database import get_session
from models import Category, Venue, Event


API_BASE_URL = "https://data.iledefrance.fr/api/explore/v2.1/catalog/datasets/evenements-publics-cibul/records"
PAGE_SIZE = 100
MAX_PAGES = 20 
REQUEST_TIMEOUT = 10  # secondes

FALLBACK_PATH = Path(__file__).parent / "fallback_events.json"

# Ordre important : du plus spécifique au plus générique.
KEYWORD_TO_CATEGORY = {
    "concert": "musique", "jazz": "musique", "musique": "musique",
    "danse": "spectacle", "théâtre": "spectacle", "theatre": "spectacle",
    "cirque": "spectacle", "spectacle": "spectacle", "magie": "spectacle",
    "exposition": "exposition", "expo": "exposition", "musée": "exposition",
    "sport": "sport", "football": "sport", "course": "sport",
    "cinéma": "cinema", "film": "cinema",
    "atelier": "atelier", "conférence": "conference",
}
DEFAULT_CATEGORY_SLUG = "autre"

PARIS_ARRONDISSEMENT_RE = re.compile(r"^750(\d{2})$")


def _parse_datetime(value):
    """Convertit une date ISO (avec ou sans timezone) en datetime naïf,
    tel qu'attendu par la colonne DateTime de SQLite. Retourne None si
    la valeur est vide ou déjà un objet datetime."""
    if value is None or isinstance(value, datetime):
        return value
    # gère à la fois "...+00:00" (API) et "...+02:00" ou sans timezone (fallback)
    parsed = datetime.fromisoformat(value)
    return parsed.replace(tzinfo=None)


# ---------------------------------------------------------------------------
# Étape 1 : récupération depuis l'API (avec pagination + filtre)
# ---------------------------------------------------------------------------

def fetch_from_api() -> list[dict]:
    """
    Récupère les événements à venir à Paris, paginés.
    Lève une exception (requests.RequestException) si l'API est
    injoignable — c'est volontaire, le fallback est géré dans main().
    """
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    where_clause = f'location_city="Paris" and firstdate_begin >= "{now_iso}"'

    all_results = []
    offset = 0

    for page in range(MAX_PAGES):
        params = {
            "where": where_clause,
            "limit": PAGE_SIZE,
            "offset": offset,
            "order_by": "firstdate_begin asc",
        }
        response = requests.get(API_BASE_URL, params=params, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()  # lève une exception si code HTTP >= 400
        payload = response.json()

        results = payload.get("results", [])
        all_results.extend(results)

        total_count = payload.get("total_count", 0)
        offset += PAGE_SIZE
        if offset >= total_count or not results:
            break

    return all_results


# ---------------------------------------------------------------------------
# Étape 2 : fallback local
# ---------------------------------------------------------------------------

def fetch_fallback() -> list[dict]:
    """
    Charge le jeu de données de secours. Contrairement à fetch_from_api,
    ce fichier est DÉJÀ au format transformé (mêmes clés que produites
    par transform()) — pas besoin de le repasser dans transform().
    """
    if not FALLBACK_PATH.exists():
        raise FileNotFoundError(
            f"Fichier de fallback introuvable : {FALLBACK_PATH}. "
            "Crée-le avec au moins quelques événements de secours."
        )
    with open(FALLBACK_PATH, encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Étape 3 : transformation
# ---------------------------------------------------------------------------

def _parse_price(conditions: str | None) -> tuple[float | None, bool]:
    """Best-effort : extrait un prix minimum et déduit la gratuité depuis
    le texte libre 'conditions_fr'. Retourne (price_min, is_free)."""
    if not conditions:
        return None, False

    text = conditions.lower()
    if "gratuit" in text:
        return 0.0, True

    # cherche le premier nombre suivi ou précédé d'un symbole €
    match = re.search(r"(\d+(?:[.,]\d+)?)\s*€", text)
    if match:
        price = float(match.group(1).replace(",", "."))
        return price, False

    return None, False


def _map_category(keywords: list[str]) -> str:
    """Retourne le slug de catégorie déduit du premier keyword reconnu."""
    for kw in keywords or []:
        slug = KEYWORD_TO_CATEGORY.get(kw.lower().strip())
        if slug:
            return slug
    return DEFAULT_CATEGORY_SLUG


def _derive_arrondissement(postal_code: str | None, city: str | None) -> int | None:
    if city != "Paris" or not postal_code:
        return None
    match = PARIS_ARRONDISSEMENT_RE.match(postal_code)
    if not match:
        return None
    arr = int(match.group(1))
    return arr if arr != 0 else 1  # 75000/75001 -> 1er arrondissement


def transform(raw: dict) -> dict:
    """
    Aplatit et nettoie un enregistrement brut de l'API vers le format
    utilisé par upsert_venue / upsert_event.
    """
    keywords = raw.get("keywords_fr") or []
    price_min, is_free = _parse_price(raw.get("conditions_fr"))
    coords = raw.get("location_coordinates") or {}

    return {
        "venue": {
            "name": raw.get("location_name") or "Lieu non renseigné",
            "raw_address": raw.get("location_address"),
            "city": raw.get("location_city"),
            "postal_code": raw.get("location_postalcode"),
            "arrondissement": _derive_arrondissement(
                raw.get("location_postalcode"), raw.get("location_city")
            ),
            "latitude": coords.get("lat"),
            "longitude": coords.get("lon"),
            "external_id": raw.get("location_uid"),
        },
        "event": {
            "title": raw.get("title_fr") or "Sans titre",
            "description": raw.get("description_fr"),
            "long_description": raw.get("longdescription_fr"),
            "category_slug": _map_category(keywords),
            "start_date": raw.get("firstdate_begin"),
            "end_date": raw.get("firstdate_end"),
            "price_conditions": raw.get("conditions_fr"),
            "price_min": price_min,
            "is_free": is_free,
            "raw_keywords": ", ".join(keywords) if keywords else None,
            "age_min": raw.get("age_min"),
            "age_max": raw.get("age_max"),
            "image_url": raw.get("image"),
            "source_url": raw.get("canonicalurl"),
            "external_id": raw.get("uid"),
        },
    }


# ---------------------------------------------------------------------------
# Étape 4 : upsert en base
# ---------------------------------------------------------------------------

def get_or_create_category(session, slug: str) -> Category:
    category = session.query(Category).filter_by(slug=slug).first()
    if category is None:
        category = Category(name=slug.capitalize(), slug=slug)
        session.add(category)
        session.flush()  # pour récupérer category.id sans commit complet
    return category


def upsert_venue(session, venue_data: dict) -> Venue:
    external_id = venue_data["external_id"]
    venue = (
        session.query(Venue)
        .filter_by(external_id=external_id, external_source="iledefrance_openagenda")
        .first()
    )
    if venue is None:
        venue = Venue(external_source="iledefrance_openagenda", **venue_data)
        session.add(venue)
    else:
        for key, value in venue_data.items():
            setattr(venue, key, value)
    session.flush()
    return venue


def upsert_event(session, event_data: dict, venue: Venue) -> Event:
    # Ne modifie pas le dictionnaire source : le même fallback peut être
    # réutilisé lors d'une seconde synchronisation.
    event_data = event_data.copy()
    category = get_or_create_category(session, event_data.pop("category_slug"))
    event_data["start_date"] = _parse_datetime(event_data.get("start_date"))
    event_data["end_date"] = _parse_datetime(event_data.get("end_date"))
    external_id = event_data["external_id"]

    event = (
        session.query(Event)
        .filter_by(external_id=external_id, external_source="iledefrance_openagenda")
        .first()
    )
    if event is None:
        event = Event(
            external_source="iledefrance_openagenda",
            venue_id=venue.id,
            category_id=category.id,
            **event_data,
        )
        session.add(event)
    else:
        event.venue_id = venue.id
        event.category_id = category.id
        for key, value in event_data.items():
            setattr(event, key, value)
    return event


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def run_sync(raw_events: list[dict], session, already_transformed: bool = False) -> int:
    """Transforme (si besoin) et upsert une liste d'événements bruts.
    Retourne le nombre d'événements traités."""
    count = 0
    for raw in raw_events:
        try:
            data = raw if already_transformed else transform(raw)
            venue = upsert_venue(session, data["venue"])
            upsert_event(session, data["event"], venue)
            count += 1
        except Exception as exc:
            # un événement mal formé ne doit jamais bloquer tout le sync
            print(f"  ⚠️  Événement ignoré (erreur : {exc})")
            continue
    session.commit()
    return count


def sync_events() -> dict[str, int | str]:
    """Récupère les événements et les synchronise en base."""
    session = get_session()

    try:
        try:
            print("→ Tentative de récupération depuis l'API Île-de-France...")
            raw_events = fetch_from_api()
            print(f"  {len(raw_events)} événements récupérés depuis l'API.")
            already_transformed = False
            source = "api"

        except (requests.RequestException, SQLAlchemyError) as exc:
            print(f"  ⚠️  API indisponible ({exc}). Bascule sur le fallback local.")
            raw_events = fetch_fallback()
            print(f"  {len(raw_events)} événements chargés depuis le fallback.")
            already_transformed = True
            source = "fallback"

        processed = run_sync(
            raw_events,
            session,
            already_transformed=already_transformed,
        )
        print(f"✓ Sync terminé : {processed} événements traités en base.")
        return {"processed": processed, "source": source}
    finally:
        session.close()


def main():
    sync_events()


if __name__ == "__main__":
    main()
