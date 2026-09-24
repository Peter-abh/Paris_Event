import os
from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


SQLALCHEMY_DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "sqlite:///./events.db",
)

connect_args = (
    {"check_same_thread": False}
    if SQLALCHEMY_DATABASE_URL.startswith("sqlite")
    else {}
)

engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)


class Base(DeclarativeBase):
    # Classe de base commune à tous les modèles SQLAlchemy.
    pass

def init_db() -> None:
    """Crée les tables après le chargement des modèles."""
    import models  # noqa: F401

    Base.metadata.create_all(bind=engine)


def get_db() -> Generator[Session, None, None]:
    # Fournit une session SQLAlchemy à une route FastAPI
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_session() -> Session:
    #Ouvre une session pour les scripts et tâches hors requête HTTP.
    init_db()
    return SessionLocal()