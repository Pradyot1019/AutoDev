'''Database configuration for StudyDeck.'''
from __future__ import annotations

import os
from collections.abc import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

DATABASE_URL = os.getenv('DATABASE_URL', 'sqlite:///./studydeck.db')

connect_args: dict[str, object] = {}
if DATABASE_URL.startswith('sqlite'):
    connect_args = {'check_same_thread': False}

engine = create_engine(DATABASE_URL, connect_args=connect_args, future=True)

if DATABASE_URL.startswith('sqlite'):

    @event.listens_for(engine, 'connect')
    def _enable_sqlite_foreign_keys(dbapi_connection, _record) -> None:
        '''SQLite ignores ForeignKey(ondelete='CASCADE') unless this is on for each connection.'''
        cursor = dbapi_connection.cursor()
        cursor.execute('PRAGMA foreign_keys=ON')
        cursor.close()
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False, future=True)


class Base(DeclarativeBase):
    '''Declarative base class for all StudyDeck models.'''


def get_db() -> Generator[Session, None, None]:
    '''Yield a synchronous SQLAlchemy session and close it afterwards.'''
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
