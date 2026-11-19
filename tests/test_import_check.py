"""Imports between a service's own modules must name things that exist.

Live: main.py imported five functions the repository never defined. The code
parsed, ruff saw no undefined name, the gate passed, QA spent a call on it, and
every test died at import.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from verification.static_gate import _check_project_imports


def write(root: Path, files: dict[str, str]) -> Path:
    for rel, source in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8")
    return root


@pytest.fixture
def service(tmp_path: Path) -> Path:
    return tmp_path / "api"


class TestFlagged:
    def test_a_name_the_module_never_defines(self, service: Path):
        write(service, {
            "app/__init__.py": "",
            "app/repo.py": "class HabitRepository:\n    pass\n",
            "app/main.py": "from app.repo import create_habit_record\n",
        })

        check = _check_project_imports("api", service)

        assert not check.passed
        assert check.failures == [
            "api/app/main.py:1: cannot import name 'create_habit_record' from 'app.repo' "
            "(app/repo.py does not define it)"
        ]

    def test_a_module_that_does_not_exist(self, service: Path):
        write(service, {"app/__init__.py": "", "app/main.py": "from app.utils.auth import verify\n"})

        check = _check_project_imports("api", service)

        assert check.failures == ["api/app/main.py:1: no module named 'app.utils.auth' in this service"]

    def test_a_relative_import(self, service: Path):
        write(service, {
            "app/__init__.py": "",
            "app/models.py": "Base = object\n",
            "app/routes/__init__.py": "",
            "app/routes/habits.py": "from ..models import Habit\n",
        })

        check = _check_project_imports("api", service)

        assert "cannot import name 'Habit' from 'app.models'" in check.failures[0]

    def test_an_empty_package_init(self, service: Path):
        write(service, {
            "app/__init__.py": "",
            "app/models/__init__.py": "",
            "app/models/habit.py": "class Habit: ...\n",
            "app/main.py": "from app.models import Habit\n",
        })

        assert not _check_project_imports("api", service).passed


class TestShadowedModules:
    """Live: app/db.py defined get_session, but app/db/ was imported instead."""

    def test_a_module_beside_a_package_of_the_same_name_is_flagged(self, service: Path):
        write(service, {
            "app/__init__.py": "",
            "app/db.py": "def get_session(): ...\n",
            "app/db/__init__.py": "",
            "app/db/database.py": "engine = None\n",
            "app/repo.py": "from app.db import get_session\n",
        })

        check = _check_project_imports("api", service)

        assert any("app/db.py: shadowed by the package app/db/" in f for f in check.failures)
        # Resolved the way Python resolves it: against the package, which lacks the name.
        assert any("cannot import name 'get_session' from 'app.db'" in f for f in check.failures)

    def test_a_namespace_directory_does_not_shadow_the_module(self, service: Path):
        """Without __init__.py the directory is a namespace portion, and the module wins."""
        write(service, {
            "app/__init__.py": "",
            "app/db.py": "x = 1\n",
            "app/db/database.py": "y = 1\n",
            "app/main.py": "from app.db import x\n",
        })

        assert _check_project_imports("api", service).passed


class TestAccepted:
    def test_every_way_a_module_binds_a_name(self, service: Path):
        write(service, {
            "app/__init__.py": "",
            "app/lib.py": (
                "import os\n"
                "from typing import Any as Anything\n"
                "A = 1\n"
                "B: int = 2\n"
                "C, (D, E) = 3, (4, 5)\n"
                "def f(): ...\n"
                "async def g(): ...\n"
                "class K: ...\n"
                "try:\n    import ujson as fast_json\nexcept ImportError:\n    fast_json = None\n"
                "if os.name:\n    H = 1\nelse:\n    H = 2\n"
            ),
            "app/main.py": "from app.lib import os, Anything, A, B, C, D, E, f, g, K, fast_json, H\n",
        })

        check = _check_project_imports("api", service)

        assert check.passed, check.failures

    def test_a_submodule_imported_from_its_package(self, service: Path):
        write(service, {
            "app/__init__.py": "",
            "app/routes/__init__.py": "",
            "app/routes/habits.py": "router = None\n",
            "app/main.py": "from app.routes import habits\nfrom app import routes\n",
        })

        assert _check_project_imports("api", service).passed

    def test_a_namespace_package_without_init(self, service: Path):
        write(service, {"app/core/db.py": "get_db = None\n", "app/main.py": "from app.core.db import get_db\n"})

        assert _check_project_imports("api", service).passed

    def test_third_party_and_stdlib_imports_are_not_its_business(self, service: Path):
        write(service, {"main.py": "from fastapi import FastAPI\nfrom datetime import date\n"})

        assert _check_project_imports("api", service).passed

    def test_a_project_file_shadowing_the_stdlib_is_not_judged(self, service: Path):
        write(service, {"logging.py": "x = 1\n", "main.py": "from logging import getLogger\n"})

        assert _check_project_imports("api", service).passed

    def test_a_module_whose_names_cannot_be_read_is_trusted(self, service: Path):
        write(service, {
            "app/__init__.py": "",
            "app/star.py": "from os.path import *\n",
            "app/lazy.py": "def __getattr__(name):\n    return name\n",
            "app/main.py": "from app.star import join\nfrom app.lazy import anything\n",
        })

        assert _check_project_imports("api", service).passed

    def test_a_file_that_does_not_parse_is_left_to_the_compile_check(self, service: Path):
        write(service, {"app/__init__.py": "", "app/bad.py": "def (:\n", "app/main.py": "from app.bad import x\n"})

        check = _check_project_imports("api", service)

        assert check.passed


class TestMovedImports:
    """Live: `from pydantic import BaseSettings` crashed the app in three runs."""

    def test_the_pydantic_v1_settings_import_is_flagged(self, service: Path):
        from verification.static_gate import _check_moved_imports

        write(service, {
            "requirements.txt": "fastapi==0.110.0\npydantic==2.7.1\n",
            "app/database.py": "import os\nfrom pydantic import BaseSettings, Field\n",
        })

        check = _check_moved_imports("api", service)

        assert len(check.failures) == 1
        assert check.failures[0].startswith("api/app/database.py:2: BaseSettings moved")
        assert "from pydantic_settings import BaseSettings" in check.failures[0]

    def test_unpinned_pydantic_is_treated_as_current(self, service: Path):
        from verification.static_gate import _check_moved_imports

        write(service, {"requirements.txt": "pydantic\n", "config.py": "from pydantic import BaseSettings\n"})

        assert not _check_moved_imports("api", service).passed

    @pytest.mark.parametrize("pin", ["pydantic==1.10.13", "pydantic<2", "pydantic~=1.10"])
    def test_a_v1_pin_makes_the_old_import_valid(self, service: Path, pin: str):
        from verification.static_gate import _check_moved_imports

        write(service, {"requirements.txt": f"{pin}\n", "config.py": "from pydantic import BaseSettings\n"})

        assert _check_moved_imports("api", service).passed

    def test_the_new_import_and_other_pydantic_names_pass(self, service: Path):
        from verification.static_gate import _check_moved_imports

        write(service, {
            "config.py": "from pydantic import BaseModel, Field\nfrom pydantic_settings import BaseSettings\n",
        })

        assert _check_moved_imports("api", service).passed


def test_the_gate_runs_it(workspace):
    """Wired into run_static_gate, reported like a compiler error."""
    from verification.runner import LocalSubprocessRunner
    from verification.static_gate import run_static_gate

    workspace.write_source_file("api", "app/__init__.py", "")
    workspace.write_source_file("api", "app/main.py", "from app.repo import missing\n")
    workspace.write_source_file("api", "app/repo.py", "present = 1\n")

    report = run_static_gate(workspace, runner=LocalSubprocessRunner(install_deps=False))

    assert not report.passed
    assert any("cannot import name 'missing'" in failure for failure in report.failures)
