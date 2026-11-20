from fastapi import FastAPI
from app.database import engine, Base
from app.api.bookmarks import router as bookmark_router

Base.metadata.create_all(bind=engine)

app = FastAPI(title="Bookmark Manager API")

app.include_router(bookmark_router)