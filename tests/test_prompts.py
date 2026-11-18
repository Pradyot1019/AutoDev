"""How structured data is serialised into prompts.

Prompts carry whole PRDs and architecture documents. Pretty-printing them spent
468 tokens of whitespace on one PRD and 765 on one architecture document in a
measured run — against an 8,000 token-per-minute ceiling that the developer
stage had already broken. The content has to survive the change untouched, so
every test here checks the data as well as the formatting.
"""

from __future__ import annotations

import json
from pathlib import Path

from llm.registry import _prompt_text
from prompts.architect_json_prompt import get_architect_prompt
from prompts.architect_pdf_prompt import get_architecture_doc_prompt
from prompts.developer_json_prompt import get_developer_prompt
from prompts.developer_pdf_prompt import get_developer_doc_prompt
from prompts.pm_json_prompt import get_pm_prompt
from prompts.pm_pdf_prompt import get_pm_doc_prompt
from prompts.projections import (
    architecture_preamble,
    architecture_services,
    prd_for_architect,
    prd_for_developer,
)
from prompts.qa_json_prompt import get_qa_prompt
from prompts.qa_pdf_prompt import get_qa_doc_prompt
from prompts.qa_triage_prompt import get_qa_triage_prompt
from utils.json_utils import compact_json

REQUIREMENT = "Build an expense tracker."

PRD = {
    "product_name": "SpendWise",
    "features": [{"name": "Login", "priority": "high", "is_mvp": True}],
    "constraints": ["No third-party accounting integrations"],
    "open_questions": [],
    "complexity_estimate": "medium",
}

ARCHITECTURE = {
    "architecture_style": "modular_monolith",
    "system_overview": "One FastAPI service with a React frontend.",
    "services": [{"name": "backend", "tech_stack": ["Python", "FastAPI"], "dependencies": []}],
    "databases": [{"name": "app_db", "type": "postgres", "purpose": "Everything"}],
}

DEVELOPER = {
    "project_name": "SpendWise",
    "services": [{"service_name": "backend", "files": []}],
    "setup_instructions": ["pip install -r requirements.txt"],
}

QA = {"overall_assessment": "Reasonable.", "service_reports": [], "passed": True}

# Keyed by slug, the shape core/manifest.py produces.
MANIFEST = {
    "backend": {
        "display_name": "backend",
        "files": [{"file_path": "app/main.py", "description": "entry point", "language": "python"}],
    }
}


# ── The serialiser itself ────────────────────────────────────────


class TestCompactJson:
    def test_it_has_no_indentation_or_line_breaks(self):
        rendered = compact_json(PRD)
        assert "\n" not in rendered
        assert ": " not in rendered
        assert ", " not in rendered

    def test_the_content_survives_exactly(self):
        """Formatting only: what goes in must come back out unchanged."""
        assert json.loads(compact_json(PRD)) == PRD
        assert json.loads(compact_json(ARCHITECTURE)) == ARCHITECTURE

    def test_nested_structures_survive(self):
        nested = {"a": [{"b": {"c": [1, 2, {"d": None}]}}], "e": True}
        assert json.loads(compact_json(nested)) == nested

    def test_non_ascii_is_kept_rather_than_escaped(self):
        """A \\uXXXX escape is six characters where the character is one."""
        rendered = compact_json({"note": "café — naïve"})
        assert "café — naïve" in rendered
        assert "\\u" not in rendered
        assert json.loads(rendered) == {"note": "café — naïve"}

    def test_values_json_cannot_represent_become_strings(self):
        """A schema may carry a Path or a datetime; that must not raise."""
        rendered = compact_json({"where": Path("runs/abc")})
        assert json.loads(rendered)["where"] == str(Path("runs/abc"))

    def test_it_is_smaller_than_pretty_printing(self):
        assert len(compact_json(ARCHITECTURE)) < len(json.dumps(ARCHITECTURE, indent=2))


# ── The prompts that embed it ────────────────────────────────────


def _text(prompt) -> str:
    return _prompt_text(prompt)


class TestStructuredPromptsUseIt:
    """The exact compact string must appear, which proves both the formatting
    and that nothing was dropped on the way in."""

    def test_developer_prompt_embeds_the_projections_compactly(self):
        """It receives a projection of each document, not the whole thing."""
        text = _text(get_developer_prompt(REQUIREMENT, PRD, ARCHITECTURE))

        assert compact_json(prd_for_developer(PRD)) in text
        assert compact_json(architecture_preamble(ARCHITECTURE)) in text
        assert compact_json(architecture_services(ARCHITECTURE)) in text

    def test_developer_prompt_carries_no_pretty_printed_json(self):
        text = _text(get_developer_prompt(REQUIREMENT, PRD, ARCHITECTURE))
        assert json.dumps(PRD, indent=2) not in text
        assert json.dumps(ARCHITECTURE, indent=2) not in text

    def test_architect_prompt_embeds_the_projected_prd_compactly(self):
        text = _text(get_architect_prompt(REQUIREMENT, PRD))
        assert compact_json(prd_for_architect(PRD)) in text

    def test_architect_revision_embeds_the_previous_architecture_compactly(self):
        text = _text(
            get_architect_prompt(REQUIREMENT, PRD, ARCHITECTURE, feedback="Split the API")
        )
        assert compact_json(ARCHITECTURE) in text
        assert "Split the API" in text

    def test_pm_revision_embeds_the_previous_prd_compactly(self):
        text = _text(get_pm_prompt(REQUIREMENT, PRD, feedback="Add budget alerts"))
        assert compact_json(PRD) in text
        assert "Add budget alerts" in text

    def test_qa_prompt_embeds_both_documents_compactly(self):
        text = _text(get_qa_prompt(PRD, ARCHITECTURE, MANIFEST, "print('hi')"))
        assert compact_json(PRD) in text
        assert compact_json(ARCHITECTURE) in text

    def test_qa_triage_embeds_its_slices_compactly(self):
        """Triage sends a projection of each document plus the manifest paths."""
        text = get_qa_triage_prompt(PRD, ARCHITECTURE, MANIFEST)

        prd_slice = {k: PRD.get(k) for k in ("product_name", "features", "functional_requirements")}
        arch_slice = {k: ARCHITECTURE.get(k) for k in ("architecture_style", "services")}

        assert compact_json(prd_slice) in text
        assert compact_json(arch_slice) in text
        assert "backend/app/main.py" in text


class TestDocumentPromptsUseIt:
    def test_pm_document_prompt(self):
        assert compact_json(PRD) in _text(get_pm_doc_prompt(REQUIREMENT, PRD))

    def test_architecture_document_prompt(self):
        assert compact_json(PRD) in _text(get_architecture_doc_prompt(REQUIREMENT, PRD))

    def test_developer_document_prompt(self):
        assert compact_json(DEVELOPER) in _text(get_developer_doc_prompt(REQUIREMENT, DEVELOPER))

    def test_qa_document_prompt(self):
        assert compact_json(QA) in _text(get_qa_doc_prompt(QA))


class TestTheDataItselfIsStillReadable:
    """A smaller prompt is worthless if a value went missing."""

    def test_every_prd_value_still_appears_in_the_developer_prompt(self):
        text = _text(get_developer_prompt(REQUIREMENT, PRD, ARCHITECTURE))

        assert "SpendWise" in text
        assert "Login" in text
        assert "No third-party accounting integrations" in text
        assert "modular_monolith" in text
        assert "FastAPI" in text

    def test_the_embedded_json_parses_back_to_what_was_projected(self):
        text = _text(get_developer_prompt(REQUIREMENT, PRD, ARCHITECTURE))
        preamble = architecture_preamble(ARCHITECTURE)
        rendered = compact_json(preamble)

        start = text.index(rendered)
        assert json.loads(text[start : start + len(rendered)]) == preamble

    def test_the_services_survive_the_split_intact(self):
        """Splitting the architecture must not lose or reorder a service."""
        text = _text(get_developer_prompt(REQUIREMENT, PRD, ARCHITECTURE))
        rendered = compact_json(architecture_services(ARCHITECTURE))

        start = text.index(rendered)
        assert json.loads(text[start : start + len(rendered)]) == ARCHITECTURE["services"]


# ── A stable prefix, so providers can cache it ───────────────────

STATIC_FAILURE = {
    "ran": True,
    "passed": False,
    "failures": ["backend/app/main.py:3 SyntaxError: invalid syntax"],
}


class TestTheSystemMessageNeverChanges:
    """Providers discount a repeated prompt *prefix*. A retry or revision that
    altered the system message re-paid for everything after it."""

    def test_a_developer_retry_keeps_the_first_attempts_prefix(self):
        first = get_developer_prompt(REQUIREMENT, PRD, ARCHITECTURE)
        retry = get_developer_prompt(REQUIREMENT, PRD, ARCHITECTURE, static_report=STATIC_FAILURE)

        # System message and the requirement/PRD/architecture message are identical.
        assert retry[:2] == first[:2]
        # The fix-mode rules arrive with the evidence, at the end.
        assert "FIX MODE" not in _text(retry[:2])
        assert "FIX MODE" in _text(retry[2:]) and "SyntaxError" in _text(retry[2:])

    def test_a_pm_revision_keeps_the_first_drafts_prefix(self):
        first = get_pm_prompt(REQUIREMENT)
        revision = get_pm_prompt(REQUIREMENT, previous_prd=PRD, feedback="Add budgets.")

        assert revision[:2] == first[:2]
        assert "Add budgets." in _text(revision[2:])
        assert "REVISED PRD" in _text(revision[2:])

    def test_an_architecture_revision_keeps_the_first_drafts_prefix(self):
        first = get_architect_prompt(REQUIREMENT, PRD)
        revision = get_architect_prompt(
            REQUIREMENT, PRD, previous_architecture=ARCHITECTURE, feedback="Split auth out."
        )

        assert revision[:2] == first[:2]
        assert "Split auth out." in _text(revision[2:])


class TestQaIsAskedForRealCoverage:
    """A live run passed '1/1 tests' that never touched duplicates, bad input or
    the tag filter. Passing tests are only evidence if they cover the API."""

    def test_the_qa_prompt_requires_endpoint_and_error_coverage(self):
        from prompts.qa_json_prompt import SYSTEM_PROMPT

        for rule in ("TEST COVERAGE (REQUIRED)", "Every endpoint", "404", "409", "422", "two tests per endpoint"):
            assert rule in SYSTEM_PROMPT, rule

    def test_the_schema_no_longer_contradicts_the_prompt_on_paths(self):
        from schema.qa_schema import TestCase

        assert "tests/" not in TestCase.model_fields["test_file_path"].description.replace("no 'tests/' prefix", "")


class TestTheDeveloperIsNotAskedForOtherAgentsFiles:
    def test_scope_leaves_tests_and_deployment_to_other_agents(self):
        from prompts.developer_json_prompt import BASE_INSTRUCTIONS

        assert "except\n  tests, pytest configuration and deployment files" in BASE_INSTRUCTIONS
        assert "`__init__.py`" in BASE_INSTRUCTIONS
