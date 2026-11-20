"""M2-library: held-out acceptance tests written from the requirement text alone."""

from datetime import datetime

from _helpers import CREATED, ident, ids, numbers_for, unique


def book(client, copies=1):
    body = {"title": unique("b"), "author": "A. Author", "isbn": unique("978"), "copies_total": copies}
    response = client.post("/books", json=body)
    assert response.status_code in CREATED, response.text
    return response.json()


def member(client):
    response = client.post("/members", json={"name": "Reader", "email": f"{unique('m')}@example.com"})
    assert response.status_code in CREATED, response.text
    return response.json()


def lend(client, book_id, member_id):
    return client.post("/loans", json={"book_id": book_id, "member_id": member_id})


def available(client, book_id):
    body = client.get(f"/books/{book_id}/availability").json()
    found = numbers_for(body, "avail", "free")
    assert found, body
    return found[0]


def test_create_list_get_books_and_members(client):
    b, m = book(client), member(client)
    assert ident(b) in ids(client.get("/books").json())
    assert ident(m) in ids(client.get("/members").json())
    assert client.get(f"/books/{ident(b)}").status_code == 200
    assert client.get(f"/members/{ident(m)}").status_code == 200
    assert client.get("/books/987654321").status_code == 404


def test_a_loan_is_for_14_days(client):
    response = lend(client, ident(book(client)), ident(member(client)))
    assert response.status_code in CREATED, response.text
    loan = response.json()
    start = datetime.fromisoformat(str(loan["loaned_at"]).replace("Z", "+00:00"))
    due = datetime.fromisoformat(str(loan["due_at"]).replace("Z", "+00:00"))
    assert (due - start).days == 14


def test_no_free_copy_is_409_and_availability_tracks_loans(client):
    b = book(client, copies=1)
    assert available(client, ident(b)) == 1
    loan = lend(client, ident(b), ident(member(client)))
    assert loan.status_code in CREATED
    assert available(client, ident(b)) == 0
    assert lend(client, ident(b), ident(member(client))).status_code == 409
    assert client.post(f"/loans/{ident(loan.json())}/return").status_code in (200, 204)
    assert available(client, ident(b)) == 1


def test_a_member_may_hold_at_most_three_active_loans(client):
    m = member(client)
    for _ in range(3):
        assert lend(client, ident(book(client)), ident(m)).status_code in CREATED
    assert lend(client, ident(book(client)), ident(m)).status_code == 409


def test_overdue_lists_loans(client):
    response = client.get("/loans/overdue")
    assert response.status_code == 200
    assert isinstance(response.json(), (list, dict))
