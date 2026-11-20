"""E1-todo: held-out acceptance tests written from the requirement text alone."""

from _helpers import ids, unique


def make(client, **fields):
    response = client.post("/todos", json={"title": unique("task"), **fields})
    assert response.status_code == 201, response.text
    return response.json()


def test_create_returns_201_with_the_stated_fields(client):
    todo = make(client)
    assert isinstance(todo["id"], int)
    assert todo["done"] is False
    assert "created_at" in todo


def test_title_is_required_and_at_most_200_characters(client):
    assert client.post("/todos", json={}).status_code == 422
    assert client.post("/todos", json={"title": ""}).status_code == 422
    assert client.post("/todos", json={"title": "x" * 201}).status_code == 422
    assert client.post("/todos", json={"title": "x" * 200}).status_code == 201


def test_get_one_or_404(client):
    todo = make(client)
    assert client.get(f"/todos/{todo['id']}").json()["title"] == todo["title"]
    assert client.get("/todos/987654321").status_code == 404


def test_list_and_done_filter(client):
    open_todo = make(client)
    done_todo = make(client)
    assert client.patch(f"/todos/{done_todo['id']}", json={"done": True}).status_code == 200

    everything = ids(client.get("/todos").json())
    assert open_todo["id"] in everything and done_todo["id"] in everything
    only_done = ids(client.get("/todos", params={"done": "true"}).json())
    assert done_todo["id"] in only_done and open_todo["id"] not in only_done
    only_open = ids(client.get("/todos", params={"done": "false"}).json())
    assert open_todo["id"] in only_open and done_todo["id"] not in only_open


def test_patch_updates_title_and_or_done(client):
    todo = make(client)
    new_title = unique("renamed")
    assert client.patch(f"/todos/{todo['id']}", json={"title": new_title}).status_code == 200
    fetched = client.get(f"/todos/{todo['id']}").json()
    assert fetched["title"] == new_title and fetched["done"] is False


def test_delete_returns_204_then_404(client):
    todo = make(client)
    assert client.delete(f"/todos/{todo['id']}").status_code == 204
    assert client.get(f"/todos/{todo['id']}").status_code == 404
