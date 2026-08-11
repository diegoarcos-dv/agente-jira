from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
PROJECT_DIR = BACKEND_DIR.parent


@dataclass(frozen=True)
class Settings:
    database_path: Path
    schema_path: Path
    frontend_dist: Path
    frozen_template_path: Path
    local_user: str
    local_password: str
    atlassian_mcp_url: str = "https://mcp.atlassian.com/v1/mcp/authv2"
    atlassian_site_url: str = "https://dpti.atlassian.net"
    atlassian_oauth_callback_url: str = (
        "http://localhost:8000/api/integrations/atlassian/callback"
    )
    atlassian_oauth_storage_dir: Path | None = None
    jira_execution_policy_path: Path = PROJECT_DIR / "config" / "jira_execution_policy_v1.json"
    jira_execution_policy_schema_path: Path = (
        PROJECT_DIR / "docs" / "schemas" / "jira_execution_policy_v1.schema.json"
    )


def get_settings() -> Settings:
    database_path = Path(
        os.getenv("AGENTE_JIRA_DB", str(BACKEND_DIR / "data" / "agente_jira.db"))
    )
    return Settings(
        database_path=database_path,
        schema_path=PROJECT_DIR / "docs" / "schemas" / "jira_proposal_v1_1.schema.json",
        frontend_dist=PROJECT_DIR / "frontend" / "dist",
        frozen_template_path=(
            PROJECT_DIR
            / "releases"
            / "plantilla_excel_v1_1"
            / "plantilla_plan_trabajo_jira_v1_1.xlsx"
        ),
        local_user=os.getenv("AGENTE_JIRA_LOCAL_USER", "admin@agentejira.local"),
        local_password=os.getenv("AGENTE_JIRA_LOCAL_PASSWORD", "AgenteJira2026!"),
        atlassian_mcp_url=os.getenv(
            "AGENTE_JIRA_ATLASSIAN_MCP_URL",
            "https://mcp.atlassian.com/v1/mcp/authv2",
        ),
        atlassian_site_url=os.getenv(
            "AGENTE_JIRA_ATLASSIAN_SITE_URL",
            "https://dpti.atlassian.net",
        ),
        atlassian_oauth_callback_url=os.getenv(
            "AGENTE_JIRA_ATLASSIAN_CALLBACK_URL",
            "http://localhost:8000/api/integrations/atlassian/callback",
        ),
        atlassian_oauth_storage_dir=Path(
            os.getenv(
                "AGENTE_JIRA_ATLASSIAN_OAUTH_DIR",
                str(BACKEND_DIR / "data" / "atlassian_oauth"),
            )
        ),
        jira_execution_policy_path=Path(
            os.getenv(
                "AGENTE_JIRA_EXECUTION_POLICY",
                str(PROJECT_DIR / "config" / "jira_execution_policy_v1.json"),
            )
        ),
        jira_execution_policy_schema_path=(
            PROJECT_DIR / "docs" / "schemas" / "jira_execution_policy_v1.schema.json"
        ),
    )
