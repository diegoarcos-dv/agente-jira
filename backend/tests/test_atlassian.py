from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.atlassian import (
    AtlassianIntegrationManager,
    OAuthAttempt,
    VISIBLE_PROJECTS_MAX_RESULTS,
    WriteToolBlocked,
    _extract_sprints,
    _is_explicit_jira_create_rejection,
    call_read_only_tool,
)
from app.oauth_storage import EncryptedFileOAuthStorage
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
import app.atlassian as atlassian_module


class FakeResult:
    def __init__(self, payload: Any):
        self.structuredContent = payload
        self.content = []
        self.isError = False


class RecordingSession:
    def __init__(self):
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def call_tool(self, name: str, arguments: dict[str, Any]):
        self.calls.append((name, arguments))
        if name == "atlassianUserInfo":
            return FakeResult({"accountId": "account-1", "displayName": "Usuario Jira"})
        if name == "getAccessibleAtlassianResources":
            return FakeResult(
                [{"id": "cloud-123", "url": "https://dpti.atlassian.net", "name": "DPTI"}]
            )
        if name == "getVisibleJiraProjects":
            return FakeResult(
                {
                    "values": [
                        {"id": "100", "key": "AT", "name": "AT", "projectTypeKey": "software"},
                        {"id": "200", "key": "ASIT", "name": "ASIT"},
                        {"id": "300", "key": "MTTI", "name": "MTTI"},
                    ]
                }
            )
        if name == "getJiraProjectIssueTypesMetadata":
            return FakeResult({"issueTypes": [{"id": "10", "name": "Task", "subtask": False}]})
        if name == "getJiraIssueTypeMetaWithFields":
            return FakeResult(
                {
                    "fields": [
                        {"fieldId": "summary", "name": "Summary", "required": True},
                        {
                            "fieldId": "assignee",
                            "name": "Assignee",
                            "required": False,
                            "allowedValues": [{"accountId": "assignable-1"}],
                        },
                        {
                            "fieldId": "customfield_10483",
                            "name": "Tipo de seguimiento",
                            "required": False,
                            "allowedValues": [
                                {"id": "1", "value": "Semanal"},
                                {"id": "2", "value": "Mensual"},
                            ],
                        },
                    ]
                }
            )
        raise AssertionError(f"Unexpected tool call: {name}")


def tool(name: str, properties: dict[str, Any] | None = None):
    return SimpleNamespace(name=name, inputSchema={"properties": properties or {}})


class ReversibleTestProtector:
    def protect(self, value: bytes) -> bytes:
        return b"TEST-ENCRYPTED:" + value[::-1]

    def unprotect(self, value: bytes) -> bytes:
        assert value.startswith(b"TEST-ENCRYPTED:")
        return value.removeprefix(b"TEST-ENCRYPTED:")[::-1]


def test_oauth_storage_persists_encrypted_tokens_and_can_be_cleared(tmp_path):
    protector = ReversibleTestProtector()
    storage = EncryptedFileOAuthStorage(tmp_path, "admin@example.com", protector)
    asyncio.run(
        storage.set_client_info(
            OAuthClientInformationFull(
                redirect_uris=["http://localhost/callback"],
                client_id="dynamic-client",
            )
        )
    )
    asyncio.run(
        storage.set_tokens(
            OAuthToken(
                access_token="access-secret",
                refresh_token="refresh-secret",
                token_type="Bearer",
            )
        )
    )

    encrypted = storage.path.read_bytes()
    assert b"access-secret" not in encrypted
    assert b"refresh-secret" not in encrypted

    recovered = EncryptedFileOAuthStorage(tmp_path, "admin@example.com", protector)
    assert recovered.has_credentials is True
    assert asyncio.run(recovered.get_tokens()).refresh_token == "refresh-secret"
    assert asyncio.run(recovered.get_client_info()).client_id == "dynamic-client"

    recovered.clear()
    assert recovered.path.exists() is False


@pytest.mark.parametrize(
    "write_tool",
    [
        "addCommentToJiraIssue",
        "addWorklogToJiraIssue",
        "createJiraIssue",
        "editJiraIssue",
        "transitionJiraIssue",
    ],
)
def test_every_official_jira_write_tool_is_blocked_before_transport_is_called(
    write_tool: str,
):
    session = RecordingSession()

    with pytest.raises(WriteToolBlocked):
        asyncio.run(
            call_read_only_tool(
                session,
                write_tool,
                {"cloudId": "cloud-123", "summary": "Nunca debe crearse"},
            )
        )

    assert session.calls == []


def test_explicit_jira_bad_request_is_not_classified_as_ambiguous_transport():
    rejection = RuntimeError(
        'Failed to create issue: Bad Request. {"errors":{"customfield_10020":"Specify a valid value for Sprint"}}'
    )
    interruption = TimeoutError("Connection closed after request")

    assert _is_explicit_jira_create_rejection(rejection) is True
    assert _is_explicit_jira_create_rejection(interruption) is False


def test_sprints_are_extracted_from_modern_and_legacy_jira_payloads():
    payload = {
        "issues": [
            {"fields": {"customfield_10020": [{
                "id": 321,
                "name": "SPT-ACTIVO",
                "state": "active",
                "boardId": 45,
            }]}},
            {"fields": {"customfield_10020": (
                "com.atlassian.greenhopper.service.sprint.Sprint@x"
                "[id=322,rapidViewId=45,state=FUTURE,name=SPT-FUTURO,startDate=<null>]"
            )}},
        ]
    }

    result = _extract_sprints(payload, {"customfield_10020"}, "active")

    assert result == [
        {"id": "321", "name": "SPT-ACTIVO", "state": "active", "board_id": 45, "source": "ROVO_MCP_JQL"},
        {"id": "322", "name": "SPT-FUTURO", "state": "future", "board_id": "45", "source": "ROVO_MCP_JQL"},
    ]


def test_sprint_catalog_uses_rovo_jql_and_five_minute_cache(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
):
    manager: AtlassianIntegrationManager = client.app.state.atlassian_manager
    attempt = OAuthAttempt(username="tester", connected=True)
    attempt.snapshot = {
        "cloud_id": "cloud-123",
        "spaces": [{
            "key": "AT",
            "work_types": [{
                "fields": [{
                    "id": "customfield_10020",
                    "name": "Sprint",
                    "business_key": "sprint",
                }],
            }],
        }],
    }
    attempt.available_tools = {
        "searchJiraIssuesUsingJql": tool("searchJiraIssuesUsingJql", {
            "cloudId": {}, "jql": {}, "fields": {}, "maxResults": {}, "nextPageToken": {},
        }),
    }
    manager._attempts["tester"] = attempt
    calls: list[dict[str, Any]] = []

    async def fake_invoke(_attempt, name: str, values: dict[str, Any]):
        assert name == "searchJiraIssuesUsingJql"
        calls.append(values)
        active = "openSprints" in values["jql"]
        return {"issues": [{"fields": {"customfield_10020": [{
            "id": "321" if active else "322",
            "name": "SPT-ACTIVO" if active else "SPT-FUTURO",
            "state": "active" if active else "future",
            "boardId": "45",
        }]}}]}

    monkeypatch.setattr(manager, "_invoke", fake_invoke)

    first = asyncio.run(manager.list_sprints("tester", "AT"))
    cached = asyncio.run(manager.list_sprints("tester", "AT"))
    refreshed = asyncio.run(manager.list_sprints("tester", "AT", force_refresh=True))

    assert [sprint["id"] for sprint in first] == ["321", "322"]
    assert cached == first == refreshed
    assert len(calls) == 4
    assert all(call["fields"] == ["customfield_10020"] for call in calls)


def test_controlled_gateway_invokes_one_create_then_one_readback(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
):
    manager: AtlassianIntegrationManager = client.app.state.atlassian_manager
    attempt = OAuthAttempt(username="tester", connected=True)
    attempt.provider = object()
    attempt.snapshot = {"cloud_id": "cloud-123", "spaces": [{"key": "AT", "id": "100"}]}
    manager._attempts["tester"] = attempt
    calls: list[tuple[str, dict[str, Any]]] = []

    class FakeHttpClient:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

    class FakeControlledSession:
        def __init__(self, *_args):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def initialize(self):
            return None

        async def list_tools(self):
            create_properties = {
                key: {}
                for key in (
                    "cloudId", "projectKey", "issueTypeName", "summary", "description",
                    "assignee_account_id", "additional_fields", "contentFormat",
                    "responseContentFormat",
                )
            }
            return SimpleNamespace(tools=[
                tool("createJiraIssue", create_properties),
                tool("getJiraIssue", {
                    "cloudId": {}, "issueIdOrKey": {}, "fields": {},
                    "fieldsByKeys": {}, "responseContentFormat": {},
                }),
            ])

        async def call_tool(self, name: str, arguments: dict[str, Any]):
            calls.append((name, arguments))
            if name == "createJiraIssue":
                return FakeResult({"key": "AT-9001"})
            if name == "getJiraIssue":
                return FakeResult({
                    "key": "AT-9001",
                    "fields": {
                        "summary": "AgenteTest_Task_Prueba",
                        "project": {"key": "AT"},
                        "issuetype": {"name": "Task"},
                        "assignee": {"accountId": "jira-jose"},
                    },
                })
            raise AssertionError(name)

    @asynccontextmanager
    async def fake_streamable(*_args, **_kwargs):
        yield object(), object(), None

    async def restored(_username: str):
        return True

    monkeypatch.setattr(manager, "ensure_restored", restored)
    monkeypatch.setattr(atlassian_module.httpx, "AsyncClient", FakeHttpClient)
    monkeypatch.setattr(atlassian_module, "streamable_http_client", fake_streamable)
    monkeypatch.setattr(atlassian_module, "ClientSession", FakeControlledSession)

    result = asyncio.run(manager.create_single_task_and_readback(
        "tester",
        {
            "cloudId": "cloud-123",
            "projectKey": "AT",
            "issueTypeName": "Task",
            "summary": "AgenteTest_Task_Prueba",
            "description": "Prueba controlada",
            "assignee_account_id": "jira-jose",
            "additional_fields": {"labels": ["agente-test"]},
            "contentFormat": "markdown",
            "responseContentFormat": "markdown",
        },
        ["summary", "project", "issuetype", "assignee"],
        10,
    ))

    assert [name for name, _ in calls] == ["createJiraIssue", "getJiraIssue"]
    assert calls[0][1]["assignee_account_id"] == "jira-jose"
    assert calls[1][1]["issueIdOrKey"] == "AT-9001"
    assert result["issue_key"] == "AT-9001"
    assert result["real_mcp_calls"] == 2


def test_exception_group_is_flattened_and_oauth_values_are_redacted(client: TestClient):
    manager: AtlassianIntegrationManager = client.app.state.atlassian_manager
    grouped = ExceptionGroup(
        "task group failed",
        [
            ValueError(
                "callback failed?code=secret-code&state=secret-state "
                "access_token=secret-token"
            )
        ],
    )

    message = manager._safe_error(grouped, "MCP_INITIALIZE")

    assert "MCP_INITIALIZE" in message
    assert "ValueError" in message
    assert "secret-code" not in message
    assert "secret-state" not in message
    assert "secret-token" not in message
    assert "[REDACTED]" in message


def test_discovery_reads_only_target_site_and_spaces(client: TestClient):
    manager: AtlassianIntegrationManager = client.app.state.atlassian_manager
    attempt = OAuthAttempt(username="tester")
    attempt.available_tools = {
        name: tool(name, properties)
        for name, properties in {
            "atlassianUserInfo": {},
            "getAccessibleAtlassianResources": {},
            "getVisibleJiraProjects": {"cloudId": {}, "maxResults": {}},
            "getJiraProjectIssueTypesMetadata": {"cloudId": {}, "projectIdOrKey": {}},
            "getJiraIssueTypeMetaWithFields": {
                "cloudId": {},
                "projectIdOrKey": {},
                "issueTypeId": {},
            },
        }.items()
    }
    session = RecordingSession()

    snapshot = asyncio.run(manager._discover_with_session(attempt, session))

    assert snapshot["cloud_id"] == "cloud-123"
    assert [space["key"] for space in snapshot["spaces"]] == ["AT", "ASIT", "MTTI"]
    assert all(space["found"] for space in snapshot["spaces"])
    assert snapshot["spaces"][0]["work_types"][0]["name"] == "Task"
    assert snapshot["spaces"][0]["work_types"][0]["fields"][0]["id"] == "summary"
    assert attempt.assignee_allowed_accounts["AT:10"] == {"assignable-1"}
    assert "allowedValues" not in snapshot["spaces"][0]["work_types"][0]["fields"][1]
    business_field = snapshot["spaces"][0]["work_types"][0]["fields"][2]
    assert business_field["business_key"] == "tipo_seguimiento"
    assert business_field["options"] == [
        {"value": "Semanal", "label": "Semanal", "jira_id": "1"},
        {"value": "Mensual", "label": "Mensual", "jira_id": "2"},
    ]
    assert "allowedValues" not in business_field
    visible_projects_calls = [
        arguments
        for name, arguments in session.calls
        if name == "getVisibleJiraProjects"
    ]
    assert visible_projects_calls == [
        {"cloudId": "cloud-123", "maxResults": VISIBLE_PROJECTS_MAX_RESULTS}
    ]
    assert VISIBLE_PROJECTS_MAX_RESULTS <= 50
    assert {name for name, _ in session.calls}.issubset(
        {
            "atlassianUserInfo",
            "getAccessibleAtlassianResources",
            "getVisibleJiraProjects",
            "getJiraProjectIssueTypesMetadata",
            "getJiraIssueTypeMetaWithFields",
        }
    )


def test_assignee_lookup_keeps_only_an_exact_active_match(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
):
    manager: AtlassianIntegrationManager = client.app.state.atlassian_manager
    attempt = OAuthAttempt(username="tester", connected=True)
    attempt.snapshot = {
        "cloud_id": "cloud-123",
        "spaces": [{"key": "AT", "id": "100"}],
    }
    attempt.available_tools = {
        "lookupJiraAccountId": tool(
            "lookupJiraAccountId",
            {"cloudId": {}, "searchString": {}},
        )
    }
    manager._attempts["tester"] = attempt

    async def fake_invoke(_attempt, _name, _values):
        return {
            "users": [
                {"accountId": "exact", "displayName": "José Calleja", "active": True},
                {"accountId": "near", "displayName": "Jose Gil Navarrete M", "active": True},
                {"accountId": "inactive", "displayName": "José Calleja", "active": False},
            ]
        }

    monkeypatch.setattr(manager, "_invoke", fake_invoke)

    result = asyncio.run(manager.find_assignees("tester", "AT", "Jose Calleja"))

    assert [user["account_id"] for user in result] == ["exact"]


class FakeManager:
    def __init__(self):
        self.connected = False

    def status(self, _username: str):
        return {
            "connected": self.connected,
            "phase": "CONNECTED" if self.connected else "DISCONNECTED",
            "oauth_storage": "MEMORY_ONLY",
            "jira_write_enabled": False,
            "write_tools_blocked": True,
            "snapshot": {"cloud_id": "cloud-123"} if self.connected else None,
        }

    async def begin_connect(self, _username: str):
        return {
            "authorization_url": "https://auth.atlassian.example/authorize?state=state-123",
            "phase": "AWAITING_USER_CONSENT",
        }

    async def finish_callback(self, code: str, state: str):
        assert code == "code-123"
        assert state == "state-123"
        self.connected = True
        return self.status("tester")

    async def disconnect(self, _username: str):
        self.connected = False

    async def refresh(self, username: str):
        return self.status(username)

    async def find_assignees(self, _username: str, space: str, query: str):
        assert space == "AT"
        assert query == "Giselle"
        return [{"account_id": "jira-1", "display_name": "Giselle Bello", "active": True}]


def test_oauth_routes_are_per_user_and_do_not_expose_tokens(
    client: TestClient,
    auth_headers: dict[str, str],
):
    manager = FakeManager()
    client.app.state.atlassian_manager = manager

    unauthorized = client.get("/api/integrations/atlassian/status")
    assert unauthorized.status_code == 401

    connect = client.post("/api/integrations/atlassian/connect", headers=auth_headers)
    assert connect.status_code == 200
    assert connect.json()["authorization_url"].startswith("https://auth.atlassian.example/")

    callback = client.get(
        "/api/integrations/atlassian/callback?code=code-123&state=state-123",
        follow_redirects=False,
    )
    assert callback.status_code == 303
    assert callback.headers["location"] == "/?atlassian=connected"

    status = client.get("/api/integrations/atlassian/status", headers=auth_headers)
    assert status.status_code == 200
    assert status.json()["connected"] is True
    serialized = status.text.lower()
    assert "access_token" not in serialized
    assert "refresh_token" not in serialized
    assert status.json()["jira_write_enabled"] is False

    assignees = client.get(
        "/api/integrations/atlassian/assignees?space=AT&q=Giselle",
        headers=auth_headers,
    )
    assert assignees.status_code == 200
    assert assignees.json()[0]["account_id"] == "jira-1"

    disconnected = client.post(
        "/api/integrations/atlassian/disconnect",
        headers=auth_headers,
    )
    assert disconnected.status_code == 200
    assert disconnected.json()["connected"] is False
