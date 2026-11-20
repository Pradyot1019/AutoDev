import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.main import app
from app.database import Base, get_db

SQLALCHEMY_DATABASE_URL = "sqlite:///./test.db"
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def override_get_db():
    try:
        db = TestingSessionLocal()
        yield db
    finally:
        db.close()

app.dependency_overrides[get_db] = override_get_db
client = TestClient(app)

@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    yield
    # Empty the tables but leave the schema: other test modules share this database.
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

def test_create_bookmark():
    response = client.post("/bookmarks", json={"url": "https://google.com", "title": "Google", "tags": ["search"]})
    assert response.status_code == 201
    assert response.json()["url"] == "https://google.com/"

def test_create_duplicate_url():
    client.post("/bookmarks", json={"url": "https://google.com", "title": "Google"})
    response = client.post("/bookmarks", json={"url": "https://google.com", "title": "Google Duplicate"})
    assert response.status_code == 409

def test_invalid_url_scheme():
    response = client.post("/bookmarks", json={"url": "ftp://files.com", "title": "FTP"})
    assert response.status_code == 422

def test_get_bookmarks_filter():
    client.post("/bookmarks", json={"url": "https://a.com", "title": "A", "tags": ["work"]})
    client.post("/bookmarks", json={"url": "https://b.com", "title": "B", "tags": ["personal"]})
    response = client.get("/bookmarks?tag=work")
    assert len(response.json()) == 1
    assert response.json()[0]["title"] == "A"