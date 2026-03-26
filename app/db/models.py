"""
SQLAlchemy ORM models for Spiritbox PostgreSQL (Cloud SQL).

Tables:
  entries       — one row per journal entry
  events        — schedulable events extracted from entries
  sentence_tags — per-sentence category tags
  eval_runs     — eval harness results tracked over time
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean, Column, DateTime, Float, ForeignKey,
    String, Text, ARRAY,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, relationship


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    google_sub = Column(String, unique=True, nullable=False, index=True)
    email = Column(String, nullable=False)
    name = Column(String)
    picture = Column(String)
    created_at = Column(DateTime(timezone=True), default=_now)


class Entry(Base):
    __tablename__ = "entries"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(String, nullable=False)
    raw_text = Column(Text)
    summary = Column(Text)
    model_tier = Column(String)   # which model tier processed this entry
    cache_hit = Column(Boolean, default=False)  # was semantic cache used
    created_at = Column(DateTime(timezone=True), default=_now)

    events = relationship("Event", back_populates="entry", cascade="all, delete-orphan")
    sentence_tags = relationship("SentenceTag", back_populates="entry", cascade="all, delete-orphan")


class Event(Base):
    __tablename__ = "events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    entry_id = Column(UUID(as_uuid=True), ForeignKey("entries.id"))
    description = Column(Text, nullable=False)
    event_time = Column(DateTime(timezone=True))
    reminder_time = Column(DateTime(timezone=True))
    scheduler_job = Column(String)
    reminded = Column(Boolean, default=False)

    entry = relationship("Entry", back_populates="events")


class SentenceTag(Base):
    __tablename__ = "sentence_tags"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    entry_id = Column(UUID(as_uuid=True), ForeignKey("entries.id"))
    sentence = Column(Text)
    categories = Column(ARRAY(String))

    entry = relationship("Entry", back_populates="sentence_tags")


class EvalRun(Base):
    __tablename__ = "eval_runs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_at = Column(DateTime(timezone=True), default=_now)
    classifier_precision = Column(Float)
    classifier_recall = Column(Float)
    entity_f1 = Column(Float)
    prompt_version = Column(String)
    passed = Column(Boolean)
