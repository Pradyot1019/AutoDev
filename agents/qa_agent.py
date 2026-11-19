from __future__ import annotations

from typing import Any

from agents.base import run_stage, workspace_for, write_document
from core import manifest as manifest_util
from core.config import Purpose, get_settings
from core.logging import bind, get_logger
from core.paths import RunWorkspace, UnsafePathError
from llm import registry
from llm.budget import estimate_tokens
from llm.content import flatten_content
from llm.structured import schema_instructions
from prompts.qa_json_prompt import get_qa_prompt
from prompts.qa_pdf_prompt import get_qa_doc_prompt
from prompts.qa_triage_prompt import get_qa_triage_prompt
from schema.qa_schema import QASchema
from state.state import AgentStatus, MultiAgent, Stage
from utils.content_repair import repair_escaped_newlines
from utils.json_utils import extract_json_list, save_json
from utils.status_tracker import log_status, mark

logger = get_logger(__name__)

ARTIFACT_JSON = "qa.json"
ARTIFACT_PDF = "qa.pdf"

# Cap what goes into the review prompt so a large project cannot blow the context
# window. Triage decides which files matter; this is the backstop.
MAX_REVIEW_BYTES = 120_000


async def qa_agent(state: MultiAgent) -> dict[str, Any]:
    """Review the generated code and write tests for it.

    Two passes keep cost down: a cheap triage call reads only the file manifest and
    names the files worth inspecting, then only those files are read from disk and
    sent to the expensive review call.
    """
    stage = Stage.QA

    async def body() -> dict[str, Any]:
        workspace = workspace_for(state)
        prd = state.get("prd") or {}
        architecture = state.get("architecture") or {}
        manifest = state.get("code_manifest") or {}

        log_status({**state, "status": mark(state, stage, AgentStatus.IN_PROGRESS)})

        if not manifest:
            raise ValueError("No code manifest to review; the developer agent produced nothing")

        flagged = await _triage(prd, architecture, manifest)
        code = _fit_review_to_budget(workspace, prd, architecture, manifest, flagged)

        model = registry.get_structured_llm(QASchema, Purpose.STRUCTURED)
        response = await model.ainvoke(get_qa_prompt(prd, architecture, manifest, code))
        report = response.model_dump(mode="json")

        save_json(report, workspace.artifacts / ARTIFACT_JSON)
        written = _write_tests(report, workspace)
        await write_document(get_qa_doc_prompt(report), workspace, ARTIFACT_PDF)

        logger.info(
            "Review complete: %d bug(s), %d critical, %d test file(s) written",
            report.get("total_bugs_found", 0),
            report.get("critical_issues", 0),
            written,
        )
        for service in report.get("service_reports") or []:
            logger.info(
                "  %s scored %s/10",
                service.get("service_name", "?"),
                service.get("code_quality_score", "?"),
            )

        return {"qa_report": report}

    with bind(run_id=state.get("run_id"), stage=stage.value):
        return await run_stage(state, stage, body)


async def _triage(prd: dict, architecture: dict, manifest: dict) -> set[str]:
    """Ask a cheap model which files deserve a close look.

    Returns an empty set to mean "review everything", which is what happens if the
    response cannot be parsed or names nothing we recognise.
    """
    known = set(manifest_util.qualified_paths(manifest))

    try:
        raw = await registry.allm_call(get_qa_triage_prompt(prd, architecture, manifest), Purpose.CHEAP)
        requested = {str(item).strip().lstrip("/") for item in extract_json_list(raw)}
    except Exception as exc:
        logger.warning("Triage failed (%s); reviewing every file instead", exc)
        return set()

    flagged = requested & known
    if not flagged:
        logger.warning("Triage named no known files; reviewing every file instead")
        return set()

    logger.info("Triage selected %d of %d file(s) for review", len(flagged), len(known))
    return flagged


def _review_tokens(prd: dict, architecture: dict, manifest: dict, code: str) -> int:
    """What one review call reserves against the per-minute window.

    Measured the way the meter will charge it: the prompt, plus the schema the
    lower structured-output rungs append (counted always, because any rung may be
    the one that runs), plus the output allowance every call holds.
    """
    settings = get_settings()
    messages = get_qa_prompt(prd, architecture, manifest, code)
    text = "\n".join(flatten_content(getattr(message, "content", message)) for message in messages)
    reserve = max(0, settings.llm_output_reserve, settings.max_output_for(Purpose.STRUCTURED))
    return estimate_tokens(text) + estimate_tokens(schema_instructions(QASchema)) + reserve


def _fit_review_to_budget(
    workspace: RunWorkspace, prd: dict, architecture: dict, manifest: dict, flagged: set[str]
) -> str:
    """The triaged code, trimmed until one review call fits the per-minute budget.

    A call larger than the whole window is refused outright, however long it
    waits. In a live run on Groq's free tier (8,000 tokens a minute) triage chose
    8 of 17 files, the review came to 9,567 tokens, and QA failed without making a
    call. Files are dropped from the end of the manifest order, which keeps the
    entrypoint and models the architecture lists first, until the call fits; at
    least one file is always kept, and a single file still too large is left for
    the budget to refuse with its own explanation.
    """
    ordered = [
        qualified
        for qualified in manifest_util.qualified_paths(manifest)
        if not flagged or qualified in flagged
    ]
    limit = get_settings().llm_tokens_per_minute
    selected = list(ordered)
    code = _collect_code(workspace, manifest, set(selected))

    if limit <= 0:
        return code

    while len(selected) > 1 and _review_tokens(prd, architecture, manifest, code) > limit:
        selected.pop()
        code = _collect_code(workspace, manifest, set(selected))

    if len(selected) < len(ordered):
        logger.info(
            "Reviewing %d of %d selected file(s) so one review call fits the %d-token per-minute budget",
            len(selected),
            len(ordered),
            limit,
        )
    return code


def _collect_code(workspace: RunWorkspace, manifest: dict, flagged: set[str]) -> str:
    chunks: list[str] = []
    budget = MAX_REVIEW_BYTES
    skipped = 0

    for slug, entry in manifest_util.iter_files(manifest):
        qualified = f"{slug}/{entry['file_path']}"
        if flagged and qualified not in flagged:
            continue

        try:
            content = workspace.read_source_file(slug, entry["file_path"])
        except (OSError, UnsafePathError) as exc:
            chunks.append(f"\n--- FILE: {qualified} (unreadable: {exc}) ---\n")
            continue

        if len(content) > budget:
            skipped += 1
            continue

        budget -= len(content)
        divider = "=" * 60
        chunks.append(f"\n{divider}\nFILE: {qualified}\n{divider}\n{content}\n")

    if skipped:
        logger.warning("Omitted %d file(s) from the review prompt to stay within budget", skipped)

    return "".join(chunks)


def _write_tests(report: dict, workspace: RunWorkspace) -> int:
    """Write the report's tests; returns the number of files written.

    Several cases often name the same file. Each used to overwrite the last: in a
    live run 11 cases became 4 files, each holding only its final case, which used
    a ``client`` the overwritten first case had set up, so every test failed with
    a NameError the developer was then asked to fix. Cases sharing a file are now
    joined in report order.
    """
    files: dict[tuple[str, str], list[str]] = {}

    for service in report.get("service_reports") or []:
        service_name = service.get("service_name") or "unnamed-service"

        for case in service.get("test_cases") or []:
            path = (case.get("test_file_path") or "").strip()
            code = case.get("test_code") or ""
            if not path or not code.strip():
                continue
            normalised = _normalise_test_path(path)
            files.setdefault((service_name, normalised), []).append(
                repair_escaped_newlines(normalised, code).strip("\n")
            )

    written = 0
    for (service_name, path), chunks in files.items():
        try:
            workspace.write_test_file(service_name, path, "\n\n\n".join(chunks) + "\n")
        except UnsafePathError as exc:
            logger.warning("Rejected test file path: %s", exc)
            continue
        if len(chunks) > 1:
            logger.info("Joined %d test cases into %s/%s", len(chunks), service_name, path)
        written += 1

    return written


def _normalise_test_path(path: str) -> str:
    """Drop a redundant leading ``tests/`` segment.

    Test files already live under the run's tests directory, so a model-supplied
    ``tests/test_auth.py`` would otherwise nest as ``tests/<service>/tests/...``.
    """
    cleaned = path.replace("\\", "/").lstrip("/")
    for prefix in ("tests/", "test/"):
        if cleaned.startswith(prefix):
            return cleaned[len(prefix) :] or "test_generated.py"
    return cleaned
