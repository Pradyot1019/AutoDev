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


def make_deck(client, name='Deck', description=None):
    payload = {'name': name}
    if description is not None:
        payload['description'] = description
    response = client.post('/api/decks', json=payload)
    assert response.status_code == 201
    return response.json()


def test_list_decks_empty(client):
    response = client.get('/api/decks')
    assert response.status_code == 200
    assert response.json() == []


def test_create_deck(client):
    response = client.post('/api/decks', json={'name': 'Spanish', 'description': 'Words'})
    assert response.status_code == 201
    body = response.json()
    assert body['name'] == 'Spanish'
    assert body['description'] == 'Words'
    assert body['card_count'] == 0
    assert body['due_count'] == 0


def test_create_deck_rejects_empty_name(client):
    response = client.post('/api/decks', json={'name': ''})
    assert response.status_code == 422


def test_create_deck_rejects_long_name(client):
    response = client.post('/api/decks', json={'name': 'x' * 81})
    assert response.status_code == 422


def test_create_deck_rejects_long_description(client):
    response = client.post('/api/decks', json={'name': 'Deck', 'description': 'x' * 301})
    assert response.status_code == 422


def test_patch_deck_name(client):
    deck = make_deck(client, name='Old')
    deck_id = deck['id']
    response = client.patch(f'/api/decks/{deck_id}', json={'name': 'New'})
    assert response.status_code == 200
    body = response.json()
    assert body['name'] == 'New'
    assert body['description'] is None


def test_patch_deck_description(client):
    deck = make_deck(client, name='Deck', description='Old')
    deck_id = deck['id']
    response = client.patch(f'/api/decks/{deck_id}', json={'description': 'New'})
    assert response.status_code == 200
    assert response.json()['description'] == 'New'


def test_patch_deck_rejects_empty_name(client):
    deck = make_deck(client)
    deck_id = deck['id']
    response = client.patch(f'/api/decks/{deck_id}', json={'name': ''})
    assert response.status_code == 422


def test_patch_unknown_deck_returns_404(client):
    response = client.patch('/api/decks/9999', json={'name': 'Nope'})
    assert response.status_code == 404


def test_delete_deck_removes_cards_and_reviews(client):
    deck = make_deck(client)
    deck_id = deck['id']
    card = client.post(f'/api/decks/{deck_id}/cards', json={'front': 'F', 'back': 'B'}).json()
    card_id = card['id']
    with SessionLocal() as db:
        db.add(Review(card_id=card_id, grade='good', reviewed_at=datetime.now()))
        db.commit()
    response = client.delete(f'/api/decks/{deck_id}')
    assert response.status_code == 204
    with SessionLocal() as db:
        assert db.get(Deck, deck_id) is None
        assert db.get(Card, card_id) is None
        assert db.scalar(select(Review).where(Review.card_id == card_id)) is None


def test_delete_unknown_deck_returns_404(client):
    response = client.delete('/api/decks/9999')
    assert response.status_code == 404


def test_list_decks_includes_card_and_due_counts(client, monkeypatch):
    import app.srs as srs
    from datetime import date
    monkeypatch.setattr(srs, 'today', lambda: date(2025, 1, 1))
    deck = make_deck(client)
    deck_id = deck['id']
    client.post(f'/api/decks/{deck_id}/cards', json={'front': 'F1', 'back': 'B1'})
    client.post(f'/api/decks/{deck_id}/cards', json={'front': 'F2', 'back': 'B2'})
    body = client.get('/api/decks').json()[0]
    assert body['card_count'] == 2
    assert body['due_count'] == 2
