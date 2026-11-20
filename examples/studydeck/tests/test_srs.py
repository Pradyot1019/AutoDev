from datetime import date
import pytest
from app import srs


def test_schedule_again():
    result = srs.schedule(ease=2.5, interval_days=4, repetitions=3, grade='again', review_date=date(2025, 1, 1))
    assert result.repetitions == 0
    assert result.interval_days == 1
    assert result.ease == pytest.approx(2.3)
    assert result.due_date == date(2025, 1, 2)


def test_schedule_hard():
    result = srs.schedule(ease=2.5, interval_days=10, repetitions=2, grade='hard', review_date=date(2025, 1, 1))
    assert result.interval_days == 12
    assert result.repetitions == 3
    assert result.ease == pytest.approx(2.35)
    assert result.due_date == date(2025, 1, 13)


def test_schedule_hard_new_card_minimum_interval():
    result = srs.schedule(ease=2.5, interval_days=0, repetitions=0, grade='hard', review_date=date(2025, 1, 1))
    assert result.interval_days == 1
    assert result.due_date == date(2025, 1, 2)


def test_schedule_good_first_review():
    result = srs.schedule(ease=2.5, interval_days=0, repetitions=0, grade='good', review_date=date(2025, 1, 1))
    assert result.interval_days == 1
    assert result.repetitions == 1
    assert result.ease == pytest.approx(2.5)
    assert result.due_date == date(2025, 1, 2)


def test_schedule_good_second_review():
    result = srs.schedule(ease=2.5, interval_days=1, repetitions=1, grade='good', review_date=date(2025, 1, 1))
    assert result.interval_days == 3
    assert result.repetitions == 2
    assert result.due_date == date(2025, 1, 4)


def test_schedule_good_later_review():
    result = srs.schedule(ease=2.5, interval_days=4, repetitions=2, grade='good', review_date=date(2025, 1, 1))
    assert result.interval_days == 10
    assert result.repetitions == 3
    assert result.due_date == date(2025, 1, 11)


def test_schedule_easy_first_review_minimum_two_days():
    result = srs.schedule(ease=2.5, interval_days=0, repetitions=0, grade='easy', review_date=date(2025, 1, 1))
    assert result.interval_days == 2
    assert result.repetitions == 1
    assert result.ease == pytest.approx(2.65)
    assert result.due_date == date(2025, 1, 3)


def test_schedule_easy_second_review():
    result = srs.schedule(ease=2.5, interval_days=1, repetitions=1, grade='easy', review_date=date(2025, 1, 1))
    assert result.interval_days == 4
    assert result.repetitions == 2
    assert result.ease == pytest.approx(2.65)
    assert result.due_date == date(2025, 1, 5)


def test_schedule_ease_floor_for_again():
    result = srs.schedule(ease=1.3, interval_days=1, repetitions=1, grade='again', review_date=date(2025, 1, 1))
    assert result.ease == pytest.approx(1.3)


def test_schedule_ease_floor_for_hard():
    result = srs.schedule(ease=1.35, interval_days=1, repetitions=1, grade='hard', review_date=date(2025, 1, 1))
    assert result.ease == pytest.approx(1.3)


def test_schedule_unknown_grade_raises():
    with pytest.raises(ValueError):
        srs.schedule(ease=2.5, interval_days=0, repetitions=0, grade='bad', review_date=date(2025, 1, 1))


def test_today_returns_date():
    assert isinstance(srs.today(), date)
