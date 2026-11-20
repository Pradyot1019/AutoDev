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


def make_card(client, deck_id, front='F', back='B'):
    response = client.post(f'/api/decks/{deck_id}/cards', json={'front': front, 'back': back})
    assert response.status_code == 201
    return response.json()


def test_due_cards_sorted_by_due_date_and_id(client, monkeypatch):
    import app.srs as srs
    from datetime import date
    monkeypatch.setattr(srs, 'today', lambda: date(2025, 1, 1))
    deck = make_deck(client)
    deck_id = deck['id']
    c1 = make_card(client, deck_id, 'a', '1')
    c2 = make_card(client, deck_id, 'b', '2')
    monkeypatch.setattr(srs, 'today', lambda: date(2025, 1, 2))
    c3 = make_card(client, deck_id, 'c', '3')
    monkeypatch.setattr(srs, 'today', lambda: date(2025, 1, 3))
    response = client.get(f'/api/decks/{deck_id}/due')
    assert response.status_code == 200
    assert [c['id'] for c in response.json()] == [c1['id'], c2['id'], c3['id']]


def test_due_unknown_deck_returns_404(client):
    response = client.get('/api/decks/9999/due')
    assert response.status_code == 404


def test_due_excludes_future_cards(client, monkeypatch):
    import app.srs as srs
    from datetime import date
    monkeypatch.setattr(srs, 'today', lambda: date(2025, 1, 1))
    deck = make_deck(client)
    deck_id = deck['id']
    monkeypatch.setattr(srs, 'today', lambda: date(2025, 1, 10))
    make_card(client, deck_id, 'future', 'card')
    monkeypatch.setattr(srs, 'today', lambda: date(2025, 1, 1))
    response = client.get(f'/api/decks/{deck_id}/due')
    assert response.status_code == 200
    assert response.json() == []
