"""M3-events: held-out acceptance tests written from the requirement text alone."""

from datetime import UTC, datetime, timedelta

from _helpers import CREATED, contains_text, ident, ids, unique, values_for


def event(client, capacity=1, days=30):
    starts = (datetime.now(UTC) + timedelta(days=days)).replace(microsecond=0).isoformat()
    response = client.post("/events", json={"name": unique("ev"), "starts_at": starts, "capacity": capacity})
    assert response.status_code in CREATED, response.text
    return response.json()


def book(client, event_id, email):
    return client.post(f"/events/{event_id}/bookings", json={"attendee_email": email})


def emails_under(body, *fragments):
    out = []
    for value in values_for(body, *fragments):
        out.extend(e for e in [value] if isinstance(e, str))
        if isinstance(value, list):
            for entry in value:
                out.append(entry if isinstance(entry, str) else str(entry))
    return " ".join(out)


def test_create_and_list_upcoming(client):
    ev = event(client)
    assert ident(ev) in ids(client.get("/events").json())


def test_full_event_waitlists_and_says_so(client):
    ev = event(client, capacity=1)
    first = book(client, ident(ev), f"{unique('a')}@example.com")
    assert first.status_code in CREATED
    second = book(client, ident(ev), f"{unique('b')}@example.com")
    assert second.status_code in CREATED
    assert contains_text(second.json(), "wait")


def test_one_booking_per_person_per_event(client):
    ev = event(client, capacity=5)
    email = f"{unique('dup')}@example.com"
    assert book(client, ident(ev), email).status_code in CREATED
    assert book(client, ident(ev), email).status_code == 409


def test_cancel_promotes_the_first_on_the_waitlist(client):
    ev = event(client, capacity=1)
    a, b, c = (f"{unique(x)}@example.com" for x in "abc")
    booking_a = book(client, ident(ev), a).json()
    book(client, ident(ev), b)
    book(client, ident(ev), c)

    before = client.get(f"/events/{ident(ev)}/attendees").json()
    assert a in emails_under(before, "confirm", "attendee", "booked")
    waitlist = emails_under(before, "wait")
    assert b in waitlist and c in waitlist and waitlist.index(b) < waitlist.index(c)

    assert client.delete(f"/bookings/{ident(booking_a)}").status_code in (200, 204)
    after = client.get(f"/events/{ident(ev)}/attendees").json()
    assert b in emails_under(after, "confirm", "attendee", "booked")
    assert b not in emails_under(after, "wait")
