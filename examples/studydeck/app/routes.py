'''HTTP routes for the StudyDeck JSON API.'''
from __future__ import annotations

import logging
from datetime import datetime, time, timedelta

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

import app.srs as srs
from app.database import get_db
from app.models import Card, Deck, Review
from app.schemas import (
    CardCreate,
    CardOut,
    CardUpdate,
    DeckCreate,
    DeckOut,
    DeckStats,
    DeckUpdate,
    ReviewRequest,
    StatsOut,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix='/api', tags=['api'])


def _get_deck_or_404(db: Session, deck_id: int) -> Deck:
    deck = db.get(Deck, deck_id)
    if deck is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Deck not found')
    return deck


def _get_card_or_404(db: Session, card_id: int) -> Card:
    card = db.get(Card, card_id)
    if card is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Card not found')
    return card


def _card_count(db: Session, deck_id: int) -> int:
    count = db.scalar(select(func.count(Card.id)).where(Card.deck_id == deck_id))
    return int(count or 0)


def _due_count(db: Session, deck_id: int, on_date=None) -> int:
    if on_date is None:
        on_date = srs.today()
    count = db.scalar(
        select(func.count(Card.id)).where(
            Card.deck_id == deck_id,
            Card.due_date <= on_date,
        )
    )
    return int(count or 0)


def _reviewed_today_count(db: Session, deck_id: int, on_date=None) -> int:
    if on_date is None:
        on_date = srs.today()
    start = datetime.combine(on_date, time.min)
    end = start + timedelta(days=1)
    count = db.scalar(
        select(func.count(Review.id))
        .join(Card, Review.card_id == Card.id)
        .where(
            Card.deck_id == deck_id,
            Review.reviewed_at >= start,
            Review.reviewed_at < end,
        )
    )
    return int(count or 0)


def _deck_out(db: Session, deck: Deck) -> DeckOut:
    return DeckOut(
        id=deck.id,
        name=deck.name,
        description=deck.description,
        card_count=_card_count(db, deck.id),
        due_count=_due_count(db, deck.id),
    )


def _streak(db: Session, on_date=None) -> int:
    if on_date is None:
        on_date = srs.today()
    review_datetimes = db.scalars(select(Review.reviewed_at)).all()
    review_dates = {dt.date() for dt in review_datetimes if dt is not None}
    if on_date in review_dates:
        cursor = on_date
    elif (on_date - timedelta(days=1)) in review_dates:
        cursor = on_date - timedelta(days=1)
    else:
        return 0

    streak = 0
    while cursor in review_dates:
        streak += 1
        cursor -= timedelta(days=1)
    return streak


@router.get('/decks', response_model=list[DeckOut])
def list_decks(db: Session = Depends(get_db)) -> list[DeckOut]:
    decks = db.scalars(select(Deck).order_by(Deck.id.asc())).all()
    return [_deck_out(db, deck) for deck in decks]


@router.post('/decks', response_model=DeckOut, status_code=status.HTTP_201_CREATED)
def create_deck(payload: DeckCreate, db: Session = Depends(get_db)) -> DeckOut:
    deck = Deck(name=payload.name, description=payload.description)
    db.add(deck)
    db.commit()
    db.refresh(deck)
    logger.info('Created deck %s', deck.id)
    return _deck_out(db, deck)


@router.patch('/decks/{deck_id}', response_model=DeckOut)
def update_deck(deck_id: int, payload: DeckUpdate, db: Session = Depends(get_db)) -> DeckOut:
    deck = _get_deck_or_404(db, deck_id)
    fields_set = payload.model_fields_set
    if 'name' in fields_set:
        if payload.name is None:
            raise HTTPException(status_code=422, detail='Deck name cannot be null')
        deck.name = payload.name
    if 'description' in fields_set:
        deck.description = payload.description
    db.commit()
    db.refresh(deck)
    return _deck_out(db, deck)


@router.delete('/decks/{deck_id}', status_code=status.HTTP_204_NO_CONTENT)
def delete_deck(deck_id: int, db: Session = Depends(get_db)) -> Response:
    deck = _get_deck_or_404(db, deck_id)
    card_ids = db.scalars(select(Card.id).where(Card.deck_id == deck_id)).all()
    if card_ids:
        db.execute(delete(Review).where(Review.card_id.in_(card_ids)))
        db.execute(delete(Card).where(Card.deck_id == deck_id))
    db.delete(deck)
    db.commit()
    logger.info('Deleted deck %s', deck_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get('/decks/{deck_id}/cards', response_model=list[CardOut])
def list_cards(deck_id: int, db: Session = Depends(get_db)) -> list[Card]:
    _get_deck_or_404(db, deck_id)
    return list(
        db.scalars(select(Card).where(Card.deck_id == deck_id).order_by(Card.id.asc())).all()
    )


@router.post(
    '/decks/{deck_id}/cards',
    response_model=CardOut,
    status_code=status.HTTP_201_CREATED,
)
def create_card(deck_id: int, payload: CardCreate, db: Session = Depends(get_db)) -> Card:
    deck = _get_deck_or_404(db, deck_id)
    card = Card(
        deck_id=deck.id,
        front=payload.front,
        back=payload.back,
        ease=2.5,
        interval_days=0,
        repetitions=0,
        due_date=srs.today(),
    )
    db.add(card)
    db.commit()
    db.refresh(card)
    logger.info('Created card %s in deck %s', card.id, deck.id)
    return card


@router.patch('/cards/{card_id}', response_model=CardOut)
def update_card(card_id: int, payload: CardUpdate, db: Session = Depends(get_db)) -> Card:
    card = _get_card_or_404(db, card_id)
    fields_set = payload.model_fields_set
    if 'front' in fields_set:
        if payload.front is None:
            raise HTTPException(status_code=422, detail='Card front cannot be null')
        card.front = payload.front
    if 'back' in fields_set:
        if payload.back is None:
            raise HTTPException(status_code=422, detail='Card back cannot be null')
        card.back = payload.back
    db.commit()
    db.refresh(card)
    return card


@router.delete('/cards/{card_id}', status_code=status.HTTP_204_NO_CONTENT)
def delete_card(card_id: int, db: Session = Depends(get_db)) -> Response:
    card = _get_card_or_404(db, card_id)
    db.execute(delete(Review).where(Review.card_id == card.id))
    db.delete(card)
    db.commit()
    logger.info('Deleted card %s', card_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get('/decks/{deck_id}/due', response_model=list[CardOut])
def due_cards(deck_id: int, db: Session = Depends(get_db)) -> list[Card]:
    _get_deck_or_404(db, deck_id)
    current_date = srs.today()
    cards = db.scalars(
        select(Card)
        .where(Card.deck_id == deck_id, Card.due_date <= current_date)
        .order_by(Card.due_date.asc(), Card.id.asc())
    ).all()
    return list(cards)


@router.post('/cards/{card_id}/review', response_model=CardOut)
def review_card(
    card_id: int,
    payload: ReviewRequest,
    db: Session = Depends(get_db),
) -> Card:
    card = _get_card_or_404(db, card_id)
    review_date = srs.today()
    result = srs.schedule(
        ease=card.ease,
        interval_days=card.interval_days,
        repetitions=card.repetitions,
        grade=payload.grade,
        review_date=review_date,
    )
    card.ease = result.ease
    card.interval_days = result.interval_days
    card.repetitions = result.repetitions
    card.due_date = result.due_date
    # The date comes from srs.today(), like the schedule, so stats and streaks agree with it.
    reviewed_at = datetime.combine(review_date, datetime.now().time())
    review = Review(card_id=card.id, grade=payload.grade, reviewed_at=reviewed_at)
    db.add(review)
    db.commit()
    db.refresh(card)
    logger.info('Reviewed card %s with grade %s', card.id, payload.grade)
    return card


@router.get('/stats', response_model=StatsOut)
def stats(db: Session = Depends(get_db)) -> StatsOut:
    on_date = srs.today()
    decks = db.scalars(select(Deck).order_by(Deck.id.asc())).all()
    deck_stats: list[DeckStats] = []
    total_reviewed_today = 0
    for deck in decks:
        reviewed_today = _reviewed_today_count(db, deck.id, on_date)
        total_reviewed_today += reviewed_today
        deck_stats.append(
            DeckStats(
                deck_id=deck.id,
                name=deck.name,
                card_count=_card_count(db, deck.id),
                due_count=_due_count(db, deck.id, on_date),
                reviewed_today=reviewed_today,
            )
        )
    return StatsOut(
        decks=deck_stats,
        streak=_streak(db, on_date),
        total_reviewed_today=total_reviewed_today,
    )
