"""E3-notes: held-out acceptance tests written from the requirement text alone."""

from _helpers import ids, items, unique


def make(client, tags):
    response = client.post("/notes", json={"title": unique("t"), "body": "text", "tags": tags})
    assert response.status_code == 201, response.text
    return response.json()


def tag_counts(body):
    """Accepts {"tag": n}, [{"tag": .., "count": ..}] or [{"name": .., "count": ..}]."""
    if isinstance(body, dict) and body and all(isinstance(v, int) for v in body.values()):
        return dict(body)
    out = {}
    for entry in items(body):
        if isinstance(entry, dict):
            name = entry.get("tag", entry.get("name"))
            count = next((v for k, v in entry.items() if "count" in k.lower() or k == "notes"), None)
            if name is not None and isinstance(count, int):
                out[name] = count
    return out


def test_create_and_get_or_404(client):
    note = make(client, ["alpha"])
    fetched = client.get(f"/notes/{note['id']}")
    assert fetched.status_code == 200 and fetched.json()["title"] == note["title"]
    assert client.get("/notes/987654321").status_code == 404


def test_tag_filter_returns_only_notes_with_that_tag(client):
    tag = unique("tag")
    tagged = make(client, [tag])
    other = make(client, [unique("tag")])
    found = ids(client.get("/notes", params={"tag": tag}).json())
    assert tagged["id"] in found and other["id"] not in found


def test_put_replaces_the_whole_note(client):
    note = make(client, [unique("old")])
    new_tag = unique("new")
    replaced = {"title": unique("replaced"), "body": "new body", "tags": [new_tag]}
    assert client.put(f"/notes/{note['id']}", json=replaced).status_code == 200
    fetched = client.get(f"/notes/{note['id']}").json()
    assert fetched["title"] == replaced["title"] and fetched["body"] == "new body"
    assert fetched["tags"] == [new_tag]


def test_delete_returns_204_then_404(client):
    note = make(client, [])
    assert client.delete(f"/notes/{note['id']}").status_code == 204
    assert client.get(f"/notes/{note['id']}").status_code == 404


def test_tags_lists_each_distinct_tag_with_its_count(client):
    shared, single = unique("shared"), unique("single")
    make(client, [shared, single])
    make(client, [shared])
    counts = tag_counts(client.get("/tags").json())
    assert counts.get(shared) == 2 and counts.get(single) == 1
