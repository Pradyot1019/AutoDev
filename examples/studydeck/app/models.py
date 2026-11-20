'''SQLAlchemy 2.0 ORM models for StudyDeck.'''
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

import app.srs as srs
from app.database import Base


def _today_default() -> date:
    '''Default due date, resolved dynamically so tests can monkeypatch srs.today.'''
    return srs.today()


class Deck(Base):
    __tablename__ = 'decks'

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    description: Mapped[str | None] = mapped_column(String(300), nullable=True)

    cards: Mapped[list['Card']] = relationship(
        'Card',
        back_populates='deck',
        cascade='all, delete-orphan',
        passive_deletes=True,
    )


class Card(Base):
    __tablename__ = 'cards'

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    deck_id: Mapped[int] = mapped_column(
        ForeignKey('decks.id', ondelete='CASCADE'), nullable=False, index=True
    )
    front: Mapped[str] = mapped_column(Text, nullable=False)
    back: Mapped[str] = mapped_column(Text, nullable=False)
    ease: Mapped[float] = mapped_column(Float, nullable=False, default=2.5)
    interval_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    repetitions: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    due_date: Mapped[date] = mapped_column(Date, nullable=False, default=_today_default)

    deck: Mapped['Deck'] = relationship('Deck', back_populates='cards')
    reviews: Mapped[list['Review']] = relationship(
        'Review',
        back_populates='card',
        cascade='all, delete-orphan',
        passive_deletes=True,
    )


class Review(Base):
    __tablename__ = 'reviews'

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    card_id: Mapped[int] = mapped_column(
        ForeignKey('cards.id', ondelete='CASCADE'), nullable=False, index=True
    )
    grade: Mapped[str] = mapped_column(String(10), nullable=False)
    reviewed_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.now
    )

    card: Mapped['Card'] = relationship('Card', back_populates='reviews')
