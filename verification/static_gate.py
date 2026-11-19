"""The cheap gate: does the generated code even parse?

This runs before anything is executed and before the QA agent is asked for an
opinion. A syntax error or an undefined name is not a matter of judgement, and
there is no point spending a model call to discover one. Nothing in this module
imports or executes generated code — Python files are checked with :func:`compile`,
which parses without running.
"""

from __future__ import annotations

import ast
import json
import re
import sys
from importlib.util import find_spec
from pathlib import Path

from core.contracts import check_contract
from core.logging import get_logger
from core.paths import RunWorkspace
from schema.verification_schema import StaticCheck, StaticReport
from verification.runner import Runner, get_runner

logger = get_logger(__name__)

# Enough for the developer agent to act on without flooding its context window.
MAX_REPORTED_FAILURES = 40

_SKIP_DIRS = {".venv", "venv", "node_modules", "__pycache__", ".git", ".pytest_cache", "dist"}

# Syntax errors, undefined names, f-string and comparison mistakes. Deliberately
# not style rules: the point is code that cannot work, not code that is untidy.
_RUFF_RULES = "E9,F63,F7,F82"

# ruff --output-format=concise emits "path:line:col: CODE message". Matching that
# shape exactly keeps banners like "All checks passed!" out of the failure list.
_RUFF_DIAGNOSTIC = re.compile(r"^(?P<path>.+?):\d+:\d+: [A-Z]+\d+ ")


def run_static_gate(
    workspace: RunWorkspace,
    services: list[str] | None = None,
    runner: Runner | None = None,
    contract: dict | None = None,
    manifest: dict | None = None,
) -> StaticReport:
    """Parse-check every generated file in the workspace.

    ``contract`` adds a second deterministic pass over the same code: the
    architecture a human approved, reduced by :mod:`core.contracts` to the claims
    a path lookup can settle. It runs here rather than as a node of its own
    because it asks the same kind of question the parse checks ask — is this fact
    about the generated code true — and answering it in the same report means a
    violation reaches the developer through the machinery that already carries a
    syntax error, with no second gate, no second router and no second retry
    budget.

    The order is checks first, then the contract, so the flattened failure list
    reads compiler output before design mismatches.
    """
    report = StaticReport()
    service_dirs = _service_dirs(workspace, services)

    if not service_dirs and not contract:
        report.ran = False
        report.checks.append(
            StaticCheck(
                name="compile",
                service="-",
                skipped=True,
                skip_reason="No generated source directories were found.",
            )
        )
        return report

    if service_dirs:
        runner = runner or get_runner()

        for service_dir in service_dirs:
            service = service_dir.name
            report.checks.append(_check_python_syntax(service, service_dir))
            report.checks.append(_check_json(service, service_dir))
            report.checks.append(_check_undefined_names(service, service_dir, runner))
            report.checks.append(_check_project_imports(service, service_dir))
            report.checks.append(_check_moved_imports(service, service_dir))

    if contract:
        # A service the architecture declared but nobody generated has no
        # directory to check, so this is also the only pass that can notice it.
        report.checks.extend(check_contract(contract, manifest, workspace))

    report.ran = True
    failures: list[str] = []
    for check in report.checks:
        failures.extend(check.failures)

    report.failures = failures[:MAX_REPORTED_FAILURES]
    if len(failures) > MAX_REPORTED_FAILURES:
        report.failures.append(f"... and {len(failures) - MAX_REPORTED_FAILURES} more")
    report.passed = not failures

    logger.info(
        "static_gate.done",
        extra={"passed": report.passed, "failures": len(failures)},
    )
    return report


# ── Individual checks ────────────────────────────────────────────


def _check_python_syntax(service: str, service_dir: Path) -> StaticCheck:
    check = StaticCheck(name="compile", service=service)
    files = _iter_files(service_dir, ".py")

    if not files:
        check.skipped = True
        check.skip_reason = "No Python files."
        return check

    for path in files:
        rel = path.relative_to(service_dir).as_posix()
        try:
            source = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            check.failures.append(f"{service}/{rel}: unreadable ({exc})")
            continue
        try:
            compile(source, str(path), "exec", dont_inherit=True)
        except SyntaxError as exc:
            check.failures.append(f"{service}/{rel}:{exc.lineno or 0}: {exc.msg}")
        except ValueError as exc:
            # Null bytes and similar; compile() rejects these outside SyntaxError.
            check.failures.append(f"{service}/{rel}: {exc}")

    check.passed = not check.failures
    return check


def _check_json(service: str, service_dir: Path) -> StaticCheck:
    check = StaticCheck(name="json", service=service)
    files = _iter_files(service_dir, ".json")

    if not files:
        check.skipped = True
        check.skip_reason = "No JSON files."
        return check

    for path in files:
        rel = path.relative_to(service_dir).as_posix()
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            check.failures.append(f"{service}/{rel}:{exc.lineno}: invalid JSON, {exc.msg}")
        except (OSError, UnicodeDecodeError) as exc:
            check.failures.append(f"{service}/{rel}: unreadable ({exc})")

    check.passed = not check.failures
    return check


def _check_undefined_names(service: str, service_dir: Path, runner: Runner) -> StaticCheck:
    """Catch missing imports and typo'd names, which are the model's usual slip."""
    check = StaticCheck(name="pyflakes", service=service)

    if not _iter_files(service_dir, ".py"):
        check.skipped = True
        check.skip_reason = "No Python files."
        return check

    if find_spec("ruff") is None:
        check.skipped = True
        check.skip_reason = "ruff is not installed."
        return check

    result = runner.exec(
        [
            sys.executable,
            "-m",
            "ruff",
            "check",
            "--isolated",  # ignore any pyproject.toml above the workspace
            "--no-cache",
            f"--select={_RUFF_RULES}",
            "--output-format=concise",
            ".",
        ],
        cwd=service_dir,
        timeout=120,
    )

    if result.exit_code not in (0, 1):
        check.skipped = True
        check.skip_reason = f"ruff could not run ({result.summary()})."
        return check

    for raw in result.stdout.splitlines():
        line = _strip_dot_prefix(raw.strip())
        match = _RUFF_DIAGNOSTIC.match(line)
        if not match:
            continue
        # ruff reports native separators; the agents deal in POSIX paths.
        path = match.group("path").replace("\\", "/")
        check.failures.append(f"{service}/{path}{line[match.end('path') :]}")

    check.passed = not check.failures
    return check


def _check_project_imports(service: str, service_dir: Path) -> StaticCheck:
    """Imports between the service's own modules must name things that exist.

    Live: ``app/main.py`` imported five functions from ``habit_repository`` that
    were never written. Every file parsed and ruff saw no undefined name, so it
    passed this gate, QA spent a call reviewing it, and the tests died at import.
    Settled from the syntax tree alone, like everything here: a ``from X import y``
    where X is a module of this service is checked against the names X defines at
    its top level. Imports of anything outside the service are not this check's
    business, and a module whose names cannot be read statically (a star import,
    a module ``__getattr__``) is trusted.
    """
    check = StaticCheck(name="imports", service=service)
    files = _iter_files(service_dir, ".py")
    if not files:
        check.skipped = True
        check.skip_reason = "No Python files."
        return check

    modules: dict[str, Path] = {}
    packages: set[str] = set()
    plain: dict[str, Path] = {}  # name.py files, before packages are known
    for path in files:
        parts = list(path.relative_to(service_dir).with_suffix("").parts)
        for depth in range(1, len(parts)):
            packages.add(".".join(parts[:depth]))
        if parts[-1] == "__init__":
            parts = parts[:-1]
            if not parts:
                continue
            packages.add(".".join(parts))
            modules[".".join(parts)] = path
        else:
            plain[".".join(parts)] = path

    # Python imports a regular package (one with __init__.py) before a module of
    # the same name, so `app/db.py` beside `app/db/__init__.py` can never be
    # imported. A namespace directory without __init__.py does not shadow it.
    # Live: the developer added `app/db/` for the architecture's folder list, and
    # every import of `get_session` from `app.db` failed although db.py defined it.
    for name, path in plain.items():
        if name in modules:
            rel = path.relative_to(service_dir).as_posix()
            check.failures.append(
                f"{service}/{rel}: shadowed by the package {rel[: -len('.py')]}/, which Python "
                "imports instead; move this module's code into that package or rename one of them"
            )
        else:
            modules[name] = path

    # A project file that shares a standard-library name is too ambiguous to judge.
    roots = {name.split(".")[0] for name in (*modules, *packages)} - set(sys.stdlib_module_names)
    trees: dict[Path, ast.Module | None] = {}

    def tree_of(path: Path) -> ast.Module | None:
        if path not in trees:
            try:
                trees[path] = ast.parse(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, SyntaxError, ValueError):
                trees[path] = None  # the compile check reports these
        return trees[path]

    for path in files:
        tree = tree_of(path)
        if tree is None:
            continue
        rel = path.relative_to(service_dir).as_posix()
        package = list(path.relative_to(service_dir).parent.parts)

        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom):
                continue
            target = _resolve_import(node, package)
            if target is None or target.split(".")[0] not in roots:
                continue

            where = f"{service}/{rel}:{node.lineno}"
            if target not in modules and target not in packages:
                check.failures.append(f"{where}: no module named '{target}' in this service")
                continue
            if target not in modules:
                continue  # a package without __init__.py defines no names of its own

            defined = _top_level_names(tree_of(modules[target]))
            if defined is None:
                continue
            for alias in node.names:
                name = alias.name
                submodule = f"{target}.{name}"
                if name == "*" or name in defined or submodule in modules or submodule in packages:
                    continue
                target_rel = modules[target].relative_to(service_dir).as_posix()
                check.failures.append(
                    f"{where}: cannot import name '{name}' from '{target}' ({target_rel} does not define it)"
                )

    check.passed = not check.failures
    return check


# Names a library moved in a major version that models trained on older code keep
# importing from the old place. Each costs a whole attempt when caught only by the
# test run: `from pydantic import BaseSettings` appeared in three live runs against
# pydantic 2, and the app crashed on import each time.
# Keyed by (module, name), with the requirement pin that makes the old import valid.
_MOVED_IMPORTS: dict[tuple[str, str], tuple[str, re.Pattern[str]]] = {
    ("pydantic", "BaseSettings"): (
        "BaseSettings moved to the pydantic-settings package in pydantic 2: use "
        "`from pydantic_settings import BaseSettings` and add pydantic-settings to requirements.txt",
        re.compile(r"^\s*pydantic\s*(?:==\s*1\.|<\s*2|~=\s*1\.)", re.IGNORECASE | re.MULTILINE),
    ),
}


def _check_moved_imports(service: str, service_dir: Path) -> StaticCheck:
    """Imports of names a pinned major version has moved elsewhere."""
    check = StaticCheck(name="moved-imports", service=service)
    files = _iter_files(service_dir, ".py")
    if not files:
        check.skipped = True
        check.skip_reason = "No Python files."
        return check

    requirements = ""
    for candidate in (service_dir / "requirements.txt", service_dir.parent / "requirements.txt"):
        try:
            requirements += candidate.read_text(encoding="utf-8") + "\n"
        except (OSError, UnicodeDecodeError):
            continue

    for path in files:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, SyntaxError, ValueError):
            continue  # the compile check reports these
        rel = path.relative_to(service_dir).as_posix()
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or node.level or not node.module:
                continue
            for alias in node.names:
                moved = _MOVED_IMPORTS.get((node.module, alias.name))
                if moved is None:
                    continue
                advice, old_pin = moved
                if old_pin.search(requirements):
                    continue  # pinned to the version where the old import works
                check.failures.append(f"{service}/{rel}:{node.lineno}: {advice}")

    check.passed = not check.failures
    return check


def _resolve_import(node: ast.ImportFrom, package: list[str]) -> str | None:
    """The absolute dotted module a ``from ... import`` names, or None if unresolvable."""
    if not node.level:
        return node.module
    if node.level - 1 > len(package):
        return None
    base = package[: len(package) - (node.level - 1)]
    parts = [*base, *(node.module.split(".") if node.module else [])]
    return ".".join(parts) or None


def _top_level_names(tree: ast.Module | None) -> set[str] | None:
    """Names a module binds at import time, or None when that cannot be read statically."""
    if tree is None:
        return None
    names: set[str] = set()

    def visit(body: list[ast.stmt]) -> bool:
        for stmt in body:
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                names.add(stmt.name)
                if stmt.name == "__getattr__":
                    return False
            elif isinstance(stmt, (ast.Import, ast.ImportFrom)):
                for alias in stmt.names:
                    if alias.name == "*":
                        return False
                    names.add(alias.asname or alias.name.split(".")[0])
            elif isinstance(stmt, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
                targets = stmt.targets if isinstance(stmt, ast.Assign) else [stmt.target]
                for target in targets:
                    names.update(n.id for n in ast.walk(target) if isinstance(n, ast.Name))
            else:
                if isinstance(stmt, (ast.For, ast.AsyncFor, ast.With, ast.AsyncWith)):
                    targets = (
                        [stmt.target]
                        if isinstance(stmt, (ast.For, ast.AsyncFor))
                        else [item.optional_vars for item in stmt.items if item.optional_vars]
                    )
                    for target in targets:
                        names.update(n.id for n in ast.walk(target) if isinstance(n, ast.Name))
                for field in ("body", "orelse", "finalbody"):
                    if not visit(getattr(stmt, field, None) or []):
                        return False
                for handler in getattr(stmt, "handlers", None) or []:
                    if not visit(handler.body):
                        return False
        return True

    return names if visit(tree.body) else None


# ── Helpers ──────────────────────────────────────────────────────


def _service_dirs(workspace: RunWorkspace, services: list[str] | None) -> list[Path]:
    if services:
        candidates = [workspace.service_source(name) for name in services]
    elif workspace.source.is_dir():
        candidates = sorted(p for p in workspace.source.iterdir() if p.is_dir())
    else:
        candidates = []
    return [path for path in candidates if path.is_dir() and path.name not in _SKIP_DIRS]


def _strip_dot_prefix(line: str) -> str:
    for prefix in ("./", ".\\"):
        if line.startswith(prefix):
            return line[len(prefix) :]
    return line


def _iter_files(root: Path, suffix: str) -> list[Path]:
    return sorted(
        path
        for path in root.rglob(f"*{suffix}")
        if path.is_file() and not _SKIP_DIRS.intersection(path.parts)
    )
