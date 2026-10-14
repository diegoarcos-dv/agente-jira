export type Space = "AT" | "ASIT" | "MTTI";
export type Decision = "INCLUIR" | "REVISAR" | "EXCLUIR";
export type WorkType = "Epic" | "Story" | "Task" | "Bug" | "Subtask";

export interface Session {
  access_token: string;
  token_type: "bearer";
  radar_telegram_url?: string | null;
  user: {
    username: string;
    display_name: string;
    role?: "ADMIN" | "USER";
    email?: string;
    atlassian_account_id?: string;
  };
  onboarding?: {
    version: number;
    current_version: number;
    required: boolean;
    completed_at?: string | null;
    skipped_at?: string | null;
  };
}

export interface ValidationIssue {
  code: string;
  message: string;
  row: number | null;
  column: string | null;
}

export interface ReviewRequirement {
  code: string;
  field: string;
  message: string;
}

export interface ProposalItem {
  source: {
    source_row: number;
    actividad: string;
    responsable_display: string;
    frente_trabajo_origen: string | null;
    contexto_resultado: string | null;
    fecha_objetivo: string | null;
    estado_actual: string;
    comentarios: string | null;
    source_section?: string | null;
    source_evidence?: string;
    inferred?: boolean;
    area_responsable?: string | null;
    area_source?: "LOCAL" | "JIRA";
    area_status?: "EXPLICIT" | "AMBIGUOUS" | "UNSPECIFIED";
    area_candidates?: string[];
    area_mentions?: string[];
  };
  generated: {
    row_id: string;
    create_in_jira: boolean;
    decision: Decision;
    decision_reason: string;
    work_type: WorkType;
    title: string;
    description: string;
    space: Space;
    parent_row_id: string | null;
    assignee: {
      display_name: string;
      email: string | null;
      account_id: string | null;
      resolution: "RESOLVED" | "AMBIGUOUS" | "NOT_FOUND" | "INACTIVE";
    };
    fields: Record<string, string | null>;
    confidence: number;
  };
  validation: {
    errors: string[];
    warnings: string[];
    pending_requirements?: ReviewRequirement[];
  };
  review: {
    user_modified: boolean;
    approved: boolean;
    review_note: string | null;
    confirmed_fields?: ("source_state" | "work_type")[];
    source_state_override?: "ACTIVE" | null;
    source_state_override_reason?: string | null;
    source_state_override_at?: string | null;
    source_state_override_by?: string | null;
    reactivation_reviewed?: boolean;
    manual_exclusion_reason?: string | null;
    manual_excluded_at?: string | null;
    manual_excluded_by?: string | null;
  };
  execution: {
    result: "NOT_STARTED";
  };
}

export interface Proposal {
  minutes?: {
    prompt_version: string;
    document: { project: string | null; date: string | null; objective: string | null;
      participants: { name: string; role: string | null }[]; draft_id?: string; candidate_ids?: string[] };
    warnings: string[];
    enrichment?: MinutesEnrichment;
  };
  proposal_id: string;
  version: number;
  template_version: "1.1" | "1.2" | "1.3";
  status: string;
  source_file: {
    name: string;
    sha256: string;
  };
  defaults: {
    space: Space;
    iniciativa: string | null;
    linea_trabajo: string | null;
    sprint: string | null;
    tipo_seguimiento: string | null;
    semaforo: string | null;
  };
  items: ProposalItem[];
  created_at: string;
  created_by: string;
  approved_at: string | null;
  approved_by: string | null;
}

export interface MinutesEnrichmentSuggestion {
  row_id: string;
  title: string;
  description: string;
  base_title: string;
  base_description: string;
}

export interface MinutesEnrichment {
  proposal_id?: string;
  base_version: number;
  state: "PENDING" | "READY" | "FAILED" | "STALE" | "NONE";
  suggestions: MinutesEnrichmentSuggestion[];
  message: string | null;
  failure_code?: string | null;
  started_at?: string;
  completed_at?: string | null;
  duration_ms?: number | null;
}

export type MinuteFieldStatus = "VALID" | "REVIEW" | "INVALID" | "EMPTY_ALLOWED";
export interface MinuteDraftRow {
  candidate_id: string;
  actividad: string | null;
  area_responsable?: string | null;
  area_source?: "LOCAL" | "JIRA" | "SINGLE_MAPPING" | "TEXT_CONFIRMED" | "USER_SELECTED" | "MANUAL" | "UNRESOLVED";
  area_status?: "EXPLICIT" | "AMBIGUOUS" | "UNSPECIFIED";
  area_candidates?: string[];
  area_mentions?: string[];
  row_status?: "READY" | "NEEDS_REVIEW" | "INVALID" | "CREATED" | "CREATE_ERROR";
  row_errors?: Array<{ field: string; code: string; message: string }>;
  row_warnings?: string[];
  proposal_id?: string | null;
  proposal_status?: string;
  creation_status?: "CREATED_VERIFIED" | "CREATED_UNVERIFIED" | "REJECTED" | "UNKNOWN" | null;
  jira_issue_key?: string | null;
  jira_issue_url?: string | null;
  created_at?: string | null;
  creation_idempotency_key?: string | null;
  responsable: string;
  responsable_account_id: string | null;
  responsable_source?: "EXPLICIT" | "JIRA" | "MANUAL" | "UNRESOLVED";
  responsable_resolution_status?: "UNRESOLVED" | "RESOLVING" | "EXPLICIT_MINUTES" | "AUTO_RESOLVED" | "VALIDATED_JIRA" | "MULTIPLE_MATCHES" | "NOT_FOUND" | "UNAVAILABLE" | "NEEDS_REVIEW";
  responsable_lookup_query?: string;
  tipo_de_seguimiento: string;
  tipo_de_seguimiento_id: string | null;
  fecha_objetivo: string | null;
  proyecto_o_frente: string | null;
  contexto_o_resultado: string | null;
  comentarios: string | null;
  source_section: string;
  source_evidence: string;
  extraction_mode: string;
  touched_fields: string[];
  suggestions: Array<{ field: string; value: string; message?: string }>;
  ignored_suggestions: string[];
  field_status: Record<string, MinuteFieldStatus>;
  validation_errors: Array<{ field: string; code: string; message: string }>;
}
export interface MinuteExcelDraft {
  draft_id: string;
  source: "MINUTA";
  version: number;
  state: "ANALYZING" | "READY" | "NEEDS_REVIEW" | "INVALID" | "ENRICHING" | "STALE_ENRICHMENT" | "EXPORTING" | "EXPORT_ERROR";
  created_at: string;
  updated_at: string;
  extraction_mode: string;
  duplicates_removed: number;
  warnings: string[];
  document?: {
    project?: string | null;
    date?: string | null;
    participants?: Array<{ name: string; role: string | null }>;
    project_responsible?: string | null;
    project_responsible_evidence?: string | null;
    project_responsible_account_id?: string | null;
    project_responsible_source?: "EXPLICIT" | "JIRA" | "MANUAL" | "UNRESOLVED";
    project_responsible_resolution_status?: MinuteDraftRow["responsable_resolution_status"];
    project_responsible_lookup_query?: string | null;
  };
  rows: MinuteDraftRow[];
  tracking_options: Array<{ value: string; label: string; jira_id?: string | null }>;
  validation_summary: { activities: number; complete: number; created?: number; needs_review: number; technical_errors: number };
  enrichment: { state: "NONE" | "PENDING" | "READY" | "FAILED" | "STALE"; base_version: number; suggestions: unknown[]; message: string | null };
  proposal_id: string | null;
  jira_space_key?: string;
  catalog_status?: "LOADING" | "READY" | "STALE" | "UNAVAILABLE";
  tracking_field_id?: string | null;
}

export type ProposalDefaults = Proposal["defaults"];

export interface ProposalSummary {
  proposal_id: string;
  version: number;
  status: string;
  source_file: string;
  display_name: string;
  space: Space;
  counts: Record<Decision, number>;
  created_at: string;
  archived: boolean;
  archived_at: string | null;
  archived_by: string | null;
  deleted?: boolean;
  deleted_at?: string | null;
  deleted_by?: string | null;
  purge_at?: string | null;
  display_name_updated_at: string | null;
  display_name_updated_by: string | null;
}

export interface AtlassianField {
  id: string | null;
  name: string | null;
  required: boolean;
  business_key?: keyof Omit<ProposalDefaults, "space">;
  options?: Array<{
    value: string;
    label: string;
    jira_id?: string;
  }>;
}

export interface AtlassianWorkType {
  id: string | null;
  name: string | null;
  subtask: boolean;
  fields: AtlassianField[];
}

export interface AtlassianSpace {
  key: Space;
  found: boolean;
  id: string | null;
  name: string | null;
  project_type: string | null;
  work_types: AtlassianWorkType[];
}

export interface AtlassianSnapshot {
  verified_at: string;
  site_url: string;
  site_name: string | null;
  cloud_id: string;
  atlassian_user: {
    account_id: string | null;
    display_name: string | null;
    email: string | null;
  };
  spaces: AtlassianSpace[];
  read_tools_available: string[];
  write_tools_exposed_by_server: number;
}

export interface AtlassianStatus {
  performance?: PerformanceSummary | null;
  global_write_lock?: JiraWriteLockStatus;
  diagnostic?: {
    state: string; message: string; action: string; phase: string;
    request_id: string; checked_at: string | null; last_success_at: string | null;
    duration_ms: number | null; error_code: string | null; technical: string | null;
    checks: Record<string, string>; capabilities: string[]; account: string | null;
    write_performed: boolean; tools_invoked: string[];
  };
  connected: boolean;
  phase: "DISCONNECTED" | "CONNECTING" | "AWAITING_USER_CONSENT" | "CONNECTED" | "ERROR";
  mcp_endpoint?: string;
  target_site?: string;
  target_spaces?: Space[];
  oauth_storage: "OS_ENCRYPTED" | "MEMORY_ONLY";
  jira_write_enabled: boolean;
    write_tools_blocked: boolean;
  error: string | null;
  snapshot: AtlassianSnapshot | null;
  stage?: string;
}

export interface PerformanceSummary {
  operation: string;
  request_id: string;
  duration_ms: number;
  phase_durations_ms?: Record<string, number>;
  slowest_phase?: { name: string | null; duration_ms: number } | null;
  jira_call_count: number;
  cache_hits: number;
  cache_misses: number;
  max_concurrency: number;
  calls_by_operation?: Record<string, number>;
  cache_events_by_operation?: Record<string, { hit: number; miss: number }>;
  proposal_id?: string | null;
  activity_count?: number | null;
  status_code?: number | null;
  events?: Array<Record<string, unknown>>;
}

export interface JiraWriteLockStatus {
  state: 'LOCKED' | 'UNLOCKED_TEMPORARY' | 'EXPIRED' | string;
  locked: boolean;
  expires_at: string | null;
  ttl_seconds: number;
  enabled_by: string | null;
  last_changed_at: string | null;
  last_event?: { event: string; actor: string; at: string | null; expires_at: string | null; state: string; reason: string | null } | null;
}

export interface JiraAssignee {
  account_id: string | null;
  display_name: string | null;
  email: string | null;
  active: boolean;
  capability?: "findAssignableUsers" | "lookupJiraAccountId";
}

export interface JiraSprint {
  id: string;
  name: string;
  state: "active" | "future";
  board_id: string | null;
  source: string;
}

export interface DryRunIssue {
  code: string;
  field: string;
  message: string;
  options?: { value: string; jira_id?: string | null }[];
}

export interface JiraDryRunItem {
  row_id: string;
  source_row: number;
  status: "READY" | "READY_WITH_WARNINGS" | "BLOCKED" | "SKIPPED";
  title: string;
  space: Space;
  work_type: WorkType;
  parent_row_id?: string | null;
  errors: DryRunIssue[];
  warnings: DryRunIssue[];
  target: {
    project_name: string | null;
    project_type: string | null;
    jira_work_type: string | null;
    required_field_count: number;
  } | null;
  assignee: {
    display_name: string | null;
    email: string | null;
    account_id: string | null;
    validation: "JIRA_ACCOUNT_MATCH" | "JIRA_ASSIGNABLE_USER_MATCH";
  } | null;
  sprint_resolution?: {
    selected: JiraSprint | null;
    mode: "ID_MATCH" | "PLAN_NAME_MATCH" | "AUTO_SINGLE_ACTIVE" | "AMBIGUOUS_PLAN_VALUE" | "PLAN_VALUE_NOT_FOUND" | "MULTIPLE_ACTIVE" | "NO_ACTIVE_SPRINT";
    requested: string | null;
    error: DryRunIssue | null;
    warning: DryRunIssue | null;
    field_id?: string;
  } | null;
  logical_payload: Record<string, unknown> | null;
  idempotency_key: string | null;
}

export interface JiraCorrectionItem {
  row_id: string;
  category: "USER_ACTION" | "TECHNICAL" | "CORRECTED";
  instruction: string;
  issues: DryRunIssue[];
}

export interface JiraCorrectionWorkflow {
  active: boolean;
  summary: {
    pending_user: number;
    technical: number;
    corrected: number;
  };
  items: JiraCorrectionItem[];
}

export interface JiraDryRun {
  dry_run_id: string;
  proposal_id: string;
  proposal_version: number;
  proposal_hash: string;
  generated_at: string;
  generated_by: string;
  jira_snapshot_verified_at: string;
  site_url: string;
  status: "READY" | "READY_WITH_WARNINGS" | "BLOCKED";
  summary: {
    ready: number;
    ready_with_warnings?: number;
    blocked: number;
    skipped: number;
  };
  items: JiraDryRunItem[];
  write_performed: false;
  reused: boolean;
  stale?: boolean;
  correction_workflow?: JiraCorrectionWorkflow;
}

export interface ApprovalDryRunResult {
  proposal: Proposal;
  dry_run: JiraDryRun;
}

export type Objective4AStatus =
  | "PREPARED"
  | "CONFIRMED"
  | "SIMULATED"
  | "CANCELLED"
  | "EXPIRED"
  | "INVALIDATED"
  | "REAL_PREPARED"
  | "REAL_CONFIRMED"
  | "SUBMITTED"
  | "CREATED_VERIFIED"
  | "CREATED_UNVERIFIED"
  | "REJECTED"
  | "UNKNOWN";

export interface Objective4AIntent {
  objective: "4A";
  mode: "SIMULATION_ONLY";
  execution_id: string;
  status: Objective4AStatus;
  proposal_id: string;
  proposal_version: number;
  row_id: string;
  dry_run_id: string;
  idempotency_key: string;
  payload_hash: string;
  payload: {
    tool: "createJiraIssue";
    contract_status: "CANDIDATE_UNTIL_REAL_SCHEMA_IS_CONFIRMED";
    arguments: Record<string, unknown>;
  };
  preview: {
    title: string;
    description: string;
    space: Space;
    work_type: WorkType;
    assignee: {
      display_name: string | null;
      account_id: string | null;
      validation: string | null;
    };
    warnings: DryRunIssue[];
  };
  confirmation: {
    required: true;
    expires_at: string;
    confirmed_at: string | null;
    confirmed_by: string | null;
  };
  simulation: {
    simulated_calls: number;
    real_mcp_calls: 0;
    write_performed: false;
    result: {
      simulation_key: string;
      accepted: boolean;
      transport: "LOCAL_SIMULATOR";
      mcp_tool_invoked: null;
      jira_issue_created: false;
    } | null;
  };
    audit: Array<{
      state: Objective4AStatus;
      event: string;
      at: string;
      by: string;
      real_mcp_calls: number;
      write_performed: boolean;
  }>;
  created_at: string;
  updated_at: string;
  created_by: string;
  reused: boolean;
    jira_write_enabled: boolean;
  real_confirmation?: {
    expires_at: string;
    confirmed_at: string | null;
    confirmed_by: string | null;
  };
  real_execution?: {
    mode: "SINGLE_CONTROLLED_TASK";
    confirmation_phrase: string;
    payload: { tool: "createJiraIssue"; arguments: Record<string, unknown> };
    payload_hash: string;
    prepared_at: string;
    confirmed_at: string | null;
    submitted_at: string | null;
    completed_at: string | null;
    real_mcp_calls: number;
    automatic_retries: 0;
    issue_key: string | null;
    issue_url: string | null;
    result: string | null;
    error: string | null;
    readback: {
      checks: Record<string, boolean>;
      payload: unknown;
    } | null;
    sprint_resolution?: JiraDryRunItem["sprint_resolution"];
    sprint_revalidated_at?: string | null;
  };
}

export interface Objective4AReadiness {
  objective: "4A" | "4C.1" | "4D" | "4E";
  status: "READY_FOR_SIMULATION" | "READY_FOR_CONTROLLED_WRITE" | "READY_FOR_CONTROLLED_BATCH" | "READY_FOR_CONTROLLED_MULTI_TYPE_BATCH" | "READY_FOR_CONTROLLED_HIERARCHY_BATCH" | "BLOCKED";
  jira_write_enabled: boolean;
  simulation_only: boolean;
  policy_violations: string[];
  mcp_tools: {
    connected: boolean;
    inspection_only: true;
    tools_invoked: 0;
    create: { name: string; exposed: boolean; schema_sha256?: string | null };
    readback: { name: string; exposed: boolean; schema_sha256?: string | null };
  };
  task_contract: {
    space: "AT";
    space_id: string | null;
    work_type: "Task" | "Bug" | "Story";
    work_type_id: string | null;
    fields: AtlassianField[];
  };
  real_canary_checks: Record<string, boolean>;
  real_canary_ready: boolean;
  controlled_write_ready?: boolean;
  batch_write_ready?: boolean;
  policy?: {
    mode: "PLANNING_ONLY" | "SINGLE_CANARY" | "CONTROLLED_BATCH" | "CONTROLLED_MULTI_TYPE_BATCH" | "CONTROLLED_HIERARCHY_BATCH";
    max_items_per_execution: number;
    allowed_work_types?: WorkType[];
    [key: string]: unknown;
  };
  confirmation_phrase?: string;
  next_gate: "EXPLICIT_OBJECTIVE_4B_ACTIVATION" | "START_WITH_OBJECTIVE_4B_POLICY" | "EXPLICIT_IN_APP_CONFIRMATION" | "SELECT_ONE_TO_FIVE_TASKS" | "SELECT_PARENT_BEFORE_CHILD_BATCH";
}

export type Objective4C1ItemStatus =
  | "PENDING" | "SUBMITTED" | "CREATED_VERIFIED" | "CREATED_UNVERIFIED"
  | "REJECTED" | "UNKNOWN" | "NOT_ATTEMPTED";

export interface Objective4C1Item {
  position: number;
  row_id: string;
  idempotency_key: string;
  status: Objective4C1ItemStatus;
  payload_hash: string;
  preview: {
    title: string;
    source_title: string;
    space: "AT";
    work_type: WorkType;
    assignee: JiraDryRunItem["assignee"];
    parent_row_id?: string | null;
    parent_issue_key?: string | null;
  };
  parent_reference?: { row_id: string; issue_key: string | null } | null;
  resolved_parent?: { row_id: string; issue_key: string } | null;
  submitted_payload_hash?: string | null;
  sprint_resolution?: JiraDryRunItem["sprint_resolution"];
  sprint_revalidated_at?: string | null;
  issue_key: string | null;
  issue_url: string | null;
  result: string | null;
  error: string | null;
  real_mcp_calls: number;
  automatic_retries: 0;
  readback: { checks: Record<string, boolean>; payload: unknown } | null;
}

export interface Objective4C1Batch {
  objective: "4C.1" | "4D" | "4E";
  mode: "CONTROLLED_TASK_BATCH" | "CONTROLLED_WORK_ITEM_BATCH" | "CONTROLLED_HIERARCHY_BATCH";
  execution_id: string;
  status: "BATCH_PREPARED" | "BATCH_CONFIRMED" | "BATCH_RUNNING" | "COMPLETED"
    | "STOPPED_REJECTED" | "STOPPED_UNKNOWN" | "STOPPED_UNVERIFIED";
  proposal_id: string;
  proposal_version: number;
  dry_run_id: string;
  payload_hash: string;
  confirmation_phrase: string;
  confirmation: {
    required: true;
    expires_at: string;
    confirmed_at: string | null;
    confirmed_by: string | null;
  };
  items: Objective4C1Item[];
  summary: Record<string, number>;
  real_mcp_calls: number;
  automatic_retries: 0;
  reused?: boolean;
}

export interface Objective4C2Progress {
  objective: "4C.2" | "4D" | "4E";
  mode: "SUCCESSIVE_CONTROLLED_BATCHES" | "SUCCESSIVE_MULTI_TYPE_BATCHES" | "SUCCESSIVE_HIERARCHY_BATCHES";
  proposal_id: string;
  proposal_version: number;
  dry_run_id: string;
  max_items_per_batch: 5;
  available_row_ids: string[];
  counts: {
    eligible: number;
    available: number;
    reserved: number;
    created_verified: number;
    created_unverified: number;
    rejected: number;
    unknown: number;
  };
  batch_count: number;
  real_mcp_calls: number;
  automatic_retries: 0;
}
