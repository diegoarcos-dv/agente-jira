import type {
  AtlassianStatus,
  ApprovalDryRunResult,
  JiraAssignee,
  JiraSprint,
  JiraWriteLockStatus,
  MinutesEnrichment,
  MinuteExcelDraft,
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
import type { DashboardIssuePage, DashboardSpace, DashboardStatus, DashboardSummary } from "./dashboardTypes";
import { SESSION_EXPIRED_EVENT } from "./authEvents";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly issues: ValidationIssue[] = [],
    readonly code?: string,
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
    if (response.status === 401) {
      window.dispatchEvent(new Event(SESSION_EXPIRED_EVENT));
    }
    const payload = await response.json().catch(() => ({}));
    const detail =
      typeof payload.detail === "string"
        ? payload.detail
        : `No se pudo completar ${options.method ?? "GET"} ${path} (HTTP ${response.status}). `
          + "Recarga la página; si persiste, comparte este código con soporte.";
    throw new ApiError(detail, response.status, payload.issues ?? [], payload.code);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export const getCurrentSession = () => request<Session>("/api/auth/me");
export const getOnboardingStatus = (token: string) => request<NonNullable<Session["onboarding"]>>("/api/onboarding/status", {}, token);
export const completeOnboarding = (token: string) => request<NonNullable<Session["onboarding"]>>("/api/onboarding/complete", { method: "POST" }, token);
export const skipOnboarding = (token: string) => request<NonNullable<Session["onboarding"]>>("/api/onboarding/skip", { method: "POST" }, token);
export const startAtlassianLogin = (returnPath = "/") =>
  request<{ authorization_url: string }>(
    `/api/auth/atlassian/start?return_path=${encodeURIComponent(returnPath)}`,
  );
export const logout = () => request<void>("/api/auth/logout", { method: "POST" });
export const unlinkAtlassian = () => request<void>("/api/auth/atlassian/unlink", { method: "POST" });

export const getDashboardStatus = (token: string) =>
  request<DashboardStatus>("/api/dashboard/status", {}, token);
export const getDashboardSummary = (token: string) =>
  request<DashboardSummary>("/api/dashboard/summary", {}, token);
export const getDashboardSpace = (token: string, key: string) =>
  request<DashboardSpace>(`/api/dashboard/spaces/${encodeURIComponent(key)}`, {}, token);
export const refreshDashboard = (token: string) =>
  request<DashboardStatus>("/api/dashboard/refresh", { method: "POST" }, token);
export function getDashboardIssues(token: string, query: URLSearchParams) {
  const suffix = query.toString();
  return request<DashboardIssuePage>(`/api/dashboard/issues${suffix ? `?${suffix}` : ""}`, {}, token);
}

export function createProposal(
  token: string,
  form: FormData,
): Promise<Proposal> {
  return request<Proposal>("/api/proposals", { method: "POST", body: form }, token);
}

export function preflightProposal(token: string, proposalId: string): Promise<unknown> {
  return request<unknown>(`/api/proposals/${proposalId}/preflight`, { method: "POST" }, token);
}

export function listProposals(token: string, includeTrash = false): Promise<ProposalSummary[]> {
  return request<ProposalSummary[]>(
    includeTrash ? "/api/proposals?include_trash=true" : "/api/proposals",
    {},
    token,
  );
}

export interface MinutesStatus {
  state: "DISABLED" | "UNAVAILABLE" | "READY";
  model: string | null;
  detail: string;
  max_chars: number;
}
export const getMinutesStatus = (token: string) => request<MinutesStatus>("/api/minutes/status", {}, token);
export const analyzeMinutes = (token: string, text: string) => request<{ proposal?: Proposal; draft?: MinuteExcelDraft }>(
  "/api/minutes/analyze", { method: "POST", body: JSON.stringify({ text, output: "draft" }) }, token,
);
export const getLatestMinuteDraft = (token: string) => request<MinuteExcelDraft>("/api/minutes/drafts/latest", {}, token);
export const getMinuteDraft = (token: string, draftId: string) => request<MinuteExcelDraft>(`/api/minutes/drafts/${draftId}`, {}, token);
export const getMinuteTrackingCatalog = (token: string, draftId: string) => request<{
  state: "READY" | "STALE" | "UNAVAILABLE"; space: string; work_type: string;
  field_id: string; field_name?: string; options: MinuteExcelDraft["tracking_options"];
  area_options?: Array<{ key: string; value: string; label: string }>; draft: MinuteExcelDraft;
}>(`/api/minutes/drafts/${draftId}/catalog`, {}, token);
export const updateMinuteDraftRow = (token: string, draftId: string, candidateId: string, expectedVersion: number,
  changes: Partial<MinuteExcelDraft["rows"][number]>) => request<MinuteExcelDraft>(
  `/api/minutes/drafts/${draftId}/rows/${candidateId}`,
  { method: "PATCH", body: JSON.stringify({ expected_version: expectedVersion, changes }) }, token);
export const updateMinuteDraftProjectResponsible = (token: string, draftId: string, expectedVersion: number,
  changes: Partial<NonNullable<MinuteExcelDraft["document"]>>) => request<MinuteExcelDraft>(
  `/api/minutes/drafts/${draftId}/project-responsible`,
  { method: "PATCH", body: JSON.stringify({ expected_version: expectedVersion, changes }) }, token);
export const addMinuteDraftRow = (token: string, draftId: string, expectedVersion: number) => request<MinuteExcelDraft>(
  `/api/minutes/drafts/${draftId}/rows`, { method: "POST", body: JSON.stringify({ expected_version: expectedVersion }) }, token);
export const deleteMinuteDraftRow = (token: string, draftId: string, candidateId: string, expectedVersion: number) =>
  request<MinuteExcelDraft>(`/api/minutes/drafts/${draftId}/rows/${candidateId}?expected_version=${expectedVersion}`,
    { method: "DELETE" }, token);
export const validateMinuteDraft = (token: string, draftId: string) => request<MinuteExcelDraft>(
  `/api/minutes/drafts/${draftId}/validate`, { method: "POST" }, token);
export const createProposalFromMinuteDraft = (token: string, draftId: string, candidateIds: string[]) => request<Proposal>(
  `/api/minutes/drafts/${draftId}/proposal`,
  { method: "POST", body: JSON.stringify({ candidate_ids: candidateIds }) }, token);
export async function downloadMinuteDraftXlsx(token: string, draftId: string): Promise<void> {
  const response = await fetch(`/api/minutes/drafts/${draftId}/xlsx`, { headers: { Authorization: `Bearer ${token}` } });
  if (!response.ok) throw new ApiError("No fue posible generar el Excel.", response.status);
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  const disposition = response.headers.get("Content-Disposition") ?? "";
  anchor.download = disposition.match(/filename="?([^";]+)"?/)?.[1] ?? "plan_trabajo_jira.xlsx";
  anchor.click();
  URL.revokeObjectURL(url);
}
export const getMinutesEnrichment = (token: string, proposalId: string) => request<MinutesEnrichment>(
  `/api/proposals/${proposalId}/enrichment`, {}, token,
);
export const bulkUpdateProposal = (
  token: string,
  proposalId: string,
  field: "tipo_seguimiento" | "work_type" | "sprint",
  value: string,
  rowIds?: string[],
) => request<Proposal>(
  `/api/proposals/${proposalId}/bulk-update`,
  { method: "POST", body: JSON.stringify({ field, value, row_ids: rowIds ?? null }) }, token,
);

export const excludeProposalItems = (
  token: string,
  proposalId: string,
  rowIds: string[],
  reason: string,
) => request<Proposal>(
  `/api/proposals/${proposalId}/exclude`,
  { method: "POST", body: JSON.stringify({ row_ids: rowIds, reason }) },
  token,
);
export interface MinutesItemEdit {
  title: string;
  description: string;
  responsible_candidate_text: string | null;
  area_responsable?: string | null;
  due_date_candidate: string | null;
  project_or_front: string | null;
  context: string | null;
  comments: string | null;
}
export const editMinutesItem = (token: string, id: string, rowId: string, edit: MinutesItemEdit) => request<Proposal>(
  `/api/proposals/${id}/items/${rowId}`, { method: "PATCH", body: JSON.stringify(edit) }, token,
);

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

export function trashProposal(
  token: string,
  proposalId: string,
): Promise<ProposalSummary> {
  return request<ProposalSummary>(
    `/api/proposals/${proposalId}/trash`,
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

export function permanentlyDeleteProposal(
  token: string,
  proposalId: string,
): Promise<{ proposal_id: string; permanently_deleted: boolean }> {
  return request<{ proposal_id: string; permanently_deleted: boolean }>(
    `/api/proposals/${proposalId}/permanent`,
    { method: "DELETE" },
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

const atlassianStatusInFlight = new Map<string, Promise<AtlassianStatus>>();

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
  const existing = atlassianStatusInFlight.get(token);
  if (existing) return existing;
  const pending = request<AtlassianStatus>("/api/integrations/atlassian/status", { signal: AbortSignal.timeout(100000) }, token)
    .finally(() => atlassianStatusInFlight.delete(token));
  atlassianStatusInFlight.set(token, pending);
  return pending;
}

export function diagnoseAtlassian(token: string): Promise<AtlassianStatus> {
  return request<AtlassianStatus>('/api/integrations/atlassian/diagnose',
    { method: 'POST', signal: AbortSignal.timeout(45000) }, token);
}

export function getJiraWriteLock(token: string): Promise<JiraWriteLockStatus> {
  return request<JiraWriteLockStatus>('/api/jira/write-lock', {}, token);
}

export function unlockJiraWrites(token: string): Promise<JiraWriteLockStatus> {
  return request<JiraWriteLockStatus>('/api/jira/write-lock/unlock', { method: 'POST' }, token);
}

export function lockJiraWrites(token: string): Promise<JiraWriteLockStatus> {
  return request<JiraWriteLockStatus>('/api/jira/write-lock/lock', { method: 'POST' }, token);
}

export function connectAtlassian(
  token: string,
): Promise<{ authorization_url: string; phase: string }> {
  return request<{ authorization_url: string; phase: string }>(
    "/api/integrations/atlassian/connect",
    { method: "POST", signal: AbortSignal.timeout(40000) },
    token,
  );
}

export function connectAtlassianExternal(
  token: string,
): Promise<{ authorization_url: string; phase: string; browser: string }> {
  return request<{ authorization_url: string; phase: string; browser: string }>(
    "/api/integrations/atlassian/connect/external",
    { method: "POST", signal: AbortSignal.timeout(40000) },
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
    { method: "POST", signal: AbortSignal.timeout(100000) },
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

const ASSIGNEE_CACHE_TTL_MS = 45_000;
const assigneeLookupCache = new Map<string, { expiresAt: number; value: JiraAssignee[] }>();
const assigneeLookupInFlight = new Map<string, Promise<JiraAssignee[]>>();
function tokenFingerprint(token: string): string {
  let hash = 2166136261;
  for (let index = 0; index < token.length; index += 1) hash = Math.imul(hash ^ token.charCodeAt(index), 16777619);
  return (hash >>> 0).toString(16);
}
export function findJiraAssigneesCached(token: string, space: string, query: string): Promise<JiraAssignee[]> {
  const normalized = query.trim().toLocaleLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g, "");
  const key = `${tokenFingerprint(token)}:${space.toUpperCase()}:${normalized}`;
  const cached = assigneeLookupCache.get(key);
  if (cached && cached.expiresAt > Date.now()) return Promise.resolve(cached.value);
  const pending = assigneeLookupInFlight.get(key);
  if (pending) return pending;
  const requestPromise = findJiraAssignees(token, space, query).then(value => {
    assigneeLookupCache.set(key, { expiresAt: Date.now() + ASSIGNEE_CACHE_TTL_MS, value });
    return value;
  }).finally(() => assigneeLookupInFlight.delete(key));
  assigneeLookupInFlight.set(key, requestPromise);
  return requestPromise;
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
    tipo_seguimiento: string | null;
    review_note: string | null;
    assignee_account_id: string | null;
    assignee_query: string | null;
    parent_row_id: string | null;
    confirm_source_state: boolean;
    confirm_work_type: boolean;
    confirm_reactivation: boolean;
    due_date_candidate?: string | null;
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

export function revalidateObjective4C1Batch(
  token: string,
  executionId: string,
): Promise<Objective4C1Batch> {
  return request<Objective4C1Batch>(
    `/api/objectives/4c1/batches/${executionId}/revalidate`,
    { method: "POST" },
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
