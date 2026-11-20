"""M1-expenses: held-out acceptance tests written from the requirement text alone."""

import pytest
from _helpers import CREATED, ids, numbers_for, unique, walk


def register(client):
    creds = {"email": f"{unique('u')}@example.com", "password": "S3cure-pass!"}
    assert client.post("/auth/register", json=creds).status_code in CREATED
    return creds


def login(client, creds):
    """JSON body, or the OAuth2 password form -- the requirement names neither."""
    response = client.post("/auth/login", json=creds)
    if response.status_code == 422:
        response = client.post("/auth/login", data={"username": creds["email"], "password": creds["password"]})
    assert response.status_code == 200, response.text
    tokens = [v for _, v in walk(response.json()) if isinstance(v, str) and v.count(".") == 2]
    assert tokens, response.json()
    return {"Authorization": f"Bearer {tokens[0]}"}


@pytest.fixture
def user(client):
    return login(client, register(client))


def expense(client, headers, **fields):
    body = {"amount": 12.5, "category": "food", "description": "lunch", "date": "2026-01-15", **fields}
    response = client.post("/expenses", json=body, headers=headers)
    assert response.status_code in CREATED, response.text
    return response.json()


def test_duplicate_email_is_409(client):
    creds = register(client)
    assert client.post("/auth/register", json=creds).status_code == 409


def test_login_returns_a_jwt(client):
    assert login(client, register(client))["Authorization"].startswith("Bearer ")


def test_expenses_require_the_token(client):
    assert client.get("/expenses").status_code in (401, 403)
    assert client.post("/expenses", json={"amount": 1, "category": "food"}).status_code in (401, 403)


def test_crud_on_own_expenses(client, user):
    created = expense(client, user)
    assert client.get(f"/expenses/{created['id']}", headers=user).status_code == 200
    assert created["id"] in ids(client.get("/expenses", headers=user).json())
    updated = client.put(f"/expenses/{created['id']}", headers=user, json={
        "amount": 20, "category": "transport", "description": "bus", "date": "2026-01-16"})
    if updated.status_code != 200:  # "CRUD" names no method: a partial PATCH counts too
        updated = client.patch(f"/expenses/{created['id']}", headers=user, json={"amount": 20})
    assert updated.status_code == 200
    assert client.delete(f"/expenses/{created['id']}", headers=user).status_code in (200, 204)
    assert client.get(f"/expenses/{created['id']}", headers=user).status_code == 404


def test_amount_must_be_positive_and_category_from_the_list(client, user):
    base = {"description": "x", "date": "2026-01-15"}
    assert client.post("/expenses", headers=user, json={**base, "amount": -5, "category": "food"}).status_code == 422
    assert client.post("/expenses", headers=user, json={**base, "amount": 5, "category": "gadgets"}).status_code == 422


def test_users_only_see_their_own_expenses(client, user):
    other = login(client, register(client))
    mine = expense(client, user)
    assert mine["id"] not in ids(client.get("/expenses", headers=other).json())
    assert client.get(f"/expenses/{mine['id']}", headers=other).status_code in (403, 404)


def test_monthly_report_totals(client, user):
    expense(client, user, amount=10, category="food", date="2025-03-02")
    expense(client, user, amount=5.5, category="food", date="2025-03-20")
    expense(client, user, amount=4, category="transport", date="2025-03-21")
    expense(client, user, amount=100, category="food", date="2025-04-01")  # other month
    report = client.get("/reports/monthly", params={"year": 2025, "month": 3}, headers=user)
    assert report.status_code == 200
    body = report.json()
    assert 19.5 in numbers_for(body, "total")
    assert 15.5 in numbers_for(body, "food", "total", "amount")
