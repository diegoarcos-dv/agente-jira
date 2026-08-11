from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


Space = Literal["AT", "ASIT", "MTTI"]
Decision = Literal["INCLUIR", "REVISAR", "EXCLUIR"]
WorkType = Literal["Epic", "Story", "Task", "Bug", "Subtask"]


class LoginRequest(BaseModel):
    username: str
    password: str


class SessionResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    user: dict[str, str]


class PlanDefaults(BaseModel):
    model_config = ConfigDict(extra="forbid")

    space: Space
    iniciativa: str | None = None
    linea_trabajo: str | None = None
    sprint: str | None = None
    tipo_seguimiento: str | None = None
    semaforo: str | None = None


class ProposalDefaultsUpdate(PlanDefaults):
    """Complete replacement of the plan-level values for a new proposal version."""

    pass


class ItemUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1)
    description: str | None = Field(default=None, min_length=1)
    work_type: WorkType | None = None
    decision: Decision | None = None
    decision_reason: str | None = Field(default=None, min_length=1)
    review_note: str | None = None
    assignee_account_id: str | None = None
    assignee_query: str | None = Field(default=None, min_length=2, max_length=200)
    parent_row_id: str | None = Field(default=None, pattern=r"^ROW-[0-9]{4,}$")
    confirm_source_state: bool = False
    confirm_work_type: bool = False
    confirm_reactivation: bool = False


class ProposalMetadataUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str = Field(min_length=1, max_length=120)


class ReactivationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=5, max_length=500)


class JiraAssigneeSelectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    account_id: str = Field(min_length=1, max_length=200)
    query: str = Field(min_length=2, max_length=200)


class JiraSimulationPrepareRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    row_id: str = Field(min_length=1, max_length=100)


class JiraSimulationConfirmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    payload_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    confirmed: Literal[True]


class JiraRealConfirmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    payload_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    confirmation_phrase: str = Field(min_length=1, max_length=100)


class JiraBatchPrepareRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    row_ids: list[str] = Field(min_length=1, max_length=5)


class JiraBatchConfirmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    payload_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    confirmation_phrase: str = Field(min_length=1, max_length=100)


class ProposalSummary(BaseModel):
    proposal_id: str
    version: int
    status: str
    source_file: str
    display_name: str
    space: Space
    counts: dict[str, int]
    created_at: str | None = None
    archived: bool = False
    archived_at: str | None = None
    archived_by: str | None = None
    display_name_updated_at: str | None = None
    display_name_updated_by: str | None = None
