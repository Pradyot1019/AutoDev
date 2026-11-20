from datetime import datetime
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


def make_card(client, deck_id, front='Front', back='Back'):
    response = client.post(f'/api/decks/{deck_id}/cards', json={'front': front, 'back': back})
    assert response.status_code == 201
    return response.json()


def test_list_cards_for_deck(client):
    deck = make_deck(client)
    deck_id = deck['id']
    card = make_card(client, deck_id)
    response = client.get(f'/api/decks/{deck_id}/cards')
    assert response.status_code == 200
    assert [c['id'] for c in response.json()] == [card['id']]


def test_list_cards_unknown_deck_returns_404(client):
    response = client.get('/api/decks/9999/cards')
    assert response.status_code == 404


def test_create_card_initial_schedule(client, monkeypatch):
    import app.srs as srs
    from datetime import date
    monkeypatch.setattr(srs, 'today', lambda: date(2025, 1, 1))
    deck = make_deck(client)
    deck_id = deck['id']
    response = client.post(f'/api/decks/{deck_id}/cards', json={'front': 'Front', 'back': 'Back'})
    assert response.status_code == 201
    body = response.json()
    assert body['ease'] == 2.5
    assert body['interval_days'] == 0
    assert body['repetitions'] == 0
    assert body['due_date'] == '2025-01-01'


def test_create_card_rejects_empty_front(client):
    deck = make_deck(client)
    deck_id = deck['id']
    response = client.post(f'/api/decks/{deck_id}/cards', json={'front': '', 'back': 'B'})
    assert response.status_code == 422


def test_create_card_rejects_long_back(client):
    deck = make_deck(client)
    deck_id = deck['id']
    response = client.post(f'/api/decks/{deck_id}/cards', json={'front': 'F', 'back': 'x' * 501})
    assert response.status_code == 422


def test_create_card_unknown_deck_returns_404(client):
    response = client.post('/api/decks/9999/cards', json={'front': 'F', 'back': 'B'})
    assert response.status_code == 404


def test_patch_card_front_and_back(client):
    deck = make_deck(client)
    deck_id = deck['id']
    card = make_card(client, deck_id)
    card_id = card['id']
    response = client.patch(f'/api/cards/{card_id}', json={'front': 'New F', 'back': 'New B'})
    assert response.status_code == 200
    body = response.json()
    assert body['front'] == 'New F'
    assert body['back'] == 'New B'


def test_patch_card_preserves_schedule(client):
    deck = make_deck(client)
    deck_id = deck['id']
    card = make_card(client, deck_id)
    card_id = card['id']
    response = client.patch(f'/api/cards/{card_id}', json={'front': 'New F'})
    assert response.status_code == 200
    body = response.json()
    assert body['ease'] == card['ease']
    assert body['interval_days'] == card['interval_days']
    assert body['repetitions'] == card['repetitions']
    assert body['due_date'] == card['due_date']


def test_patch_card_rejects_empty_front(client):
    deck = make_deck(client)
    deck_id = deck['id']
    card = make_card(client, deck_id)
    card_id = card['id']
    response = client.patch(f'/api/cards/{card_id}', json={'front': ''})
    assert response.status_code == 422


def test_patch_unknown_card_returns_404(client):
    response = client.patch('/api/cards/9999', json={'front': 'F'})
    assert response.status_code == 404


def test_delete_card_removes_reviews(client):
    deck = make_deck(client)
    deck_id = deck['id']
    card = make_card(client, deck_id)
    card_id = card['id']
    with SessionLocal() as db:
        db.add(Review(card_id=card_id, grade='good', reviewed_at=datetime.now()))
        db.commit()
    response = client.delete(f'/api/cards/{card_id}')
    assert response.status_code == 204
    with SessionLocal() as db:
        assert db.get(Card, card_id) is None
        assert db.scalar(select(Review).where(Review.card_id == card_id)) is None


def test_delete_unknown_card_returns_404(client):
    response = client.delete('/api/cards/9999')
    assert response.status_code == 404
