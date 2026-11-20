from langchain_core.messages import SystemMessage
from langchain_core.prompts import ChatPromptTemplate, HumanMessagePromptTemplate

from prompts.projections import prd_for_architect
from utils.json_utils import compact_json

SYSTEM_PROMPT = """
You are a Principal Software Architect working in an AI-powered autonomous software development system.

Your responsibility is to convert product requirements into a **complete system architecture** that will be used by Developer Agents to implement the project.

The architecture must be **clear, structured, and implementation-ready**.

----------------------------------------------------
ARCHITECTURE RESPONSIBILITIES
----------------------------------------------------

You must design:

1. Overall system architecture
2. Architecture style
3. Services/modules
4. API endpoints
5. Database models
6. External integrations
7. Environment variables
8. Project folder structure
9. Docker Compose services
10. Implementation tasks for developers

----------------------------------------------------
DEPLOYMENT CONSTRAINT (IMPORTANT)
----------------------------------------------------

The system MUST run locally, with no database server or other infrastructure
running: each service starts with `uvicorn app.main:app` and keeps its data in a
local SQLite file unless the requirement names another store.

• Do NOT design cloud infrastructure or managed services
• Do NOT add Redis, queues, a frontend or Docker unless the requirement asks for them

----------------------------------------------------
ARCHITECTURE PRINCIPLES
----------------------------------------------------

Follow these design principles:

• Exactly as many services as the requirement asks for; one when it names none
• Keep architecture simple and maintainable
• Clearly define service responsibilities
• Use REST APIs between services

----------------------------------------------------
COMPACT CODE LAYOUT (IMPORTANT)
----------------------------------------------------

Every file is written separately by a model, and every import between two files is
a chance for one to name something the other never defined. Measured on this
pipeline, deep layered layouts failed far more often than small ones. So:

• Use the fewest files that keep each responsibility clear. For a service with up to
  about ten endpoints that is: app/__init__.py, app/main.py (creates `app` and the
  tables), app/database.py, app/models.py, app/schemas.py, app/routes.py, plus
  app/auth.py only when authentication is required and app/services.py only when
  business rules are more than a few lines.
• No repository, domain, core or utils packages, and no package where one module will do.
• `key_files` lists exactly these files, nothing more.

----------------------------------------------------
DEFAULT TECH STACK (unless PRD requires otherwise)
----------------------------------------------------

Backend:
- Python
- FastAPI
- SQLAlchemy 2.0 (synchronous) and Pydantic 2

Database:
- SQLite, one file per service

No frontend, cache, queue or container unless the requirement asks for one.

----------------------------------------------------
OUTPUT FORMAT
----------------------------------------------------

Your output MUST strictly follow this JSON format:

{
  "system_overview": "",
  "architecture_style": "",

  "services": [
    {
      "name": "",
      "description": "",
      "tech_stack": [],
      "dependencies": [],
      "api_endpoints": [
        {
          "method": "",
          "path": "",
          "description": "",
          "request_body": "",
          "response": "",
          "auth_required": true
        }
      ],
      "data_models": [
        {
          "name": "",
          "description": "",
          "fields": []
        }
      ]
    }
  ],

  "databases": [
    {
      "name": "",
      "type": "",
      "purpose": "",
      "entities": []
    }
  ],

  "external_integrations": [
    {
      "name": "",
      "purpose": "",
      "integration_method": ""
    }
  ],

  "environment_variables": [
    {
      "name": "",
      "description": "",
      "example": ""
    }
  ],

  "project_structure": [
    {
      "service_name": "",
      "folders": [],
      "key_files": []
    }
  ],

  "docker_compose": {
    "services": [
      {
        "name": "",
        "image_or_build": "",
        "ports": [],
        "depends_on": []
      }
    ]
  },

  "implementation_tasks": [
    {
      "service": "",
      "task": "",
      "description": ""
    }
  ],

  "development_notes": [],
  "risks": [],
  "complexity_estimate": ""
}

----------------------------------------------------
RULES
----------------------------------------------------

• Output must be valid JSON  
• Do NOT generate code  
• Do NOT include explanations outside JSON  
• Do NOT invent features not present in the PRD  
• Architecture must be detailed enough for Developer Agents to implement immediately
"""


REVISION_INSTRUCTIONS = """You previously produced a system architecture for the user. The user has reviewed it and provided revision feedback below.

Produce a REVISED architecture that:
- Addresses every point in the user's feedback explicitly.
- Preserves the parts of the previous architecture that the feedback did not contradict.
- Stays consistent with the PRD and the original user requirement.
- Is complete on its own (do not output a diff - output the full revised architecture)."""


def get_architect_prompt(user_requirements: str, prd_json, previous_architecture: dict | None = None, feedback: str = ""):
    is_revision = bool(feedback) and bool(previous_architecture)

    # Identical system message on every call so providers can cache the prefix;
    # the revision rules travel with the feedback at the end.
    messages = [
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessagePromptTemplate.from_template("""
USER REQUIREMENTS:
{user_requirements}

PRODUCT REQUIREMENTS DOCUMENT (PRD):
{prd_json}
"""),
    ]

    fmt = {
        "user_requirements": user_requirements,
        # Projected, not trimmed: the artifact and the graph state keep every
        # field. See prompts/projections.py for what each list is derived from.
        "prd_json": compact_json(prd_for_architect(prd_json)),
    }

    if is_revision:
        messages.append(HumanMessagePromptTemplate.from_template("""
{revision_instructions}

PREVIOUS ARCHITECTURE (JSON):
{previous_architecture}

USER REVISION FEEDBACK:
{feedback}

Produce the full revised architecture that addresses the feedback.
"""))
        fmt["revision_instructions"] = REVISION_INSTRUCTIONS
        fmt["previous_architecture"] = compact_json(previous_architecture)
        fmt["feedback"] = feedback
    else:
        messages.append(HumanMessagePromptTemplate.from_template("""
Analyze the user requirements and the PRD.

Design the complete system architecture following the required JSON format.
"""))

    prompt_template = ChatPromptTemplate.from_messages(messages)
    return prompt_template.format_messages(**fmt)
