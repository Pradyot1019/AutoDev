"""AgentForge test harness — generated so the test suite can find the application.

This file is written by the pipeline, not by the developer agent, and is not
part of the delivered project.
"""

import importlib
import os
import sys
import traceback
from pathlib import Path

import pytest

SERVICE_ROOT = Path(os.environ.get("AGENTFORGE_SERVICE_ROOT", ".")).resolve()
if str(SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVICE_ROOT))

# Sensible defaults so importing the app does not fail on missing configuration.
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("DATABASE_URL", "sqlite:///" + (SERVICE_ROOT / "test.db").as_posix())
os.environ.setdefault("SECRET_KEY", "agentforge-test-secret")
os.environ.setdefault("JWT_SECRET_KEY", "agentforge-test-secret")
os.environ.setdefault("ALGORITHM", "HS256")
os.environ.setdefault("ACCESS_TOKEN_EXPIRE_MINUTES", "30")

_APP_MODULES = ("app.main", "main", "app", "src.main", "api.main", "server.main")


def _project_location(exc):
    # The last frame inside the service, so the failure names the file to fix
    # rather than this conftest, which is only where the import was attempted.
    found = ""
    for frame in traceback.extract_tb(exc.__traceback__):
        try:
            rel = Path(frame.filename).resolve().relative_to(SERVICE_ROOT)
        except (ValueError, OSError):
            continue
        if ".venv" in rel.parts or "site-packages" in rel.parts:
            continue
        found = "{0}:{1}".format(rel.as_posix(), frame.lineno)
    if isinstance(exc, SyntaxError) and exc.filename:
        try:
            rel = Path(exc.filename).resolve().relative_to(SERVICE_ROOT)
            found = "{0}:{1}".format(rel.as_posix(), exc.lineno or 0)
        except (ValueError, OSError):
            pass
    return found


def _load_app():
    attempts = []
    absent = []
    for name in _APP_MODULES:
        try:
            module = importlib.import_module(name)
        except ModuleNotFoundError as exc:
            if exc.name and (name == exc.name or name.startswith(exc.name + ".")):
                absent.append(name)  # the candidate simply does not exist
                continue
            attempts.append(_describe(name, exc))
            continue
        except Exception as exc:  # noqa: BLE001
            attempts.append(_describe(name, exc))
            continue
        instance = getattr(module, "app", None)
        if instance is not None:
            return instance, attempts
        attempts.append("{0}: imported but defines no 'app'".format(name))
    if absent:
        attempts.append("not present: " + ", ".join(absent))
    return None, attempts


def _describe(name, exc):
    where = _project_location(exc)
    text = "{0}: {1}: {2}".format(name, type(exc).__name__, str(exc).splitlines()[0] if str(exc) else "")
    return text + (" (at {0})".format(where) if where else "")


@pytest.fixture(scope="session")
def app():
    instance, attempts = _load_app()
    if instance is None:
        pytest.fail("Could not import an ASGI app. Tried:\n  " + "\n  ".join(attempts))
    return instance


@pytest.fixture()
def client(app):
    try:
        from fastapi.testclient import TestClient
    except ImportError:  # pragma: no cover
        from starlette.testclient import TestClient

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(autouse=True)
def _module_level_client(request):
    # Generated tests often use `client` as a module global instead of asking
    # for the fixture. Supply it only to modules that use it and never define it,
    # so tests of pure functions do not import the app.
    module = request.module
    if "client" in request.fixturenames or hasattr(module, "client"):
        yield
        return
    try:
        uses_client = "client." in Path(module.__file__).read_text(encoding="utf-8")
    except OSError:
        uses_client = False
    if not uses_client:
        yield
        return
    module.client = request.getfixturevalue("client")
    try:
        yield
    finally:
        del module.client
