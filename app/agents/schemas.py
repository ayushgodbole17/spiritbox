"""
Pydantic schemas for validating LLM agent outputs.

Each schema enforces structure and constraints on the JSON that agents produce,
catching hallucinated fields, wrong types, and invalid category values before
they propagate through the pipeline.
"""
from __future__ import annotations

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
    events: list[dict] = []
    amounts: list[str] = []
    organizations: list[str] = []


# ---------------------------------------------------------------------------
# Intent Detector (reminders)
# ---------------------------------------------------------------------------

class ReminderItem(BaseModel):
    event_description: str = ""
    event_time: str = ""
    reminder_time: str = ""
    channel: str = "email"


class ReminderResult(BaseModel):
    reminders: list[ReminderItem]
