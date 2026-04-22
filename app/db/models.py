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
    Boolean, Column, DateTime, Float, ForeignKey, Integer,
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
    prompt_tokens = Column(Integer, default=0)
    completion_tokens = Column(Integer, default=0)
    embedding_tokens = Column(Integer, default=0)
    estimated_cost_usd = Column(Float, default=0.0)
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


class Habit(Base):
    __tablename__ = "habits"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(String, nullable=False, index=True)
    name = Column(String, nullable=False)
    category = Column(String)
    cadence = Column(String, default="occasional")  # daily | weekly | occasional
    created_at = Column(DateTime(timezone=True), default=_now)
    last_logged_at = Column(DateTime(timezone=True))
    streak_days = Column(Integer, default=0)

    logs = relationship("HabitLog", back_populates="habit", cascade="all, delete-orphan")


class HabitLog(Base):
    __tablename__ = "habit_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    habit_id = Column(UUID(as_uuid=True), ForeignKey("habits.id"), index=True)
    entry_id = Column(UUID(as_uuid=True), ForeignKey("entries.id"))
    logged_at = Column(DateTime(timezone=True), default=_now)

    habit = relationship("Habit", back_populates="logs")


class EvalRun(Base):
    __tablename__ = "eval_runs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_at = Column(DateTime(timezone=True), default=_now)
    classifier_precision = Column(Float)
    classifier_recall = Column(Float)
    entity_f1 = Column(Float)
    prompt_version = Column(String)
    passed = Column(Boolean)


class IngestJob(Base):
    __tablename__ = "ingest_jobs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(String, nullable=False, index=True)
    kind = Column(String, nullable=False)  # "audio" | "text"
    status = Column(String, nullable=False, default="queued", index=True)  # queued|running|completed|failed
    filename = Column(String)
    entry_id = Column(UUID(as_uuid=True))
    result_json = Column(Text)  # full pipeline result on success (serialized dict)
    error = Column(Text)
    created_at = Column(DateTime(timezone=True), default=_now, index=True)
    updated_at = Column(DateTime(timezone=True), default=_now, onupdate=_now)


class RequestMetric(Base):
    __tablename__ = "request_metrics"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    endpoint = Column(String, nullable=False, index=True)  # "ingest_text" | "ingest_audio" | "chat"
    user_id = Column(String, index=True)
    duration_ms = Column(Integer, nullable=False)
    status = Column(String, default="ok")  # "ok" | "error"
    created_at = Column(DateTime(timezone=True), default=_now, index=True)


class ReminderDeadLetter(Base):
    __tablename__ = "reminder_dead_letters"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_id = Column(UUID(as_uuid=True), ForeignKey("events.id"), index=True)
    user_email = Column(String)
    description = Column(Text)
    event_time = Column(DateTime(timezone=True))
    error = Column(Text)
    retry_count = Column(Integer, default=0)
    resolved = Column(Boolean, default=False, index=True)
    created_at = Column(DateTime(timezone=True), default=_now, index=True)
    last_retried_at = Column(DateTime(timezone=True))
