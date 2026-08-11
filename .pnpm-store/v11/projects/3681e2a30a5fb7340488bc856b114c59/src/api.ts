import type {
  AtlassianStatus,
  ApprovalDryRunResult,
  JiraAssignee,
  JiraSprint,
  JiraDryRun,
  Objective4AIntent,
  Objective4AReadiness,
  Objective4C1Batch,
  Objective4C2Progress,
  Proposal,
  ProposalDefaults,
  ProposalSummary,
  Session,
  ValidationIssue,
  WorkType,
} from "./types";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly issues: ValidationIssue[] = [],
  ) {
    super(message);
  }
}

async function request<T>(
  path: string,
  options: RequestInit = {},
  token?: string,
): Promise<T> {
  const headers = new Headers(options.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (options.body && !(options.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }
  const response = await fetch(path, { ...options, headers });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    const detail =
      typeof payload.detail === "string"
        ? payload.detail
        : "La operación no pudo completarse.";
    throw new ApiError(detail, response.status, payload.issues ?? []);
  }
  return response.json() as Promise<T>;
}

export function login(username: string, password: string): Promise<Session> {
  return request<Session>("/api/auth/login", {
    method: "POST",
    body: JSON.stringify({ username, password }),
  });
}

export function createProposal(
  token: string,
  form: FormData,
): Promise<Proposal> {
  return request<Proposal>("/api/proposals", { method: "POST", body: form }, token);
}

export function listProposals(token: string): Promise<ProposalSummary[]> {
  return request<ProposalSummary[]>("/api/proposals", {}, token);
}

export function archiveProposal(
  token: string,
  proposalId: string,
): Promise<ProposalSummary> {
  return request<ProposalSummary>(
    `/api/proposals/${proposalId}/archive`,
    { method: "POST" },
    token,
  );
}

export function restoreProposal(
  token: string,
  proposalId: string,
): Promise<ProposalSummary> {
  return request<ProposalSummary>(
    `/api/proposals/${proposalId}/restore`,
    { method: "POST" },
    token,
  );
}

export function renameProposal(
  token: string,
  proposalId: string,
  displayName: string,
): Promise<ProposalSummary> {
  return request<ProposalSummary>(
    `/api/proposals/${proposalId}/metadata`,
    { method: "PATCH", body: JSON.stringify({ display_name: displayName }) },
    token,
  );
}

export function getProposal(token: string, proposalId: string): Promise<Proposal> {
  return request<Proposal>(`/api/proposals/${proposalId}`, {}, token);
}

export function updateProposalDefaults(
  token: string,
  proposalId: string,
  defaults: ProposalDefaults,
): Promise<Proposal> {
  return request<Proposal>(
    `/api/proposals/${proposalId}/defaults`,
    { method: "PATCH", body: JSON.stringify(defaults) },
    token,
  );
}

export function getAtlassianStatus(token: string): Promise<AtlassianStatus> {
  return request<AtlassianStatus>("/api/integrations/atlassian/status", {}, token);
}

export function connectAtlassian(
  token: string,
): Promise<{ authorization_url: string; phase: string }> {
  return request<{ authorization_url: string; phase: string }>(
    "/api/integrations/atlassian/connect",
    { method: "POST" },
    token,
  );
}

export function disconnectAtlassian(token: string): Promise<AtlassianStatus> {
  return request<AtlassianStatus>(
    "/api/integrations/atlassian/disconnect",
    { method: "POST" },
    token,
  );
}

export function refreshAtlassian(token: string): Promise<AtlassianStatus> {
  return request<AtlassianStatus>(
    "/api/integrations/atlassian/refresh",
    { method: "POST" },
    token,
  );
}

export function findJiraAssignees(
  token: string,
  space: string,
  query: string,
): Promise<JiraAssignee[]> {
  const parameters = new URLSearchParams({ space, q: query });
  return request<JiraAssignee[]>(
    `/api/integrations/atlassian/assignees?${parameters.toString()}`,
    {},
    token,
  );
}

export function listJiraSprints(
  token: string,
  space: string,
  refresh = false,
): Promise<JiraSprint[]> {
  const parameters = new URLSearchParams({ space, refresh: String(refresh) });
  return request<JiraSprint[]>(
    `/api/integrations/atlassian/sprints?${parameters.toString()}`,
    {},
    token,
  );
}

export function updateProposalItem(
  token: string,
  proposalId: string,
  rowId: string,
  update: {
    title: string;
    description: string;
    work_type: WorkType;
    review_note: string | null;
    assignee_account_id: string | null;
    assignee_query: string | null;
    parent_row_id: string | null;
    confirm_source_state: boolean;
    confirm_work_type: boolean;
    confirm_reactivation: boolean;
  },
): Promise<Proposal> {
  return request<Proposal>(
    `/api/proposals/${proposalId}/items/${rowId}`,
    { method: "PATCH", body: JSON.stringify(update) },
    token,
  );
}

export function reactivateProposalItem(
  token: string,
  proposalId: string,
  rowId: string,
  reason: string,
): Promise<Proposal> {
  return request<Proposal>(
    `/api/proposals/${proposalId}/items/${rowId}/reactivate`,
    { method: "POST", body: JSON.stringify({ reason }) },
    token,
  );
}

export function updateProposalJiraAssignee(
  token: string,
  proposalId: string,
  rowId: string,
  accountId: string,
  query: string,
): Promise<Proposal> {
  return request<Proposal>(
    `/api/proposals/${proposalId}/items/${rowId}/jira-assignee`,
    {
      method: "PATCH",
      body: JSON.stringify({ account_id: accountId, query }),
    },
    token,
  );
}

export function approveProposal(token: string, proposalId: string): Promise<Proposal> {
  return request<Proposal>(
    `/api/proposals/${proposalId}/approve`,
    { method: "POST" },
    token,
  );
}

export function approveProposalAndDryRun(
  token: string,
  proposalId: string,
): Promise<ApprovalDryRunResult> {
  return request<ApprovalDryRunResult>(
    `/api/proposals/${proposalId}/approve-and-dry-run`,
    { method: "POST" },
    token,
  );
}

export function reopenProposal(token: string, proposalId: string): Promise<Proposal> {
  return request<Proposal>(
    `/api/proposals/${proposalId}/reopen`,
    { method: "POST" },
    token,
  );
}

export function generateJiraDryRun(
  token: string,
  proposalId: string,
): Promise<JiraDryRun> {
  return request<JiraDryRun>(
    `/api/proposals/${proposalId}/dry-run`,
    { method: "POST" },
    token,
  );
}

export function getLatestJiraDryRun(
  token: string,
  proposalId: string,
): Promise<JiraDryRun> {
  return request<JiraDryRun>(
    `/api/proposals/${proposalId}/dry-run/latest`,
    {},
    token,
  );
}

export function getObjective4AReadiness(token: string): Promise<Objective4AReadiness> {
  return request<Objective4AReadiness>("/api/objectives/4/readiness", {}, token);
}

export function prepareObjective4ASimulation(
  token: string,
  proposalId: string,
  rowId: string,
): Promise<Objective4AIntent> {
  return request<Objective4AIntent>(
    `/api/proposals/${proposalId}/objective-4a/prepare`,
    { method: "POST", body: JSON.stringify({ row_id: rowId }) },
    token,
  );
}

export function getLatestObjective4ASimulation(
  token: string,
  proposalId: string,
): Promise<Objective4AIntent> {
  return request<Objective4AIntent>(
    `/api/proposals/${proposalId}/objective-4a/latest`,
    {},
    token,
  );
}

export function confirmObjective4ASimulation(
  token: string,
  executionId: string,
  payloadHash: string,
): Promise<Objective4AIntent> {
  return request<Objective4AIntent>(
    `/api/objectives/4a/executions/${executionId}/confirm`,
    {
      method: "POST",
      body: JSON.stringify({ payload_hash: payloadHash, confirmed: true }),
    },
    token,
  );
}

export function runObjective4ASimulation(
  token: string,
  executionId: string,
): Promise<Objective4AIntent> {
  return request<Objective4AIntent>(
    `/api/objectives/4a/executions/${executionId}/simulate`,
    { method: "POST" },
    token,
  );
}

export function prepareObjective4BWrite(
  token: string,
  executionId: string,
): Promise<Objective4AIntent> {
  return request<Objective4AIntent>(
    `/api/objectives/4b/executions/${executionId}/prepare`,
    { method: "POST" },
    token,
  );
}

export function confirmObjective4BWrite(
  token: string,
  executionId: string,
  payloadHash: string,
  confirmationPhrase: string,
): Promise<Objective4AIntent> {
  return request<Objective4AIntent>(
    `/api/objectives/4b/executions/${executionId}/confirm`,
    {
      method: "POST",
      body: JSON.stringify({
        payload_hash: payloadHash,
        confirmation_phrase: confirmationPhrase,
      }),
    },
    token,
  );
}

export function executeObjective4BWrite(
  token: string,
  executionId: string,
): Promise<Objective4AIntent> {
  return request<Objective4AIntent>(
    `/api/objectives/4b/executions/${executionId}/execute`,
    { method: "POST" },
    token,
  );
}

export function getLatestObjective4C1Batch(
  token: string,
  proposalId: string,
): Promise<Objective4C1Batch> {
  return request<Objective4C1Batch>(
    `/api/proposals/${proposalId}/objective-4c1/latest`,
    {},
    token,
  );
}

export function getObjective4C2Progress(
  token: string,
  proposalId: string,
): Promise<Objective4C2Progress> {
  return request<Objective4C2Progress>(
    `/api/proposals/${proposalId}/objective-4c2/progress`,
    {},
    token,
  );
}

export function prepareObjective4C1Batch(
  token: string,
  proposalId: string,
  rowIds: string[],
): Promise<Objective4C1Batch> {
  return request<Objective4C1Batch>(
    `/api/proposals/${proposalId}/objective-4c1/prepare`,
    { method: "POST", body: JSON.stringify({ row_ids: rowIds }) },
    token,
  );
}

export function confirmObjective4C1Batch(
  token: string,
  executionId: string,
  payloadHash: string,
  confirmationPhrase: string,
): Promise<Objective4C1Batch> {
  return request<Objective4C1Batch>(
    `/api/objectives/4c1/batches/${executionId}/confirm`,
    {
      method: "POST",
      body: JSON.stringify({ payload_hash: payloadHash, confirmation_phrase: confirmationPhrase }),
    },
    token,
  );
}

export function executeObjective4C1Batch(
  token: string,
  executionId: string,
): Promise<Objective4C1Batch> {
  return request<Objective4C1Batch>(
    `/api/objectives/4c1/batches/${executionId}/execute`,
    { method: "POST" },
    token,
  );
}

export function cancelObjective4ASimulation(
  token: string,
  executionId: string,
): Promise<Objective4AIntent> {
  return request<Objective4AIntent>(
    `/api/objectives/4a/executions/${executionId}/cancel`,
    { method: "POST" },
    token,
  );
}

export async function downloadObjective4AEvidence(
  token: string,
  executionId: string,
): Promise<void> {
  const response = await fetch(
    `/api/objectives/4a/executions/${executionId}/evidence`,
    { headers: { Authorization: `Bearer ${token}` } },
  );
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new ApiError(payload.detail ?? "No fue posible descargar la evidencia 4A.", response.status);
  }
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `${executionId}_evidencia_4A.json`;
  anchor.click();
  URL.revokeObjectURL(url);
}

export async function downloadObjective4BEvidence(
  token: string,
  executionId: string,
): Promise<void> {
  const response = await fetch(
    `/api/objectives/4b/executions/${executionId}/evidence`,
    { headers: { Authorization: `Bearer ${token}` } },
  );
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new ApiError(payload.detail ?? "No fue posible descargar la evidencia 4B.", response.status);
  }
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `${executionId}_evidencia_4B.json`;
  anchor.click();
  URL.revokeObjectURL(url);
}

export async function downloadObjective4C1Evidence(
  token: string,
  executionId: string,
): Promise<void> {
  const response = await fetch(
    `/api/objectives/4c1/batches/${executionId}/evidence`,
    { headers: { Authorization: `Bearer ${token}` } },
  );
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new ApiError(payload.detail ?? "No fue posible descargar la evidencia 4C.1.", response.status);
  }
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `${executionId}_evidencia_controlada.json`;
  anchor.click();
  URL.revokeObjectURL(url);
}

export async function downloadApprovedProposal(
  token: string,
  proposalId: string,
  displayName: string,
): Promise<void> {
  const response = await fetch(`/api/proposals/${proposalId}/approved-export`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new ApiError(payload.detail ?? "No fue posible descargar la propuesta.", response.status);
  }
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `${displayName || "propuesta_aprobada"}.json`;
  anchor.click();
  URL.revokeObjectURL(url);
}

export async function downloadDryRunEvidence(
  token: string,
  proposalId: string,
  displayName: string,
): Promise<void> {
  const response = await fetch(`/api/proposals/${proposalId}/dry-run-evidence`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new ApiError(payload.detail ?? "No fue posible descargar la evidencia.", response.status);
  }
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `${displayName || "prevalidacion_jira"}_evidencia_3B2.json`;
  anchor.click();
  URL.revokeObjectURL(url);
}
