"""Doubly escaped line breaks in generated files.

Live: requirements.txt arrived as one line of literal backslash-n, pip rejected it,
and no test ran on any of three attempts.
"""

from __future__ import annotations

from utils.content_repair import repair_escaped_newlines

LIVE_REQUIREMENTS = (
    "fastapi==0.110.0\\nuvicorn[standard]==0.27.0\\nSQLAlchemy==2.0.25\\n"
    "pydantic==2.6.1\\npython-dotenv==1.0.0\\n"
)


class TestRepaired:
    def test_the_live_requirements_file(self):
        repaired = repair_escaped_newlines("requirements.txt", LIVE_REQUIREMENTS)
        assert repaired.splitlines() == [
            "fastapi==0.110.0",
            "uvicorn[standard]==0.27.0",
            "SQLAlchemy==2.0.25",
            "pydantic==2.6.1",
            "python-dotenv==1.0.0",
        ]

    def test_python_that_only_parses_once_unescaped(self):
        code = "import os\\n\\ndef f():\\n\\treturn os.sep\\n"
        repaired = repair_escaped_newlines("app/main.py", code)
        assert repaired == "import os\n\ndef f():\n\treturn os.sep\n"

    def test_json_that_only_parses_once_unescaped(self):
        assert repair_escaped_newlines("package.json", '{\\n  "a": 1\\n}') == '{\n  "a": 1\n}'

    def test_windows_breaks_become_single_breaks(self):
        assert repair_escaped_newlines("a.txt", "x\\r\\ny\\r\\n") == "x\ny\n"


class TestLeftAlone:
    def test_a_file_with_real_line_breaks(self):
        code = 'print("a\\nb")\nprint("c")\n'
        assert repair_escaped_newlines("app/main.py", code) == code

    def test_a_one_line_python_file_whose_escape_is_meant(self):
        code = 'print("a\\nb\\nc")'
        assert repair_escaped_newlines("app/main.py", code) == code

    def test_compact_json_with_an_escaped_string(self):
        data = '{"note":"line one\\nline two\\nthree"}'
        assert repair_escaped_newlines("data.json", data) == data

    def test_a_single_escaped_break_in_other_text(self):
        assert repair_escaped_newlines("notes.txt", "a\\nb") == "a\\nb"

    def test_content_with_no_escapes(self):
        assert repair_escaped_newlines("requirements.txt", "fastapi") == "fastapi"
