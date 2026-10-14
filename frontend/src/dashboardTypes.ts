export type DashboardState = "ACTUALIZADO" | "ACTUALIZANDO" | "STALE" | "PARTIAL" |
  "NO_DATA" | "NO_PERMISSION" | "JIRA_DISCONNECTED" | "RATE_LIMITED" | "ERROR";

export interface DashboardStatus {
  state: DashboardState;
  has_snapshot: boolean;
  last_updated: string | null;
  last_duration_ms: number | null;
  issues_read: number | null;
  jira_reads: number | null;
  mcp_calls: number | null;
  errors: number;
  timeouts: number;
  rate_limits: number;
  cache_hits: number;
  refresh_started_at: string | null;
  error: string | null;
  failed_spaces: Array<{ key: string; state: DashboardState; message: string }>;
  jira_write_enabled: false;
  write_lock: "LOCKED";
}

export interface DashboardCount {
  total: number; todo: number; in_progress: number; done: number; unassigned: number;
  active: number; overdue: number; due_next_7d: number; has_due_date: number;
  no_due_date: number; created_7d: number; updated_7d: number; updated_30d: number;
  recent_activity: boolean;
  completed_7d: { value: number | null; known_count: number; missing_resolutiondate: number; state: string };
}

export interface DashboardWorkType { id: string; name: string; subtask: boolean; hierarchy_level?: number; count: number; percent: number }
export interface DashboardPriority { id: string | null; name: string; count: number }
export interface DashboardStatusRow { id: string | null; name: string; category: string; count: number }
export interface DashboardWorker { display_name: string; active: number; todo: number; in_progress: number; overdue: number; total_assigned?: number }
export interface DashboardSprint {
  id: string; name: string; state: string; start_date?: string; end_date?: string;
  board_id?: string | null; issue_keys?: string[];
}
export interface DashboardEpic {
  key: string; summary: string; total_children: number; done: number; in_progress: number;
  todo: number; progress_percent: number | null; state: string;
}
export interface DashboardSpaceSummary extends DashboardCount {
  key: string; name: string; id: string; project_type?: string; style?: string; lead?: string | null;
  access: string; unknown_status_category: number; active_assignees: number;
  statuses: DashboardStatusRow[]; work_types: DashboardWorkType[]; priorities: DashboardPriority[];
  workload: DashboardWorker[]; last_issue_updated: string | null; freshness: string | null;
  sprint: { supported: boolean; state: string; active: DashboardSprint[]; future: DashboardSprint[]; issues_in_active: number; note: string };
  epics: { supported: boolean; state: string; items: DashboardEpic[]; children_visible: number; parent_relationship_confidence: string };
  tracking: { available: boolean; state: string; name: string | null; available_types: string[]; options: Array<{ id: string; name: string; count: number }>; populated: number; empty: number; context_note: string };
}
export interface DashboardSummary {
  created_at: string; duration_ms: number;
  performance: { issues_read: number; pages: number; jira_reads: number; mcp_calls: number; errors: number; timeouts: number; rate_limits: number; cache_hits: number; http_statuses?: Record<string, number> };
  spaces: DashboardSpaceSummary[];
  issues?: DashboardIssue[];
  global: DashboardCount & { work_types: Array<{ name: string; count: number; spaces: string[]; space_types: Array<{ space: string; id: string; count: number }> }>; priorities: DashboardPriority[]; statuses: Array<{ name: string; category: string; id: string | null; count: number }>; workload: DashboardWorker[] };
}
export interface DashboardIssue {
  key: string; space: string; summary: string;
  status: { id: string | null; name: string | null; category: string } | null;
  assignee: { displayName: string } | null;
  priority: { id: string | null; name: string } | null;
  duedate: string | null;
  issuetype: { id: string; name: string } | null;
  created?: string | null;
  updated?: string | null;
  resolutiondate?: string | null;
  parent?: { key: string } | null;
  tracking?: { id?: string | null; name?: string | null } | null;
}
export interface DashboardIssuePage { total: number; page: number; page_size: number; issues: DashboardIssue[]; snapshot_at: string }
export interface DashboardSpace {
  summary: DashboardSpaceSummary;
  work_types: DashboardWorkType[];
}
