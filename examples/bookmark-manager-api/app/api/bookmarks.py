from fastapi import APIRouter, Depends, status, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from app.database import get_db
from app.schemas.bookmark import BookmarkCreate, BookmarkResponse
from app.services import bookmark_service

router = APIRouter(prefix="/bookmarks", tags=["bookmarks"])

@router.post("", response_model=BookmarkResponse, status_code=status.HTTP_201_CREATED)
def create_bookmark(bookmark: BookmarkCreate, db: Session = Depends(get_db)):
    return bookmark_service.create_bookmark(db, bookmark)

@router.get("", response_model=List[BookmarkResponse])
def list_bookmarks(tag: Optional[str] = Query(None), db: Session = Depends(get_db)):
    return bookmark_service.get_bookmarks(db, tag)

@router.get("/{id}", response_model=BookmarkResponse)
def get_bookmark(id: int, db: Session = Depends(get_db)):
    return bookmark_service.get_bookmark(db, id)

@router.delete("/{id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_bookmark(id: int, db: Session = Depends(get_db)):
    bookmark_service.delete_bookmark(db, id)
    return None