"""Undo a model escaping a file's line breaks twice.

A model writing a file inside a JSON string has to escape its newlines once. In a
live Groq run it escaped them twice, and ``requirements.txt`` arrived as one line,
``fastapi==0.110.0\\nuvicorn[standard]==0.27.0\\n...``, with backslash-n as literal
characters. pip read that as a single invalid requirement, so no test could run on
any attempt, and the developer could not see why from "dependency install failed".

The repair is deliberately narrow. It only touches content with *no* real line
break, and only when the result is clearly better: Python and JSON must go from
invalid to valid, anything else needs at least two escaped breaks. A one-line file
whose ``\\n`` is meant literally (``print("a\\nb")``) is left alone.
"""

from __future__ import annotations

import ast
import json
from pathlib import PurePosixPath

from core.logging import get_logger

logger = get_logger(__name__)

MIN_ESCAPED_BREAKS = 2


def _python_ok(text: str) -> bool:
    try:
        ast.parse(text)
    except (SyntaxError, ValueError):
        return False
    return True


def _json_ok(text: str) -> bool:
    try:
        json.loads(text)
    except ValueError:
        return False
    return True


def _unescape(content: str) -> str:
    return content.replace("\\r\\n", "\n").replace("\\n", "\n").replace("\\t", "\t")


def repair_escaped_newlines(file_path: str, content: str) -> str:
    """Return ``content`` with doubly escaped line breaks restored, when safe."""
    if "\n" in content or "\\n" not in content:
        return content

    candidate = _unescape(content)
    suffix = PurePosixPath(file_path.replace("\\", "/")).suffix.lower()

    if suffix == ".py":
        repaired = not _python_ok(content) and _python_ok(candidate)
    elif suffix == ".json":
        repaired = not _json_ok(content) and _json_ok(candidate)
    else:
        repaired = content.count("\\n") >= MIN_ESCAPED_BREAKS

    if not repaired:
        return content

    logger.warning("Restored escaped line breaks in %s; the model escaped them twice", file_path)
    return candidate
