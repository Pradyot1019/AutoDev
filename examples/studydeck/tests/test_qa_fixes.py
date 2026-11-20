"""Regression tests for the three issues QA reported on the first build."""
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import delete, select, text

import app.srs as srs
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


def make_deck(client, **fields):
    response = client.post('/api/decks', json={'name': 'Deck', **fields})
    assert response.status_code == 201
    return response.json()


def make_card(client, deck_id):
    response = client.post(f'/api/decks/{deck_id}/cards', json={'front': 'F', 'back': 'B'})
    assert response.status_code == 201
    return response.json()


# 1. SQLite enforces the declared foreign keys.

def test_sqlite_foreign_keys_are_on():
    with engine.connect() as conn:
        assert conn.execute(text('PRAGMA foreign_keys')).scalar() == 1


def test_the_database_cascades_a_deck_delete(client):
    deck = make_deck(client)
    card = make_card(client, deck['id'])
    client.post(f"/api/cards/{card['id']}/review", json={'grade': 'good'})

    # Bypass the endpoint: the database itself must remove the children.
    with SessionLocal() as db:
        db.execute(text('DELETE FROM decks WHERE id = :id').bindparams(id=deck['id']))
        db.commit()
        assert db.scalars(select(Card)).all() == []
        assert db.scalars(select(Review)).all() == []


# 2. Review timestamps follow srs.today(), so stats agree with the schedule.

def test_a_review_is_stamped_with_the_scheduling_date(client, monkeypatch):
    monkeypatch.setattr(srs, 'today', lambda: date(2030, 1, 10))
    deck = make_deck(client)
    card = make_card(client, deck['id'])

    client.post(f"/api/cards/{card['id']}/review", json={'grade': 'good'})

    with SessionLocal() as db:
        review = db.scalars(select(Review)).one()
    assert review.reviewed_at.date() == date(2030, 1, 10)
    stats = client.get('/api/stats').json()
    assert stats['total_reviewed_today'] == 1
    assert stats['streak'] == 1


def test_the_streak_counts_consecutive_review_days_through_the_endpoint(client, monkeypatch):
    deck = make_deck(client)
    card = make_card(client, deck['id'])
    for day in (8, 9, 10):
        monkeypatch.setattr(srs, 'today', lambda day=day: date(2030, 1, day))
        assert client.post(f"/api/cards/{card['id']}/review", json={'grade': 'again'}).status_code == 200

    assert client.get('/api/stats').json()['streak'] == 3


# 3. A deck's description can be edited and cleared.

def test_patching_only_the_description_keeps_the_name(client):
    deck = make_deck(client, name='Spanish', description='Old')

    response = client.patch(f"/api/decks/{deck['id']}", json={'description': 'Verbs and nouns'})

    assert response.status_code == 200
    assert response.json()['name'] == 'Spanish'
    assert response.json()['description'] == 'Verbs and nouns'


def test_a_null_description_clears_it(client):
    deck = make_deck(client, description='Old')

    response = client.patch(f"/api/decks/{deck['id']}", json={'description': None})

    assert response.json()['description'] is None


def test_the_deck_list_offers_an_edit_description_control():
    import app

    script = (Path(app.__file__).parent / 'static' / 'app.js').read_text(encoding='utf-8')
    assert "data-action='describe'" in script
    assert "body: { description: description || null }" in script
