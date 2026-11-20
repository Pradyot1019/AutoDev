# Bookmark Manager API

A lightweight REST API for managing web bookmarks.

## Setup
1. Install Python 3.9+
2. `pip install -r requirements.txt`
3. `uvicorn app.main:app --reload`

## API Reference
- POST /bookmarks: Create bookmark (URL, title, tags)
- GET /bookmarks: List all (optional ?tag= filter)
- GET /bookmarks/{id}: Get specific bookmark
- DELETE /bookmarks/{id}: Remove bookmark