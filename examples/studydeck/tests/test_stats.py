import pytest
from sqlalchemy import delete
from app.database import Base, SessionLocal, engine
from app.models import Card, Deck, Review


@pytest.fixture(autouse=True)
def clean_db():
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        db.execute(delete(Review))
        db.execute(delete(Card))
        db.execute(delete(Deck))
        db.commit()
    yield
    with SessionLocal() as db:
        db.execute(delete(Review))
        db.execute(delete(Card))
        db.execute(delete(Deck))
        db.commit()


def make_deck(client):
    response = client.post('/api/decks', json={'name': 'Deck'})
    assert response.status_code == 201
    return response.json()


def make_card(client, deck_id):
    response = client.post(f'/api/decks/{deck_id}/cards', json={'front': 'F', 'back': 'B'})
    assert response.status_code == 201
    return response.json()


def test_stats_empty(client):
    response = client.get('/api/stats')
    assert response.status_code == 200
    body = response.json()
    assert body['decks'] == []
    assert body['streak'] == 0
    assert body['total_reviewed_today'] == 0


def test_stats_counts_cards_due_and_reviewed_today(client, monkeypatch):
    import app.srs as srs
    from datetime import date, datetime, time
    fixed = date(2025, 1, 10)
    monkeypatch.setattr(srs, 'today', lambda: fixed)
    deck = make_deck(client)
    deck_id = deck['id']
    card = make_card(client, deck_id)
    card_id = card['id']
    with SessionLocal() as db:
        db.add(Review(card_id=card_id, grade='good', reviewed_at=datetime.combine(fixed, time(12, 0))))
        db.commit()
    body = client.get('/api/stats').json()
    assert body['decks'][0]['card_count'] == 1
    assert body['decks'][0]['due_count'] == 1
    assert body['decks'][0]['reviewed_today'] == 1
    assert body['total_reviewed_today'] == 1
    assert body['streak'] == 1


def test_stats_streak_includes_today(client, monkeypatch):
    import app.srs as srs
    from datetime import date, datetime, time, timedelta
    fixed = date(2025, 1, 10)
    monkeypatch.setattr(srs, 'today', lambda: fixed)
    deck = make_deck(client)
    deck_id = deck['id']
    card = make_card(client, deck_id)
    card_id = card['id']
    with SessionLocal() as db:
        db.add(Review(card_id=card_id, grade='good', reviewed_at=datetime.combine(fixed - timedelta(days=1), time(12, 0))))
        db.add(Review(card_id=card_id, grade='good', reviewed_at=datetime.combine(fixed, time(12, 0))))
        db.commit()
    body = client.get('/api/stats').json()
    assert body['streak'] == 2


def test_stats_streak_anchors_to_yesterday(client, monkeypatch):
    import app.srs as srs
    from datetime import date, datetime, time, timedelta
    fixed = date(2025, 1, 10)
    monkeypatch.setattr(srs, 'today', lambda: fixed)
    deck = make_deck(client)
    deck_id = deck['id']
    card = make_card(client, deck_id)
    card_id = card['id']
    with SessionLocal() as db:
        db.add(Review(card_id=card_id, grade='good', reviewed_at=datetime.combine(fixed - timedelta(days=1), time(12, 0))))
        db.add(Review(card_id=card_id, grade='good', reviewed_at=datetime.combine(fixed - timedelta(days=2), time(12, 0))))
        db.commit()
    body = client.get('/api/stats').json()
    assert body['streak'] == 2


def test_stats_streak_zero_without_recent_reviews(client, monkeypatch):
    import app.srs as srs
    from datetime import date, datetime, time, timedelta
    fixed = date(2025, 1, 10)
    monkeypatch.setattr(srs, 'today', lambda: fixed)
    deck = make_deck(client)
    deck_id = deck['id']
    card = make_card(client, deck_id)
    card_id = card['id']
    with SessionLocal() as db:
        db.add(Review(card_id=card_id, grade='good', reviewed_at=datetime.combine(fixed - timedelta(days=3), time(12, 0))))
        db.commit()
    body = client.get('/api/stats').json()
    assert body['streak'] == 0
