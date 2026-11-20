from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_delete_bookmark_success_and_not_found():
    create_res = client.post("/bookmarks", json={"url": "https://example.com/del-test", "title": "Delete Test"})
    assert create_res.status_code == 201
    bm_id = create_res.json()["id"]

    del_res = client.delete(f"/bookmarks/{bm_id}")
    assert del_res.status_code == 204

    del_again_res = client.delete(f"/bookmarks/{bm_id}")
    assert del_again_res.status_code == 404
