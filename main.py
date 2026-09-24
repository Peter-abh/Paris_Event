from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from math import ceil
from os import getenv
from pathlib import Path
from secrets import compare_digest
from typing import Literal
from urllib.parse import urlencode
from zoneinfo import ZoneInfo
from dotenv import load_dotenv

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from database import get_db, init_db
from models import Category, Event
from sync_events import sync_events

load_dotenv(Path(__file__).parent / ".env")


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    init_db()
    yield


app = FastAPI(title="Events App", lifespan=lifespan)
templates = Jinja2Templates(directory="templates")
app.mount(
    "/src",
    StaticFiles(directory=Path(__file__).parent / "templates" / "src"),
    name="src",
)
app.mount(
    "/static",
    StaticFiles(directory=Path(__file__).parent / "static"),
    name="static",
)
EVENTS_PER_PAGE = 12
PeriodKey = Literal["", "today", "weekend", "week", "month"]


def _pagination_pages(current_page: int, total_pages: int) -> list[int | None]:
    page_numbers = {1, total_pages}
    page_numbers.update(
        range(
            max(1, current_page - 2),
            min(total_pages, current_page + 2) + 1,
        )
    )

    pages: list[int | None] = []
    previous_page = 0
    for page_number in sorted(page_numbers):
        if previous_page and page_number > previous_page + 1:
            pages.append(None)
        pages.append(page_number)
        previous_page = page_number
    return pages


def _period_range(period: PeriodKey, today: date) -> tuple[date, date]:
    #Calcule les bornes inclusives des périodes proposées dans l'interface
    if period == "today":
        return today, today

    if period == "weekend":
        if today.weekday() == 6:
            start = today
        else:
            start = today + timedelta(days=(5 - today.weekday()) % 7)
        return start, start + timedelta(days=1)

    if period == "week":
        start = today - timedelta(days=today.weekday())
        return start, start + timedelta(days=6)

    start = today.replace(day=1)
    next_month = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
    return start, next_month - timedelta(days=1)


def _encoded_query(params: dict[str, str | None]) -> str:
    return urlencode({key: value for key, value in params.items() if value})


@app.get("/")
def read_root(
    request: Request,
    db: Session = Depends(get_db),
    page: int = Query(default=1, ge=1),
    q: str | None = None,
    category: str | None = None,
    period: PeriodKey | None = Query(default=None),
):
    search_query = (q or "").strip()
    current_category = (category or "tous").strip().lower()

    active_period = period if period else None

    events_query = db.query(Event).order_by(Event.start_date.asc())

    if search_query:
        events_query = events_query.filter(
            Event.title.ilike(f"%{search_query}%")
        )

    if current_category != "tous":
        events_query = (
            events_query.join(Event.category)
            .filter(Category.slug == current_category)
        )

    date_start = None
    date_end = None
    if active_period:
        date_start, date_end = _period_range(
            active_period,
            datetime.now(ZoneInfo("Europe/Paris")).date(),
        )

    if date_start:
        event_date = func.date(Event.start_date)
        events_query = events_query.filter(event_date >= date_start.isoformat())
        if date_end:
            events_query = events_query.filter(event_date <= date_end.isoformat())

    total_count = events_query.order_by(None).count()
    total_pages = max(1, ceil(total_count / EVENTS_PER_PAGE))
    page = min(page, total_pages)
    events = (
        events_query
        .offset((page - 1) * EVENTS_PER_PAGE)
        .limit(EVENTS_PER_PAGE)
        .all()
    )
    categories = db.query(Category).order_by(Category.name.asc()).all()

    pagination_filters = {
        "q": search_query or None,
        "category": current_category if current_category != "tous" else None,
        "period": active_period,
    }
    category_filters = {
        "q": search_query or None,
        "period": active_period,
    }
    period_filters = {
        "q": search_query or None,
        "category": current_category if current_category != "tous" else None,
    }

    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "title": "ParisEvent — L'effervescence culturelle à Paris",
            "events": events,
            "categories": categories,
            "current_category": current_category,
            "search_query": search_query,
            "current_period": active_period,
            "total_count": total_count,
            "page": page,
            "total_pages": total_pages,
            "page_numbers": _pagination_pages(page, total_pages),
            "pagination_query": _encoded_query(pagination_filters),
            "category_query": _encoded_query(category_filters),
            "period_query": _encoded_query(period_filters),
        },
    )


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/admin/sync")
def admin_sync(
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
) -> dict[str, int | str]:
    
    #Déclenche une synchronisation manuelle protégée par un token
    
    configured_token = getenv("ADMIN_SYNC_TOKEN")
    if not configured_token:
        raise HTTPException(
            status_code=503,
            detail="La synchronisation administrateur n'est pas configurée.",
        )
    if not x_admin_token or not compare_digest(x_admin_token, configured_token):
        raise HTTPException(status_code=401, detail="Token administrateur invalide.")

    try:
        return sync_events()
    except (FileNotFoundError, SQLAlchemyError) as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Échec de la synchronisation : {exc}",
        ) from exc


@app.get("/events")
def list_events(request: Request):
    target = "/"
    if request.url.query:
        target = f"{target}?{request.url.query}"
    return RedirectResponse(url=target, status_code=307)
