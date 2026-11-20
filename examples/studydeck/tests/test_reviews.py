import pytest
from sqlalchemy import delete, select
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


def test_review_again_updates_schedule(client, monkeypatch):
    import app.srs as srs
    from datetime import date
    monkeypatch.setattr(srs, 'today', lambda: date(2025, 1, 1))
    deck = make_deck(client)
    deck_id = deck['id']
    card = make_card(client, deck_id)
    card_id = card['id']
    response = client.post(f'/api/cards/{card_id}/review', json={'grade': 'again'})
    assert response.status_code == 200
    body = response.json()
    assert body['ease'] == pytest.approx(2.3)
    assert body['interval_days'] == 1
    assert body['repetitions'] == 0
    assert body['due_date'] == '2025-01-02'


def test_review_good_excludes_card_from_due(client, monkeypatch):
    import app.srs as srs
    from datetime import date
    monkeypatch.setattr(srs, 'today', lambda: date(2025, 1, 1))
    deck = make_deck(client)
    deck_id = deck['id']
    card = make_card(client, deck_id)
    card_id = card['id']
    before = client.get(f'/api/decks/{deck_id}/due')
    assert [c['id'] for c in before.json()] == [card_id]
    client.post(f'/api/cards/{card_id}/review', json={'grade': 'good'})
    after = client.get(f'/api/decks/{deck_id}/due')
    assert after.json() == []


def test_review_unknown_card_returns_404(client):
    response = client.post('/api/cards/9999/review', json={'grade': 'good'})
    assert response.status_code == 404


def test_review_unknown_grade_returns_422(client):
    deck = make_deck(client)
    deck_id = deck['id']
    card = make_card(client, deck_id)
    card_id = card['id']
    response = client.post(f'/api/cards/{card_id}/review', json={'grade': 'bad'})
    assert response.status_code == 422


def test_review_inserts_review_row(client):
    deck = make_deck(client)
    deck_id = deck['id']
    card = make_card(client, deck_id)
    card_id = card['id']
    response = client.post(f'/api/cards/{card_id}/review', json={'grade': 'hard'})
    assert response.status_code == 200
    with SessionLocal() as db:
        review = db.scalar(select(Review).where(Review.card_id == card_id))
        assert review is not None
        assert review.grade == 'hard'
