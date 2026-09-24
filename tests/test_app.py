from datetime import datetime, timedelta

import pytest
from bs4 import BeautifulSoup
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database import Base, get_db
from main import app
from models import Category, Event, Venue
from sync_events import fetch_fallback, run_sync


@pytest.fixture
def client():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=engine,
    )
    Base.metadata.create_all(bind=engine)

    session = TestingSessionLocal()
    category = Category(name="Musique", slug="musique")
    venue = Venue(
        name="Salle de test",
        city="Paris",
        postal_code="75001",
        arrondissement=1,
        external_id="test-venue",
    )
    session.add_all([category, venue])
    session.flush()

    for index in range(13):
        session.add(
            Event(
                title=f"Concert de test {index}",
                category_id=category.id,
                venue_id=venue.id,
                start_date=datetime(2026, 10, 1) + timedelta(days=index),
                source_url="https://example.com/event",
                external_id=f"test-event-{index}",
            )
        )
    session.commit()
    session.close()

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=engine)


def test_homepage_filters_paginates_and_renders_dates(client):
    response = client.get("/?q=concert&category=musique&page=2")

    assert response.status_code == 200
    soup = BeautifulSoup(response.text, "html.parser")
    assert len(soup.select("article")) == 1
    assert soup.select_one("article time[datetime]") is not None
    assert "q=concert" in response.text
    assert "category=musique" in response.text


def test_events_shortcut_redirects_to_homepage(client):
    response = client.get("/events?period=week", follow_redirects=False)

    assert response.status_code == 307
    assert response.headers["location"] == "/?period=week"


def test_admin_sync_requires_a_configured_valid_token(client, monkeypatch):
    monkeypatch.delenv("ADMIN_SYNC_TOKEN", raising=False)
    assert client.post("/admin/sync").status_code == 503

    monkeypatch.setenv("ADMIN_SYNC_TOKEN", "test-token")
    unauthorized = client.post(
        "/admin/sync",
        headers={"X-Admin-Token": "wrong-token"},
    )
    assert unauthorized.status_code == 401


def test_admin_sync_returns_sync_result(client, monkeypatch):
    monkeypatch.setenv("ADMIN_SYNC_TOKEN", "test-token")
    monkeypatch.setattr(
        "main.sync_events",
        lambda: {"processed": 13, "source": "api"},
    )

    response = client.post(
        "/admin/sync",
        headers={"X-Admin-Token": "test-token"},
    )

    assert response.status_code == 200
    assert response.json() == {"processed": 13, "source": "api"}


def test_logo_and_compiled_tailwind_are_served(client):
    assert client.get("/src/logo.png").status_code == 200
    css_response = client.get("/static/css/tailwind.css")
    assert css_response.status_code == 200
    assert "font-display" in css_response.text


def test_fallback_sync_is_idempotent():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(bind=engine)
    Base.metadata.create_all(bind=engine)
    session = TestingSessionLocal()

    fallback_events = fetch_fallback()
    assert run_sync(fallback_events, session, already_transformed=True) == 3
    assert run_sync(fallback_events, session, already_transformed=True) == 3
    assert session.query(func.count(Event.id)).scalar() == 3

    session.close()
    Base.metadata.drop_all(bind=engine)
