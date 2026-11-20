'''Pure simplified SM-2 scheduling logic for StudyDeck.'''
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Literal

Grade = Literal['again', 'hard', 'good', 'easy']
EASE_FLOOR = 1.3


def today() -> date:
    '''Return today's local date. Tests monkeypatch this helper.'''
    return date.today()


@dataclass(frozen=True)
class Schedule:
    '''Result of applying a review grade to a card.'''
    ease: float
    interval_days: int
    repetitions: int
    due_date: date


def schedule(
    ease: float,
    interval_days: int,
    repetitions: int,
    grade: Grade,
    review_date: date | None = None,
) -> Schedule:
    '''Apply one of the four simplified SM-2 grades.

    This function is pure: it has no database or framework dependencies.
    '''
    if review_date is None:
        review_date = today()

    if grade not in ('again', 'hard', 'good', 'easy'):
        raise ValueError(f'Unknown grade: {grade}')

    new_ease = float(ease)
    new_interval = int(interval_days)
    new_repetitions = int(repetitions)

    if grade == 'again':
        new_repetitions = 0
        new_interval = 1
        new_ease = max(EASE_FLOOR, new_ease - 0.2)
    elif grade == 'hard':
        new_interval = max(1, round(new_interval * 1.2))
        new_ease = max(EASE_FLOOR, new_ease - 0.15)
        new_repetitions += 1
    else:
        if new_repetitions == 0:
            base_interval = 1
        elif new_repetitions == 1:
            base_interval = 3
        else:
            base_interval = max(1, round(new_interval * new_ease))

        if grade == 'good':
            new_interval = base_interval
        else:
            new_interval = max(2, round(base_interval * 1.3))
            new_ease = new_ease + 0.15
        new_repetitions += 1

    due = review_date + timedelta(days=new_interval)
    return Schedule(
        ease=round(new_ease, 10),
        interval_days=new_interval,
        repetitions=new_repetitions,
        due_date=due,
    )


apply_grade = schedule
schedule_card = schedule
