from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from fastapi import HTTPException, status
from app.models.bookmark import Bookmark
from app.schemas.bookmark import BookmarkCreate
import json

def get_bookmarks(db: Session, tag: str = None):
    query = db.query(Bookmark)
    if tag:
        query = query.filter(Bookmark.tags.contains(tag))
    return query.all()

def get_bookmark(db: Session, bookmark_id: int):
    db_bookmark = db.query(Bookmark).filter(Bookmark.id == bookmark_id).first()
    if not db_bookmark:
        raise HTTPException(status_code=404, detail="Bookmark not found")
    return db_bookmark

def create_bookmark(db: Session, bookmark: BookmarkCreate):
    db_bookmark = Bookmark(
        url=str(bookmark.url),
        title=bookmark.title,
        tags=json.dumps(bookmark.tags) if bookmark.tags else "[]"
    )
    try:
        db.add(db_bookmark)
        db.commit()
        db.refresh(db_bookmark)
        return db_bookmark
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="URL already exists")

def delete_bookmark(db: Session, bookmark_id: int):
    db_bookmark = get_bookmark(db, bookmark_id)
    db.delete(db_bookmark)
    db.commit()
    return True