"""M4-inventory: held-out acceptance tests written from the requirement text alone."""

from _helpers import CREATED, ident, ids, items, unique


def product(client, reorder=5):
    body = {"sku": unique("SKU"), "name": "Widget", "reorder_level": reorder}
    response = client.post("/products", json=body)
    assert response.status_code in CREATED, response.text
    return response.json()


def move(client, pid, kind, qty):
    return client.post(f"/products/{pid}/movements", json={"type": kind, "quantity": qty, "reason": "test"})


def quantity(client, pid):
    return client.get(f"/products/{pid}").json()["quantity"]


def test_create_list_get(client):
    p = product(client)
    assert ident(p) in ids(client.get("/products").json())
    assert client.get(f"/products/{ident(p)}").status_code == 200
    assert quantity(client, ident(p)) == 0


def test_sku_is_unique(client):
    p = product(client)
    again = client.post("/products", json={"sku": p["sku"], "name": "Other", "reorder_level": 1})
    assert 400 <= again.status_code < 500


def test_movements_change_stock_and_never_below_zero(client):
    pid = ident(product(client))
    assert move(client, pid, "in", 10).status_code in CREATED
    assert quantity(client, pid) == 10
    assert move(client, pid, "out", 15).status_code == 409
    assert quantity(client, pid) == 10
    assert move(client, pid, "out", 4).status_code in CREATED
    assert quantity(client, pid) == 6


def test_history_is_newest_first(client):
    pid = ident(product(client))
    move(client, pid, "in", 10)
    move(client, pid, "out", 3)
    history = items(client.get(f"/products/{pid}/movements").json())
    assert len(history) == 2
    assert history[0]["type"] == "out" and history[0]["quantity"] == 3


def test_low_stock_is_at_or_below_reorder_level(client):
    low = ident(product(client, reorder=5))
    move(client, low, "in", 5)              # exactly at the level
    healthy = ident(product(client, reorder=5))
    move(client, healthy, "in", 50)
    found = ids(client.get("/products/low-stock").json())
    assert low in found and healthy not in found


def test_quantity_cannot_be_set_directly(client):
    p = product(client)
    pid = ident(p)
    move(client, pid, "in", 7)
    response = client.patch(f"/products/{pid}", json={"quantity": 999})
    if response.status_code == 405:
        response = client.put(f"/products/{pid}", json={"sku": p["sku"], "name": "Widget",
                                                        "reorder_level": 5, "quantity": 999})
    assert response.status_code >= 400 or quantity(client, pid) == 7
