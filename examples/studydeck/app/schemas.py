'''Pydantic 2 request and response models for StudyDeck.'''
from __future__ import annotations

from datetime import date
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

Grade = Literal['again', 'hard', 'good', 'easy']


class DeckCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=80)
    description: Optional[str] = Field(default=None, max_length=300)


class DeckUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=80)
    description: Optional[str] = Field(default=None, max_length=300)


class DeckOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: Optional[str] = None
    card_count: int = 0
    due_count: int = 0


class CardCreate(BaseModel):
    front: str = Field(..., min_length=1, max_length=500)
    back: str = Field(..., min_length=1, max_length=500)


class CardUpdate(BaseModel):
    front: Optional[str] = Field(default=None, min_length=1, max_length=500)
    back: Optional[str] = Field(default=None, min_length=1, max_length=500)


class CardOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    deck_id: int
    front: str
    back: str
    ease: float
    interval_days: int
    repetitions: int
    due_date: date


class ReviewRequest(BaseModel):
    grade: Grade


class DeckStats(BaseModel):
    deck_id: int
    name: str
    card_count: int
    due_count: int
    reviewed_today: int


class StatsOut(BaseModel):
    decks: list[DeckStats]
    streak: int
    total_reviewed_today: int
