'''FastAPI entry point for StudyDeck.'''
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

import app.models  # noqa: F401
from app.database import Base, engine
from app.routes import router as api_router

logging.basicConfig(level=logging.INFO)

app = FastAPI(title='StudyDeck', version='1.0.0')

app.add_middleware(
    CORSMiddleware,
    allow_origins=['*'],
    allow_credentials=False,
    allow_methods=['*'],
    allow_headers=['*'],
)

Base.metadata.create_all(engine)

app.include_router(api_router)

STATIC_DIR = Path(__file__).parent / 'static'
app.mount('/static', StaticFiles(directory=str(STATIC_DIR)), name='static')


@app.get('/', include_in_schema=False)
def read_index() -> FileResponse:
    '''Serve the single-page application entry point.'''
    return FileResponse(STATIC_DIR / 'index.html')
