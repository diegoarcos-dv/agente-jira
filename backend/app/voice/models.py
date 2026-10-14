from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

VoiceCommandStatus = Literal[
    "completed",
    "needs_clarification",
    "awaiting_confirmation",
    "blocked",
    "validation_error",
    "execution_error",
    "unknown_result",
    "cancelled",
]
VoiceArgument = str | int | float | bool | None
VoiceDraftStatus = Literal["draft", "cancelled"]
VoicePendingQuestion = Literal["assignee", "priority", "review"]
VoiceCommandRisk = Literal["READ_ONLY", "LOCAL_WRITE", "JIRA_WRITE", "FORBIDDEN"]
VoiceJiraState = Literal[
    "PREPARING_JIRA",
    "AWAITING_CONFIRMATION",
    "CREATING_JIRA",
    "VERIFYING_JIRA",
    "SUCCESS",
    "VALIDATION_ERROR",
    "EXECUTION_ERROR",
    "UNKNOWN_RESULT",
    "CANCELLED",
]
VoiceComponentState = Literal["DISABLED", "NOT_LOADED", "LOADING", "READY", "ERROR"]
VoiceOverallState = Literal["DISABLED", "NOT_STARTED", "LOADING", "READY", "PARTIAL", "ERROR"]


class VoiceIntent(BaseModel):
    """Untrusted model output. It never carries executable code or tool calls."""

    model_config = ConfigDict(extra="forbid")

    intent: str = Field(min_length=1, max_length=80, pattern=r"^[a-z][a-z0-9_]*$")
    arguments: dict[str, VoiceArgument] = Field(default_factory=dict)
    confidence: float = Field(ge=0.0, le=1.0)


class VoiceDraftAssignee(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str = Field(min_length=1, max_length=200)
    account_id: str = Field(min_length=1, max_length=200)
    email: str | None = Field(default=None, max_length=320)


class VoiceTaskDraft(BaseModel):
    """Local-only task draft. It is never a Jira or MCP payload."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^VOICE-DRAFT-[A-F0-9]{12}$")
    issue_type: Literal["Epic", "Story", "Task", "Bug", "Subtask"] = "Task"
    summary: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=4000)
    assignee: VoiceDraftAssignee | None = None
    priority: Literal["Highest", "High", "Medium", "Low", "Lowest"] | None = None
    space: Literal["AT", "ASIT", "MTTI"] = "AT"
    parent_issue_key: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]*-[1-9][0-9]*$")
    status: VoiceDraftStatus = "draft"


class VoiceJiraPreview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    issue_type: str
    summary: str
    description: str | None = None
    assignee: str | None = None
    priority: str | None = None
    space: str
    parent: str | None = None
    fields_valid: bool = True
    user_valid: bool = True
    jira_available: bool = True


class VoicePendingConfirmation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["cancel_current_draft", "create_jira_issue"]
    confirmation_id: str = Field(min_length=1, max_length=80)
    execution_id: str | None = Field(default=None, max_length=80)
    draft_id: str
    payload_hash: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    created_at: str
    expires_at: str
    preview: VoiceJiraPreview | None = None


class VoiceJiraOperationView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    execution_id: str
    state: VoiceJiraState
    payload_hash: str
    preview: VoiceJiraPreview
    issue_key: str | None = None
    issue_url: str | None = None
    readback_checks: dict[str, bool] = Field(default_factory=dict)
    create_elapsed_ms: float | None = None
    readback_elapsed_ms: float | None = None
    reused: bool = False


class VoiceConversationContext(BaseModel):
    """Bounded application-owned state. It contains no audio, prompts, or secrets."""

    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(min_length=1, max_length=128)
    username: str = Field(min_length=1, max_length=320)
    active_proposal_id: str | None = Field(default=None, max_length=128)
    active_activity_id: str | None = Field(default=None, max_length=128)
    active_draft_id: str | None = Field(default=None, max_length=64)
    last_intent: str | None = Field(default=None, max_length=80)
    pending_question: VoicePendingQuestion | None = None
    pending_confirmation: VoicePendingConfirmation | None = None
    selected_items: list[str] = Field(default_factory=list, max_length=20)
    assignee_candidates: list[VoiceDraftAssignee] = Field(default_factory=list, max_length=5)
    draft: VoiceTaskDraft | None = None
    updated_at: str
    expires_at: str

    def safe_for_model(self) -> dict[str, object]:
        draft = None
        if self.draft and self.draft.status == "draft":
            draft = self.draft.model_dump(exclude={"assignee": {"account_id", "email"}})
        return {
            "active_proposal_id": self.active_proposal_id,
            "active_activity_id": self.active_activity_id,
            "active_draft": draft,
            "last_intent": self.last_intent,
            "pending_question": self.pending_question,
            "pending_confirmation": (
                {"action": self.pending_confirmation.action}
                if self.pending_confirmation
                else None
            ),
            "selected_items": self.selected_items,
        }


class VoiceContextView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    active_proposal_id: str | None = None
    active_activity_id: str | None = None
    active_draft_id: str | None = None
    last_intent: str | None = None
    pending_question: VoicePendingQuestion | None = None
    pending_confirmation: VoicePendingConfirmation | None = None
    draft: VoiceTaskDraft | None = None
    expires_at: str

    @classmethod
    def from_context(cls, context: VoiceConversationContext) -> VoiceContextView:
        return cls.model_validate(
            context.model_dump(
                include={
                    "active_proposal_id",
                    "active_activity_id",
                    "active_draft_id",
                    "last_intent",
                    "pending_question",
                    "pending_confirmation",
                    "draft",
                    "expires_at",
                }
            )
        )


class VoiceCommandResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    transcript: str
    intent: str
    status: VoiceCommandStatus
    message: str
    requires_confirmation: bool = False
    risk: VoiceCommandRisk = "READ_ONLY"
    draft: VoiceTaskDraft | None = None
    context: VoiceContextView | None = None
    jira_operation: VoiceJiraOperationView | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
    )
    audio_available: bool = False
    audio_base64: str | None = None
    audio_mime_type: Literal["audio/wav"] | None = None
    audio_error: str | None = Field(default=None, exclude_if=lambda value: value is None)


class VoiceComponentStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Literal["STT", "LLM", "TTS"]
    state: VoiceComponentState
    enabled: bool
    configuration: str
    available: bool | None = None
    detail: str
    provider: str | None = None
    model: str | None = None


class VoiceStatusResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    state: VoiceOverallState
    activated: bool
    message: str
    stt: VoiceComponentStatus
    llm: VoiceComponentStatus
    tts: VoiceComponentStatus


class TranscriptionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=4000)
    duration_seconds: float = Field(ge=0.0)


class VoiceJiraConfirmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirmation_id: str = Field(min_length=1, max_length=80)
    payload_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    spoken_response: bool = False


class VoiceJiraCancelRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirmation_id: str = Field(min_length=1, max_length=80)
    payload_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    spoken_response: bool = False
