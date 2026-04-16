"""
Pydantic schemas for validating LLM agent outputs.

Each schema enforces structure and constraints on the JSON that agents produce,
catching hallucinated fields, wrong types, and invalid category values before
they propagate through the pipeline.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, field_validator


VALID_CATEGORIES = {
    "health", "mental_health", "finances", "work", "music",
    "relationships", "travel", "food", "fitness", "learning",
    "hobbies", "family", "other",
}


# ---------------------------------------------------------------------------
# Classifier
# ---------------------------------------------------------------------------

class SentenceClassification(BaseModel):
    sentence: str
    categories: list[str]

    @field_validator("categories")
    @classmethod
    def filter_categories(cls, v: list[str]) -> list[str]:
        valid = [c for c in v if c in VALID_CATEGORIES]
        return valid if valid else ["other"]


class ClassificationResult(BaseModel):
    classifications: list[SentenceClassification]


# ---------------------------------------------------------------------------
# Entity Extractor
# ---------------------------------------------------------------------------

class EntityResult(BaseModel):
    people: list[str] = []
    places: list[str] = []
    dates: list[str] = []
    events: list[Any] = []
    amounts: list[Any] = []
    organizations: list[str] = []


# ---------------------------------------------------------------------------
# Intent Detector (reminders)
# ---------------------------------------------------------------------------

class ReminderItem(BaseModel):
    event_description: str = ""
    event_time: str = ""
    reminder_time: str = ""
    granularity: str = "time"
    channel: str = "email"

    @field_validator("granularity")
    @classmethod
    def normalize_granularity(cls, v: str) -> str:
        v = (v or "time").strip().lower()
        return v if v in {"time", "day", "week", "month"} else "time"


class ReminderResult(BaseModel):
    reminders: list[ReminderItem]


# ---------------------------------------------------------------------------
# Habit Tracker
# ---------------------------------------------------------------------------

VALID_CADENCES = {"daily", "weekly", "occasional"}


class HabitCandidate(BaseModel):
    name: str
    category: str = "other"
    cadence: str = "occasional"

    @field_validator("cadence")
    @classmethod
    def normalize_cadence(cls, v: str) -> str:
        v = (v or "occasional").strip().lower()
        return v if v in VALID_CADENCES else "occasional"

    @field_validator("category")
    @classmethod
    def normalize_category(cls, v: str) -> str:
        v = (v or "other").strip().lower()
        return v if v in VALID_CATEGORIES else "other"


class HabitExtractionResult(BaseModel):
    matched: list[str] = []  # habit_id strings of existing habits hit by this entry
    new_candidates: list[HabitCandidate] = []
