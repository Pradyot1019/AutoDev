from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from langchain_core.messages import SystemMessage
from langchain_core.prompts import ChatPromptTemplate, HumanMessagePromptTemplate

from prompts.projections import (
    architecture_preamble,
    architecture_services,
    prd_for_developer,
)
from utils.json_utils import compact_json

BASE_INSTRUCTIONS = """
You are a senior full-stack developer. Convert the architecture into complete,
production-ready source code. Every file must be fully implemented: no TODOs, no
stubs, no placeholder logic.

SCOPE
- Generate every file listed in `project_structure`, for every service, except
  tests, pytest configuration and deployment files: other agents write those.
- Every folder listed in `project_structure` must contain at least one file. An
  empty folder cannot be delivered; for a Python package, add its `__init__.py`.
- Implement every feature in the PRD.
- Clean, modular code with error handling, logging and type hints throughout.

PATHS
- `file_path` is relative to the service root, e.g. `app/main.py`. Never begin one
  with `/`, a drive letter or `..` — such files are discarded.
- Spell `service_name` exactly as the architecture does.

BACKEND (Python/FastAPI or equivalent)
- One router file per domain (auth.py, expenses.py).
- Pydantic models with validation for every request and response body.
- Complete JWT auth: register, login, token generation, verification middleware.
- Hash passwords with bcrypt; never store plaintext.
- SQLAlchemy models with real relationships (ForeignKey, back_populates).
- Scope every query to the authenticated user — one user must never read another's rows.
- CORS configured for the frontend origin.
- Errors as `{{"detail": "message"}}`, consistently.
- Read config from the environment with `os.getenv` or pydantic-settings; no
  hardcoded secrets, passwords or API keys. `DATABASE_URL` falls back to a local
  SQLite file so the code runs without a database server.

FRONTEND (React or equivalent)
- React Router with routes defined centrally; protected routes redirect to /login.
- JWT in localStorage, sent as a Bearer token by an Axios interceptor.
- Axios `baseURL` from `REACT_APP_API_URL`.
- Reusable components, one per file, grouped by feature.
- Handle loading and error states for every API call.
- Login state via React Context or an auth hook.
- Style with the CSS framework the architecture names (Tailwind, MUI) — never
  unstyled HTML.

TESTABILITY — an automated runner imports and executes this code
- Business logic in importable modules, not inside route handlers.
- No side effects at import time: no connections, no network calls.
- Expose the app as a module-level `app` in each service's main module.

FILES EVERY SERVICE NEEDS
- `.env.example` listing every environment variable with a description, as a
  CodeFile in that service's files.
- Python: `requirements.txt` with every third-party import pinned, never empty.
- Node: `package.json` with exact versions and start/build/test scripts.
- `dependency_files` additionally carries the root-level combined file.

README (`readme_content`)
Beyond the sections the schema names, include a one-paragraph description, setup
in order (install, configure env, migrate, run), a full API reference giving the
method, path, whether auth is required, request body and response for every
endpoint, how to run in development, and troubleshooting for common failures.

NEVER
- Dockerfiles or docker-compose — a deployment agent handles those.
- Pseudo-code, or a function whose body is not real logic.
"""

FIX_INSTRUCTIONS = """
FIX MODE
Your previous attempt did not pass verification. The evidence below comes from
actually compiling and running your code, not from opinion.

1. Read every failure report carefully. Compiler errors and failing tests are facts; fix them first.
2. Output ONLY the files that need to change. Do not regenerate files that were already correct.
3. Apply every fix in the `suggested_fix` field of each reported bug.
4. Do not break a passing test in order to fix a failing one.
5. If a test itself encodes the wrong expectation, fix the source so the documented behaviour holds.

Priority order: syntax and import errors, then failing tests, then critical bugs, then everything else.
"""


@dataclass(frozen=True)
class EvidenceDetail:
    """How much of each report a fix prompt carries."""

    static_failures: int = 40
    test_failures: int = 15
    message_chars: int = 600


# Most to least detailed. The developer agent steps down this list until its call
# fits the per-minute budget: in a live run seven test failures pushed the last
# fix call to 8,006 tokens against an 8,000 window, and the run ended there.
EVIDENCE_LEVELS: tuple[EvidenceDetail, ...] = (
    EvidenceDetail(),
    EvidenceDetail(static_failures=20, test_failures=8, message_chars=300),
    EvidenceDetail(static_failures=10, test_failures=4, message_chars=150),
)

_PYTEST_ERROR_LINE = re.compile(r"^E\s+(?P<text>.+)$")
_PYTEST_LOCATION = re.compile(r"^(?P<loc>[^\s].*\.py:\d+):")


def condense_failure(message: str) -> str:
    """The part of a pytest failure that says what went wrong, and where.

    A collection failure is mostly boilerplate ("Hint: make sure your test
    modules/packages have valid Python names", an importlib frame); the cause is
    the ``E`` line, and the place is the last frame inside the project. Messages
    without ``E`` lines are returned as they are.
    """
    errors: list[str] = []
    location = ""
    for raw in message.splitlines():
        line = raw.rstrip()
        match = _PYTEST_ERROR_LINE.match(line)
        if match:
            text = match.group("text").strip()
            if text and text not in errors:
                errors.append(text)
            continue
        where = _PYTEST_LOCATION.match(line.strip())
        # Not the harness conftest: it is where the app was loaded, never what broke.
        if where and not any(skip in line for skip in ("site-packages", "importlib", "conftest.py")):
            location = where.group("loc")
    if not errors:
        return message.strip()
    return " | ".join(errors) + (f" (at {location})" if location else "")


def _render_static_report(report: dict[str, Any], detail: EvidenceDetail = EVIDENCE_LEVELS[0]) -> str:
    failures = report.get("failures") or []
    if not failures:
        return ""
    limit = detail.static_failures
    lines = ["COMPILE AND LINT FAILURES (highest priority):"]
    lines += [f"  - {failure}" for failure in failures[:limit]]
    if len(failures) > limit:
        lines.append(f"  ...and {len(failures) - limit} more")
    return "\n".join(lines)


def _render_verification_report(report: dict[str, Any], detail: EvidenceDetail = EVIDENCE_LEVELS[0]) -> str:
    services = report.get("services") or []
    blocks: list[str] = []

    for service in services:
        failures = service.get("failures") or []
        if not failures and not service.get("error"):
            continue

        header = (
            f"SERVICE {service.get('service', '?')}: "
            f"{service.get('passed', 0)} passed, {service.get('failed', 0)} failed, "
            f"{service.get('errors', 0)} errored"
        )
        block = [header]

        if service.get("error"):
            block.append(f"  runner error: {service['error']}")

        # Tests that failed for the same reason are listed once: seven collection
        # failures from one broken import are one problem, not seven.
        grouped: dict[str, list[str]] = {}
        for failure in failures:
            message = condense_failure(failure.get("message") or "")[: detail.message_chars]
            grouped.setdefault(message, []).append(str(failure.get("test", "?")))

        for message, tests in list(grouped.items())[: detail.test_failures]:
            shown = ", ".join(tests[:5]) + (f" and {len(tests) - 5} more" if len(tests) > 5 else "")
            block.append(f"  FAILED {shown}")
            if message:
                block.append(f"    {message}")
        if len(grouped) > detail.test_failures:
            block.append(f"  ...and {len(grouped) - detail.test_failures} more distinct failure(s)")
        blocks.append("\n".join(block))

    if not blocks:
        return ""
    return "REAL TEST RESULTS:\n" + "\n".join(blocks)


def _render_qa_report(report: dict[str, Any]) -> str:
    lines: list[str] = []
    for service in report.get("service_reports") or []:
        bugs = service.get("bugs") or []
        if not bugs:
            continue
        lines.append(
            f"SERVICE {service.get('service_name', '?')} "
            f"(quality score {service.get('code_quality_score', '?')}/10):"
        )
        for bug in bugs:
            lines.append(
                f"  [{str(bug.get('severity', 'unknown')).upper()}] {bug.get('file_path', '?')}"
                f" line {bug.get('line_number', '?')}: {bug.get('description', '')}"
            )
            lines.append(f"    fix: {bug.get('suggested_fix', '')}")
    if not lines:
        return ""
    return "REVIEWER-REPORTED BUGS:\n" + "\n".join(lines)


def build_failure_evidence(
    qa_report: dict[str, Any] | None,
    static_report: dict[str, Any] | None,
    verification_report: dict[str, Any] | None,
    detail: EvidenceDetail = EVIDENCE_LEVELS[0],
) -> str:
    """Assemble the grounded failure evidence for a fix pass, most objective first."""
    sections = [
        _render_static_report(static_report or {}, detail),
        _render_verification_report(verification_report or {}, detail),
        _render_qa_report(qa_report or {}),
    ]
    return "\n\n".join(section for section in sections if section)


def get_developer_prompt(
    user_requirements: str,
    prd_json: dict[str, Any],
    architect_json: dict[str, Any],
    service: dict[str, Any] | None = None,
    qa_report: dict[str, Any] | None = None,
    static_report: dict[str, Any] | None = None,
    verification_report: dict[str, Any] | None = None,
    detail: EvidenceDetail = EVIDENCE_LEVELS[0],
) -> list:
    """Build the developer prompt.

    ``service`` narrows the call to one service from the architecture. The whole
    project in one response needs about 8,200 output tokens, which cannot fit an
    8,000 token-per-minute window at any prompt size; one service needs roughly
    3,000-4,000 and does fit.

    The three reports are rendered exactly as given. Callers may hand over the
    whole project's, or the share `agents/attribution.py` attributes to this
    service — the developer agent does the latter, so a service is no longer
    shown another's compiler errors. Either way the evidence is built by
    `build_failure_evidence` below, and a report with nothing in it renders as no
    section at all, which is what turns an empty set of failures back into a
    first-generation prompt.
    """
    evidence = build_failure_evidence(qa_report, static_report, verification_report, detail)
    is_fix = bool(evidence)

    # The system message is identical on every attempt, and the fix-mode rules
    # travel with the evidence at the end. Providers cache a prompt *prefix*, so a
    # retry that changed the system message re-paid for the requirement, PRD and
    # architecture that follow it -- the bulk of the prompt, resent unchanged.
    messages = [
        SystemMessage(content=BASE_INSTRUCTIONS),
        HumanMessagePromptTemplate.from_template(
            """
USER REQUIREMENTS:
{user_requirements}

PRD:
{prd_json}

ARCHITECTURE:
{architecture_preamble}

SERVICES TO IMPLEMENT:
{architecture_services}
"""
        ),
    ]

    format_kwargs: dict[str, Any] = {
        "user_requirements": user_requirements,
        # The preamble is every-service context; the services are sent beside it
        # so a later per-service pass can send one without reshaping anything.
        "prd_json": compact_json(prd_for_developer(prd_json)),
        "architecture_preamble": compact_json(architecture_preamble(architect_json)),
        "architecture_services": compact_json(
            [service] if service is not None else architecture_services(architect_json)
        ),
    }

    if is_fix:
        messages.append(
            HumanMessagePromptTemplate.from_template(
                """{fix_instructions}
VERIFICATION FAILED. Evidence from compiling and running your previous output:

{evidence}

Return the Developer Schema output containing ONLY the files you are changing.
"""
            )
        )
        format_kwargs["evidence"] = evidence
        # A value, not template text: the rules may contain braces.
        format_kwargs["fix_instructions"] = FIX_INSTRUCTIONS
    else:
        messages.append(
            HumanMessagePromptTemplate.from_template(
                "Generate the complete Developer Schema output with fully implemented source code for every file."
            )
        )

    return ChatPromptTemplate.from_messages(messages).format_messages(**format_kwargs)
