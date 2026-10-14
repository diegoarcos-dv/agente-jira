export type VoiceUiState =
  | "idle"
  | "listening"
  | "transcribing"
  | "thinking"
  | "executing"
  | "preparing_jira"
  | "awaiting_confirmation"
  | "creating_jira"
  | "verifying_jira"
  | "speaking"
  | "success"
  | "error"
  | "validation_error"
  | "execution_error"
  | "unknown_result"
  | "cancelled";

export type VoiceComponentState = "DISABLED" | "NOT_LOADED" | "LOADING" | "READY" | "ERROR";
export type VoiceOverallState = "DISABLED" | "NOT_STARTED" | "LOADING" | "READY" | "PARTIAL" | "ERROR";

export interface VoiceComponentStatus {
  name: "STT" | "LLM" | "TTS";
  state: VoiceComponentState;
  enabled: boolean;
  configuration: string;
  available: boolean | null;
  detail: string;
  provider: string | null;
  model: string | null;
}

export interface VoiceStatusView {
  state: VoiceOverallState;
  activated: boolean;
  message: string;
  stt: VoiceComponentStatus;
  llm: VoiceComponentStatus;
  tts: VoiceComponentStatus;
}

export interface VoiceDraftAssignee {
  display_name: string;
  account_id: string;
  email: string | null;
}

export interface VoiceTaskDraft {
  id: string;
  issue_type: "Epic" | "Story" | "Task" | "Bug" | "Subtask";
  summary: string;
  description: string | null;
  assignee: VoiceDraftAssignee | null;
  priority: "Highest" | "High" | "Medium" | "Low" | "Lowest" | null;
  space: "AT" | "ASIT" | "MTTI";
  parent_issue_key?: string | null;
  status: "draft" | "cancelled";
}

export interface VoiceJiraPreview {
  issue_type: string;
  summary: string;
  description: string | null;
  assignee: string | null;
  priority: string | null;
  space: string;
  parent: string | null;
  fields_valid: boolean;
  user_valid: boolean;
  jira_available: boolean;
}

export interface VoicePendingConfirmation {
  action: "cancel_current_draft" | "create_jira_issue";
  confirmation_id: string;
  execution_id: string | null;
  draft_id: string;
  payload_hash: string | null;
  created_at: string;
  expires_at: string;
  preview: VoiceJiraPreview | null;
}

export interface VoiceJiraOperation {
  execution_id: string;
  state:
    | "PREPARING_JIRA"
    | "AWAITING_CONFIRMATION"
    | "CREATING_JIRA"
    | "VERIFYING_JIRA"
    | "SUCCESS"
    | "VALIDATION_ERROR"
    | "EXECUTION_ERROR"
    | "UNKNOWN_RESULT"
    | "CANCELLED";
  payload_hash: string;
  preview: VoiceJiraPreview;
  issue_key: string | null;
  issue_url: string | null;
  readback_checks: Record<string, boolean>;
  create_elapsed_ms: number | null;
  readback_elapsed_ms: number | null;
  reused: boolean;
}

export interface VoiceContextView {
  active_proposal_id: string | null;
  active_activity_id: string | null;
  active_draft_id: string | null;
  last_intent: string | null;
  pending_question: "assignee" | "priority" | "review" | null;
  pending_confirmation: VoicePendingConfirmation | null;
  draft: VoiceTaskDraft | null;
  expires_at: string;
}

export interface VoiceCommandResponse {
  transcript: string;
  intent: string;
  status:
    | "completed"
    | "needs_clarification"
    | "awaiting_confirmation"
    | "blocked"
    | "validation_error"
    | "execution_error"
    | "unknown_result"
    | "cancelled";
  message: string;
  requires_confirmation: boolean;
  risk: "READ_ONLY" | "LOCAL_WRITE" | "JIRA_WRITE" | "FORBIDDEN";
  draft: VoiceTaskDraft | null;
  context: VoiceContextView | null;
  jira_operation?: VoiceJiraOperation | null;
  audio_available: boolean;
  audio_base64: string | null;
  audio_mime_type: "audio/wav" | null;
  audio_error?: string | null;
}
