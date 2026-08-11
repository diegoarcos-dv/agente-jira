import { FormEvent, useEffect, useMemo, useState } from "react";
import {
  ApiError,
  approveProposalAndDryRun,
  archiveProposal,
  cancelObjective4ASimulation,
  confirmObjective4BWrite,
  confirmObjective4ASimulation,
  connectAtlassian,
  createProposal,
  disconnectAtlassian,
  downloadDryRunEvidence,
  downloadObjective4AEvidence,
  downloadObjective4BEvidence,
  downloadObjective4C1Evidence,
  executeObjective4C1Batch,
  executeObjective4BWrite,
  findJiraAssignees,
  listJiraSprints,
  generateJiraDryRun,
  getAtlassianStatus,
  getLatestJiraDryRun,
  getLatestObjective4ASimulation,
  getLatestObjective4C1Batch,
  getObjective4AReadiness,
  getObjective4C2Progress,
  getProposal,
  listProposals,
  login,
  prepareObjective4ASimulation,
  prepareObjective4BWrite,
  prepareObjective4C1Batch,
  confirmObjective4C1Batch,
  reactivateProposalItem,
  refreshAtlassian,
  renameProposal,
  reopenProposal,
  restoreProposal,
  runObjective4ASimulation,
  updateProposalItem,
  updateProposalDefaults,
} from "./api";
import type {
  AtlassianStatus,
  Decision,
  JiraAssignee,
  JiraCorrectionItem,
  JiraDryRun,
  JiraSprint,
  Objective4AIntent,
  Objective4AReadiness,
  Objective4C1Batch,
  Objective4C2Progress,
  Proposal,
  ProposalDefaults,
  ProposalItem,
  ProposalSummary,
  ReviewRequirement,
  Session,
  Space,
  WorkType,
} from "./types";

const SESSION_KEY = "agente-jira-local-session";
const SIDEBAR_KEY = "agente-jira-sidebar-collapsed";

function normalizeIdentity(value: string | null | undefined): string {
  return (value ?? "")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .trim()
    .replace(/\s+/g, " ")
    .toLocaleLowerCase();
}

function readSession(): Session | null {
  try {
    const value = sessionStorage.getItem(SESSION_KEY);
    return value ? (JSON.parse(value) as Session) : null;
  } catch {
    return null;
  }
}

function Logo() {
  return (
    <div className="logo" aria-label="Agente Jira">
      <span className="logo-mark">AJ</span>
      <span>
        <strong>Agente Jira</strong>
        <small>Propuestas controladas</small>
      </span>
    </div>
  );
}

function LoginScreen({ onLogin }: { onLogin: (session: Session) => void }) {
  const [username, setUsername] = useState("admin@agentejira.local");
  const [password, setPassword] = useState("AgenteJira2026!");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [showPassword, setShowPassword] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setLoading(true);
    setError("");
    try {
      onLogin(await login(username, password));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "No fue posible iniciar sesión.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="login-layout">
      <section className="login-story">
        <Logo />
        <div className="story-copy">
          <span className="eyebrow">Entorno local seguro</span>
          <h1>Convierte un plan en una propuesta que sí puedes revisar.</h1>
          <p>
            Carga la Plantilla Excel v1.1, concentra las excepciones y conserva
            siempre el vínculo entre el origen y la propuesta.
          </p>
          <ul className="feature-list">
            <li>Conexión personal a Jira mediante OAuth 2.1.</li>
            <li>Metadatos y responsables consultados directamente en Jira.</li>
            <li>Escritura bloqueada por defecto; el envío controlado exige confirmación explícita.</li>
          </ul>
        </div>
        <p className="security-note">Desarrollo local · autorización Atlassian cifrada para el usuario de Windows</p>
      </section>
      <section className="login-panel">
        <form className="login-card" onSubmit={submit}>
          <span className="eyebrow">Acceso de desarrollo</span>
          <h2>Inicia sesión</h2>
          <p className="muted">
            Esta interfaz está preparada para sustituir el proveedor local por Cognito.
          </p>
          <label>
            Correo
            <input
              type="email"
              value={username}
              onChange={(event) => setUsername(event.target.value)}
              autoComplete="username"
              required
            />
          </label>
          <label>
            Contraseña
            <span className="password-field">
              <input
                type={showPassword ? "text" : "password"}
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                autoComplete="current-password"
                required
              />
              <button
                type="button"
                className="password-toggle"
                onClick={() => setShowPassword((value) => !value)}
                aria-label={showPassword ? "Ocultar contraseña" : "Mostrar contraseña"}
              >
                {showPassword ? "Ocultar" : "Mostrar"}
              </button>
            </span>
          </label>
          <p className="login-help">
            La recuperación de contraseña se habilitará con Cognito en el entorno corporativo.
          </p>
          {error && <div className="alert error">{error}</div>}
          <button className="button primary full" disabled={loading}>
            {loading ? "Validando…" : "Entrar al espacio de trabajo"}
          </button>
        </form>
      </section>
    </main>
  );
}

interface UploadPanelProps {
  token: string;
  onCreated: (proposal: Proposal) => void;
}

function UploadPanel({ token, onCreated }: UploadPanelProps) {
  const [file, setFile] = useState<File | null>(null);
  const [space, setSpace] = useState<Space>("AT");
  const [expanded, setExpanded] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [sprints, setSprints] = useState<JiraSprint[]>([]);

  useEffect(() => {
    let active = true;
    listJiraSprints(token, space)
      .then((result) => { if (active) setSprints(result); })
      .catch(() => { if (active) setSprints([]); });
    return () => { active = false; };
  }, [token, space]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!file) return;
    setLoading(true);
    setError(null);
    const values = new FormData(event.currentTarget);
    values.set("file", file);
    values.set("space", space);
    try {
      onCreated(await createProposal(token, values));
    } catch (reason) {
      setError(
        reason instanceof ApiError
          ? reason
          : new ApiError("No fue posible procesar el archivo.", 500),
      );
    } finally {
      setLoading(false);
    }
  }

  return (
    <section className="upload-card">
      <div className="section-heading">
        <div>
          <span className="eyebrow">Nueva propuesta</span>
          <h2>Carga el plan de trabajo</h2>
        </div>
        <a className="text-link" href="/api/template">
          Descargar plantilla v1.1
        </a>
      </div>
      <form onSubmit={submit}>
        <label className={`drop-zone ${file ? "has-file" : ""}`}>
          <input
            type="file"
            accept=".xlsx"
            onChange={(event) => setFile(event.target.files?.[0] ?? null)}
            required
          />
          <span className="upload-icon">↑</span>
          <strong>{file ? file.name : "Selecciona la Plantilla Excel v1.1"}</strong>
          <small>
            {file
              ? `${(file.size / 1024).toFixed(1)} KB · lista para validar`
              : "Archivo .xlsx, máximo 10 MB"}
          </small>
        </label>
        <div className="form-grid">
          <label>
            Space del plan
            <select value={space} onChange={(event) => setSpace(event.target.value as Space)}>
              <option value="AT">AT · Team-managed</option>
              <option value="ASIT">ASIT · Company-managed</option>
              <option value="MTTI">MTTI · Company-managed</option>
            </select>
          </label>
          <button
            type="button"
            className="button secondary optional-toggle"
            onClick={() => setExpanded((value) => !value)}
          >
            {expanded ? "Ocultar valores opcionales" : "Agregar valores generales"}
          </button>
        </div>
        {expanded && (
          <div className="optional-grid">
            <label>Iniciativa<input name="iniciativa" /></label>
            <label>Línea de trabajo<input name="linea_trabajo" /></label>
            <label>
              Sprint
              {sprints.length > 0 ? (
                <select name="sprint" defaultValue="">
                  <option value="">
                    {sprints.filter((sprint) => sprint.state === "active").length > 1
                      ? "Selecciona un Sprint (hay varios activos)"
                      : sprints.some((sprint) => sprint.state === "active")
                        ? "Automático: usar el único Sprint activo"
                        : "Sin Sprint"}
                  </option>
                  {sprints.map((sprint) => (
                    <option key={sprint.id} value={sprint.name}>
                      {sprint.name} · {sprint.state === "active" ? "Activo" : "Futuro"}
                    </option>
                  ))}
                </select>
              ) : (
                <input name="sprint" placeholder="Nombre exacto en Jira (opcional)" />
              )}
            </label>
            <label>Tipo de seguimiento<input name="tipo_seguimiento" /></label>
            <label>Semáforo<input name="semaforo" /></label>
          </div>
        )}
        {error && (
          <div className="alert error" role="alert">
            <strong>{error.message}</strong>
            {error.issues.length > 0 && (
              <ul>
                {error.issues.map((issue, index) => (
                  <li key={`${issue.code}-${index}`}>
                    {issue.row ? `Fila ${issue.row}${issue.column ? `, ${issue.column}` : ""}: ` : ""}
                    {issue.message}
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
        <div className="form-actions">
          <span className="muted">La carga no ejecuta ninguna acción en Jira.</span>
          <button className="button primary" disabled={!file || loading}>
            {loading ? "Validando y generando…" : "Generar propuesta"}
          </button>
        </div>
      </form>
    </section>
  );
}

const DECISION_LABELS: Record<Decision, string> = {
  INCLUIR: "Listas",
  REVISAR: "Requieren revisión",
  EXCLUIR: "Excluidas",
};

type ProposalTab = Decision | "TODAS" | "JIRA_BLOCKED" | "JIRA_ACTION" | "JIRA_TECHNICAL" | "JIRA_CORRECTED";

function StatusPill({ decision }: { decision: Decision }) {
  return <span className={`status-pill ${decision.toLowerCase()}`}>{DECISION_LABELS[decision]}</span>;
}

function ProposalHeader({
  proposal,
  displayName,
  onRename,
}: {
  proposal: Proposal;
  displayName: string;
  onRename: (name: string) => Promise<void>;
}) {
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(displayName);
  const [saving, setSaving] = useState(false);
  const counts = proposal.items.reduce(
    (result, item) => {
      result[item.generated.decision] += 1;
      return result;
    },
    { INCLUIR: 0, REVISAR: 0, EXCLUIR: 0 } as Record<Decision, number>,
  );
  return (
    <div className="proposal-header">
      <div>
        <span className="eyebrow">Propuesta {proposal.proposal_id.slice(0, 8)}</span>
        {editing ? (
          <form
            className="rename-form"
            onSubmit={(event) => {
              event.preventDefault();
              setSaving(true);
              void onRename(name.trim())
                .then(() => setEditing(false))
                .finally(() => setSaving(false));
            }}
          >
            <input
              aria-label="Nombre de la propuesta"
              value={name}
              onChange={(event) => setName(event.target.value)}
              maxLength={120}
              required
              autoFocus
            />
            <button className="button primary" disabled={saving}>Guardar nombre</button>
            <button type="button" className="button ghost" onClick={() => { setName(displayName); setEditing(false); }}>Cancelar</button>
          </form>
        ) : (
          <div className="proposal-title-row">
            <h2>{displayName}</h2>
            <button className="button ghost compact" onClick={() => setEditing(true)}>Editar nombre</button>
          </div>
        )}
        <p className="muted">
          Space {proposal.defaults.space} · versión {proposal.version} · plantilla{" "}
          {proposal.template_version}
        </p>
        <p className="source-filename">Archivo fuente inmutable: {proposal.source_file.name}</p>
      </div>
      <div className="metrics" aria-label="Resumen de decisiones">
        <div><strong>{counts.INCLUIR}</strong><span>listas</span></div>
        <div className="review"><strong>{counts.REVISAR}</strong><span>por revisar</span></div>
        <div><strong>{counts.EXCLUIR}</strong><span>excluidas</span></div>
      </div>
    </div>
  );
}

interface DetailPanelProps {
  token: string;
  item: ProposalItem;
  proposalItems: ProposalItem[];
  onClose: () => void;
  locked: boolean;
  correction?: JiraCorrectionItem | null;
  onReactivate: (reason: string) => Promise<void>;
  onSave: (values: {
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
  }) => Promise<void>;
}

function isRequirementResolved(
  requirement: ReviewRequirement,
  values: {
    assigneeAccountId: string;
    confirmSourceState: boolean;
    confirmWorkType: boolean;
    workType: WorkType;
    parentRowId: string;
    confirmReactivation: boolean;
  },
): boolean {
  if (requirement.code === "ASSIGNEE_UNRESOLVED") return Boolean(values.assigneeAccountId);
  if (requirement.code === "SOURCE_STATE_UNCONFIRMED") return values.confirmSourceState;
  if (requirement.code === "WORK_TYPE_UNCONFIRMED") return values.confirmWorkType;
  if (requirement.code === "SUBTASK_PARENT_MISSING") return values.workType !== "Subtask" || Boolean(values.parentRowId);
  if (requirement.code === "REACTIVATION_REVIEW_REQUIRED") return values.confirmReactivation;
  return false;
}

function DetailPanel({ token, item, proposalItems, onClose, onSave, onReactivate, locked, correction }: DetailPanelProps) {
  const [title, setTitle] = useState(item.generated.title);
  const [description, setDescription] = useState(item.generated.description);
  const [workType, setWorkType] = useState(item.generated.work_type);
  const [parentRowId, setParentRowId] = useState(item.generated.parent_row_id ?? "");
  const [note, setNote] = useState(item.review.review_note ?? "");
  const [confirmSourceState, setConfirmSourceState] = useState(false);
  const [confirmWorkType, setConfirmWorkType] = useState(false);
  const [confirmReactivation, setConfirmReactivation] = useState(false);
  const [reactivationReason, setReactivationReason] = useState("");
  const [assigneeAccountId, setAssigneeAccountId] = useState(
    item.generated.assignee.account_id?.startsWith("local-account-")
      ? ""
      : item.generated.assignee.account_id ?? "",
  );
  const [pendingAssignee, setPendingAssignee] = useState<JiraAssignee | null>(null);
  const [assigneeQuery, setAssigneeQuery] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [jiraQuery, setJiraQuery] = useState(item.generated.assignee.display_name || item.source.responsable_display);
  const [jiraResults, setJiraResults] = useState<JiraAssignee[]>([]);
  const [jiraLookupPerformed, setJiraLookupPerformed] = useState(false);
  const [jiraSearching, setJiraSearching] = useState(false);
  const [jiraError, setJiraError] = useState("");

  const requirements = item.validation.pending_requirements ?? [];
  const requirementValues = {
    assigneeAccountId,
    confirmSourceState,
    confirmWorkType,
    workType,
    parentRowId,
    confirmReactivation,
  };
  const requirementsWithState = requirements.map((requirement) => ({
    ...requirement,
    resolved: isRequirementResolved(requirement, requirementValues),
  }));
  const unresolvedCount = requirementsWithState.filter((requirement) => !requirement.resolved).length;
  async function submit(event: FormEvent) {
    event.preventDefault();
    setSaving(true);
    try {
      await onSave({
        title,
        description,
        work_type: workType,
        review_note: note.trim() || null,
        assignee_account_id: pendingAssignee?.account_id ?? null,
        assignee_query: pendingAssignee ? assigneeQuery : null,
        parent_row_id: parentRowId || null,
        confirm_source_state: confirmSourceState,
        confirm_work_type: confirmWorkType,
        confirm_reactivation: confirmReactivation,
      });
    } finally {
      setSaving(false);
    }
  }

  const allowedParentTypes: WorkType[] = workType === "Subtask"
    ? ["Task", "Bug", "Story"]
    : (["Task", "Bug", "Story"] as WorkType[]).includes(workType)
      ? ["Epic"]
      : [];
  const parentCandidates = proposalItems.filter((candidate) =>
    candidate.generated.row_id !== item.generated.row_id
    && candidate.generated.decision !== "EXCLUIR"
    && allowedParentTypes.includes(candidate.generated.work_type),
  );

  function changeWorkType(next: WorkType) {
    setWorkType(next);
    const nextAllowed: WorkType[] = next === "Subtask"
      ? ["Task", "Bug", "Story"]
      : (["Task", "Bug", "Story"] as WorkType[]).includes(next) ? ["Epic"] : [];
    const currentParent = proposalItems.find((candidate) => candidate.generated.row_id === parentRowId);
    if (!currentParent || !nextAllowed.includes(currentParent.generated.work_type)) setParentRowId("");
  }

  async function searchJiraAssignees() {
    if (jiraQuery.trim().length < 2) return;
    setJiraSearching(true);
    setJiraError("");
    setJiraLookupPerformed(false);
    try {
      setJiraResults(await findJiraAssignees(token, item.generated.space, jiraQuery.trim()));
      setJiraLookupPerformed(true);
    } catch (reason) {
      setJiraError(reason instanceof Error ? reason.message : "No fue posible buscar en Jira.");
    } finally {
      setJiraSearching(false);
    }
  }

  function chooseJiraAssignee(assignee: JiraAssignee) {
    setJiraError("");
    setPendingAssignee(assignee);
    setAssigneeAccountId(assignee.account_id ?? "");
    setAssigneeQuery(jiraQuery.trim());
    setJiraResults([]);
    setJiraLookupPerformed(false);
  }

  async function reactivate() {
    if (reactivationReason.trim().length < 5) return;
    setSaving(true);
    try {
      await onReactivate(reactivationReason.trim());
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="drawer-backdrop" role="presentation" onMouseDown={onClose}>
      <aside
        className="detail-drawer"
        aria-label={`Editar ${item.generated.row_id}`}
        onMouseDown={(event) => event.stopPropagation()}
      >
        <div className="drawer-heading">
          <div>
            <span className="eyebrow">Fila {item.source.source_row}</span>
            <h2>Origen y propuesta</h2>
          </div>
          <button className="icon-button" onClick={onClose} aria-label="Cerrar">×</button>
        </div>
        {correction && (
          <section className={`jira-correction-card ${correction.category === "TECHNICAL" ? "technical" : "action"}`} aria-label={correction.category === "TECHNICAL" ? "Validación técnica" : "Corrección requerida"}>
            <span className="eyebrow">
              {correction.category === "TECHNICAL" ? "Validación técnica" : "Corrección requerida"}
            </span>
            <strong>{correction.instruction}</strong>
            <ul>
              {correction.issues.map((issue) => <li key={`${issue.code}-${issue.field}`}>{issue.message}</li>)}
            </ul>
            {correction.category === "USER_ACTION" && correction.issues.some((issue) => issue.field === "assignee") && (
              <button
                type="button"
                className="button primary compact"
                onClick={() => document.getElementById(`jira-assignee-${item.generated.row_id}`)?.scrollIntoView({ behavior: "smooth", block: "start" })}
              >
                Ir a corregir responsable
              </button>
            )}
          </section>
        )}
        <div className="source-card">
          <h3>Dato de origen</h3>
          <dl>
            <div><dt>Actividad</dt><dd>{item.source.actividad}</dd></div>
            <div><dt>Responsable</dt><dd>{item.source.responsable_display}</dd></div>
            {item.source.frente_trabajo_origen && (
              <div><dt>Frente</dt><dd>{item.source.frente_trabajo_origen}</dd></div>
            )}
            <div><dt>Estado</dt><dd>{item.source.estado_actual}</dd></div>
          </dl>
        </div>
        <form className="edit-form" onSubmit={submit}>
          <div className="edit-heading">
            <div>
              <h3>Propuesta editable</h3>
              <p>La decisión se recalcula al guardar; no necesitas cambiarla manualmente.</p>
            </div>
            <StatusPill decision={item.generated.decision} />
          </div>
          {item.generated.decision === "REVISAR" && (
            <section className="requirements-card" aria-label="Pendientes por resolver">
              <div>
                <span className="eyebrow">Pendientes por resolver</span>
                <strong>
                  {unresolvedCount === 0
                    ? "Todo listo para volver a validar"
                    : `${unresolvedCount} ${unresolvedCount === 1 ? "pendiente" : "pendientes"}`}
                </strong>
              </div>
              <ul>
                {requirementsWithState.map((requirement) => (
                  <li className={requirement.resolved ? "resolved" : ""} key={requirement.code}>
                    <span>{requirement.resolved ? "✓" : "!"}</span>
                    {requirement.message}
                  </li>
                ))}
              </ul>
            </section>
          )}
          {item.generated.decision === "INCLUIR" && !correction && (
            <div className="decision-note ready">
              <strong>Actividad lista</strong>
              <span>Actualmente no tiene pendientes de revisión.</span>
            </div>
          )}
          {item.generated.decision === "EXCLUIR" && (
            <div className="decision-note excluded">
              <strong>Actividad excluida</strong>
              <span>{item.generated.decision_reason}</span>
              {!locked && (
                <div className="reactivation-form">
                  <label>
                    Motivo para recuperar la actividad
                    <textarea
                      rows={3}
                      value={reactivationReason}
                      onChange={(event) => setReactivationReason(event.target.value)}
                      placeholder="Explica por qué debe volver a revisión"
                    />
                  </label>
                  <button
                    type="button"
                    className="button secondary"
                    disabled={saving || reactivationReason.trim().length < 5}
                    onClick={() => void reactivate()}
                  >
                    Reactivar y revisar
                  </button>
                </div>
              )}
            </div>
          )}
          {item.review.source_state_override && (
            <div className="audit-note">
              <strong>Reactivación registrada</strong>
              <span>{item.review.source_state_override_reason}</span>
              <small>{item.review.source_state_override_by} · {item.review.source_state_override_at}</small>
            </div>
          )}
          <label>Título<input value={title} onChange={(event) => setTitle(event.target.value)} required disabled={locked || item.generated.decision === "EXCLUIR"} /></label>
          <label>
            Work Type
            <select value={workType} onChange={(event) => changeWorkType(event.target.value as WorkType)} disabled={locked || item.generated.decision === "EXCLUIR"}>
              {(["Epic", "Story", "Task", "Bug", "Subtask"] as WorkType[]).map((type) => (
                <option key={type}>{type}</option>
              ))}
            </select>
          </label>
          {allowedParentTypes.length > 0 && (
            <label>
              Actividad padre {workType === "Subtask" ? "(obligatoria)" : "(opcional)"}
              <select
                value={parentRowId}
                onChange={(event) => setParentRowId(event.target.value)}
                required={workType === "Subtask"}
                disabled={locked || item.generated.decision === "EXCLUIR"}
              >
                <option value="">{workType === "Subtask" ? "Selecciona una actividad padre" : "Sin Epic padre"}</option>
                {parentCandidates.map((candidate) => (
                  <option key={candidate.generated.row_id} value={candidate.generated.row_id}>
                    {candidate.generated.row_id} · {candidate.generated.work_type} · {candidate.generated.title}
                  </option>
                ))}
              </select>
              <small>
                {workType === "Subtask"
                  ? "Jira requiere una Task, Bug o Story como padre directo."
                  : "Si la seleccionas, Jira registrará esta actividad debajo de la Epic."}
              </small>
            </label>
          )}
          {requirements.some((requirement) => requirement.code === "WORK_TYPE_UNCONFIRMED") && (
            <label className="confirmation-row">
              <input
                type="checkbox"
                checked={confirmWorkType}
                onChange={(event) => setConfirmWorkType(event.target.checked)}
              />
              Confirmo que el Work Type seleccionado es correcto.
            </label>
          )}
          {requirements.some((requirement) => requirement.code === "REACTIVATION_REVIEW_REQUIRED") && (
            <label className="confirmation-row">
              <input
                type="checkbox"
                checked={confirmReactivation}
                onChange={(event) => setConfirmReactivation(event.target.checked)}
              />
              Revisé la actividad recuperada y confirmo que debe continuar en la propuesta.
            </label>
          )}
          <label>Descripción<textarea rows={7} value={description} onChange={(event) => setDescription(event.target.value)} required disabled={locked || item.generated.decision === "EXCLUIR"} /></label>
          <label>Nota de revisión<textarea rows={2} value={note} onChange={(event) => setNote(event.target.value)} disabled={locked || item.generated.decision === "EXCLUIR"} /></label>
          {!locked && item.generated.decision !== "EXCLUIR" && (
            <section id={`jira-assignee-${item.generated.row_id}`} className="jira-assignee-editor" aria-label="Corregir responsable con Jira real">
              <div>
                <span className="eyebrow">Responsable en Jira</span>
                <p>Las opciones se consultan directamente en Jira. Busca el nombre completo o correo y selecciona la cuenta correcta.</p>
              </div>
              <div className="jira-assignee-search">
                <input
                  value={jiraQuery}
                  onChange={(event) => { setJiraQuery(event.target.value); setJiraLookupPerformed(false); }}
                  aria-label="Buscar cuenta Jira para la actividad"
                  placeholder="Nombre completo o correo corporativo"
                />
                <button type="button" className="button secondary" disabled={jiraSearching || jiraQuery.trim().length < 2} onClick={() => void searchJiraAssignees()}>
                  {jiraSearching ? "Buscando…" : "Buscar en Jira"}
                </button>
              </div>
              {jiraError && <div className="alert error">{jiraError}</div>}
              {jiraLookupPerformed && jiraResults.length === 0 && (
                <div className="assignee-empty" role="status">
                  <strong>No encontramos una cuenta Jira</strong>
                  <span>Verifica el nombre o utiliza el correo corporativo.</span>
                </div>
              )}
              {jiraResults.length > 0 && (
                <div className="jira-assignee-options">
                  {jiraResults.map((assignee) => (
                    <div key={assignee.account_id || assignee.display_name}>
                      <span><strong>{assignee.display_name}</strong><small>{assignee.email || "Cuenta Jira activa"}</small></span>
                      <button type="button" className="button secondary compact" disabled={jiraSearching || !assignee.account_id} onClick={() => chooseJiraAssignee(assignee)}>
                        Seleccionar responsable
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </section>
          )}
          {requirements.some((requirement) => requirement.code === "SOURCE_STATE_UNCONFIRMED") && (
            <label className="confirmation-row">
              <input
                type="checkbox"
                checked={confirmSourceState}
                onChange={(event) => setConfirmSourceState(event.target.checked)}
              />
              Confirmo que la actividad sigue vigente y debe considerarse en la propuesta.
            </label>
          )}
          <div className="assignee-resolution">
            <span>Responsable actual de la propuesta</span>
            <strong>{pendingAssignee?.display_name ?? item.generated.assignee.display_name}</strong>
            <small>
              {pendingAssignee
                ? "Cambio pendiente · se guardará junto con las demás ediciones"
                : item.generated.assignee.account_id?.startsWith("local-account-")
                ? "Pendiente de verificar contra Jira"
                : item.generated.assignee.email ?? "Cuenta Jira verificada"}
            </small>
          </div>
          <div className="drawer-actions">
            <button type="button" className="button secondary" onClick={onClose}>Cancelar</button>
            {!locked && item.generated.decision !== "EXCLUIR" && (
              <button className="button primary" disabled={saving || unresolvedCount > 0}>
                {saving ? "Guardando y validando…" : correction?.category === "USER_ACTION" ? "Guardar corrección y continuar" : "Guardar y volver a validar"}
              </button>
            )}
          </div>
        </form>
      </aside>
    </div>
  );
}

function DryRunPanel({ dryRun, currentProposalVersion }: { dryRun: JiraDryRun; currentProposalVersion: number }) {
  const stale = dryRun.stale || dryRun.proposal_version !== currentProposalVersion;
  const hasWarnings = dryRun.status === "READY_WITH_WARNINGS";
  const successful = dryRun.status !== "BLOCKED";
  return (
    <section className={`dry-run-panel ${successful ? "dry-run-ready" : "dry-run-blocked"} ${hasWarnings ? "dry-run-warning" : ""} ${stale ? "dry-run-stale" : ""}`} aria-label="Resultado de la validación con Jira">
      <div className="dry-run-heading">
        <div>
          <span className="eyebrow">Validación con Jira · sin escritura</span>
          <h3>{stale ? "Resultado histórico de la validación" : dryRun.status === "READY" ? "Prevalidación completada" : hasWarnings ? "Prevalidación completada con advertencias técnicas" : "Prevalidación requiere correcciones"}</h3>
          <p>
            Propuesta v{dryRun.proposal_version} · {dryRun.reused ? "resultado idempotente recuperado" : "nuevo registro de auditoría"}
          </p>
        </div>
        <div className="dry-run-metrics">
          <span><strong>{dryRun.summary.ready}</strong> Listas</span>
          <span><strong>{dryRun.summary.ready_with_warnings ?? 0}</strong> Con advertencias</span>
          <span><strong>{dryRun.summary.blocked}</strong> Bloqueadas</span>
          <span><strong>{dryRun.summary.skipped}</strong> Excluidas</span>
        </div>
      </div>
      {stale && (
        <div className="dry-run-stale-notice" role="status">
          Este resultado corresponde a la versión {dryRun.proposal_version}. Se conserva como evidencia histórica y no determina el estado de la versión actual {currentProposalVersion}.
        </div>
      )}
      <div className="dry-run-seal">
        <strong>✓ Cero escrituras Jira</strong>
        <span>{dryRun.dry_run_id}</span>
      </div>
      <div className="dry-run-items">
        {dryRun.items.map((item) => (
          <details key={item.row_id} open={item.status === "BLOCKED"}>
            <summary>
              <span>
                <strong>{item.row_id} · {item.title}</strong>
                <small>{item.space} · {item.work_type}</small>
              </span>
              <span className={`dry-run-status status-${item.status.toLocaleLowerCase()}`}>
                {item.status === "READY" ? "Lista" : item.status === "READY_WITH_WARNINGS" ? "Lista con advertencia" : item.status === "BLOCKED" ? "Bloqueada" : "Excluida"}
              </span>
            </summary>
            <div className="dry-run-detail">
              {item.assignee && (
                <p><b>Responsable Jira:</b> {item.assignee.display_name}</p>
              )}
              {item.sprint_resolution?.selected && (
                <p>
                  <b>Sprint resuelto:</b> {item.sprint_resolution.selected.name} · {item.sprint_resolution.selected.state === "active" ? "Activo" : "Futuro"}
                  {item.sprint_resolution.mode === "AUTO_SINGLE_ACTIVE" ? " · seleccionado automáticamente" : ""}
                </p>
              )}
              {item.idempotency_key && (
                <p><b>Clave idempotente:</b> <code>{item.idempotency_key}</code></p>
              )}
              {item.errors.length > 0 && (
                <ul className="dry-run-errors">
                  {item.errors.map((issue) => <li key={`${issue.code}-${issue.field}`}>{issue.message} <code>{issue.code}</code></li>)}
                </ul>
              )}
              {item.warnings.length > 0 && (
                <ul className="dry-run-warnings">
                  {item.warnings.map((issue) => <li key={`${issue.code}-${issue.field}`}>{issue.message}</li>)}
                </ul>
              )}
            </div>
          </details>
        ))}
      </div>
    </section>
  );
}

export function Objective4C1Panel({
  token,
  proposal,
  dryRun,
  onNewProposal,
  allowedWorkTypes = ["Task"],
}: {
  token: string;
  proposal: Proposal;
  dryRun: JiraDryRun;
  onNewProposal: () => void;
  allowedWorkTypes?: WorkType[];
}) {
  const eligible = dryRun.items.filter(
    (item) => (item.status === "READY" || item.status === "READY_WITH_WARNINGS")
      && item.space === "AT" && allowedWorkTypes.includes(item.work_type),
  );
  const multiType = allowedWorkTypes.length > 1;
  const hierarchyMode = allowedWorkTypes.includes("Epic") || allowedWorkTypes.includes("Subtask");
  const parentOf = (rowId: string) => {
    const item = dryRun.items.find((candidate) => candidate.row_id === rowId);
    const logicalParent = item?.logical_payload?.parent_row_id;
    return item?.parent_row_id ?? (typeof logicalParent === "string" ? logicalParent : null);
  };
  const dependencyAwareSelection = (rowIds: string[]) => {
    const available = new Set(rowIds);
    const result: string[] = [];
    for (const rowId of rowIds) {
      const parent = parentOf(rowId);
      if (parent && available.has(parent) && !result.includes(parent) && result.length < 5) result.push(parent);
      if (!result.includes(rowId) && result.length < 5) result.push(rowId);
      if (result.length === 5) break;
    }
    return result;
  };
  const [selected, setSelected] = useState<string[]>(dependencyAwareSelection(eligible.map((item) => item.row_id)));
  const [batch, setBatch] = useState<Objective4C1Batch | null>(null);
  const [progress, setProgress] = useState<Objective4C2Progress | null>(null);
  const [phrase, setPhrase] = useState("");
  const [expanded, setExpanded] = useState(true);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    setBatch(null);
    setPhrase("");
    Promise.allSettled([
      getLatestObjective4C1Batch(token, proposal.proposal_id),
      getObjective4C2Progress(token, proposal.proposal_id),
    ]).then(([latestResult, progressResult]) => {
      if (!active) return;
      const currentBatch = latestResult.status === "fulfilled"
        && latestResult.value.proposal_version === proposal.version
        && latestResult.value.dry_run_id === dryRun.dry_run_id
        ? latestResult.value : null;
      const currentProgress = progressResult.status === "fulfilled"
        && progressResult.value.proposal_version === proposal.version
        && progressResult.value.dry_run_id === dryRun.dry_run_id
        ? progressResult.value : null;
      setBatch(currentBatch);
      setProgress(currentProgress);
      if (currentBatch) {
        setSelected(currentBatch.items.map((item) => item.row_id));
      } else if (currentProgress) {
        setSelected(dependencyAwareSelection(currentProgress.available_row_ids));
      }
      if (latestResult.status === "rejected") {
        const reason = latestResult.reason;
        if (!(reason instanceof ApiError) || reason.status !== 404) {
          setError(reason instanceof Error ? reason.message : "No fue posible recuperar el lote.");
        }
      }
      if (progressResult.status === "rejected") {
        const reason = progressResult.reason;
        setError(reason instanceof Error ? reason.message : "No fue posible recuperar el avance del plan.");
      }
    });
    return () => { active = false; };
  }, [dryRun.dry_run_id, proposal.proposal_id, proposal.version, token]);

  function toggle(rowId: string) {
    setSelected((current) => {
      if (current.includes(rowId)) {
        return current.filter((value) => value !== rowId && parentOf(value) !== rowId);
      }
      const parent = parentOf(rowId);
      const additions = parent && selectable.some((item) => item.row_id === parent) && !current.includes(parent)
        ? [parent, rowId]
        : [rowId];
      return current.length + additions.length <= 5 ? [...current, ...additions] : current;
    });
  }

  async function prepare() {
    setLoading(true); setError("");
    try {
      setBatch(await prepareObjective4C1Batch(token, proposal.proposal_id, selected));
      setPhrase("");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "No fue posible preparar el lote.");
    } finally { setLoading(false); }
  }

  async function confirm() {
    if (!batch) return;
    setLoading(true); setError("");
    try {
      setBatch(await confirmObjective4C1Batch(token, batch.execution_id, batch.payload_hash, phrase));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "No fue posible confirmar el lote.");
    } finally { setLoading(false); }
  }

  async function execute() {
    if (!batch) return;
    setLoading(true); setError("");
    try {
      const result = await executeObjective4C1Batch(token, batch.execution_id);
      setBatch(result);
      setProgress(await getObjective4C2Progress(token, proposal.proposal_id));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "No fue posible ejecutar el lote.");
    } finally { setLoading(false); }
  }

  function continueWithNextBatch() {
    if (!progress) return;
    setBatch(null);
    setPhrase("");
    setError("");
    setSelected(dependencyAwareSelection(progress.available_row_ids));
  }

  const availableIds = new Set(progress?.available_row_ids ?? eligible.map((item) => item.row_id));
  const selectable = eligible.filter((item) => availableIds.has(item.row_id));

  const terminal = batch && ["COMPLETED", "STOPPED_REJECTED", "STOPPED_UNKNOWN", "STOPPED_UNVERIFIED"].includes(batch.status);
  const title = batch?.status === "COMPLETED" ? "Lote creado y verificado"
    : batch?.status.startsWith("STOPPED_") ? "Lote detenido de forma segura"
      : batch?.status === "BATCH_CONFIRMED" ? "Lote autorizado para escritura"
        : batch?.status === "BATCH_PREPARED" ? "Revisar y confirmar lote"
          : hierarchyMode ? "Crear actividades y sus relaciones" : "Crear un lote controlado de Tasks";

  return (
    <section id="controlled-batch" className="objective4a-panel current-step-card" aria-label="Lote controlado de Jira">
      <header className="objective4a-heading">
        <div>
          <span className="eyebrow">Paso actual · envío controlado</span>
          <h3>{multiType ? title.replace("Tasks", "actividades") : title}</h3>
          <p>Selecciona de 1 a 5 {hierarchyMode ? "actividades Task, Bug, Story, Epic o Subtask" : multiType ? "actividades Task, Bug o Story" : "Tasks"}. Se crearán una por una y el lote se detendrá ante la primera anomalía.</p>
        </div>
        <div className="section-heading-actions">
          <div className={`simulation-seal ${batch?.status === "COMPLETED" ? "real-success" : ""}`}>
            <strong>{batch ? `${batch.summary.created_verified ?? 0} de ${batch.summary.total} verificadas` : `${selected.length} seleccionadas`}</strong>
            <span>0 reintentos automáticos</span>
          </div>
          <button type="button" className="button ghost compact" aria-expanded={expanded} onClick={() => setExpanded((value) => !value)}>
            {expanded ? "Minimizar" : "Mostrar"}
          </button>
        </div>
      </header>
      {expanded && <div className="objective4a-content batch-flow">
        {error && <div className="alert error">{error}</div>}

        {!batch && <>
          <div className="batch-selection" role="group" aria-label="Actividades del lote">
            {selectable.map((item) => {
              const checked = selected.includes(item.row_id);
              const disabled = !checked && selected.length >= 5;
              return <label key={item.row_id} className={checked ? "selected" : ""}>
                <input type="checkbox" checked={checked} disabled={disabled} onChange={() => toggle(item.row_id)} />
                <span><strong>{item.title}</strong><small>{item.work_type} · {item.assignee?.display_name ?? "Sin responsable"} · {parentOf(item.row_id) ? `Padre ${parentOf(item.row_id)} · ` : ""}{item.sprint_resolution?.selected?.name ?? "Sin Sprint"}</small></span>
              </label>;
            })}
          </div>
          {progress && <div className="batch-progress" aria-label="Avance del plan">
            <span><strong>{progress.counts.created_verified}</strong> verificadas</span>
            <span><strong>{progress.counts.available}</strong> pendientes</span>
            <span><strong>{progress.batch_count}</strong> lotes registrados</span>
          </div>}
          {selectable.length > 5 && <p className="helper-text">Quedan {selectable.length} {multiType ? "actividades" : "Tasks"}; se seleccionaron las siguientes 5.</p>}
          {selectable.length === 0
            ? <div className="objective4a-warning"><strong>No quedan {multiType ? "actividades" : "Tasks"} disponibles</strong><span>Las elegibles ya fueron creadas, intentadas o reservadas por otro lote.</span></div>
            : <div className="objective4a-actions"><button className="button primary" disabled={loading || selected.length < 1 || selected.length > 5} onClick={() => void prepare()}>{loading ? "Preparando…" : `Preparar lote de ${selected.length} ${multiType ? (selected.length === 1 ? "actividad" : "actividades") : (selected.length === 1 ? "Task" : "Tasks")}`}</button></div>}
        </>}

        {batch?.status === "BATCH_PREPARED" && <section className="real-confirmation-card">
          <span className="eyebrow">Confirmación final</span>
          <h4>Se crearán {batch.items.length} {multiType ? "actividades" : "Tasks"} reales en AT, en este orden</h4>
          <ol className="batch-items">
            {batch.items.map((item) => <li key={item.row_id}><strong>{item.preview.source_title}</strong><span>{item.preview.work_type} · {item.preview.assignee?.display_name} · {item.preview.parent_row_id ? `Padre ${item.preview.parent_issue_key ?? item.preview.parent_row_id} · ` : ""}{item.sprint_resolution?.selected?.name ?? "Sin Sprint"}</span><small>Nombre identificable: {item.preview.title}</small></li>)}
          </ol>
          <p>Si una falla o no puede verificarse, las restantes no se intentarán. No hay rollback ni reintentos automáticos.</p>
          <label>Escribe <strong>{batch.confirmation_phrase}</strong>
            <input value={phrase} onChange={(event) => setPhrase(event.target.value)} aria-label="Frase de confirmación del lote" autoComplete="off" />
          </label>
          <details className="payload-details"><summary>Ver huellas técnicas del lote</summary><code>{JSON.stringify(batch.items.map((item) => ({ row_id: item.row_id, payload_hash: item.payload_hash, idempotency_key: item.idempotency_key })), null, 2)}</code><small>SHA-256 del lote: {batch.payload_hash}</small></details>
          <div className="objective4a-actions"><button className="button primary danger" disabled={loading || phrase.trim().toUpperCase() !== batch.confirmation_phrase} onClick={() => void confirm()}>{loading ? "Confirmando…" : "Confirmar lote real"}</button></div>
        </section>}

        {batch?.status === "BATCH_CONFIRMED" && <section className="real-execute-card">
          <div><span className="eyebrow">Autorización registrada</span><strong>La siguiente acción sí creará {batch.items.length} {multiType ? "actividades" : "Tasks"} en Jira</strong><p>Antes de escribir se revalidarán todos los Sprints. Después cada actividad se creará y comprobará por separado.</p></div>
          <button className="button primary danger" disabled={loading} onClick={() => void execute()}>{loading ? "Creando y verificando…" : `Crear ${batch.items.length} ${multiType ? "actividades" : "Tasks"} reales en AT`}</button>
        </section>}

        {batch?.status === "BATCH_RUNNING" && <section className="real-write-pending" role="status"><div><strong>Lote en ejecución o pendiente de conciliación</strong><p>No vuelvas a enviarlo automáticamente. Revisa Jira por las claves y la evidencia registrada.</p></div></section>}

        {terminal && batch && <section className={`real-write-result ${batch.status === "COMPLETED" ? "created_verified" : "unknown"}`}>
          <div className="batch-result-content">
            <span className="eyebrow">Resultado consolidado</span>
            <strong>{batch.status === "COMPLETED" ? `Éxito: ${batch.summary.created_verified} ${multiType ? "actividades" : "Tasks"} creadas y verificadas` : "Ejecución detenida; las actividades pendientes no se intentaron"}</strong>
            <ol className="batch-items results">
              {batch.items.map((item) => <li key={item.row_id}>
                <span><strong>{item.preview.source_title}</strong><small>{item.status.replaceAll("_", " ")}{item.error ? ` · ${item.error}` : ""}</small></span>
                {item.resolved_parent && <small>Padre verificado: {item.resolved_parent.issue_key}</small>}
                {item.issue_url ? <a href={item.issue_url} target="_blank" rel="noreferrer">Abrir {item.issue_key}</a> : null}
              </li>)}
            </ol>
            <small>{batch.real_mcp_calls} llamadas MCP · {batch.automatic_retries} reintentos</small>
          </div>
          <div className="objective4a-actions">
            <button className="button secondary" onClick={() => void downloadObjective4C1Evidence(token, batch.execution_id)}>Descargar evidencia {batch.objective}</button>
            {(progress?.counts.available ?? 0) > 0
              ? <button className="button primary" onClick={continueWithNextBatch}>Preparar siguiente lote</button>
              : <button className="button secondary" onClick={onNewProposal}>Generar nueva propuesta</button>}
          </div>
        </section>}
      </div>}
    </section>
  );
}

function Objective4APanel({
  token,
  proposal,
  dryRun,
  onNewProposal,
}: {
  token: string;
  proposal: Proposal;
  dryRun: JiraDryRun;
  onNewProposal: () => void;
}) {
  const eligible = dryRun.items.filter(
    (item) =>
      (item.status === "READY" || item.status === "READY_WITH_WARNINGS")
      && item.space === "AT"
      && item.work_type === "Task",
  );
  const [rowId, setRowId] = useState(eligible[0]?.row_id ?? "");
  const [intent, setIntent] = useState<Objective4AIntent | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [expanded, setExpanded] = useState(true);
  const [fieldLabels, setFieldLabels] = useState<Record<string, string>>({});
  const [readiness, setReadiness] = useState<Objective4AReadiness | null>(null);
  const [realPhrase, setRealPhrase] = useState("");

  useEffect(() => {
    let active = true;
    setIntent(null);
    setConfirmed(false);
    getLatestObjective4ASimulation(token, proposal.proposal_id)
      .then((result) => {
        if (
          active
          && result.proposal_version === proposal.version
          && result.dry_run_id === dryRun.dry_run_id
        ) {
          setIntent(result);
          setRowId(result.row_id);
        }
      })
      .catch((reason) => {
        if (active && (!(reason instanceof ApiError) || reason.status !== 404)) {
          setError(reason instanceof Error ? reason.message : "No fue posible recuperar la simulación.");
        }
      });
    return () => { active = false; };
  }, [dryRun.dry_run_id, proposal.proposal_id, proposal.version, token]);

  useEffect(() => {
    let active = true;
    getAtlassianStatus(token)
      .then((result) => {
        if (!active || !result.snapshot) return;
        const labels: Record<string, string> = {};
        result.snapshot.spaces.forEach((space) => {
          space.work_types.forEach((workType) => {
            workType.fields.forEach((field) => {
              if (field.id && field.name) labels[field.id] = field.name;
            });
          });
        });
        setFieldLabels(labels);
      })
      .catch(() => setFieldLabels({}));
    return () => { active = false; };
  }, [token]);

  useEffect(() => {
    let active = true;
    getObjective4AReadiness(token)
      .then((result) => { if (active) setReadiness(result); })
      .catch(() => { if (active) setReadiness(null); });
    return () => { active = false; };
  }, [token]);

  async function prepare() {
    if (!rowId) return;
    setLoading(true);
    setError("");
    try {
      const result = await prepareObjective4ASimulation(
        token,
        proposal.proposal_id,
        rowId,
      );
      setIntent(result);
      setConfirmed(false);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "No fue posible preparar la simulación.");
    } finally {
      setLoading(false);
    }
  }

  async function confirm() {
    if (!intent || !confirmed) return;
    setLoading(true);
    setError("");
    try {
      setIntent(await confirmObjective4ASimulation(
        token,
        intent.execution_id,
        intent.payload_hash,
      ));
      setConfirmed(false);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "No fue posible confirmar.");
    } finally {
      setLoading(false);
    }
  }

  async function simulate() {
    if (!intent) return;
    setLoading(true);
    setError("");
    try {
      setIntent(await runObjective4ASimulation(token, intent.execution_id));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "No fue posible ejecutar la simulación.");
    } finally {
      setLoading(false);
    }
  }

  async function cancel() {
    if (!intent) return;
    setLoading(true);
    setError("");
    try {
      setIntent(await cancelObjective4ASimulation(token, intent.execution_id));
      setConfirmed(false);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "No fue posible cancelar.");
    } finally {
      setLoading(false);
    }
  }

  async function prepareRealWrite() {
    if (!intent) return;
    setLoading(true);
    setError("");
    try {
      setIntent(await prepareObjective4BWrite(token, intent.execution_id));
      setRealPhrase("");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "No fue posible preparar el envio real.");
    } finally {
      setLoading(false);
    }
  }

  async function confirmRealWrite() {
    if (!intent?.real_execution) return;
    setLoading(true);
    setError("");
    try {
      setIntent(await confirmObjective4BWrite(
        token,
        intent.execution_id,
        intent.real_execution.payload_hash,
        realPhrase,
      ));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "No fue posible confirmar el envio real.");
    } finally {
      setLoading(false);
    }
  }

  async function executeRealWrite() {
    if (!intent) return;
    setLoading(true);
    setError("");
    try {
      setIntent(await executeObjective4BWrite(token, intent.execution_id));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "No fue posible ejecutar el envio real.");
    } finally {
      setLoading(false);
    }
  }

  const terminal = intent && ["CANCELLED", "EXPIRED", "INVALIDATED"].includes(intent.status);
  const completedSimulation = intent && [
    "SIMULATED",
    "REAL_PREPARED",
    "REAL_CONFIRMED",
    "SUBMITTED",
    "CREATED_VERIFIED",
    "CREATED_UNVERIFIED",
    "REJECTED",
    "UNKNOWN",
  ].includes(intent.status);
  const rawFields = intent?.payload.arguments.fields;
  const standardFields = new Set(["summary", "description", "assignee", "project", "issuetype"]);
  const visibleFields = rawFields && typeof rawFields === "object" && !Array.isArray(rawFields)
    ? Object.entries(rawFields as Record<string, unknown>).filter(
        ([fieldId, value]) => !standardFields.has(fieldId.toLocaleLowerCase()) && value !== null && value !== "",
      )
    : [];

  function readableValue(value: unknown): string {
    if (typeof value === "string") return value;
    if (typeof value === "number" || typeof value === "boolean") return String(value);
    if (value && typeof value === "object") {
      const record = value as Record<string, unknown>;
      const preferred = record.value ?? record.name ?? record.displayName ?? record.id;
      if (preferred !== undefined) return String(preferred);
    }
    return JSON.stringify(value);
  }

  if (["CONTROLLED_BATCH", "CONTROLLED_MULTI_TYPE_BATCH", "CONTROLLED_HIERARCHY_BATCH"].includes(readiness?.policy?.mode ?? "")) {
    return <Objective4C1Panel token={token} proposal={proposal} dryRun={dryRun} onNewProposal={onNewProposal} allowedWorkTypes={readiness?.policy?.allowed_work_types ?? ["Task"]} />;
  }

  return (
    <section id="safe-simulation" className={`objective4a-panel current-step-card ${completedSimulation ? "objective4a-complete" : ""}`} aria-label="Prueba segura antes del envío">
      <header className="objective4a-heading">
        <div>
          <span className="eyebrow">Paso actual · prueba segura</span>
          <h3>{
            intent?.status === "CREATED_VERIFIED" ? "Task creada y verificada en Jira"
              : intent?.status === "CREATED_UNVERIFIED" ? "Task creada; verificación incompleta"
                : intent?.status === "REJECTED" ? "Jira rechazó la creación"
                  : intent?.status === "UNKNOWN" ? "Resultado incierto; no reintentar"
                    : ["REAL_PREPARED", "REAL_CONFIRMED", "SUBMITTED"].includes(intent?.status ?? "") ? "Envío real controlado"
                      : completedSimulation ? "Simulación local exitosa"
                        : "Probar una Task sin crearla en Jira"
          }</h3>
          <p>{completedSimulation ? "La simulación local terminó sin errores. El estado de la escritura real se muestra por separado." : "Selecciona una actividad, revisa cómo se enviaría y ejecuta una simulación local."}</p>
        </div>
        <div className="section-heading-actions">
          <div className={`simulation-seal ${intent?.status === "CREATED_VERIFIED" ? "real-success" : ""}`}>
            <strong>{intent?.status === "CREATED_VERIFIED" ? "1 Task verificada" : "0 escrituras en la simulación"}</strong>
            <span>{intent?.status === "CREATED_VERIFIED" ? "Jira real" : "Simulación local"}</span>
          </div>
          <button type="button" className="button ghost compact" aria-expanded={expanded} onClick={() => setExpanded((value) => !value)}>
            {expanded ? "Minimizar" : "Mostrar"}
          </button>
        </div>
      </header>

      {expanded && (
        <div className="objective4a-content">
          {error && <div className="alert error">{error}</div>}

          {completedSimulation && intent ? (
        <div className="controlled-write-flow">
          <section className="simulation-outcome success" aria-label="Resultado de la simulación local">
            <div>
              <span className="eyebrow">Simulación local exitosa</span>
              <strong>El payload se construyó, confirmó y procesó sin errores locales</strong>
              <ul className="execution-checks">
                <li>✓ Payload y huella confirmados</li>
                <li>✓ Simulador local: accepted=true</li>
                <li>✓ Cero llamadas MCP y cero escrituras durante la simulación</li>
              </ul>
              <small>{intent.simulation.result?.simulation_key} · {intent.execution_id}</small>
            </div>
            <button className="button secondary" onClick={() => void downloadObjective4AEvidence(token, intent.execution_id)}>Evidencia de simulación</button>
          </section>

          {intent.status === "SIMULATED" && readiness?.controlled_write_ready && (
            <section className="real-write-gate">
              <div>
                <span className="eyebrow">Siguiente paso · una escritura real</span>
                <strong>Preparar una sola Task en AT</strong>
                <p>Preparar no escribe todavía. Después verás el payload exacto y deberás confirmar expresamente la creación.</p>
              </div>
              <button className="button primary" disabled={loading} onClick={() => void prepareRealWrite()}>
                {loading ? "Preparando…" : "Preparar envío real"}
              </button>
            </section>
          )}

          {intent.status === "SIMULATED" && !readiness?.controlled_write_ready && (
            <section className="real-write-disabled">
              <div>
                <span className="eyebrow">Escritura real deshabilitada</span>
                <strong>El kill switch sigue en modo seguro</strong>
                <p>La simulación terminó correctamente. Para habilitar una única Task controlada, inicia la aplicación con <code>scripts\start-objective-4b.cmd</code>.</p>
              </div>
              <button className="button secondary" onClick={onNewProposal}>Generar nueva propuesta</button>
            </section>
          )}

          {intent.status === "REAL_PREPARED" && intent.real_execution && (
            <section className="real-confirmation-card">
              <span className="eyebrow">Confirmación final de escritura</span>
              <h4>Se creará exactamente una Task real en AT</h4>
              <dl className="real-payload-summary">
                <div><dt>Título</dt><dd>{String(intent.real_execution.payload.arguments.summary ?? "")}</dd></div>
                <div><dt>Destino</dt><dd>AT · Task</dd></div>
                <div><dt>Responsable</dt><dd>{intent.preview.assignee.display_name}</dd></div>
                {intent.real_execution.sprint_resolution?.selected && (
                  <div><dt>Sprint</dt><dd>{intent.real_execution.sprint_resolution.selected.name} · {intent.real_execution.sprint_resolution.selected.state === "active" ? "Activo" : "Futuro"}</dd></div>
                )}
                <div><dt>Reintentos automáticos</dt><dd>0</dd></div>
              </dl>
              <label>
                Escribe <strong>{intent.real_execution.confirmation_phrase}</strong>
                <input value={realPhrase} onChange={(event) => setRealPhrase(event.target.value)} aria-label="Frase de confirmación para crear la Task" autoComplete="off" />
              </label>
              <details className="payload-details">
                <summary>Ver payload real y huella</summary>
                <code>{JSON.stringify(intent.real_execution.payload.arguments, null, 2)}</code>
                <small>SHA-256: {intent.real_execution.payload_hash}</small>
              </details>
              <div className="objective4a-actions">
                <button className="button primary danger" disabled={loading || realPhrase.trim().toUpperCase() !== intent.real_execution.confirmation_phrase} onClick={() => void confirmRealWrite()}>
                  {loading ? "Confirmando…" : "Confirmar creación real"}
                </button>
              </div>
            </section>
          )}

          {intent.status === "REAL_CONFIRMED" && (
            <section className="real-execute-card">
              <div>
                <span className="eyebrow">Autorización registrada</span>
                <strong>La siguiente acción sí escribirá en Jira</strong>
                <p>Primero se revalidará el Sprint. Sólo si sigue activo o futuro se invocará una vez <code>createJiraIssue</code> y después <code>getJiraIssue</code>. No habrá reintento automático.</p>
              </div>
              <button className="button primary danger" disabled={loading} onClick={() => void executeRealWrite()}>
                {loading ? "Creando y verificando…" : "Crear 1 Task real en AT"}
              </button>
            </section>
          )}

          {intent.status === "SUBMITTED" && (
            <section className="real-write-pending" role="status">
              <strong>Envío registrado; esperando respuesta</strong>
              <p>No cierres ni repitas la operación. Si la conexión se interrumpe, el resultado quedará como incierto para conciliación manual.</p>
            </section>
          )}

          {intent.real_execution && ["CREATED_VERIFIED", "CREATED_UNVERIFIED", "REJECTED", "UNKNOWN"].includes(intent.status) && (
            <section className={`real-write-result ${intent.status.toLocaleLowerCase()}`}>
              <div>
                <span className="eyebrow">Resultado de Jira real</span>
                <strong>{
                  intent.status === "CREATED_VERIFIED" ? `Creación exitosa: ${intent.real_execution.issue_key}`
                    : intent.status === "CREATED_UNVERIFIED" ? `Task creada, pero la lectura posterior quedó incompleta: ${intent.real_execution.issue_key}`
                      : intent.status === "REJECTED" ? "Jira rechazó la creación; no se creó ni se reintentó"
                        : "El resultado es incierto; no se realizará ningún reintento automático"
                }</strong>
                {intent.real_execution.error && <p>{intent.real_execution.error}</p>}
                {intent.real_execution.readback && (
                  <ul className="execution-checks">
                    {Object.entries(intent.real_execution.readback.checks).map(([key, passed]) => <li key={key}>{passed ? "✓" : "!"} {key}</li>)}
                  </ul>
                )}
                {intent.real_execution.sprint_revalidated_at && <p>✓ Sprint revalidado inmediatamente antes de la creación.</p>}
                <small>{intent.real_execution.real_mcp_calls} llamadas MCP · {intent.real_execution.automatic_retries} reintentos</small>
              </div>
              <div className="objective4a-actions">
                {intent.real_execution.issue_url && <a className="button primary" href={intent.real_execution.issue_url} target="_blank" rel="noreferrer">Abrir {intent.real_execution.issue_key}</a>}
                <button className="button secondary" onClick={() => void downloadObjective4BEvidence(token, intent.execution_id)}>Descargar evidencia 4B</button>
                <button className="button secondary" onClick={onNewProposal}>Generar nueva propuesta</button>
              </div>
            </section>
          )}
        </div>
      ) : intent?.status === "CONFIRMED" ? (
        <div className="objective4a-next">
          <div>
            <span className="eyebrow">Confirmación registrada</span>
            <strong>La vista previa está lista para ensayarse</strong>
            <p>La siguiente acción sólo llamará al simulador local. No existe acceso a Jira desde este ejecutor.</p>
          </div>
          <div className="objective4a-actions">
            <button className="button secondary" disabled={loading} onClick={() => void cancel()}>Cancelar preparación</button>
            <button className="button primary" disabled={loading} onClick={() => void simulate()}>{loading ? "Simulando…" : "Ejecutar simulación segura"}</button>
          </div>
        </div>
      ) : intent?.status === "PREPARED" ? (
        <div className="objective4a-preview">
          <dl>
            <div><dt>Título de la actividad de prueba</dt><dd>{intent.preview.title}</dd></div>
            <div><dt>Destino</dt><dd>{intent.preview.space} · {intent.preview.work_type}</dd></div>
            <div><dt>Responsable</dt><dd>{intent.preview.assignee.display_name}<small>Cuenta Jira confirmada</small></dd></div>
            <div><dt>Confirmación válida hasta</dt><dd>{new Date(intent.confirmation.expires_at).toLocaleString()}</dd></div>
          </dl>
          {intent.preview.warnings.length > 0 && (
            <div className="objective4a-warning">
              <strong>{intent.preview.warnings.length} advertencia técnica</strong>
              <span>La operación real seguiría siendo atómica: si Jira rechaza al responsable, no se crearía la Task.</span>
            </div>
          )}
          {visibleFields.length > 0 && (
            <section className="friendly-fields" aria-label="Campos adicionales de Jira">
              <div>
                <span className="eyebrow">Campos adicionales</span>
                <p>Estos valores también formarían parte de la actividad.</p>
              </div>
              <dl>
                {visibleFields.map(([fieldId, value]) => (
                  <div key={fieldId}>
                    <dt>{fieldLabels[fieldId] ?? "Campo configurado en Jira"}</dt>
                    <dd>{readableValue(value)}</dd>
                    {!fieldLabels[fieldId] && <small>ID técnico: {fieldId}</small>}
                  </div>
                ))}
              </dl>
            </section>
          )}
          <details className="payload-details">
            <summary>Ver detalles técnicos y huella</summary>
            <code>{JSON.stringify(intent.payload.arguments, null, 2)}</code>
            <small>SHA-256: {intent.payload_hash}</small>
          </details>
          <label className="confirmation-row">
            <input type="checkbox" checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} />
            Revisé título, destino y responsable. Confirmo esta vista previa para una simulación local que no escribirá en Jira.
          </label>
          <div className="objective4a-actions">
            <button className="button secondary" disabled={loading} onClick={() => void cancel()}>Cancelar</button>
            <button className="button primary" disabled={!confirmed || loading} onClick={() => void confirm()}>{loading ? "Confirmando…" : "Confirmar vista previa"}</button>
          </div>
        </div>
      ) : (
        <div className="objective4a-prepare">
          {terminal && <div className="objective4a-warning"><strong>La preparación anterior ya no es válida</strong><span>Genera una vista previa nueva para continuar.</span></div>}
          {eligible.length > 0 ? (
            <>
              <label>
                Actividad para la prueba
                <select value={rowId} onChange={(event) => setRowId(event.target.value)}>
                  {eligible.map((item) => <option key={item.row_id} value={item.row_id}>{item.title}</option>)}
                </select>
              </label>
              <button className="button primary" disabled={loading || !rowId} onClick={() => void prepare()}>{loading ? "Preparando…" : "Preparar simulación"}</button>
            </>
          ) : (
            <div className="objective4a-warning"><strong>No hay una Task elegible en AT</strong><span>Esta primera prueba controlada no admite otros Work Types ni otros Spaces.</span></div>
          )}
        </div>
      )}
        </div>
      )}
    </section>
  );
}

const GENERAL_VALUE_FIELDS: Array<{
  key: keyof Omit<ProposalDefaults, "space">;
  label: string;
}> = [
  { key: "iniciativa", label: "Iniciativa" },
  { key: "linea_trabajo", label: "L\u00ednea de trabajo" },
  { key: "sprint", label: "Sprint" },
  { key: "tipo_seguimiento", label: "Tipo de seguimiento" },
  { key: "semaforo", label: "Sem\u00e1foro" },
];

function inferBusinessKey(name: string | null | undefined): keyof Omit<ProposalDefaults, "space"> | null {
  const normalized = normalizeIdentity(name).replace(/_/g, " ");
  const aliases: Record<string, keyof Omit<ProposalDefaults, "space">> = {
    iniciativa: "iniciativa",
    initiative: "iniciativa",
    "linea de trabajo": "linea_trabajo",
    "linea trabajo": "linea_trabajo",
    workstream: "linea_trabajo",
    sprint: "sprint",
    "tipo de seguimiento": "tipo_seguimiento",
    "tipo seguimiento": "tipo_seguimiento",
    semaforo: "semaforo",
    "traffic light": "semaforo",
  };
  return aliases[normalized] ?? null;
}

function GeneralValuesEditor({
  token,
  initial,
  approved,
  saving,
  onClose,
  onSave,
}: {
  token: string;
  initial: ProposalDefaults;
  approved: boolean;
  saving: boolean;
  onClose: () => void;
  onSave: (defaults: ProposalDefaults) => Promise<void>;
}) {
  const [values, setValues] = useState<ProposalDefaults>({ ...initial });
  const [status, setStatus] = useState<AtlassianStatus | null>(null);
  const [sprints, setSprints] = useState<JiraSprint[]>([]);
  const [catalogError, setCatalogError] = useState("");

  useEffect(() => {
    let active = true;
    getAtlassianStatus(token)
      .then((result) => { if (active) setStatus(result); })
      .catch((reason) => {
        if (active) setCatalogError(reason instanceof Error ? reason.message : "No fue posible consultar los cat\u00e1logos de Jira.");
      });
    return () => { active = false; };
  }, [token]);

  useEffect(() => {
    let active = true;
    if (!status?.connected) {
      setSprints([]);
      return () => { active = false; };
    }
    listJiraSprints(token, values.space, true)
      .then((result) => { if (active) setSprints(result); })
      .catch((reason) => {
        if (active) {
          setSprints([]);
          setCatalogError(reason instanceof Error ? reason.message : "No fue posible recuperar los Sprints de Jira.");
        }
      });
    return () => { active = false; };
  }, [status?.connected, token, values.space]);

  const catalogs = useMemo(() => {
    const result = new Map<keyof Omit<ProposalDefaults, "space">, Array<{ value: string; label: string }>>();
    const space = status?.snapshot?.spaces.find((candidate) => candidate.key === values.space);
    for (const workType of space?.work_types ?? []) {
      for (const field of workType.fields) {
        const key = field.business_key ?? inferBusinessKey(field.name);
        if (!key) continue;
        const current = result.get(key) ?? [];
        for (const option of field.options ?? []) {
          if (!current.some((candidate) => normalizeIdentity(candidate.value) === normalizeIdentity(option.value))) {
            current.push({ value: option.value, label: option.label });
          }
        }
        result.set(key, current.sort((left, right) => left.label.localeCompare(right.label, "es")));
      }
    }
    if (sprints.length > 0) {
      result.set("sprint", sprints.map((sprint) => ({
        value: sprint.name,
        label: `${sprint.name} · ${sprint.state === "active" ? "Activo" : "Futuro"}`,
      })));
    }
    return result;
  }, [status, values.space, sprints]);

  function updateValue(key: keyof ProposalDefaults, value: string) {
    setValues((current) => ({ ...current, [key]: value || null } as ProposalDefaults));
  }

  return (
    <div className="modal-backdrop" role="presentation">
      <form
        className="approval-modal general-values-modal"
        aria-label="Editar valores generales"
        onSubmit={(event) => { event.preventDefault(); void onSave(values); }}
      >
        <span className="eyebrow">{"Configuraci\u00f3n del plan"}</span>
        <h2>Editar valores generales</h2>
        <p>{"Estos valores se aplicar\u00e1n a todas las actividades. El archivo original permanecer\u00e1 sin cambios para conservar la trazabilidad."}</p>
        {approved && (
          <div className="alert warning" role="status">
            {"Esta propuesta est\u00e1 aprobada. Al guardar se crear\u00e1 una versi\u00f3n editable y deber\u00e1s aprobarla y validarla nuevamente con Jira."}
          </div>
        )}
        <label>
          Space del plan
          <select value={values.space} onChange={(event) => updateValue("space", event.target.value)}>
            <option value="AT">AT &middot; Team-managed</option>
            <option value="ASIT">ASIT &middot; Company-managed</option>
            <option value="MTTI">MTTI &middot; Company-managed</option>
          </select>
        </label>
        <div className="general-values-grid">
          {GENERAL_VALUE_FIELDS.map(({ key, label }) => {
            const options = catalogs.get(key) ?? [];
            const currentValue = values[key] ?? "";
            const knownCurrent = options.some((option) => option.value === currentValue);
            const activeSprintCount = sprints.filter((sprint) => sprint.state === "active").length;
            return (
              <label key={key}>
                {label}
                {options.length > 0 ? (
                  <select value={currentValue} onChange={(event) => updateValue(key, event.target.value)}>
                    <option value="">
                      {key === "sprint" && activeSprintCount > 1
                        ? "Selecciona un Sprint (hay varios activos)"
                        : key === "sprint" && activeSprintCount === 1
                          ? "Automático: usar el único Sprint activo"
                          : "Sin valor"}
                    </option>
                    {currentValue && !knownCurrent && <option value={currentValue}>{currentValue} · valor actual</option>}
                    {options.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
                  </select>
                ) : (
                  <input
                    value={currentValue}
                    onChange={(event) => updateValue(key, event.target.value)}
                    placeholder={key === "sprint" ? "Nombre exacto en Jira" : "Opcional"}
                  />
                )}
                <small className={options.length > 0 ? "catalog-status live" : "catalog-status"}>
                  {options.length > 0
                    ? `${options.length} ${options.length === 1 ? "opci\u00f3n recuperada" : "opciones recuperadas"} de Jira`
                    : key === "sprint" && status?.connected
                      ? "No se recuperaron Sprints con actividades visibles. Puedes escribir el nombre; se resolverá y validará antes de cualquier envío."
                    : status?.connected
                      ? "Jira no public\u00f3 un cat\u00e1logo para este campo; se permite captura manual."
                      : "Conecta Jira para consultar opciones; por ahora se permite captura manual."}
                </small>
              </label>
            );
          })}
        </div>
        {catalogError && <div className="alert warning">{catalogError} Puedes continuar con captura manual.</div>}
        <div className="drawer-actions">
          <button type="button" className="button secondary" onClick={onClose}>Cancelar</button>
          <button type="submit" className="button primary" disabled={saving}>
            {saving ? "Guardando nueva versi\u00f3n\u2026" : "Guardar como nueva versi\u00f3n"}
          </button>
        </div>
      </form>
    </div>
  );
}

export function ProposalReview({
  token,
  proposal,
  displayName,
  onRename,
  onUpdated,
  onNewProposal,
}: {
  token: string;
  proposal: Proposal;
  displayName: string;
  onRename: (name: string) => Promise<void>;
  onUpdated: (proposal: Proposal) => void;
  onNewProposal: () => void;
}) {
  const [tab, setTab] = useState<ProposalTab>(
    proposal.items.some((item) => item.generated.decision === "REVISAR")
      ? "REVISAR"
      : "INCLUIR",
  );
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<ProposalItem | null>(null);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [approvalOpen, setApprovalOpen] = useState(false);
  const [approvalConfirmed, setApprovalConfirmed] = useState(false);
  const [processingLifecycle, setProcessingLifecycle] = useState(false);
  const [dryRun, setDryRun] = useState<JiraDryRun | null>(null);
  const [dryRunLoading, setDryRunLoading] = useState(false);
  const [continueCorrections, setContinueCorrections] = useState(false);
  const [defaultsOpen, setDefaultsOpen] = useState(false);
  const [defaultsSaving, setDefaultsSaving] = useState(false);
  const approved = proposal.status === "APPROVED";
  const currentDryRun = dryRun
    && !dryRun.stale
    && dryRun.proposal_version === proposal.version
    ? dryRun
    : null;

  useEffect(() => {
    setDryRun(null);
    let active = true;
    getLatestJiraDryRun(token, proposal.proposal_id)
      .then((result) => {
        if (active) {
          if (!result?.summary || !Array.isArray(result.items)) return;
          setDryRun(result);
          const workflow = result.correction_workflow;
          if (!approved && workflow?.active) {
            if (workflow.summary.pending_user > 0) setTab("JIRA_ACTION");
            else if (workflow.summary.technical > 0) setTab("JIRA_TECHNICAL");
            else setTab("JIRA_CORRECTED");
            if (continueCorrections) {
              const next = workflow.items.find((item) => item.category === "USER_ACTION");
              setSelected(next
                ? proposal.items.find((item) => item.generated.row_id === next.row_id) ?? null
                : null);
              setContinueCorrections(false);
            }
          }
        }
      })
      .catch((reason) => {
        if (active && (!(reason instanceof ApiError) || reason.status !== 404)) {
          setError(reason instanceof Error ? reason.message : "No fue posible recuperar la validación con Jira.");
        }
      });
    return () => {
      active = false;
    };
  }, [approved, continueCorrections, proposal, token]);

  const blockedRowIds = useMemo(
    () => new Set(dryRun?.items.filter((item) => item.status === "BLOCKED").map((item) => item.row_id) ?? []),
    [dryRun],
  );

  const blockedCurrentCount = proposal.items.filter((item) => blockedRowIds.has(item.generated.row_id)).length;
  const correctionWorkflow = dryRun?.correction_workflow;
  const correctionMode = !approved && Boolean(correctionWorkflow?.active);
  const correctionByRow = useMemo(
    () => new Map(correctionWorkflow?.items.map((item) => [item.row_id, item]) ?? []),
    [correctionWorkflow],
  );

  const filtered = useMemo(() => {
    const normalized = query.trim().toLocaleLowerCase();
    return proposal.items.filter((item) => {
      const correction = correctionByRow.get(item.generated.row_id);
      const matchesTab = tab === "TODAS"
        || (tab === "JIRA_BLOCKED" && blockedRowIds.has(item.generated.row_id))
        || (tab === "JIRA_ACTION" && correction?.category === "USER_ACTION")
        || (tab === "JIRA_TECHNICAL" && correction?.category === "TECHNICAL")
        || (tab === "JIRA_CORRECTED" && correction?.category === "CORRECTED")
        || (["INCLUIR", "REVISAR", "EXCLUIR"].includes(tab) && item.generated.decision === tab);
      const matchesQuery =
        !normalized ||
        item.generated.title.toLocaleLowerCase().includes(normalized) ||
        item.source.actividad.toLocaleLowerCase().includes(normalized) ||
        item.generated.assignee.display_name.toLocaleLowerCase().includes(normalized);
      return matchesTab && matchesQuery;
    });
  }, [blockedRowIds, correctionByRow, proposal, query, tab]);

  const count = (decision: Decision) =>
    proposal.items.filter((item) => item.generated.decision === decision).length;

  const workflowCount = (category: JiraCorrectionItem["category"]) =>
    correctionWorkflow?.items.filter((item) => item.category === category).length ?? 0;

  function openNextCorrection() {
    const next = correctionWorkflow?.items.find((item) => item.category === "USER_ACTION");
    if (!next) return;
    setTab("JIRA_ACTION");
    setSelected(proposal.items.find((item) => item.generated.row_id === next.row_id) ?? null);
  }

  async function save(values: Parameters<DetailPanelProps["onSave"]>[0]) {
    if (!selected) return;
    setError("");
    setSuccess("");
    try {
      const updated = await updateProposalItem(
        token,
        proposal.proposal_id,
        selected.generated.row_id,
        values,
      );
      const updatedItem = updated.items.find(
        (item) => item.generated.row_id === selected.generated.row_id,
      );
      const correction = correctionByRow.get(selected.generated.row_id);
      if (correction?.category === "USER_ACTION") {
        setSuccess(`Versión ${updated.version} guardada. Comprobaremos la corrección y abriremos la siguiente actividad pendiente.`);
        setContinueCorrections(true);
        setTab("JIRA_ACTION");
      } else if (updatedItem?.generated.decision === "INCLUIR") {
        setSuccess(
          `Versión ${updated.version} guardada. Se resolvieron todos los pendientes y la actividad pasó a Listas.`,
        );
        setTab("INCLUIR");
      } else if (updatedItem?.generated.decision === "REVISAR") {
        const remaining = updatedItem.validation.pending_requirements ?? [];
        setSuccess(
          `Versión ${updated.version} guardada. La actividad conserva ${remaining.length} ${remaining.length === 1 ? "pendiente" : "pendientes"}.`,
        );
        setTab("REVISAR");
      } else {
        setSuccess(`Versión ${updated.version} guardada y validada.`);
        if (updatedItem) setTab(updatedItem.generated.decision);
      }
      onUpdated(updated);
      setSelected(null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "No fue posible guardar.");
    }
  }

  async function reactivate(reason: string) {
    if (!selected) return;
    setError("");
    try {
      const updated = await reactivateProposalItem(
        token,
        proposal.proposal_id,
        selected.generated.row_id,
        reason,
      );
      onUpdated(updated);
      setSelected(null);
      setTab("REVISAR");
      setSuccess(
        `Versión ${updated.version} creada. La actividad pasó a Requieren revisión para confirmar sus datos.`,
      );
    } catch (reasonValue) {
      setError(reasonValue instanceof Error ? reasonValue.message : "No fue posible reactivar.");
    }
  }

  async function approve() {
    setProcessingLifecycle(true);
    setError("");
    try {
      const result = await approveProposalAndDryRun(token, proposal.proposal_id);
      onUpdated(result.proposal);
      setDryRun(result.dry_run);
      setApprovalOpen(false);
      setApprovalConfirmed(false);
      setSuccess(
        result.dry_run.status === "BLOCKED"
          ? `La versión ${result.proposal.version} se aprobó, pero la prevalidación detectó ${result.dry_run.summary.blocked} bloqueos que deben corregirse.`
          : `Validación con Jira completada para la versión ${result.proposal.version}, sin crear ni modificar actividades.`,
      );
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "No fue posible aprobar.");
    } finally {
      setProcessingLifecycle(false);
    }
  }

  async function reopen() {
    setProcessingLifecycle(true);
    setError("");
    try {
      const updated = await reopenProposal(token, proposal.proposal_id);
      onUpdated(updated);
      setSuccess(`Versión ${updated.version} reabierta. La aprobación anterior se conserva en el historial.`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "No fue posible reabrir.");
    } finally {
      setProcessingLifecycle(false);
    }
  }

  async function runDryRun() {
    setDryRunLoading(true);
    setError("");
    setSuccess("");
    try {
      const result = await generateJiraDryRun(token, proposal.proposal_id);
      setDryRun(result);
      setSuccess(
        result.status === "READY"
          ? `Validación lista: ${result.summary.ready} actividades comprobadas sin escribir en Jira.`
          : result.status === "READY_WITH_WARNINGS"
            ? `Prevalidación completada con ${result.summary.ready_with_warnings ?? 0} advertencias técnicas no bloqueantes para esta fase sin escritura.`
          : `Validación bloqueada: corrige ${result.summary.blocked} actividades antes de continuar.`,
      );
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "No fue posible ejecutar la validación con Jira.");
    } finally {
      setDryRunLoading(false);
    }
  }

  async function saveDefaults(defaults: ProposalDefaults) {
    setDefaultsSaving(true);
    setError("");
    setSuccess("");
    try {
      const updated = await updateProposalDefaults(
        token,
        proposal.proposal_id,
        defaults,
      );
      onUpdated(updated);
      setDefaultsOpen(false);
      setSuccess(
        `Versi\u00f3n ${updated.version} creada con los valores generales actualizados. `
        + "La versi\u00f3n anterior se conserva y deber\u00e1s repetir la aprobaci\u00f3n y la validaci\u00f3n con Jira.",
      );
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "No fue posible actualizar los valores generales.");
    } finally {
      setDefaultsSaving(false);
    }
  }

  const visibleTabs: Array<[ProposalTab, string]> = correctionMode
    ? [
        ["JIRA_ACTION", "Por corregir"],
        ["JIRA_TECHNICAL", "Validación técnica"],
        ["JIRA_CORRECTED", "Corregidas"],
        ["TODAS", "Todas"],
      ]
    : [
        ["REVISAR", "Requieren revisión"],
        ["INCLUIR", "Listas"],
        ["EXCLUIR", "Excluidas"],
        ["TODAS", "Todas"],
      ];

  function tabCount(value: ProposalTab): number | null {
    if (value === "JIRA_ACTION") return workflowCount("USER_ACTION");
    if (value === "JIRA_TECHNICAL") return workflowCount("TECHNICAL");
    if (value === "JIRA_CORRECTED") return workflowCount("CORRECTED");
    if (value === "JIRA_BLOCKED") return blockedCurrentCount;
    if (value === "INCLUIR" || value === "REVISAR" || value === "EXCLUIR") return count(value);
    return null;
  }

  return (
    <section className="proposal-card">
      <ProposalHeader proposal={proposal} displayName={displayName} onRename={onRename} />
      <nav className="workflow-guide" aria-label="Progreso de la propuesta">
        <div className={!approved ? "active" : "complete"}>
          <span>1</span><strong>Revisar actividades</strong><small>Corrige sólo los pendientes</small>
        </div>
        <div className={approved && !currentDryRun ? "active" : currentDryRun ? "complete" : ""}>
          <span>2</span><strong>Validar con Jira</strong><small>Comprueba datos sin escribir</small>
        </div>
        <div className={approved && currentDryRun?.status !== "BLOCKED" ? "active" : ""}>
          <span>3</span><strong>Probar y enviar</strong><small>Simula antes de crear una Task</small>
        </div>
      </nav>
      {approved ? (
        <section className={`approval-banner ${currentDryRun?.status === "BLOCKED" ? "correction-state" : "approved-state"}`}>
          <div>
            <span className="eyebrow">{currentDryRun && currentDryRun.status !== "BLOCKED" ? "Validación con Jira completada" : currentDryRun ? "Correcciones Jira pendientes" : "Validación con Jira pendiente"}</span>
            <strong>{currentDryRun?.status === "READY_WITH_WARNINGS" ? "Prevalidación completada con advertencias técnicas" : currentDryRun?.status === "READY" ? "Prevalidación completada" : currentDryRun?.status === "BLOCKED" ? `${currentDryRun.summary.blocked} ${currentDryRun.summary.blocked === 1 ? "actividad requiere" : "actividades requieren"} corrección` : "Versión aprobada; falta comprobarla contra Jira"}</strong>
            <p>{currentDryRun?.status === "READY_WITH_WARNINGS" ? "Las cuentas Jira fueron identificadas. La asignabilidad estricta se comprobará antes de autorizar cualquier escritura real." : currentDryRun?.status === "READY" ? "La propuesta y los metadatos Jira quedaron prevalidados. No se realizó ninguna escritura." : currentDryRun?.status === "BLOCKED" ? "Reabre la propuesta y corrige únicamente las actividades bloqueadas; después la aprobación repetirá la prevalidación automáticamente." : dryRun ? `El resultado visible corresponde a la versión ${dryRun.proposal_version}; ejecuta la comprobación de la versión ${proposal.version}.` : `Aprobada por ${proposal.approved_by} · ${proposal.approved_at}`}</p>
          </div>
          <div className="approval-actions">
            {currentDryRun?.status === "BLOCKED" && <button className="button primary" disabled={processingLifecycle} onClick={() => void reopen()}>Reabrir y resolver bloqueos</button>}
            {!currentDryRun && <button className="button primary" disabled={dryRunLoading} onClick={() => void runDryRun()}>{dryRunLoading ? "Prevalidando…" : "Ejecutar prevalidación final"}</button>}
            {currentDryRun && <button className="button secondary" disabled={dryRunLoading} onClick={() => void runDryRun()}>{dryRunLoading ? "Prevalidando…" : "Repetir prevalidación"}</button>}
            {currentDryRun && <button className="button secondary" onClick={() => void downloadDryRunEvidence(token, proposal.proposal_id, displayName)}>Descargar evidencia JSON</button>}
            {currentDryRun?.status !== "BLOCKED" && <button className="button secondary" disabled={processingLifecycle} onClick={() => void reopen()}>Reabrir para editar</button>}
          </div>
        </section>
      ) : correctionMode && (correctionWorkflow?.summary.pending_user ?? 0) > 0 ? (
        <section className="approval-banner correction-state">
          <div>
            <span className="eyebrow">Corrección previa a la aprobación</span>
            <strong>{correctionWorkflow?.summary.pending_user} {correctionWorkflow?.summary.pending_user === 1 ? "actividad requiere" : "actividades requieren"} una corrección</strong>
            <p>{correctionWorkflow?.summary.technical ?? 0} {(correctionWorkflow?.summary.technical ?? 0) === 1 ? "validación técnica no requiere" : "validaciones técnicas no requieren"} que modifiques datos. Te guiaremos actividad por actividad.</p>
          </div>
          <button className="button primary" onClick={openNextCorrection}>Resolver siguiente bloqueo</button>
        </section>
      ) : correctionMode ? (
        <section className="approval-banner ready-state">
          <div>
            <span className="eyebrow">Correcciones de usuario completadas</span>
            <strong>Ya puedes revisar y aprobar las correcciones</strong>
            <p>{correctionWorkflow?.summary.technical ?? 0} {(correctionWorkflow?.summary.technical ?? 0) === 1 ? "validación técnica se repetirá" : "validaciones técnicas se repetirán"} en la comprobación final. Aún no se escribirá nada en Jira.</p>
          </div>
          <button className="button primary" onClick={() => setApprovalOpen(true)}>Revisar y aprobar correcciones</button>
        </section>
      ) : count("REVISAR") === 0 ? (
        <section className="approval-banner ready-state">
          <div>
            <span className="eyebrow">Lista para aprobación</span>
            <strong>Ya no hay actividades pendientes</strong>
            <p>Revisa el resumen y aprueba la propuesta final. Aún no se escribirá nada en Jira.</p>
          </div>
          <button className="button primary" onClick={() => setApprovalOpen(true)}>Revisar y aprobar propuesta final</button>
        </section>
      ) : (
        <section className="approval-banner pending-state">
          <div>
            <span className="eyebrow">Preparación de la propuesta</span>
            <strong>{count("REVISAR")} {count("REVISAR") === 1 ? "actividad pendiente" : "actividades pendientes"}</strong>
            <p>Resuelve todas las revisiones antes de habilitar la aprobación final.</p>
          </div>
        </section>
      )}
      {dryRun && (
        <details className="dry-run-history">
          <summary>
            <span>Resultado de la validación con Jira</span>
            <small>Versión {dryRun.proposal_version} · {dryRun.status === "BLOCKED" ? `${dryRun.summary.blocked} bloqueadas` : "sin bloqueos"}</small>
          </summary>
          <DryRunPanel dryRun={dryRun} currentProposalVersion={proposal.version} />
        </details>
      )}
      {approved && currentDryRun && currentDryRun.status !== "BLOCKED" && (
        <Objective4APanel token={token} proposal={proposal} dryRun={currentDryRun} onNewProposal={onNewProposal} />
      )}
      <details className="workflow-section activities-section" open={!approved || correctionMode}>
        <summary>
          <span>Actividades de la propuesta</span>
          <small>{proposal.items.length} actividades · {count("REVISAR")} por revisar</small>
        </summary>
      <div className="defaults-strip">
        <span><b>Valores generales</b></span>
        <span>Space: {proposal.defaults.space}</span>
        {proposal.defaults.iniciativa && <span>Iniciativa: {proposal.defaults.iniciativa}</span>}
        {proposal.defaults.linea_trabajo && <span>{"L\u00ednea de trabajo"}: {proposal.defaults.linea_trabajo}</span>}
        {proposal.defaults.sprint && <span>Sprint: {proposal.defaults.sprint}</span>}
        {proposal.defaults.tipo_seguimiento && <span>Tipo de seguimiento: {proposal.defaults.tipo_seguimiento}</span>}
        {proposal.defaults.semaforo && <span>{"Sem\u00e1foro"}: {proposal.defaults.semaforo}</span>}
        <button type="button" className="text-action defaults-edit" onClick={() => setDefaultsOpen(true)}>
          Editar valores
        </button>
      </div>
      <div className="review-toolbar">
        <div className="tabs" role="tablist" aria-label="Decisiones">
          {visibleTabs.map(([value, label]) => (
            <button
              key={value}
              className={tab === value ? "active" : ""}
              onClick={() => setTab(value)}
              role="tab"
              aria-selected={tab === value}
            >
              {label}
              {tabCount(value) !== null && <span>{tabCount(value)}</span>}
            </button>
          ))}
        </div>
        <input
          className="search"
          placeholder="Buscar actividad o responsable"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          aria-label="Buscar propuesta"
        />
      </div>
      {success && <div className="alert success" role="status">{success}</div>}
      {error && <div className="alert error">{error}</div>}
      <div className="proposal-table" role="table">
        <div className="proposal-row table-header" role="row">
          <span>Origen</span>
          <span>Propuesta</span>
          <span>Tipo</span>
          <span>Responsable</span>
          <span>Estado</span>
          <span></span>
        </div>
        {filtered.map((item) => (
          <button
            className="proposal-row"
            key={item.generated.row_id}
            onClick={() => setSelected(item)}
            role="row"
          >
            <span>
              <small>Fila {item.source.source_row}</small>
              {item.source.actividad}
            </span>
            <span>
              <strong>{item.generated.title}</strong>
              <small>{item.generated.decision_reason}</small>
            </span>
            <span><span className="work-type">{item.generated.work_type}</span></span>
            <span>
              {item.generated.assignee.display_name}
              <small>{item.generated.assignee.resolution}</small>
            </span>
            <span className="proposal-state-stack">
              {correctionMode && correctionByRow.get(item.generated.row_id) ? (
                <span className={`correction-status ${correctionByRow.get(item.generated.row_id)?.category.toLocaleLowerCase()}`}>
                  {correctionByRow.get(item.generated.row_id)?.category === "USER_ACTION"
                    ? "Por corregir"
                    : correctionByRow.get(item.generated.row_id)?.category === "TECHNICAL"
                      ? "Validación técnica"
                      : "Corrección guardada"}
                </span>
              ) : (
                <StatusPill decision={item.generated.decision} />
              )}
              {!correctionMode && blockedRowIds.has(item.generated.row_id) && (
                <span className="dry-run-status status-blocked" title={`Resultado de la validación de la versión ${dryRun?.proposal_version}`}>
                  Bloqueada Jira · v{dryRun?.proposal_version}
                </span>
              )}
            </span>
            <span className="open-arrow">›</span>
          </button>
        ))}
        {filtered.length === 0 && (
          <div className="empty-state">
            <strong>No hay actividades en esta vista.</strong>
            <span>Prueba otra pestaña o cambia la búsqueda.</span>
          </div>
        )}
      </div>
      </details>
      {selected && (
        <DetailPanel
          token={token}
          item={selected}
          proposalItems={proposal.items}
          onClose={() => setSelected(null)}
          onSave={save}
          onReactivate={reactivate}
          locked={approved || correctionByRow.get(selected.generated.row_id)?.category === "TECHNICAL"}
          correction={correctionByRow.get(selected.generated.row_id)}
        />
      )}
      {defaultsOpen && (
        <GeneralValuesEditor
          token={token}
          initial={proposal.defaults}
          approved={approved}
          saving={defaultsSaving}
          onClose={() => setDefaultsOpen(false)}
          onSave={saveDefaults}
        />
      )}
      {approvalOpen && (
        <div className="modal-backdrop" role="presentation" onMouseDown={() => setApprovalOpen(false)}>
          <section className="approval-modal" role="dialog" aria-modal="true" aria-labelledby="approval-title" onMouseDown={(event) => event.stopPropagation()}>
            <span className="eyebrow">Confirmación final</span>
            <h2 id="approval-title">Aprobar {displayName}</h2>
            <p>Se aprobará la versión y, en el mismo paso, se ejecutará la prevalidación final contra Jira. No se escribirá ninguna actividad.</p>
            <dl className="approval-summary">
              <div><dt>Listas para Jira</dt><dd>{count("INCLUIR")}</dd></div>
              <div><dt>Excluidas</dt><dd>{count("EXCLUIR")}</dd></div>
              <div><dt>Archivo fuente</dt><dd>{proposal.source_file.name}</dd></div>
              <div><dt>Huella SHA-256</dt><dd>{proposal.source_file.sha256}</dd></div>
            </dl>
            <label className="confirmation-row">
              <input type="checkbox" checked={approvalConfirmed} onChange={(event) => setApprovalConfirmed(event.target.checked)} />
              Revisé las actividades incluidas y excluidas y confirmo esta propuesta final.
            </label>
            <div className="drawer-actions">
              <button className="button secondary" onClick={() => setApprovalOpen(false)}>Cancelar</button>
              <button className="button primary" disabled={!approvalConfirmed || processingLifecycle} onClick={() => void approve()}>{processingLifecycle ? "Aprobando y prevalidando…" : "Aprobar y ejecutar prevalidación final"}</button>
            </div>
            <p className="jira-future-note">La creación en Jira seguirá bloqueada hasta autorizar expresamente el paso de envío controlado.</p>
          </section>
        </div>
      )}
    </section>
  );
}

export function AtlassianConnectionPanel({
  token,
  onStatusChange,
}: {
  token: string;
  onStatusChange?: (status: AtlassianStatus) => void;
}) {
  const [status, setStatus] = useState<AtlassianStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [lookupSpace, setLookupSpace] = useState<Space>("AT");
  const [lookupQuery, setLookupQuery] = useState("");
  const [assignees, setAssignees] = useState<JiraAssignee[]>([]);
  const [lookupPerformed, setLookupPerformed] = useState(false);
  const [lastLookupQuery, setLastLookupQuery] = useState("");
  const [objective4AReadiness, setObjective4AReadiness] = useState<Objective4AReadiness | null>(null);

  async function loadStatus() {
    setError("");
    try {
      const nextStatus = await getAtlassianStatus(token);
      setStatus(nextStatus);
      onStatusChange?.(nextStatus);
      if (nextStatus.error) setError(nextStatus.error);
      if (nextStatus.connected) {
        const readiness = await getObjective4AReadiness(token);
        if (readiness?.objective === "4A") setObjective4AReadiness(readiness);
      } else {
        setObjective4AReadiness(null);
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "No fue posible consultar la conexión.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    const parameters = new URLSearchParams(window.location.search);
    const result = parameters.get("atlassian");
    if (result) {
      window.history.replaceState({}, "", window.location.pathname);
      if (result === "denied") setError("La autorización de Atlassian fue cancelada.");
    }
    void loadStatus();
  }, [token]);

  async function connect() {
    setLoading(true);
    setError("");
    try {
      const response = await connectAtlassian(token);
      window.location.assign(response.authorization_url);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "No fue posible iniciar OAuth.");
      setLoading(false);
    }
  }

  async function disconnect() {
    if (!window.confirm("¿Desconectar tu cuenta Atlassian? Se eliminará la autorización cifrada guardada en este equipo.")) return;
    setLoading(true);
    setError("");
    try {
      const nextStatus = await disconnectAtlassian(token);
      setStatus(nextStatus);
      onStatusChange?.(nextStatus);
      setObjective4AReadiness(null);
      setAssignees([]);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "No fue posible desconectar Atlassian.");
    } finally {
      setLoading(false);
    }
  }

  async function refresh() {
    setLoading(true);
    setError("");
    try {
      const nextStatus = await refreshAtlassian(token);
      setStatus(nextStatus);
      onStatusChange?.(nextStatus);
      if (nextStatus.connected) setObjective4AReadiness(await getObjective4AReadiness(token));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "No fue posible actualizar el diagnóstico.");
    } finally {
      setLoading(false);
    }
  }

  async function lookup(event: FormEvent) {
    event.preventDefault();
    setLoading(true);
    setError("");
    setLookupPerformed(false);
    try {
      const query = lookupQuery.trim();
      const received = await findJiraAssignees(token, lookupSpace, query);
      const deduplicated = Array.from(
        new Map(received.map((assignee) => [assignee.account_id || normalizeIdentity(assignee.display_name), assignee])).values(),
      );
      const normalizedQuery = normalizeIdentity(query);
      const exact = deduplicated.filter(
        (assignee) =>
          normalizeIdentity(assignee.display_name) === normalizedQuery ||
          normalizeIdentity(assignee.email) === normalizedQuery,
      );
      setAssignees(exact.length > 0 ? exact : deduplicated);
      setLastLookupQuery(query);
      setLookupPerformed(true);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "No fue posible buscar responsables.");
    } finally {
      setLoading(false);
    }
  }

  const snapshot = status?.snapshot;
  return (
    <section className={`integration-card ${status?.connected ? "connected" : ""}`}>
      <div className="integration-heading">
        <div>
          <span className="eyebrow">Configuración de Jira</span>
          <h2>Conexión de la aplicación con Jira</h2>
          <p>
            OAuth 2.1 por usuario · consulta de metadatos · {status?.jira_write_enabled ? "una Task controlada habilitada" : "escritura Jira bloqueada"}.
          </p>
        </div>
        <span className={`connection-pill ${status?.connected ? "online" : "offline"}`}>
          {loading ? "Consultando…" : status?.connected ? status.jira_write_enabled ? "Conectado · envío controlado" : "Conectado · solo lectura" : "Desconectado"}
        </span>
      </div>

      {error && <div className="alert error" role="alert">{error}</div>}

      {!status?.connected ? (
        <div className="integration-onboarding">
          <div className="read-only-seal">
            <strong>Protección activa</strong>
            <span>El backend rechaza cualquier herramienta MCP fuera de la lista de lectura.</span>
          </div>
          <div className="integration-actions horizontal">
            {status?.phase === "ERROR" && (
              <button className="button secondary" onClick={() => void refresh()} disabled={loading}>
                Reintentar diagnóstico
              </button>
            )}
            <button className="button primary" onClick={() => void connect()} disabled={loading}>
              {status?.phase === "ERROR" ? "Volver a autorizar" : "Conectar mi cuenta Atlassian"}
            </button>
          </div>
        </div>
      ) : (
        <>
          <div className="integration-summary">
            <dl>
              <div><dt>Sitio verificado</dt><dd>{snapshot?.site_url}</dd></div>
              <div><dt>cloudId</dt><dd><code>{snapshot?.cloud_id}</code></dd></div>
              <div><dt>Usuario Atlassian</dt><dd>{snapshot?.atlassian_user.display_name || snapshot?.atlassian_user.account_id}</dd></div>
              <div><dt>Autorización OAuth</dt><dd>{status.oauth_storage === "OS_ENCRYPTED" ? "Cifrada por Windows · se conserva al salir y reiniciar" : "Sólo memoria · se pierde al reiniciar"}</dd></div>
            </dl>
            <div className="integration-actions">
              <button className="button secondary compact" onClick={() => void refresh()} disabled={loading}>Actualizar diagnóstico</button>
              <button className="button ghost compact" onClick={() => void disconnect()} disabled={loading}>Desconectar</button>
            </div>
          </div>

          <div className="space-diagnostics" aria-label="Diagnóstico de Spaces Jira">
            {snapshot?.spaces.map((space) => (
              <details className={space.found ? "space-ok" : "space-missing"} key={space.key}>
                <summary>
                  <strong>{space.key}</strong>
                  <span>{space.found ? `${space.work_types.length} Work Types` : "No visible"}</span>
                </summary>
                {space.found && (
                  <div className="work-type-list">
                    {space.work_types.length === 0 ? (
                      <p>El Space existe, pero no se recibieron Work Types.</p>
                    ) : space.work_types.map((workType) => (
                      <div key={`${space.key}-${workType.id || workType.name}`}>
                        <strong>{workType.name}</strong>
                        <span>{workType.fields.length} campos · {workType.fields.filter((field) => field.required).length} obligatorios</span>
                      </div>
                    ))}
                  </div>
                )}
              </details>
            ))}
          </div>

          {objective4AReadiness && (
            <section className="objective4a-readiness" aria-label="Preparación del envío controlado">
              <div>
                <span className="eyebrow">Comprobación técnica</span>
                <strong>{objective4AReadiness.controlled_write_ready ? "Prueba segura y envío controlado habilitados" : "Prueba segura habilitada; escritura real bloqueada"}</strong>
                <p>Rovo sólo fue inspeccionado. El diagnóstico realizó {objective4AReadiness.mcp_tools.tools_invoked} invocaciones y la política reporta <code>jira_write_enabled={String(objective4AReadiness.jira_write_enabled)}</code>.</p>
              </div>
              <ul>
                <li className={objective4AReadiness.mcp_tools.create.exposed ? "ok" : "pending"}>createJiraIssue {objective4AReadiness.mcp_tools.create.exposed ? "anunciada" : "pendiente"}</li>
                <li className={objective4AReadiness.mcp_tools.readback.exposed ? "ok" : "pending"}>getJiraIssue {objective4AReadiness.mcp_tools.readback.exposed ? "anunciada" : "pendiente"}</li>
                <li className={objective4AReadiness.real_canary_checks.task_metadata_available ? "ok" : "pending"}>Contrato AT / Task {objective4AReadiness.real_canary_checks.task_metadata_available ? "visible" : "pendiente"}</li>
              </ul>
            </section>
          )}

          <form className="assignee-lookup" onSubmit={lookup}>
            <div>
              <span className="eyebrow">Comprobación de cuentas Jira</span>
              <p>Busca una identidad real; la asignabilidad se valida por separado durante la comprobación final.</p>
            </div>
            <select value={lookupSpace} onChange={(event) => setLookupSpace(event.target.value as Space)} aria-label="Space para buscar responsable">
              <option value="AT">AT</option>
              <option value="ASIT">ASIT</option>
              <option value="MTTI">MTTI</option>
            </select>
            <input value={lookupQuery} onChange={(event) => { setLookupQuery(event.target.value); setLookupPerformed(false); }} placeholder="Nombre o correo" aria-label="Nombre o correo del responsable" minLength={2} required />
            <button className="button secondary" disabled={loading || lookupQuery.trim().length < 2}>Buscar</button>
          </form>
          {assignees.length > 0 && (
            <div className="assignee-results">
              {assignees.map((assignee) => (
                <div key={assignee.account_id || assignee.display_name}>
                  <strong>{assignee.display_name}</strong>
                  <span>{assignee.email || assignee.account_id}</span>
                </div>
              ))}
            </div>
          )}
          {lookupPerformed && assignees.length === 0 && (
            <div className="assignee-empty" role="status">
              <strong>No encontramos una cuenta Jira</strong>
              <span>No hubo coincidencias activas para “{lastLookupQuery}” en {lookupSpace}. Verifica el nombre completo o prueba con el correo corporativo.</span>
            </div>
          )}
          <p className="read-only-footnote">
            {snapshot?.write_tools_exposed_by_server || 0} herramientas no permitidas pueden estar expuestas por Rovo; esta aplicación no las invoca.
          </p>
        </>
      )}
    </section>
  );
}

type HistoryFilter = "ACTIVE" | "REVIEW" | "READY" | "ARCHIVED";

export function ProposalHistory({
  proposals,
  currentId,
  loadingId,
  collapsed,
  onOpen,
  onArchive,
  onRestore,
  onNewProposal,
  onOpenSettings,
  settingsActive,
  jiraConnected,
  jiraWriteEnabled,
}: {
  proposals: ProposalSummary[];
  currentId: string | null;
  loadingId: string;
  collapsed: boolean;
  onOpen: (proposalId: string) => void;
  onArchive: (proposal: ProposalSummary) => void;
  onRestore: (proposal: ProposalSummary) => void;
  onNewProposal: () => void;
  onOpenSettings: () => void;
  settingsActive: boolean;
  jiraConnected: boolean;
  jiraWriteEnabled: boolean;
}) {
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<HistoryFilter>("ACTIVE");

  const visible = useMemo(() => {
    const normalized = query.trim().toLocaleLowerCase();
    return proposals.filter((proposal) => {
      const archived = Boolean(proposal.archived);
      const matchesFilter =
        filter === "ARCHIVED"
          ? archived
          : !archived &&
            (filter === "ACTIVE" ||
              (filter === "REVIEW" && proposal.counts.REVISAR > 0) ||
              (filter === "READY" && proposal.counts.REVISAR === 0));
      const matchesQuery =
        !normalized ||
        proposal.display_name.toLocaleLowerCase().includes(normalized) ||
        proposal.source_file.toLocaleLowerCase().includes(normalized) ||
        proposal.space.toLocaleLowerCase().includes(normalized) ||
        proposal.proposal_id.toLocaleLowerCase().includes(normalized);
      return matchesFilter && matchesQuery;
    });
  }, [filter, proposals, query]);

  return (
    <aside className="history-panel" aria-label="Historial de propuestas">
      <nav className="sidebar-navigation" aria-label="Acciones principales">
        <button type="button" onClick={onNewProposal} title="Generar nueva propuesta">
          <span className="sidebar-nav-icon">＋</span>
          <span className="sidebar-nav-copy"><strong>Nueva propuesta</strong><small>Limpiar el área de trabajo</small></span>
        </button>
        <button type="button" className={settingsActive ? "active" : ""} onClick={onOpenSettings} title="Configurar conexión Jira">
          <span className="sidebar-nav-icon">⚙</span>
          <span className="sidebar-nav-copy"><strong>Configuración Jira</strong><small>{jiraConnected ? jiraWriteEnabled ? "Conectada · envío controlado" : "Conectada · sólo lectura" : "Desconectada"}</small></span>
          <span className={`sidebar-connection-dot ${jiraConnected ? "online" : "offline"}`}></span>
        </button>
      </nav>
      <div className="history-heading">
        <span className="eyebrow">Historial local</span>
        <h2>Propuestas</h2>
      </div>
      <div className="history-tools">
        <input
          type="search"
          placeholder="Buscar propuesta"
          aria-label="Buscar propuestas"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
        />
        <select
          value={filter}
          onChange={(event) => setFilter(event.target.value as HistoryFilter)}
          aria-label="Filtrar propuestas"
        >
          <option value="ACTIVE">Activas</option>
          <option value="REVIEW">Con pendientes</option>
          <option value="READY">Sin pendientes</option>
          <option value="ARCHIVED">Archivadas</option>
        </select>
      </div>
      {visible.length === 0 ? (
        <p className="history-empty">
          {proposals.length === 0 ? "Aún no hay propuestas." : "No hay coincidencias."}
        </p>
      ) : (
        <div className="history-list">
          {visible.map((proposal) => (
            <div
              className={`history-item ${currentId === proposal.proposal_id ? "active" : ""}`}
              key={proposal.proposal_id}
              title={collapsed ? proposal.display_name : undefined}
            >
              <button
                className="history-open"
                onClick={() => onOpen(proposal.proposal_id)}
                disabled={proposal.archived}
                aria-label={`Abrir ${proposal.display_name}`}
              >
                <span className="history-short">{proposal.space}</span>
                <span className="history-copy">
                  <strong title={proposal.display_name}>{proposal.display_name}</strong>
                  <small title={`${proposal.source_file} · ${proposal.space} · versión ${proposal.version}`}>
                    {proposal.source_file} · {proposal.space} · versión {proposal.version}
                  </small>
                </span>
                <span className="history-count">
                  {loadingId === proposal.proposal_id ? "…" : proposal.counts.REVISAR}
                </span>
              </button>
              <button
                className="history-action"
                onClick={() => proposal.archived ? onRestore(proposal) : onArchive(proposal)}
                aria-label={proposal.archived ? `Restaurar ${proposal.display_name}` : `Archivar ${proposal.display_name}`}
                title={proposal.archived ? "Restaurar" : "Archivar"}
              >
                {proposal.archived ? "Restaurar" : "Archivar"}
              </button>
            </div>
          ))}
        </div>
      )}
    </aside>
  );
}

export function Workspace({ session, onLogout }: { session: Session; onLogout: () => void }) {
  const [proposals, setProposals] = useState<ProposalSummary[]>([]);
  const [current, setCurrent] = useState<Proposal | null>(null);
  const [loadingId, setLoadingId] = useState("");
  const [lifecycleError, setLifecycleError] = useState("");
  const [settingsOpen, setSettingsOpen] = useState(
    () => new URLSearchParams(window.location.search).has("atlassian"),
  );
  const [atlassianStatus, setAtlassianStatus] = useState<AtlassianStatus | null>(null);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(
    () => localStorage.getItem(SIDEBAR_KEY) === "true",
  );

  async function refreshList() {
    setProposals(await listProposals(session.access_token));
  }

  useEffect(() => {
    void refreshList();
    void getAtlassianStatus(session.access_token)
      .then(setAtlassianStatus)
      .catch(() => setAtlassianStatus(null));
  }, []);

  useEffect(() => {
    localStorage.setItem(SIDEBAR_KEY, String(sidebarCollapsed));
  }, [sidebarCollapsed]);

  useEffect(() => {
    function toggleSidebar(event: KeyboardEvent) {
      if (event.ctrlKey && event.key.toLocaleLowerCase() === "b") {
        event.preventDefault();
        setSidebarCollapsed((value) => !value);
      }
    }
    window.addEventListener("keydown", toggleSidebar);
    return () => window.removeEventListener("keydown", toggleSidebar);
  }, []);

  function created(proposal: Proposal) {
    setCurrent(proposal);
    setSettingsOpen(false);
    void refreshList();
  }

  function newProposal() {
    setCurrent(null);
    setSettingsOpen(false);
    setLifecycleError("");
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  async function openProposal(proposalId: string) {
    setLoadingId(proposalId);
    try {
      setCurrent(await getProposal(session.access_token, proposalId));
      setSettingsOpen(false);
    } finally {
      setLoadingId("");
    }
  }

  function updated(proposal: Proposal) {
    setCurrent(proposal);
    void refreshList();
  }

  async function archive(summary: ProposalSummary) {
    if (!window.confirm(`¿Archivar la propuesta "${summary.display_name}"? Podrás restaurarla después.`)) {
      return;
    }
    setLifecycleError("");
    try {
      await archiveProposal(session.access_token, summary.proposal_id);
      if (current?.proposal_id === summary.proposal_id) setCurrent(null);
      await refreshList();
    } catch (reason) {
      setLifecycleError(reason instanceof Error ? reason.message : "No fue posible archivar.");
    }
  }

  async function restore(summary: ProposalSummary) {
    setLifecycleError("");
    try {
      await restoreProposal(session.access_token, summary.proposal_id);
      await refreshList();
    } catch (reason) {
      setLifecycleError(reason instanceof Error ? reason.message : "No fue posible restaurar.");
    }
  }

  async function rename(name: string) {
    if (!current || !name.trim()) return;
    setLifecycleError("");
    try {
      await renameProposal(session.access_token, current.proposal_id, name.trim());
      await refreshList();
    } catch (reason) {
      const message = reason instanceof Error ? reason.message : "No fue posible renombrar.";
      setLifecycleError(message);
      throw reason;
    }
  }

  const currentSummary = proposals.find(
    (proposal) => proposal.proposal_id === current?.proposal_id,
  );

  return (
    <div className={`app-shell ${sidebarCollapsed ? "sidebar-collapsed" : ""}`}>
      <header className="topbar">
        <button
          className="sidebar-toggle"
          onClick={() => setSidebarCollapsed((value) => !value)}
          aria-label="Alternar barra lateral"
          title="Alternar barra lateral (Ctrl+B)"
        >
          {sidebarCollapsed ? "›" : "‹"}
        </button>
        <Logo />
        <div className={`environment-badge ${atlassianStatus?.connected ? atlassianStatus.jira_write_enabled ? "controlled" : "" : "offline"}`}>
          <span></span> Local · {atlassianStatus?.connected ? atlassianStatus.jira_write_enabled ? "Jira conectada · envío controlado" : "Jira conectada en solo lectura" : "Jira desconectada"}
        </div>
        <div className="mobile-actions" aria-label="Acciones principales">
          <button type="button" onClick={newProposal} aria-label="Generar nueva propuesta" title="Nueva propuesta">＋</button>
          <button type="button" onClick={() => { setSettingsOpen(true); setCurrent(null); }} aria-label="Configurar Jira" title="Configuración Jira">⚙</button>
        </div>
        <div className="user-menu">
          <span>
            <strong>{session.user.display_name}</strong>
            <small>{session.user.username}</small>
          </span>
          <button className="button ghost" onClick={onLogout}>Salir</button>
        </div>
      </header>
      <main className="workspace">
        <ProposalHistory
          proposals={proposals}
          currentId={current?.proposal_id ?? null}
          loadingId={loadingId}
          collapsed={sidebarCollapsed}
          onOpen={(proposalId) => void openProposal(proposalId)}
          onArchive={(proposal) => void archive(proposal)}
          onRestore={(proposal) => void restore(proposal)}
          onNewProposal={newProposal}
          onOpenSettings={() => { setSettingsOpen(true); setCurrent(null); }}
          settingsActive={settingsOpen}
          jiraConnected={Boolean(atlassianStatus?.connected)}
          jiraWriteEnabled={Boolean(atlassianStatus?.jira_write_enabled)}
        />
        <div className="content-area">
          {lifecycleError && <div className="alert error">{lifecycleError}</div>}
          {settingsOpen ? (
            <AtlassianConnectionPanel token={session.access_token} onStatusChange={setAtlassianStatus} />
          ) : current ? (
            <ProposalReview
              token={session.access_token}
              proposal={current}
              displayName={currentSummary?.display_name ?? current.source_file.name.replace(/\.xlsx$/i, "")}
              onRename={rename}
              onUpdated={updated}
              onNewProposal={newProposal}
            />
          ) : (
            <>
              <UploadPanel token={session.access_token} onCreated={created} />
              <section className="welcome-card">
                <span className="welcome-mark">01</span>
                <div>
                  <span className="eyebrow">Comienza aquí</span>
                  <h2>Genera una nueva propuesta</h2>
                  <p>
                    Carga el plan y sigue los tres pasos indicados: revisar, validar con Jira y probar el envío.
                  </p>
                </div>
              </section>
            </>
          )}
        </div>
      </main>
    </div>
  );
}

export default function App() {
  const [session, setSession] = useState<Session | null>(() => readSession());

  function handleLogin(nextSession: Session) {
    sessionStorage.setItem(SESSION_KEY, JSON.stringify(nextSession));
    setSession(nextSession);
  }

  async function logout() {
    sessionStorage.removeItem(SESSION_KEY);
    setSession(null);
  }

  return session ? (
    <Workspace session={session} onLogout={logout} />
  ) : (
    <LoginScreen onLogin={handleLogin} />
  );
}
