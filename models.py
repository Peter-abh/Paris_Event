"""
Modèles SQLAlchemy
"""
from sqlalchemy import (
    Column, Integer, String, Text, Numeric, Boolean, DateTime,
    ForeignKey, UniqueConstraint
)
from sqlalchemy.orm import relationship
from datetime import datetime

from database import Base


class Category(Base):
    __tablename__ = "categories"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(50), nullable=False)
    slug = Column(String(50), nullable=False, unique=True)
    icon = Column(String(50))

    events = relationship("Event", back_populates="category")


class Venue(Base):
    __tablename__ = "venues"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False)
    raw_address = Column(String(500))
    city = Column(String(100))
    postal_code = Column(String(5))
    arrondissement = Column(Integer)
    latitude = Column(Numeric(9, 6))
    longitude = Column(Numeric(9, 6))
    external_id = Column(String(100), nullable=False)
    external_source = Column(String(50), default="iledefrance_openagenda")

    events = relationship("Event", back_populates="venue")

    __table_args__ = (
        UniqueConstraint("external_id", "external_source", name="uq_venue_external"),
    )


class Event(Base):
    __tablename__ = "events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(255), nullable=False)
    description = Column(Text)
    long_description = Column(Text)
    category_id = Column(Integer, ForeignKey("categories.id"))
    venue_id = Column(Integer, ForeignKey("venues.id"))
    start_date = Column(DateTime, nullable=False)
    end_date = Column(DateTime)
    price_conditions = Column(String(255))
    price_min = Column(Numeric(6, 2))
    is_free = Column(Boolean, default=False)
    raw_keywords = Column(String(500))
    age_min = Column(Integer)
    age_max = Column(Integer)
    image_url = Column(String(500))
    source_url = Column(String(500))
    external_id = Column(String(100), nullable=False)
    external_source = Column(String(50), default="iledefrance_openagenda")
    created_at = Column(DateTime, default=datetime.utcnow)

    category = relationship("Category", back_populates="events")
    venue = relationship("Venue", back_populates="events")

    __table_args__ = (
        UniqueConstraint("external_id", "external_source", name="uq_event_external"),
    )
