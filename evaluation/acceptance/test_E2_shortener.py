"""E2-shortener: held-out acceptance tests written from the requirement text alone."""

import re

from _helpers import numbers_for, unique, walk


def shorten(client, url):
    response = client.post("/links", json={"url": url})
    assert response.status_code == 201, response.text
    body = response.json()
    codes = [v for k, v in walk(body) if k in ("code", "short_code", "shortcode", "slug")]
    assert codes, body
    return codes[0]


def test_returns_a_unique_six_character_alphanumeric_code(client):
    first = shorten(client, f"https://example.com/{unique()}")
    second = shorten(client, f"https://example.com/{unique()}")
    assert re.fullmatch(r"[A-Za-z0-9]{6}", first)
    assert first != second


def test_rejects_non_http_urls_with_422(client):
    for bad in ("ftp://example.com/file", "not a url", "javascript:alert(1)"):
        assert client.post("/links", json={"url": bad}).status_code == 422, bad


def test_redirects_with_307_to_the_original(client):
    url = f"https://example.com/{unique()}"
    code = shorten(client, url)
    response = client.get(f"/{code}", follow_redirects=False)
    assert response.status_code == 307
    assert response.headers["location"].rstrip("/") == url.rstrip("/")


def test_unknown_code_is_404(client):
    assert client.get("/zz9zz9", follow_redirects=False).status_code == 404


def test_stats_report_url_clicks_and_creation_time(client):
    url = f"https://example.com/{unique()}"
    code = shorten(client, url)
    client.get(f"/{code}", follow_redirects=False)
    client.get(f"/{code}", follow_redirects=False)
    stats = client.get(f"/links/{code}/stats")
    assert stats.status_code == 200
    body = stats.json()
    assert url.rstrip("/") in str(body)
    assert 2.0 in numbers_for(body, "click")
    assert any("creat" in k.lower() for k, _ in walk(body) if isinstance(k, str))
