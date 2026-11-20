"""Shape-tolerant helpers for the held-out acceptance tests.

The tests check only what a requirement states -- paths, status codes, rules,
named fields -- and stay neutral about everything it leaves open, such as
whether a list comes back bare or wrapped, or what a count field is called.
"""

from __future__ import annotations

import contextlib
import uuid
from typing import Any

CREATED = (200, 201)  # where a requirement does not name 201 explicitly


def unique(prefix: str = "x") -> str:
    return f"{prefix}{uuid.uuid4().hex[:10]}"


def items(body: Any) -> list[Any]:
    """A list response, bare or wrapped in a common envelope key."""
    if isinstance(body, list):
        return body
    if isinstance(body, dict):
        for key in ("items", "data", "results", "todos", "notes", "links", "books", "members",
                    "loans", "events", "products", "movements", "expenses", "tags"):
            if isinstance(body.get(key), list):
                return body[key]
    return []


def ident(obj: Any) -> Any:
    if isinstance(obj, dict):
        for key in ("id", "_id"):
            if key in obj:
                return obj[key]
        for value in obj.values():  # e.g. {"booking": {...}} or {"todo": {...}}
            if isinstance(value, dict) and "id" in value:
                return value["id"]
    return None


def ids(body: Any) -> list[Any]:
    return [ident(entry) for entry in items(body)]


def walk(value: Any):
    """Every (key, value) pair at any depth."""
    if isinstance(value, dict):
        for key, inner in value.items():
            yield key, inner
            yield from walk(inner)
    elif isinstance(value, list):
        for inner in value:
            yield from walk(inner)


def values_for(body: Any, *fragments: str) -> list[Any]:
    """Values whose key contains any of the fragments (case-insensitive)."""
    wanted = [f.lower() for f in fragments]
    return [v for k, v in walk(body) if isinstance(k, str) and any(f in k.lower() for f in wanted)]


def numbers_for(body: Any, *fragments: str) -> list[float]:
    out = []
    for value in values_for(body, *fragments):
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            out.append(float(value))
        elif isinstance(value, str):
            with contextlib.suppress(ValueError):
                out.append(float(value))
    return out


def contains_text(body: Any, text: str) -> bool:
    return text.lower() in str(body).lower()
