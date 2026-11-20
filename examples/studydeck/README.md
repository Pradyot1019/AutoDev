# StudyDeck

StudyDeck is a single-service flashcard study website with simplified SM-2 spaced repetition. It lets a local user create decks, add cards, study due cards one at a time, grade each card as again, hard, good or easy, and see per-deck progress together with an overall study streak. The FastAPI app serves both the JSON API under /api and the plain HTML/CSS/JavaScript single-page interface from app/static. There is no authentication, no user account system and no external build step.

## Architecture summary

- One FastAPI service named studydeck.
- Synchronous SQLAlchemy 2.0 with SQLite.
- Pydantic 2 request and response schemas.
- Pure simplified SM-2 logic in app/srs.py.
- Plain HTML, CSS and vanilla JavaScript SPA with hash routing in app/static.
- SQLite database file defaults to sqlite:///./studydeck.db.

## Services

### studydeck

The service contains the API, database models, scheduling logic and static frontend assets. It is the only service in the project.

## Prerequisites

- Python 3.10 or newer.
- pip.
- A modern web browser.
- No Docker, PostgreSQL, Redis, npm or CDN access is required.

## Setup and run

1. Change into the project directory.
2. Create a virtual environment with `python -m venv .venv`.
3. Activate it with `source .venv/bin/activate` on macOS/Linux or `.venv\Scripts\activate` on Windows.
4. Install dependencies with `pip install -r requirements.txt`.
5. Optionally copy `.env.example` to `.env` and change `DATABASE_URL`.
6. Run the app with `uvicorn app.main:app --reload`.
7. Open http://127.0.0.1:8000/ in a browser.

The app calls `Base.metadata.create_all(engine)` at startup, so the SQLite schema is created automatically.

## Environment variables

| Name | Required | Default | Description |
| --- | --- | --- | --- |
| DATABASE_URL | No | sqlite:///./studydeck.db | SQLAlchemy database URL. The default is a local SQLite file. |

## Development

Run the server with auto-reload:

```bash
uvicorn app.main:app --reload
```

Run the test suite when tests are present:

```bash
pytest
```

The static frontend is served directly by FastAPI. Edit files under app/static and refresh the browser. API calls from the frontend use relative /api/... paths only.

## API reference

All endpoints are unauthenticated. All API paths are under /api except the root HTML page and static assets.

| Method | Path | Auth required | Request body | Response |
| --- | --- | --- | --- | --- |
| GET | /api/decks | No | None | JSON array of decks, each with id, name, description, card_count and due_count |
| POST | /api/decks | No | name required 1-80 chars, description optional up to 300 chars | 201 with created deck including card_count and due_count |
| PATCH | /api/decks/{id} | No | Optional name 1-80 chars and/or description up to 300 chars | 200 with updated deck |
| DELETE | /api/decks/{id} | No | None | 204 No Content. Deletes child reviews, cards and the deck. |
| GET | /api/decks/{id}/cards | No | None | JSON array of cards in the deck |
| POST | /api/decks/{id}/cards | No | front required 1-500 chars, back required 1-500 chars | 201 with created card. New cards start at ease 2.5, interval 0, repetitions 0 and due today. |
| PATCH | /api/cards/{id} | No | Optional front and/or back text, each 1-500 chars | 200 with updated card |
| DELETE | /api/cards/{id} | No | None | 204 No Content. Deletes child review rows first. |
| GET | /api/decks/{id}/due | No | None | JSON array of cards due today or overdue, ordered by due_date then id |
| POST | /api/cards/{id}/review | No | grade must be again, hard, good or easy | 200 with the updated card. Unknown grade returns 422. |
| GET | /api/stats | No | None | Per-deck card_count, due_count and reviewed_today, plus overall streak and total reviewed today |
| GET | / | No | None | 200 HTML index page |
| GET | /static/{path} | No | None | Static frontend asset such as /static/style.css or /static/app.js |

## Scheduling rules

The pure scheduling function in app/srs.py applies these simplified SM-2 rules:

- again: repetitions reset to 0, interval_days becomes 1, ease becomes max(1.3, ease - 0.2), due date is review date plus 1 day.
- hard: interval_days becomes max(1, round(old_interval * 1.2)), ease becomes max(1.3, ease - 0.15), repetitions increase by 1.
- good: first review interval is 1 day, second review interval is 3 days, later reviews use round(old_interval * old_ease). Repetitions increase by 1.
- easy: behaves like good, then multiplies the interval by 1.3, rounds it, enforces a minimum of 2 days, and adds 0.15 to ease. Repetitions increase by 1.
- The due date is always review date plus the new interval in days.

Every successful review is also saved as a Review row containing card_id, grade and reviewed_at for statistics.

## Frontend routes

- #/ shows the deck list, create form, rename and delete controls, and the stats bar.
- #/deck/{id} shows the deck cards with add, edit, delete and Study now controls.
- #/study/{id} runs the study flow: one due card at a time, Show answer, four grade buttons, and Done for today when finished.

Keyboard shortcuts in study mode:

- Space shows the answer.
- 1 grades again.
- 2 grades hard.
- 3 grades good.
- 4 grades easy.

## Troubleshooting

- The app cannot find the database: confirm DATABASE_URL is valid or unset so it defaults to sqlite:///./studydeck.db.
- Port 8000 is already in use: run uvicorn with --port 8001 and open the matching URL.
- Static files do not load: confirm app/static/index.html, style.css and app.js exist and run the app from the project root.
- A deck or card returns 404: the resource may have been deleted or the id is wrong.
- A request returns 422: check deck name length 1-80, description up to 300, card front and back 1-500, and review grade is one of again, hard, good or easy.
- Tests monkeypatch dates: use app.srs.today as the single date helper so scheduling and streak logic stay testable.
