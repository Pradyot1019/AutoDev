"""AgentForge test harness — the application must import, whatever else is tested.

Live: QA's two tests checked only the Pydantic schemas, both passed, and the app
itself crashed on import. Written by the pipeline, not part of the project.
"""


def test_the_application_imports(app):
    assert app is not None
