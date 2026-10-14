import { FormEvent, type ReactNode, useEffect, useMemo, useRef, useState } from "react";
import {
  ApiError,
  approveProposalAndDryRun,
  archiveProposal,
  bulkUpdateProposal,
  trashProposal,
  cancelObjective4ASimulation,
  confirmObjective4BWrite,
  confirmObjective4ASimulation,
  connectAtlassianExternal,
  createProposal,
  preflightProposal,
  downloadDryRunEvidence,
  downloadObjective4AEvidence,
  downloadObjective4BEvidence,
  downloadObjective4C1Evidence,
  executeObjective4C1Batch,
  executeObjective4BWrite,
  excludeProposalItems,
  findJiraAssignees,
  listJiraSprints,
  generateJiraDryRun,
  getAtlassianStatus,
  lockJiraWrites,
  getLatestJiraDryRun,
  getLatestObjective4ASimulation,
  getLatestObjective4C1Batch,
  getObjective4AReadiness,
  getObjective4C2Progress,
  getProposal,
  listProposals,
  getCurrentSession,
  logout as logoutSession,
  prepareObjective4ASimulation,
  prepareObjective4BWrite,
  prepareObjective4C1Batch,
  revalidateObjective4C1Batch,
  confirmObjective4C1Batch,
  reactivateProposalItem,
  refreshAtlassian,
  renameProposal,
  permanentlyDeleteProposal,
  reopenProposal,
  restoreProposal,
  runObjective4ASimulation,
  unlockJiraWrites,
  unlinkAtlassian,
  updateProposalItem,
  updateProposalDefaults,
  startAtlassianLogin,
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
import { ThemeToggle } from "./ThemeToggle";
import { applyTheme, readInitialTheme, type Theme } from "./theme";
import { VoiceAssistant } from "./voice/VoiceAssistant";
import { SESSION_EXPIRED_EVENT } from "./authEvents";
import { diagnoseAtlassian } from './api';
import { JiraDiagnostics } from './JiraDiagnostics';
import { NewProposal, MinutesReview } from "./Minutes";
import { Dashboard } from "./Dashboard";
import { Onboarding } from "./Onboarding";
import { emitOnboardingEvent } from "./onboardingEvents";

const SIDEBAR_KEY = "agente-jira-sidebar-collapsed";
// Temporarily keep voice out of the main workspace while its integration is repaired.
const VOICE_UI_ENABLED = false;

function userInitials(displayName: string): string {
  const initials = displayName.trim().split(/\s+/).filter(Boolean).slice(0, 2).map(part => part[0]).join("");
  return initials.toUpperCase() || "AJ";
}

type IconName = "plus" | "sliders" | "chevron-left" | "chevron-right" | "download" | "upload" | "shield" | "pencil" | "dashboard" | "users" | "file" | "bolt" | "lock" | "check" | "arrow-right";

function Icon({ name, className = "" }: { name: IconName; className?: string }) {
  const paths: Record<IconName, ReactNode> = {
    plus: <><path d="M12 5v14" /><path d="M5 12h14" /></>,
    sliders: <><path d="M4 7h7" /><path d="M15 7h5" /><circle cx="13" cy="7" r="2" /><path d="M4 17h3" /><path d="M11 17h9" /><circle cx="9" cy="17" r="2" /></>,
    "chevron-left": <path d="m15 18-6-6 6-6" />,
    "chevron-right": <path d="m9 18 6-6-6-6" />,
    download: <><path d="M12 4v11" /><path d="m8 11 4 4 4-4" /><path d="M5 20h14" /></>,
    upload: <><path d="M12 20V9" /><path d="m8 13 4-4 4 4" /><path d="M5 4h14" /></>,
    shield: <><path d="M12 3 5 6v5c0 4.6 2.8 8.2 7 10 4.2-1.8 7-5.4 7-10V6l-7-3Z" /><path d="m9 12 2 2 4-4" /></>,
    pencil: <><path d="m16 5 3 3" /><path d="M4 20h4l11-11a2.1 2.1 0 0 0-4-4L4 16v4Z" /></>,
    dashboard: <><rect x="3.5" y="3.5" width="7" height="7" rx="1" /><rect x="13.5" y="3.5" width="7" height="4" rx="1" /><rect x="13.5" y="10.5" width="7" height="10" rx="1" /><rect x="3.5" y="13.5" width="7" height="7" rx="1" /></>,
    users: <><circle cx="9" cy="8" r="3" /><path d="M3.5 20a5.5 5.5 0 0 1 11 0" /><path d="M16 5.5a3 3 0 0 1 0 5.8" /><path d="M17 14.5a5.2 5.2 0 0 1 3.5 5" /></>,
    file: <><path d="M6 3.5h8l4 4V20.5H6z" /><path d="M14 3.5v4h4" /><path d="M9 12h6M9 15.5h6" /></>,
    bolt: <path d="m13.2 2.8-8 10.4h6.1l-.7 8 8.2-11h-6.2z" />,
    lock: <><rect x="5" y="10" width="14" height="11" rx="2" /><path d="M8 10V7a4 4 0 0 1 8 0v3" /></>,
    check: <path d="m5 12 4 4L19 6" />,
    "arrow-right": <><path d="M5 12h14" /><path d="m13 6 6 6-6 6" /></>,
  };
  return (
    <svg className={`ui-icon ${className}`} viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <g stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">{paths[name]}</g>
    </svg>
  );
}

function normalizeIdentity(value: string | null | undefined): string {
  return (value ?? "")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .trim()
    .replace(/\s+/g, " ")
    .toLocaleLowerCase();
}

function jiraSiteLabel(value: string | null | undefined): string {
  if (!value) return "Sitio no disponible";
  try {
    return new URL(value).hostname.replace(/^www\./, "");
  } catch {
    return value.replace(/^https?:\/\//, "").replace(/\/$/, "");
  }
}

type GeneralValueKey = keyof Omit<ProposalDefaults, "space">;
type GeneralValueOption = { value: string; label: string };

const GENERAL_VALUE_FIELDS: Array<{
  key: GeneralValueKey;
  label: string;
}> = [
  { key: "iniciativa", label: "Iniciativa" },
  { key: "linea_trabajo", label: "L\u00ednea de trabajo" },
  { key: "sprint", label: "Sprint" },
  { key: "tipo_seguimiento", label: "Tipo de seguimiento" },
  { key: "semaforo", label: "Sem\u00e1foro" },
];

function inferBusinessKey(name: string | null | undefined): GeneralValueKey | null {
  const normalized = normalizeIdentity(name).replace(/_/g, " ");
  const aliases: Record<string, GeneralValueKey> = {
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

function buildGeneralValueCatalogs(
  status: AtlassianStatus | null,
  spaceKey: Space,
  sprints: JiraSprint[],
): Map<GeneralValueKey, GeneralValueOption[]> {
  const result = new Map<GeneralValueKey, GeneralValueOption[]>();
  const space = status?.snapshot?.spaces.find((candidate) => candidate.key === spaceKey);
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
      label: `${sprint.name} \u00b7 ${sprint.state === "active" ? "Activo" : "Futuro"}`,
    })));
  }
  return result;
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

function LoginScreen() {
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    const code = new URLSearchParams(window.location.search).get("auth");
    if (!code) return;
    const messages: Record<string, string> = {
      ACCESS_DENIED: "La autorización de Atlassian fue cancelada.",
      STATE_INVALID: "La sesión de inicio ya no es válida. Intenta de nuevo.",
      TOKEN_EXCHANGE_FAILED: "Atlassian no pudo completar la autorización. Intenta de nuevo.",
      NO_ALLOWED_LOCAL_USER: "Tu cuenta Atlassian fue autenticada, pero no tienes acceso al Agente Jira.",
      IDENTITY_UNAVAILABLE: "Atlassian no entregó la identidad requerida. Intenta de nuevo.",
    };
    if (messages[code]) setError(messages[code]);
    window.history.replaceState({}, "", window.location.pathname);
  }, []);

  async function continueWithAtlassian() {
    setLoading(true);
    setError("");
    try {
      const result = await startAtlassianLogin(window.location.pathname || "/");
      window.location.assign(result.authorization_url);
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
          <span className="eyebrow">De conversaciones a resultados</span>
          <h1>Convierte minutas y planes en trabajo claro <span>para Jira.</span></h1>
          <p>Carga tu minuta o plan, revisa las excepciones y crea actividades únicamente cuando todo esté confirmado.</p>
          <ul className="feature-list login-benefits">
            <li><span className="login-benefit-icon"><Icon name="users" /></span><span><strong>Datos y responsables desde Jira</strong><small>Consulta información real de tu entorno.</small></span></li>
            <li><span className="login-benefit-icon"><Icon name="file" /></span><span><strong>Archivo original protegido</strong><small>Conserva la trazabilidad completa.</small></span></li>
            <li><span className="login-benefit-icon"><Icon name="bolt" /></span><span><strong>Creación controlada y confirmada</strong><small>Tú decides qué se crea, siempre.</small></span></li>
          </ul>
        </div>
        <div className="login-flow-illustration" aria-hidden="true">
          <div className="login-flow-card">
            <div className="login-flow-file"><span className="login-flow-file-icon"><Icon name="file" /></span><span><strong>Minuta de proyecto.docx</strong><small>Analizando contenido…</small></span></div>
            <div className="login-flow-step"><span><Icon name="check" /></span>Identificando tareas</div>
            <div className="login-flow-step"><span><Icon name="check" /></span>Validando responsables</div>
            <div className="login-flow-step"><span><Icon name="check" /></span>Revisando excepciones</div>
            <div className="login-flow-ready"><span><Icon name="check" /></span>Listo para crear en Jira</div>
          </div>
        </div>
        <p className="security-note"><Icon name="shield" /><span><strong>Entorno local seguro</strong><small>Solo tu organización</small></span></p>
      </section>
      <section className="login-panel">
        <section className="login-card">
          <span className="eyebrow">Acceso corporativo</span>
          <h2>Accede con tu cuenta corporativa</h2>
          <p className="muted">
            Usa tu cuenta de Atlassian para identificarte. Agente Jira no recibe ni almacena tu contraseña.
          </p>
          <button type="button" className="button primary full login-atlassian-button" onClick={continueWithAtlassian} disabled={loading}>
            <span className="login-atlassian-mark" aria-hidden="true">A</span>
            <span>{loading ? "Conectando con Atlassian…" : "Continuar con Atlassian"}</span>
            {!loading && <Icon name="arrow-right" className="login-button-arrow" />}
            {loading && <span className="login-spinner" aria-hidden="true" />}
          </button>
          <div className="login-divider"><span>Una sola cuenta para entrar y consultar Jira.</span></div>
          <ul className="login-trust-list">
            <li><Icon name="check" />Se respetan tus permisos reales de Jira.</li>
            <li><Icon name="check" />Acceso seguro a través de Atlassian.</li>
          </ul>
          {error && <div className="alert error">{error}</div>}
          <div className="login-credential-note"><span className="login-credential-icon"><Icon name="lock" /></span><span><strong>Tu contraseña permanece con Atlassian.</strong><small>Agente Jira no la almacena ni la procesa.</small></span></div>
        </section>
        <div className="login-panel-footer"><span>AGENTE JIRA</span><small>Planificación inteligente. Equipos más fuertes.</small></div>
      </section>
    </main>
  );
}

interface UploadPanelProps {
  token: string;
  onCreated: (proposal: Proposal) => void;
}

export function UploadPanel({ token, onCreated }: UploadPanelProps) {
  const [file, setFile] = useState<File | null>(null);
  const [space, setSpace] = useState<Space>("AT");
  const [expanded, setExpanded] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [jiraStatus, setJiraStatus] = useState<AtlassianStatus | null>(null);
  const [catalogLoading, setCatalogLoading] = useState(true);
  const [catalogError, setCatalogError] = useState("");
  const [sprints, setSprints] = useState<JiraSprint[]>([]);
  const [sprintsLoading, setSprintsLoading] = useState(false);

  useEffect(() => {
    let active = true;
    setCatalogLoading(true);
    getAtlassianStatus(token)
      .then((result) => { if (active) setJiraStatus(result); })
      .catch((reason) => {
        if (active) setCatalogError(reason instanceof Error ? reason.message : "No fue posible consultar los catálogos de Jira.");
      })
      .finally(() => { if (active) setCatalogLoading(false); });
    return () => { active = false; };
  }, [token]);

  useEffect(() => {
    let active = true;
    if (!expanded || !jiraStatus?.connected) {
      setSprints([]);
      setSprintsLoading(false);
      return () => { active = false; };
    }
    setSprintsLoading(true);
    setCatalogError("");
    listJiraSprints(token, space)
      .then((result) => { if (active) setSprints(result); })
      .catch((reason) => {
        if (active) {
          setSprints([]);
          setCatalogError(reason instanceof Error ? reason.message : "No fue posible recuperar los Sprints de Jira.");
        }
      })
      .finally(() => { if (active) setSprintsLoading(false); });
    return () => { active = false; };
  }, [expanded, jiraStatus?.connected, token, space]);

  const catalogs = useMemo(
    () => buildGeneralValueCatalogs(jiraStatus, space, sprints),
    [jiraStatus, space, sprints],
  );

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!file) return;
    setLoading(true);
    setError(null);
    const values = new FormData(event.currentTarget);
    values.set("file", file);
    values.set("space", space);
    try {
      const created = await createProposal(token, values);
      // Preflight is read-only; an unavailable Jira connection must not block local review.
      void preflightProposal(token, created.proposal_id).catch(() => undefined);
      onCreated(created);
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

  async function downloadTemplate() {
    const response = await fetch("/api/template/v1.3", {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!response.ok) {
      setError(new ApiError("No fue posible generar la plantilla con el catálogo actual de Jira.", response.status));
      return;
    }
    if (response.headers.get("X-Catalog-Status") === "unavailable") {
      setError(new ApiError("No fue posible actualizar el catálogo de Jira. Puedes capturar la actividad, pero el Tipo de seguimiento deberá validarse al importar.", 200));
    }
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = "plantilla_plan_trabajo_jira_v1_3.xlsx";
    anchor.click();
    URL.revokeObjectURL(url);
  }

  return (
    <section className="upload-card upload-studio">
      <aside className="upload-intro">
        <div>
          <span className="upload-number">01</span>
          <span className="eyebrow">Crear actividades</span>
          <h2>Del Excel a un plan claro y revisable.</h2>
          <p>
            El agente organiza las actividades, consulta los valores de Jira y separa
            únicamente lo que necesita tu atención.
          </p>
        </div>
        <ol className="upload-roadmap" aria-label="Flujo de preparación">
          <li className="active"><span>1</span><div><strong>Cargar el archivo</strong><small>Conservamos el original sin cambios</small></div></li>
          <li><span>2</span><div><strong>Revisar excepciones</strong><small>Sólo verás decisiones que requieren criterio</small></div></li>
          <li><span>3</span><div><strong>Comprobar con Jira</strong><small>Nada se crea sin tu confirmación</small></div></li>
        </ol>
        <button type="button" className="template-link" onClick={() => void downloadTemplate()}>
          <span><Icon name="download" /></span>
          <div><strong>Descargar plantilla Excel</strong><small>Versión 1.2 · catálogos guiados (compatible con v1.1)</small></div>
        </button>
      </aside>
      <form className="upload-workbench" onSubmit={submit}>
        <div className="upload-form-heading">
          <div>
            <span className="eyebrow">Datos de entrada</span>
            <h3>Prepara tu archivo</h3>
          </div>
          <span className={`jira-sync-state ${jiraStatus?.connected ? "online" : ""}`}>
            <i></i>{catalogLoading ? "Consultando Jira" : jiraStatus?.connected ? "Jira sincronizada" : "Jira sin conectar"}
          </span>
        </div>
        <label className={`drop-zone ${file ? "has-file" : ""}`}>
          <input
            type="file"
            accept=".xlsx"
            onChange={(event) => setFile(event.target.files?.[0] ?? null)}
            required
          />
          <span className="upload-icon"><Icon name={file ? "shield" : "upload"} /></span>
          <strong>{file ? file.name : "Arrastra o selecciona tu Excel"}</strong>
          <small>
            {file
              ? `${(file.size / 1024).toFixed(1)} KB · lista para validar`
              : "Archivo .xlsx · máximo 10 MB"}
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
            {expanded ? "Ocultar campos de Jira" : "Configurar campos de Jira"}
          </button>
        </div>
        {expanded && (
          <>
            {!catalogLoading && !jiraStatus?.connected && (
              <div className="alert warning" role="status">
                Conecta Jira desde Configuración Jira para cargar los valores disponibles.
              </div>
            )}
            <div className="optional-grid">
              {GENERAL_VALUE_FIELDS.map(({ key, label }) => {
                const options = catalogs.get(key) ?? [];
                const activeSprintCount = sprints.filter((sprint) => sprint.state === "active").length;
                const fieldLoading = catalogLoading || (key === "sprint" && sprintsLoading);
                return (
                  <label key={key}>
                    {label}
                    <select
                      name={key}
                      aria-label={label}
                      defaultValue=""
                      disabled={fieldLoading || !jiraStatus?.connected || options.length === 0}
                      aria-busy={fieldLoading}
                    >
                      <option value="">
                        {fieldLoading
                          ? "Cargando opciones de Jira…"
                          : !jiraStatus?.connected
                            ? "Conecta Jira para cargar opciones"
                            : options.length === 0
                              ? "Jira no publicó opciones para este campo"
                              : key === "sprint" && activeSprintCount > 1
                                ? "Selecciona un Sprint (hay varios activos)"
                                : key === "sprint" && activeSprintCount === 1
                                  ? "Automático: usar el único Sprint activo"
                                  : "Sin valor"}
                      </option>
                      {options.map((option) => (
                        <option key={option.value} value={option.value}>{option.label}</option>
                      ))}
                    </select>
                    <small className={options.length > 0 ? "catalog-status live" : "catalog-status"}>
                      {options.length > 0
                        ? `${options.length} ${options.length === 1 ? "opción recuperada" : "opciones recuperadas"} de Jira`
                        : fieldLoading
                          ? "Consultando Jira…"
                          : jiraStatus?.connected
                            ? key === "sprint"
                              ? "Jira no devolvió Sprints activos o futuros para este Space."
                              : "Jira no publicó opciones para este campo."
                            : "Conecta Jira para consultar valores reales."}
                    </small>
                  </label>
                );
              })}
            </div>
            {catalogError && <div className="alert warning" role="alert">{catalogError}</div>}
          </>
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
          <span className="muted"><b>Modo seguro:</b> todavía no se creará nada en Jira.</span>
          <button className="button primary" disabled={!file || loading}>
            {loading ? "Preparando propuesta…" : "Preparar propuesta"}
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
  onEdit,
  editDisabled,
}: {
  proposal: Proposal;
  displayName: string;
  onRename: (name: string) => Promise<void>;
  onEdit: () => void;
  editDisabled: boolean;
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
        <p className="source-filename">{proposal.minutes ? "Origen: " : "Archivo fuente inmutable: "}{proposal.source_file.name}</p>
      </div>
      <div className="proposal-header-side">
        <button
          type="button"
          className="button secondary proposal-edit"
          onClick={onEdit}
          disabled={editDisabled}
          title={editDisabled ? "La edición se habilitará al terminar la operación en curso." : "Editar actividades o valores de la propuesta"}
        >
          Editar propuesta
        </button>
        <div className="metrics" aria-label="Resumen de decisiones">
          <div><strong>{counts.INCLUIR}</strong><span>listas</span></div>
          <div className="review"><strong>{counts.REVISAR}</strong><span>por revisar</span></div>
          <div><strong>{counts.EXCLUIR}</strong><span>excluidas</span></div>
        </div>
      </div>
    </div>
  );
}

interface DetailPanelProps {
  token: string;
  item: ProposalItem;
  proposalItems: ProposalItem[];
  isMinutesProposal: boolean;
  onClose: () => void;
  locked: boolean;
  correction?: JiraCorrectionItem | null;
  onReactivate: (reason: string) => Promise<void>;
  onSave: (values: {
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
    dueDate: string;
  },
): boolean {
  if (requirement.code === "ASSIGNEE_UNRESOLVED") return Boolean(values.assigneeAccountId);
  if (requirement.code === "SOURCE_STATE_UNCONFIRMED") return values.confirmSourceState;
  if (requirement.code === "WORK_TYPE_UNCONFIRMED") return values.confirmWorkType;
  if (requirement.code === "SUBTASK_PARENT_MISSING") return values.workType !== "Subtask" || Boolean(values.parentRowId);
  if (requirement.code === "REACTIVATION_REVIEW_REQUIRED") return values.confirmReactivation;
  if (requirement.code === "DUE_DATE_EXPIRED") {
    const today = new Date();
    const localToday = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}-${String(today.getDate()).padStart(2, "0")}`;
    return /^\d{4}-\d{2}-\d{2}$/.test(values.dueDate) && values.dueDate >= localToday;
  }
  return false;
}

function DetailPanel({ token, item, proposalItems, isMinutesProposal, onClose, onSave, onReactivate, locked, correction }: DetailPanelProps) {
  const [title, setTitle] = useState(item.generated.title);
  const [description, setDescription] = useState(item.generated.description);
  const [dueDate, setDueDate] = useState(item.source.fecha_objetivo ?? "");
  const [workType, setWorkType] = useState(item.generated.work_type);
  const trackingIssue = (correction?.issues ?? []).find((issue) => issue.field === "tipo_seguimiento");
  const [tipoSeguimiento, setTipoSeguimiento] = useState(item.generated.fields.tipo_seguimiento ?? "");
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
  const [assigneeCorrectionSelected, setAssigneeCorrectionSelected] = useState(false);
  const [assigneeQuery, setAssigneeQuery] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [jiraQuery, setJiraQuery] = useState(item.generated.assignee.display_name || item.source.responsable_display);
  const [jiraResults, setJiraResults] = useState<JiraAssignee[]>([]);
  const [jiraLookupPerformed, setJiraLookupPerformed] = useState(false);
  const [jiraSearching, setJiraSearching] = useState(false);
  const [jiraError, setJiraError] = useState("");
  const [saveError, setSaveError] = useState("");

  const requirements = item.validation.pending_requirements ?? [];
  const requirementValues = {
    assigneeAccountId,
    confirmSourceState,
    confirmWorkType,
    workType,
    parentRowId,
    confirmReactivation,
    dueDate,
  };
  const requirementsWithState = requirements.map((requirement) => ({
    ...requirement,
    resolved: isRequirementResolved(requirement, requirementValues),
  }));
  const unresolvedCount = requirementsWithState.filter((requirement) => !requirement.resolved).length
    + (trackingIssue && !tipoSeguimiento ? 1 : 0);
  async function submit(event: FormEvent) {
    event.preventDefault();
    setSaving(true);
    setSaveError("");
    try {
      await onSave({
        title,
        description,
        work_type: workType,
        tipo_seguimiento: tipoSeguimiento || null,
        review_note: note.trim() || null,
        assignee_account_id: pendingAssignee?.account_id ?? null,
        assignee_query: pendingAssignee ? assigneeQuery : null,
        parent_row_id: parentRowId || null,
        confirm_source_state: confirmSourceState,
        confirm_work_type: confirmWorkType,
        confirm_reactivation: confirmReactivation,
        ...(isMinutesProposal ? { due_date_candidate: dueDate || null } : {}),
      });
    } catch (reason) {
      setSaveError(reason instanceof Error ? reason.message : "No fue posible guardar y volver a validar.");
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
    setAssigneeCorrectionSelected(true);
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
            <span className="eyebrow">{item.source.source_evidence ? "Actividad de minuta" : `Fila ${item.source.source_row}`}</span>
            <h2>Origen y propuesta</h2>
          </div>
          <button className="icon-button" onClick={onClose} aria-label="Cerrar">×</button>
        </div>
        {correction && (
          <section className={`jira-correction-card ${correction.category === "TECHNICAL" ? "technical" : "action"}`} aria-label={correction.category === "TECHNICAL" ? "Comprobación automática" : "Corrección requerida"}>
            <span className="eyebrow">
              {correction.category === "TECHNICAL" ? "Comprobación automática" : "Corrección requerida"}
            </span>
            {assigneeCorrectionSelected && correction.category === "USER_ACTION" && correction.issues.some((issue) => issue.field === "assignee") ? (
              <strong>Responsable corregido: {pendingAssignee?.display_name}. Guarda para aplicar el cambio.</strong>
            ) : <strong>{correction.instruction}</strong>}
            <ul>
              {correction.issues.filter((issue) => !(assigneeCorrectionSelected && issue.field === "assignee")).map((issue) => <li key={`${issue.code}-${issue.field}`}>{issue.message}</li>)}
            </ul>
            {correction.category === "USER_ACTION" && !assigneeCorrectionSelected && correction.issues.some((issue) => issue.field === "assignee") && (
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
          {trackingIssue?.options && trackingIssue.options.length > 0 && (
            <label>
              Tipo de seguimiento
              <select value={tipoSeguimiento} onChange={(event) => setTipoSeguimiento(event.target.value)} required>
                <option value="">Selecciona uno vigente de Jira</option>
                {trackingIssue.options.map((option) => <option key={option.jira_id ?? option.value} value={option.value}>{option.value}</option>)}
              </select>
              <small>El valor anterior se conserva en la evidencia histórica; selecciona una opción vigente.</small>
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
          {isMinutesProposal && (
            <label>Fecha objetivo (no es la fecha de la minuta)<input type="date" value={dueDate} onChange={(event) => setDueDate(event.target.value)} disabled={locked || item.generated.decision === "EXCLUIR"} /></label>
          )}
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
          {saveError && <div className="alert error" role="alert">{saveError}</div>}
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
    <section className={`dry-run-panel ${successful ? "dry-run-ready" : "dry-run-blocked"} ${hasWarnings ? "dry-run-warning" : ""} ${stale ? "dry-run-stale" : ""}`} aria-label="Resultado de la comprobación en Jira">
      <div className="dry-run-heading">
        <div>
          <span className="eyebrow">Comprobación en Jira · sin crear</span>
          <h3>{stale ? "Resultado anterior" : dryRun.status === "READY" ? "Comprobación completada" : hasWarnings ? "Comprobación completada con advertencias" : "Hay datos por corregir"}</h3>
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
  onBusyChange,
  allowedWorkTypes = ["Task"],
}: {
  token: string;
  proposal: Proposal;
  dryRun: JiraDryRun;
  onNewProposal: () => void;
  onBusyChange?: (busy: boolean) => void;
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
  const [reviewConfirmed, setReviewConfirmed] = useState(false);
  const [finalModalOpen, setFinalModalOpen] = useState(false);
  const [authorizationExpired, setAuthorizationExpired] = useState(false);
  const [expanded, setExpanded] = useState(true);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [hydrated, setHydrated] = useState(false);
  const autoPrepareKeyRef = useRef("");

  useEffect(() => {
    let active = true;
    setBatch(null);
    setReviewConfirmed(false);
    setFinalModalOpen(false);
    setAuthorizationExpired(false);
    setError("");
    setHydrated(false);
    autoPrepareKeyRef.current = "";
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
      setAuthorizationExpired(Boolean(currentBatch && Date.now() > new Date(currentBatch.confirmation.expires_at).getTime()));
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
      setHydrated(true);
    });
    return () => { active = false; };
  }, [dryRun.dry_run_id, proposal.proposal_id, proposal.version, token]);

  useEffect(() => {
    if (!batch || !["BATCH_PREPARED", "BATCH_CONFIRMED"].includes(batch.status)) {
      setAuthorizationExpired(false);
      return;
    }
    const refresh = () => setAuthorizationExpired(Date.now() > new Date(batch.confirmation.expires_at).getTime());
    refresh();
    const timer = window.setInterval(refresh, 1000);
    return () => window.clearInterval(timer);
  }, [batch]);

  const creationBusy = batch?.status === "BATCH_RUNNING"
    || (loading && (batch?.status === "BATCH_PREPARED" || batch?.status === "BATCH_CONFIRMED"));

  useEffect(() => {
    onBusyChange?.(creationBusy);
  }, [creationBusy, onBusyChange]);

  useEffect(() => () => onBusyChange?.(false), [onBusyChange]);

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
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "No fue posible preparar el lote.");
    } finally { setLoading(false); }
  }

  async function confirmAndExecute() {
    if (!batch) return;
    setLoading(true); setError("");
    try {
      const confirmedBatch = await confirmObjective4C1Batch(
        token,
        batch.execution_id,
        batch.payload_hash,
        batch.confirmation_phrase,
      );
      setFinalModalOpen(false);
      setBatch(confirmedBatch);
      // A deliberate "Escribir en Jira" action owns the short write window;
      // users should not have to understand or operate a separate lock switch.
      await unlockJiraWrites(token);
      const result = await executeObjective4C1Batch(token, confirmedBatch.execution_id);
      setBatch(result);
      setProgress(await getObjective4C2Progress(token, proposal.proposal_id));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "No fue posible confirmar y crear el lote.");
    } finally { setLoading(false); }
  }

  async function revalidate() {
    if (!batch) return;
    setLoading(true); setError("");
    try {
      const refreshed = await revalidateObjective4C1Batch(token, batch.execution_id);
      setBatch(refreshed);
      setReviewConfirmed(false);
      setAuthorizationExpired(false);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "No fue posible verificar nuevamente.");
    } finally { setLoading(false); }
  }

  async function writeToJira() {
    if (!batch) return;
    setLoading(true); setError("");
    try {
      await unlockJiraWrites(token);
      const result = await executeObjective4C1Batch(token, batch.execution_id);
      setBatch(result);
      setProgress(await getObjective4C2Progress(token, proposal.proposal_id));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "No fue posible escribir el lote en Jira.");
    } finally { setLoading(false); }
  }

  function continueWithNextBatch() {
    if (!progress) return;
    setBatch(null);
    setError("");
    setSelected(dependencyAwareSelection(progress.available_row_ids));
    autoPrepareKeyRef.current = "";
  }

  const availableIds = new Set(progress?.available_row_ids ?? eligible.map((item) => item.row_id));
  const selectable = eligible.filter((item) => availableIds.has(item.row_id));

  useEffect(() => {
    if (!hydrated || batch || loading || error || selected.length < 1 || selected.length > 5 || selectable.length === 0) return;
    const key = `${proposal.version}:${dryRun.dry_run_id}:${selected.join("|")}`;
    if (autoPrepareKeyRef.current === key) return;
    autoPrepareKeyRef.current = key;
    void prepare();
  }, [batch, dryRun.dry_run_id, error, hydrated, loading, proposal.version, selectable.length, selected]);

  const terminal = batch && ["COMPLETED", "STOPPED_REJECTED", "STOPPED_UNKNOWN", "STOPPED_UNVERIFIED"].includes(batch.status);
  const title = batch?.status === "COMPLETED" ? "Lote creado y verificado"
    : batch?.status.startsWith("STOPPED_") ? "Lote detenido de forma segura"
      : batch?.status === "BATCH_CONFIRMED" ? "Lote autorizado para escritura"
        : batch?.status === "BATCH_PREPARED" ? "Confirmar creación en Jira"
          : hierarchyMode ? "Resumen final de actividades y relaciones" : "Resumen final para crear en Jira";

  return (
    <section id="controlled-batch" className="objective4a-panel current-step-card" aria-label="Lote controlado de Jira">
      <header className="objective4a-heading">
        <div>
          <span className="eyebrow">Paso 2 · confirmar y crear</span>
          <h3>{multiType ? title.replace("Tasks", "actividades") : title}</h3>
          <p>El resumen se prepara automáticamente con hasta 5 {hierarchyMode ? "actividades Task, Bug, Story, Epic o Subtask" : multiType ? "actividades Task, Bug o Story" : "Tasks"}. Revisa el contenido antes de confirmar; se crearán una por una y el proceso se detendrá ante la primera anomalía.</p>
        </div>
        <div className="section-heading-actions">
          <div className={`simulation-seal ${batch?.status === "COMPLETED" ? "real-success" : ""}`}>
            <strong>{batch ? `${batch.items.length} ${multiType ? "actividades listas para crear" : "Tasks listas para crear"}` : `${selected.length} seleccionadas`}</strong>
            <span>{batch && !terminal ? "No se ha creado ninguna actividad en Jira." : ""}</span>
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
            : error
              ? <div className="objective4a-actions"><button className="button secondary" disabled={loading || selected.length < 1 || selected.length > 5} onClick={() => void prepare()}>{loading ? "Preparando resumen…" : "Reintentar preparación del resumen"}</button></div>
              : <div className="objective4a-warning" role="status"><strong>Preparando el resumen final…</strong><span>Este paso es automático y no crea nada en Jira.</span></div>}
        </>}

        {batch && ["BATCH_PREPARED", "BATCH_CONFIRMED"].includes(batch.status) && authorizationExpired && <section className="real-confirmation-card expiry-card">
          <span className="eyebrow">La verificación de seguridad venció</span>
          <h4>Tus actividades siguen guardadas y no se creó nada en Jira.</h4>
          <p>Por seguridad necesitamos verificar nuevamente la información antes de crear.</p>
          <div className="objective4a-actions"><button className="button primary" disabled={loading} onClick={() => void revalidate()}>{loading ? "Verificando…" : "Verificar nuevamente"}</button></div>
        </section>}

        {batch?.status === "BATCH_PREPARED" && !authorizationExpired && <section className="real-confirmation-card">
          <span className="eyebrow">Confirmación final</span>
          <h4>Se crearán {batch.items.length} {multiType ? "actividades" : "Tasks"} reales en AT, en este orden</h4>
          <ol className="batch-items">
            {batch.items.map((item) => <li key={item.row_id}><strong>{item.preview.source_title}</strong><span>{item.preview.work_type} · {item.preview.assignee?.display_name} · {item.preview.parent_row_id ? `Padre ${item.preview.parent_issue_key ?? item.preview.parent_row_id} · ` : ""}{item.sprint_resolution?.selected?.name ?? "Sin Sprint"}</span><small>Nombre identificable: {item.preview.title}</small></li>)}
          </ol>
          <p>Si una actividad no puede crearse, el proceso se detendrá antes de continuar con las siguientes.</p>
          <p className="helper-text">Verificación válida hasta {new Date(batch.confirmation.expires_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}.</p>
          <label className="confirmation-checkbox"><input type="checkbox" checked={reviewConfirmed} onChange={(event) => setReviewConfirmed(event.target.checked)} /> Confirmo que revisé estas actividades y deseo crearlas en Jira.</label>
          <details className="payload-details"><summary>Detalles técnicos</summary><code>{JSON.stringify(batch.items.map((item) => ({ row_id: item.row_id, payload_hash: item.payload_hash, idempotency_key: item.idempotency_key })), null, 2)}</code><small>SHA-256 del lote: {batch.payload_hash}</small></details>
          <div className="objective4a-actions"><button className="button primary danger" disabled={loading || !reviewConfirmed} onClick={() => setFinalModalOpen(true)}>{`Crear ${batch.items.length} ${multiType ? "actividades" : batch.items.length === 1 ? "Task" : "Tasks"} en Jira`}</button></div>
        </section>}

        {finalModalOpen && batch?.status === "BATCH_PREPARED" && <div className="modal-backdrop" role="presentation"><section className="modal-card" role="dialog" aria-modal="true" aria-labelledby="final-create-title"><h4 id="final-create-title">Escribir actividades en Jira</h4><p>Se crearán {batch.items.length} actividades reales en el Space AT.</p><ul><li>{batch.items.length} actividades</li><li>{new Set(batch.items.map((item) => item.preview.assignee?.display_name)).size} responsables</li><li>Sprint seleccionado: {batch.items.map((item) => item.sprint_resolution?.selected?.name).filter(Boolean).join(", ") || "Sin Sprint"}</li></ul><p className="warning-text">Esta acción realizará escrituras reales en Jira.</p><div className="objective4a-actions"><button className="button secondary" disabled={loading} onClick={() => setFinalModalOpen(false)}>Cancelar</button><button className="button primary danger" disabled={loading} onClick={() => void confirmAndExecute()}>{loading ? "Escribiendo…" : "Escribir en Jira"}</button></div></section></div>}

        {batch?.status === "BATCH_CONFIRMED" && <section className="real-execute-card">
          <div><span className="eyebrow">Confirmación registrada</span><strong>Listo para escribir en Jira</strong><p>Antes de crear se revalidarán los Sprints y cada actividad se comprobará por separado.</p></div>
          <div className="objective4a-actions">
            <button className="button primary danger" disabled={loading} onClick={() => void writeToJira()}>{loading ? "Escribiendo y verificando…" : "Escribir en Jira"}</button>
          </div>
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
  onBusyChange,
}: {
  token: string;
  proposal: Proposal;
  dryRun: JiraDryRun;
  onNewProposal: () => void;
  onBusyChange?: (busy: boolean) => void;
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

  const singleWriteBusy = intent?.status === "SUBMITTED"
    || (loading && (intent?.status === "REAL_PREPARED" || intent?.status === "REAL_CONFIRMED"));

  useEffect(() => {
    if (!["CONTROLLED_BATCH", "CONTROLLED_MULTI_TYPE_BATCH", "CONTROLLED_HIERARCHY_BATCH"].includes(readiness?.policy?.mode ?? "")) {
      onBusyChange?.(singleWriteBusy);
    }
  }, [onBusyChange, readiness?.policy?.mode, singleWriteBusy]);

  useEffect(() => () => onBusyChange?.(false), [onBusyChange]);

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
    return <Objective4C1Panel token={token} proposal={proposal} dryRun={dryRun} onNewProposal={onNewProposal} onBusyChange={onBusyChange} allowedWorkTypes={readiness?.policy?.allowed_work_types ?? ["Task"]} />;
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
  const [statusLoading, setStatusLoading] = useState(true);
  const [sprintsLoading, setSprintsLoading] = useState(false);
  const [connecting, setConnecting] = useState(false);

  useEffect(() => {
    let active = true;
    setStatusLoading(true);
    setCatalogError("");
    getAtlassianStatus(token)
      .then((result) => { if (active) setStatus(result); })
      .catch((reason) => {
        if (active) setCatalogError(reason instanceof Error ? reason.message : "No fue posible consultar los cat\u00e1logos de Jira.");
      })
      .finally(() => { if (active) setStatusLoading(false); });
    return () => { active = false; };
  }, [token]);

  useEffect(() => {
    let active = true;
    if (!status?.connected) {
      setSprints([]);
      setSprintsLoading(false);
      return () => { active = false; };
    }
    setSprintsLoading(true);
    listJiraSprints(token, values.space, true)
      .then((result) => { if (active) setSprints(result); })
      .catch((reason) => {
        if (active) {
          setSprints([]);
          setCatalogError(reason instanceof Error ? reason.message : "No fue posible recuperar los Sprints de Jira.");
        }
      })
      .finally(() => { if (active) setSprintsLoading(false); });
    return () => { active = false; };
  }, [status?.connected, token, values.space]);

  const catalogs = useMemo(
    () => buildGeneralValueCatalogs(status, values.space, sprints),
    [status, values.space, sprints],
  );

  function updateValue(key: keyof ProposalDefaults, value: string) {
    setValues((current) => ({ ...current, [key]: value || null } as ProposalDefaults));
  }

  async function reconnectJira() {
    setConnecting(true);
    setCatalogError("");
    try {
      await connectAtlassianExternal(token);
      setCatalogError("Se abrió Atlassian en el navegador predeterminado. Completa el consentimiento allí y vuelve a esta ventana.");
    } catch (reason) {
      setCatalogError(reason instanceof Error ? reason.message : "No fue posible iniciar la autorización de Jira.");
      setConnecting(false);
    }
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
            {"Esta propuesta ya fue validada. Al guardar se crear\u00e1 una versi\u00f3n editable y deber\u00e1s validarla nuevamente con Jira."}
          </div>
        )}
        {statusLoading && (
          <div className="alert info" role="status">Consultando los catálogos de Jira…</div>
        )}
        {!statusLoading && !status?.connected && (
          <div className="jira-catalog-reconnect" role="status">
            <div>
              <strong>Conecta Jira para recuperar los menús desplegables</strong>
              <p>{status?.error || "La aplicación necesita una conexión Atlassian activa para mostrar únicamente valores reales de Jira."}</p>
            </div>
            <button type="button" className="button secondary" disabled={connecting} onClick={() => void reconnectJira()}>
              {connecting
                ? "Abriendo Atlassian…"
                : status?.phase === "ERROR"
                  ? "Volver a autorizar Jira"
                  : status?.phase === "AWAITING_USER_CONSENT"
                    ? "Continuar autorización Jira"
                    : "Conectar Jira"}
            </button>
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
            const fieldLoading = statusLoading || (key === "sprint" && sprintsLoading);
            return (
              <label key={key}>
                {label}
                <select
                  aria-label={label}
                  value={currentValue}
                  disabled={fieldLoading || !status?.connected || options.length === 0}
                  aria-busy={fieldLoading}
                  onChange={(event) => updateValue(key, event.target.value)}
                >
                  <option value="">
                    {fieldLoading
                      ? "Cargando opciones de Jira…"
                      : !status?.connected
                        ? "Conecta Jira para cargar opciones"
                        : options.length === 0
                          ? "Jira no publicó opciones para este campo"
                          : key === "sprint" && activeSprintCount > 1
                            ? "Selecciona un Sprint (hay varios activos)"
                            : key === "sprint" && activeSprintCount === 1
                              ? "Automático: usar el único Sprint activo"
                              : "Sin valor"}
                  </option>
                  {currentValue && !knownCurrent && <option value={currentValue}>{currentValue} · valor actual</option>}
                  {options.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
                </select>
                <small className={options.length > 0 ? "catalog-status live" : "catalog-status"}>
                  {options.length > 0
                    ? `${options.length} ${options.length === 1 ? "opci\u00f3n recuperada" : "opciones recuperadas"} de Jira`
                    : key === "sprint" && status?.connected
                      ? "Jira no devolvió Sprints activos o futuros para este Space."
                    : status?.connected
                      ? "Jira no public\u00f3 opciones para este campo."
                      : "Conecta Jira para consultar y seleccionar valores reales."}
                </small>
              </label>
            );
          })}
        </div>
        {catalogError && <div className="alert warning">{catalogError}</div>}
        <div className="drawer-actions">
          <button type="button" className="button secondary" onClick={onClose}>Cancelar</button>
          <button type="submit" className="button primary" disabled={saving || statusLoading || !status?.connected || connecting}>
            {saving ? "Guardando nueva versi\u00f3n\u2026" : !status?.connected ? "Conecta Jira para guardar" : "Guardar como nueva versi\u00f3n"}
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
  const [processingLifecycle, setProcessingLifecycle] = useState(false);
  const [dryRun, setDryRun] = useState<JiraDryRun | null>(null);
  const [dryRunLoading, setDryRunLoading] = useState(false);
  const [continueCorrections, setContinueCorrections] = useState(false);
  const [defaultsOpen, setDefaultsOpen] = useState(false);
  const [defaultsSaving, setDefaultsSaving] = useState(false);
  const [executionBusy, setExecutionBusy] = useState(false);
  const [bulkTrackingValue, setBulkTrackingValue] = useState("");
  const [bulkTrackingSaving, setBulkTrackingSaving] = useState(false);
  const [excludingPending, setExcludingPending] = useState(false);
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
        // The previous dry-run remains available as historical evidence, but is
        // no longer shown as an active blocker for the newly versioned proposal.
        setDryRun(null);
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
      throw reason;
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
      setSuccess(
        result.dry_run.status === "BLOCKED"
          ? `La validación de la versión ${result.proposal.version} detectó ${result.dry_run.summary.blocked} bloqueos que deben corregirse.`
          : `Validación con Jira completada para la versión ${result.proposal.version}, sin crear ni modificar actividades.`,
      );
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "No fue posible validar la propuesta.");
    } finally {
      setProcessingLifecycle(false);
    }
  }

  async function reopen(): Promise<Proposal | null> {
    setProcessingLifecycle(true);
    setError("");
    try {
      const updated = await reopenProposal(token, proposal.proposal_id);
      onUpdated(updated);
      setDryRun(null);
      setSuccess(
        `Versión ${updated.version} abierta para edición. La validación anterior se conservó en el historial, pero ya no autoriza ninguna creación.`,
      );
      return updated;
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "No fue posible reabrir.");
      return null;
    } finally {
      setProcessingLifecycle(false);
    }
  }

  async function editProposal() {
    if (processingLifecycle || dryRunLoading || executionBusy) return;
    if (approved) {
      const reopened = await reopen();
      if (!reopened) return;
    }
    window.setTimeout(() => {
      document.getElementById("proposal-activities")?.scrollIntoView({ behavior: "smooth", block: "start" });
    }, 0);
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
            ? `Validación completada con ${result.summary.ready_with_warnings ?? 0} advertencias técnicas no bloqueantes y sin escrituras en Jira.`
          : `Validación bloqueada: corrige ${result.summary.blocked} actividades antes de continuar.`,
      );
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "No fue posible ejecutar la validación con Jira.");
    } finally {
      setDryRunLoading(false);
    }
  }

  async function runReadOnlyPreflight() {
    setDryRunLoading(true);
    setError("");
    setSuccess("");
    try {
      const result = await preflightProposal(token, proposal.proposal_id) as JiraDryRun;
      setDryRun(result);
      setSuccess(
        result.status === "READY" || result.status === "READY_WITH_WARNINGS"
          ? "Comprobación con Jira completada en modo lectura. No se creó ninguna actividad."
          : `Comprobación con Jira completada: ${result.summary.blocked} actividades requieren corrección.`,
      );
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "No fue posible comprobar la propuesta con Jira.");
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
        + "La versi\u00f3n anterior se conserva y deber\u00e1s repetir la validaci\u00f3n con Jira.",
      );
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "No fue posible actualizar los valores generales.");
    } finally {
      setDefaultsSaving(false);
    }
  }

  async function applyTrackingToAll() {
    if (!bulkTrackingValue || bulkTrackingSaving) return;
    const activeRows = proposal.items.filter((item) => item.generated.decision !== "EXCLUIR");
    if (!window.confirm(`Se actualizarán ${activeRows.length} actividades localmente. No se modificará Jira.`)) return;
    setBulkTrackingSaving(true);
    setError("");
    try {
      const updated = await bulkUpdateProposal(token, proposal.proposal_id, "tipo_seguimiento", bulkTrackingValue,
        activeRows.map((item) => item.generated.row_id));
      onUpdated(updated);
      setSuccess(`Tipo de seguimiento aplicado a ${activeRows.length} actividades. Vuelve a verificar con Jira.`);
      setBulkTrackingValue("");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "No fue posible aplicar el valor a las actividades.");
    } finally { setBulkTrackingSaving(false); }
  }

  async function excludePendingItems() {
    const pending = proposal.items.filter((item) => item.generated.decision === "REVISAR");
    if (pending.length === 0 || excludingPending) return;
    if (!window.confirm(
      `Se excluirán ${pending.length} ${pending.length === 1 ? "actividad pendiente" : "actividades pendientes"} de esta propuesta. No se modificará Jira.`,
    )) return;
    setExcludingPending(true);
    setError("");
    setSuccess("");
    try {
      const updated = await excludeProposalItems(
        token,
        proposal.proposal_id,
        pending.map((item) => item.generated.row_id),
        "Excluida por decisión del usuario para crear únicamente las actividades seleccionadas.",
      );
      onUpdated(updated);
      setTab("INCLUIR");
      setDryRun(null);
      setSuccess(
        `${pending.length} ${pending.length === 1 ? "actividad pendiente fue excluida" : "actividades pendientes fueron excluidas"} localmente. Comprueba con Jira las actividades listas.`,
      );
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "No fue posible excluir las actividades pendientes.");
    } finally {
      setExcludingPending(false);
    }
  }

  const visibleTabs: Array<[ProposalTab, string]> = correctionMode
    ? [
        ["JIRA_ACTION", "Por corregir"],
        ["JIRA_TECHNICAL", "Comprobación automática"],
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
    <section data-tour-id="proposal-review" className="proposal-card">
      <ProposalHeader
        proposal={proposal}
        displayName={displayName}
        onRename={onRename}
        onEdit={() => void editProposal()}
        editDisabled={processingLifecycle || dryRunLoading || executionBusy}
      />
      <nav className="workflow-guide" aria-label="Progreso de la propuesta">
        <div className={approved && currentDryRun?.status !== "BLOCKED" ? "complete" : "active"}>
          <span>1</span><strong>Comprobar en Jira</strong><small>Revisa datos y corrige los pendientes</small>
        </div>
        <div className={approved && currentDryRun?.status !== "BLOCKED" ? "active" : ""}>
          <span>2</span><strong>Revisar y crear</strong><small>Confirma el resumen antes de crear</small>
        </div>
      </nav>
      {approved ? (
        <section className={`approval-banner ${currentDryRun?.status === "BLOCKED" ? "correction-state" : "approved-state"}`}>
          <div>
            <span className="eyebrow">{currentDryRun && currentDryRun.status !== "BLOCKED" ? "Validación con Jira completada" : currentDryRun ? "Correcciones Jira pendientes" : "Validación con Jira pendiente"}</span>
            <strong>{currentDryRun?.status === "READY_WITH_WARNINGS" ? `${count("INCLUIR")} ${count("INCLUIR") === 1 ? "actividad lista" : "actividades listas"} con advertencias` : currentDryRun?.status === "READY" ? `${count("INCLUIR")} ${count("INCLUIR") === 1 ? "actividad lista" : "actividades listas"} para confirmar y crear` : currentDryRun?.status === "BLOCKED" ? `${currentDryRun.summary.blocked} ${currentDryRun.summary.blocked === 1 ? "actividad requiere" : "actividades requieren"} corrección` : "La propuesta debe validarse con Jira"}</strong>
            <p>{currentDryRun?.status === "READY_WITH_WARNINGS" ? "Revisa las advertencias en el resumen final. Todavía no se ha creado ninguna actividad." : currentDryRun?.status === "READY" ? "Los datos y metadatos quedaron comprobados. Todavía no se ha creado ninguna actividad." : currentDryRun?.status === "BLOCKED" ? "Edita únicamente las actividades bloqueadas y vuelve a validar con Jira." : dryRun ? `La validación visible corresponde a la versión ${dryRun.proposal_version}; valida la versión actual ${proposal.version}.` : `Versión preparada por ${proposal.approved_by} · ${proposal.approved_at}`}</p>
          </div>
          <div className="approval-actions">
            {currentDryRun?.status === "BLOCKED" && <button className="button primary" disabled={processingLifecycle} onClick={() => void editProposal()}>Editar y resolver bloqueos</button>}
            {!currentDryRun && <button className="button primary" disabled={dryRunLoading} onClick={() => void runDryRun()}>{dryRunLoading ? "Comprobando en Jira…" : "Comprobar en Jira"}</button>}
            {currentDryRun && <button className="button secondary" disabled={dryRunLoading || executionBusy} onClick={() => void runDryRun()}>{dryRunLoading ? "Comprobando en Jira…" : "Comprobar nuevamente"}</button>}
            {currentDryRun && <button className="button secondary" onClick={() => void downloadDryRunEvidence(token, proposal.proposal_id, displayName)}>Descargar evidencia JSON</button>}
          </div>
        </section>
      ) : correctionMode && (correctionWorkflow?.summary.pending_user ?? 0) > 0 ? (
        <section className="approval-banner correction-state">
          <div>
            <span className="eyebrow">Corrección previa a la validación</span>
            <strong>{correctionWorkflow?.summary.pending_user} {correctionWorkflow?.summary.pending_user === 1 ? "actividad requiere" : "actividades requieren"} una corrección</strong>
            <p>{correctionWorkflow?.summary.technical ?? 0} {(correctionWorkflow?.summary.technical ?? 0) === 1 ? "validación técnica no requiere" : "validaciones técnicas no requieren"} que modifiques datos. Te guiaremos actividad por actividad.</p>
          </div>
          <button className="button primary" onClick={openNextCorrection}>Resolver siguiente bloqueo</button>
        </section>
      ) : correctionMode ? (
        <section className="approval-banner ready-state">
          <div>
            <span className="eyebrow">Propuesta lista para validar</span>
            <strong>Las correcciones necesarias están completas</strong>
            <p>{correctionWorkflow?.summary.technical ?? 0} {(correctionWorkflow?.summary.technical ?? 0) === 1 ? "comprobación técnica se repetirá" : "comprobaciones técnicas se repetirán"} al validar con Jira. No se creará ninguna actividad.</p>
          </div>
          <button className="button primary" disabled={processingLifecycle} onClick={() => void approve()}>{processingLifecycle ? "Comprobando en Jira…" : "Comprobar en Jira"}</button>
        </section>
      ) : count("REVISAR") === 0 ? (
        <section className="approval-banner ready-state">
          <div>
            <span className="eyebrow">Propuesta lista para validar</span>
            <strong>Ya no hay actividades pendientes</strong>
            <p>Comprueba la propuesta con Jira. Esta acción no creará ninguna actividad.</p>
          </div>
          <button className="button primary" disabled={processingLifecycle} onClick={() => void approve()}>{processingLifecycle ? "Comprobando en Jira…" : "Comprobar en Jira"}</button>
        </section>
      ) : (
        <section className="approval-banner pending-state">
          <div>
            <span className="eyebrow">Preparación de la propuesta</span>
            <strong>{count("REVISAR")} {count("REVISAR") === 1 ? "actividad pendiente" : "actividades pendientes"}</strong>
            <p>Resuelve todas las revisiones antes de validar la propuesta con Jira.</p>
          </div>
          <div className="approval-actions">
            <button className="button secondary" disabled={dryRunLoading || excludingPending} onClick={() => void runReadOnlyPreflight()}>
              {dryRunLoading ? "Comprobando en Jira…" : "Comprobar con Jira"}
            </button>
            {count("INCLUIR") > 0 && (
              <button className="button secondary" disabled={dryRunLoading || excludingPending} onClick={() => void excludePendingItems()}>
                {excludingPending ? "Excluyendo pendientes…" : "Excluir pendientes y continuar"}
              </button>
            )}
          </div>
        </section>
      )}
      {dryRun && (
        <details className="dry-run-history">
          <summary>
            <span>Resultado de la comprobación en Jira</span>
            <small>Versión {dryRun.proposal_version} · {dryRun.status === "BLOCKED" ? `${dryRun.summary.blocked} bloqueadas` : "sin bloqueos"}</small>
          </summary>
          <DryRunPanel dryRun={dryRun} currentProposalVersion={proposal.version} />
        </details>
      )}
      {approved && currentDryRun && currentDryRun.status !== "BLOCKED" && (
        <Objective4APanel
          token={token}
          proposal={proposal}
          dryRun={currentDryRun}
          onNewProposal={onNewProposal}
          onBusyChange={setExecutionBusy}
        />
      )}
      <details id="proposal-activities" className="workflow-section activities-section" open={!approved || correctionMode}>
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
      {dryRun && dryRun.status === "BLOCKED" && (() => {
        const options = dryRun.items.flatMap((item) => item.errors.find((issue) => issue.field === "tipo_seguimiento")?.options ?? []);
        const unique = Array.from(new Map(options.map((option) => [option.value, option])).values());
        return unique.length > 0 ? <section className="bulk-correction" aria-label="Aplicar tipo de seguimiento a varias actividades">
          <div><strong>Aplicar Tipo de seguimiento a todas</strong><small>Decisión local; Jira se volverá a consultar después.</small></div>
          <select aria-label="Tipo de seguimiento para aplicar a todas" value={bulkTrackingValue} onChange={(event) => setBulkTrackingValue(event.target.value)}>
            <option value="">Selecciona un valor vigente de Jira</option>
            {unique.map((option) => <option key={option.value} value={option.value}>{option.value}</option>)}
          </select>
          <button type="button" className="button secondary" disabled={!bulkTrackingValue || bulkTrackingSaving} onClick={() => void applyTrackingToAll()}>{bulkTrackingSaving ? "Aplicando…" : `Aplicar a ${proposal.items.filter((item) => item.generated.decision !== "EXCLUIR").length}`}</button>
        </section> : null;
      })()}
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
                      ? "Comprobación automática"
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
          isMinutesProposal={Boolean(proposal.minutes)}
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
  const [oauthNotice, setOauthNotice] = useState("");
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
      if (nextStatus.error && !nextStatus.diagnostic) setError(nextStatus.error);
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
    void loadStatus().then(() => {
      const callbackMessages: Record<string, string> = {
        denied: 'La autorización de Atlassian fue cancelada.',
        OAUTH_CALLBACK_INVALID: 'La respuesta de autorización está incompleta. Intenta conectar de nuevo.',
        OAUTH_STATE_INVALID: 'El estado de la autorización no existe o ya venció. Intenta conectar de nuevo.',
      };
      if (result && callbackMessages[result]) setError(callbackMessages[result]);
    });
  }, [token]);

  useEffect(() => {
    if (status?.diagnostic?.state !== 'OAUTH_IN_PROGRESS') return;
    const timer = window.setTimeout(() => void loadStatus(), 3000);
    return () => window.clearTimeout(timer);
  }, [status, token]);

  async function checkConnection() {
    setLoading(true);
    setError('');
    try {
      const next = await diagnoseAtlassian(token);
      setStatus(next);
      onStatusChange?.(next);
    } catch {
      setStatus(null);
      setError('No fue posible comprobar el backend local. Revisa que esté activo y vuelve a intentarlo.');
    } finally { setLoading(false); }
  }

  async function connect() {
    setLoading(true);
    setError("");
    setOauthNotice("");
    try {
      await connectAtlassianExternal(token);
      setOauthNotice("Se abrió Atlassian en el navegador predeterminado. Completa el consentimiento allí; esta pantalla detectará el regreso automáticamente.");
      // OAuth is handled by the system browser. Keep this app open so the
      // diagnostic poller can observe the loopback callback.
      await loadStatus();
    } catch (reason) {
      setOauthNotice("");
      setError(reason instanceof Error ? reason.message : "No fue posible iniciar OAuth.");
      setLoading(false);
      void loadStatus();
    }
  }

  async function disconnect() {
    if (!window.confirm("¿Desvincular tu cuenta Atlassian? Se eliminará la autorización cifrada guardada en este equipo.")) return;
    setLoading(true);
    setError("");
    try {
      await unlinkAtlassian();
      await loadStatus();
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

  async function changeGlobalWriteLock(action: 'unlock' | 'lock') {
    setLoading(true);
    setError("");
    try {
      const nextLock = action === 'unlock' ? await unlockJiraWrites(token) : await lockJiraWrites(token);
      const nextStatus = await getAtlassianStatus(token);
      setStatus({ ...nextStatus, global_write_lock: nextLock });
      onStatusChange?.({ ...nextStatus, global_write_lock: nextLock });
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "No fue posible cambiar el bloqueo global.");
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
  const account = snapshot?.atlassian_user;
  const connected = Boolean(status?.connected);
  const readAvailable = connected && Boolean(snapshot?.read_tools_available?.length);
  const writeAvailable = connected && Boolean(status?.jira_write_enabled) && status?.global_write_lock?.locked !== true;
  const connectionLabel = loading
    ? "Comprobando…"
    : connected
      ? "Jira conectado"
      : status?.diagnostic?.state === "OAUTH_EXPIRED" || status?.diagnostic?.state === "OAUTH_INVALID"
        ? "Requiere atención"
        : "Jira desconectado";
  return (
    <section className={`integration-card jira-settings-card ${connected ? "connected" : ""}`}>
      <div className="integration-heading">
        <div>
          <span className="eyebrow">Configuración de Jira</span>
          <h2>Cuenta Atlassian y Jira</h2>
          <p>{connected ? "Tu cuenta está lista para trabajar con Jira." : "Conecta tu cuenta para consultar tus espacios y preparar actividades."}</p>
        </div>
        <span className={`connection-pill ${connected ? "online" : "offline"}`}>
          {connected && <Icon name="check" />}{connectionLabel}
        </span>
      </div>

      {error && <div className="alert error" role="alert">{error}</div>}
      {oauthNotice && <div className="alert info" role="status">{oauthNotice}</div>}

      {status?.diagnostic?.state === 'JIRA_READY' && !status.connected && <button className="button primary" disabled={loading} onClick={() => void refresh()}>Restaurar conexión con la autorización guardada</button>}
      {!status && !loading && <button className="button secondary" onClick={() => void loadStatus()}>Reintentar</button>}
      {status?.connected && status.diagnostic?.state.startsWith('OAUTH_') && <button className="button primary" disabled={loading} onClick={() => void connect()}>Reconectar cuenta</button>}

      {!status?.connected ? (
        <>
          <div className="integration-onboarding">
            <div className="read-only-seal">
              <strong>Protección activa</strong>
              <span>Las pruebas de conexión sólo consultan información de Atlassian.</span>
            </div>
            <div className="integration-actions horizontal">
              {!status?.diagnostic && status?.phase === "ERROR" && (
                <button className="button secondary" onClick={() => void refresh()} disabled={loading}>
                  Reintentar diagnóstico
                </button>
              )}
              {status?.diagnostic?.state !== 'JIRA_READY' && <button className="button primary" onClick={() => void connect()} disabled={loading}>
                {status?.diagnostic?.state === 'OAUTH_IN_PROGRESS' || status?.diagnostic?.state === 'OAUTH_CANCELLED' || status?.diagnostic?.state === 'OAUTH_TIMEOUT' ? 'Intentar de nuevo' : status?.phase === "ERROR" || ['OAUTH_EXPIRED', 'OAUTH_INVALID'].includes(status?.diagnostic?.state || '') ? "Reconectar cuenta" : "Conectar mi cuenta Atlassian"}
              </button>}
            </div>
          </div>
          {status && (
            <details className="technical-details">
              <summary>Ver detalles técnicos</summary>
              <JiraDiagnostics status={status} busy={loading} onCheck={() => void checkConnection()} />
            </details>
          )}
        </>
      ) : (
        <>
          <section className="jira-account-card" aria-label="Cuenta conectada">
            <div className="jira-account-identity">
              <span className="jira-account-avatar" aria-hidden="true">{userInitials(account?.display_name || account?.email || "AJ")}</span>
              <div><strong>{account?.display_name || account?.email || "Cuenta Atlassian"}</strong><span>{jiraSiteLabel(snapshot?.site_url)}</span></div>
            </div>
            <div className="jira-account-states">
              <div className={readAvailable ? "state-ok" : "state-warning"}><span><Icon name={readAvailable ? "check" : "arrow-right"} /></span><div><strong>Lectura disponible</strong><small>{readAvailable ? "Puedes consultar información de Jira." : "La lectura necesita reconexión."}</small></div></div>
              <div className={writeAvailable ? "state-ok" : "state-warning"}><span><Icon name={writeAvailable ? "check" : "arrow-right"} /></span><div><strong>{writeAvailable ? "Escritura activa" : "Escritura no disponible"}</strong><small>{writeAvailable ? "Puedes preparar y crear actividades según la política actual." : "La política actual mantiene las escrituras bloqueadas."}</small></div></div>
              <div className={connected ? "state-ok" : "state-warning"}><span><Icon name={connected ? "check" : "arrow-right"} /></span><div><strong>Confirmación final requerida</strong><small>Nada se envía a Jira sin tu confirmación.</small></div></div>
            </div>
           </section>

           <section className="jira-spaces-section" aria-labelledby="jira-spaces-title">
            <div className="jira-section-heading"><div className="jira-section-icon"><Icon name="dashboard" /></div><div><h3 id="jira-spaces-title">Espacios disponibles</h3><p>Proyectos y espacios en los que puedes trabajar.</p></div></div>
            <div className="jira-spaces-grid">
            {snapshot?.spaces.map((space) => (
              <article className={`jira-space-card ${space.found ? "space-ok" : "space-missing"}`} key={space.key}><span>{space.key}</span><div><strong>{space.key}</strong><small>{space.found ? "Espacio de trabajo" : "No visible"}</small></div></article>
            ))}
            </div>
          </section>

          <div className="jira-settings-actions">
            <div><button className="button primary" onClick={() => void checkConnection()} disabled={loading}><Icon name="check" />{loading ? "Comprobando…" : "Probar conexión"}</button><small>Verifica que todo esté funcionando correctamente.</small></div>
            <div><button className="button danger-outline" onClick={() => void disconnect()} disabled={loading}><Icon name="lock" />Desvincular Atlassian</button><small>Desconecta tu cuenta de Jira de forma segura.</small></div>
          </div>

          <details className="technical-details">
            <summary>Ver detalles técnicos</summary>
            {status && <JiraDiagnostics status={status} busy={loading} onCheck={() => void checkConnection()} />}
            {objective4AReadiness && (
              <section className="objective4a-readiness" aria-label="Preparación del envío controlado">
                <div><span className="eyebrow">Comprobación técnica</span><strong>{objective4AReadiness.controlled_write_ready ? "Prueba segura y envío controlado habilitados" : "Prueba segura habilitada; escritura real bloqueada"}</strong><p>Rovo sólo fue inspeccionado. El diagnóstico realizó {objective4AReadiness.mcp_tools.tools_invoked} invocaciones y la política reporta <code>jira_write_enabled={String(objective4AReadiness.jira_write_enabled)}</code>.</p></div>
                <ul><li className={objective4AReadiness.mcp_tools.create.exposed ? "ok" : "pending"}>createJiraIssue {objective4AReadiness.mcp_tools.create.exposed ? "anunciada" : "pendiente"}</li><li className={objective4AReadiness.mcp_tools.readback.exposed ? "ok" : "pending"}>getJiraIssue {objective4AReadiness.mcp_tools.readback.exposed ? "anunciada" : "pendiente"}</li><li className={objective4AReadiness.real_canary_checks.task_metadata_available ? "ok" : "pending"}>Contrato AT / Task {objective4AReadiness.real_canary_checks.task_metadata_available ? "visible" : "pendiente"}</li></ul>
              </section>
            )}
            <div className="integration-summary"><dl><div><dt>Sitio verificado</dt><dd>{snapshot?.site_url}</dd></div><div><dt>cloudId</dt><dd><code>{snapshot?.cloud_id}</code></dd></div><div><dt>Cuenta Atlassian</dt><dd>{account?.display_name || account?.account_id}</dd></div><div><dt>Autorización OAuth</dt><dd>{status.oauth_storage === "OS_ENCRYPTED" ? "Cifrada por Windows" : "Sólo memoria"}</dd></div></dl></div>
            <form className="assignee-lookup" onSubmit={lookup}><div><span className="eyebrow">Comprobación de cuentas Jira</span><p>Herramienta técnica para soporte; la resolución normal ocurre durante la propuesta.</p></div><select value={lookupSpace} onChange={(event) => setLookupSpace(event.target.value as Space)} aria-label="Space para buscar responsable"><option value="AT">AT</option><option value="ASIT">ASIT</option><option value="MTTI">MTTI</option></select><input value={lookupQuery} onChange={(event) => { setLookupQuery(event.target.value); setLookupPerformed(false); }} placeholder="Nombre o correo" aria-label="Nombre o correo del responsable" minLength={2} required /><button className="button secondary" disabled={loading || lookupQuery.trim().length < 2}>Buscar</button></form>
            {assignees.length > 0 && <div className="assignee-results">{assignees.map((assignee) => <div key={assignee.account_id || assignee.display_name}><strong>{assignee.display_name}</strong><span>{assignee.email || assignee.account_id}</span></div>)}</div>}
            {lookupPerformed && assignees.length === 0 && <div className="assignee-empty" role="status"><strong>No encontramos una cuenta Jira</strong><span>No hubo coincidencias activas para “{lastLookupQuery}” en {lookupSpace}.</span></div>}
            <p className="read-only-footnote">{snapshot?.write_tools_exposed_by_server || 0} herramientas no permitidas pueden estar expuestas por Rovo; esta aplicación no las invoca.</p>
          </details>
        </>
      )}
    </section>
  );
}

type HistoryFilter = "ACTIVE" | "REVIEW" | "READY" | "ARCHIVED" | "TRASH";

export function ProposalHistory({
  proposals,
  currentId,
  loadingId,
  collapsed,
  onOpen,
  onArchive,
  onTrash = () => undefined,
  onRestore,
  onRename,
  onPurge,
  onNewProposal,
  onOpenSettings,
  onOpenDashboard,
  onFilterChange,
  settingsActive,
  dashboardActive,
  jiraConnected,
  jiraWriteEnabled,
  onToggleSidebar = () => undefined,
}: {
  proposals: ProposalSummary[];
  currentId: string | null;
  loadingId: string;
  collapsed: boolean;
  onOpen: (proposalId: string) => void;
  onArchive: (proposal: ProposalSummary) => void;
  onTrash?: (proposal: ProposalSummary) => void;
  onRestore: (proposal: ProposalSummary) => void;
  onRename: (proposal: ProposalSummary, displayName: string) => Promise<void>;
  onPurge: (proposal: ProposalSummary) => void;
  onNewProposal: () => void;
  onOpenSettings: () => void;
  onFilterChange?: (filter: HistoryFilter) => void;
  settingsActive: boolean;
  dashboardActive?: boolean;
  onOpenDashboard?: () => void;
  jiraConnected: boolean;
  jiraWriteEnabled: boolean;
  onToggleSidebar?: () => void;
}) {
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<HistoryFilter>("ACTIVE");
  const [editingProposalId, setEditingProposalId] = useState<string | null>(null);
  const [editingName, setEditingName] = useState("");
  const [savingName, setSavingName] = useState(false);

  const visible = useMemo(() => {
    const normalized = query.trim().toLocaleLowerCase();
    return proposals.filter((proposal) => {
      const archived = Boolean(proposal.archived);
      const trashed = Boolean(proposal.deleted);
      const matchesFilter =
        filter === "TRASH"
          ? trashed
          : filter === "ARCHIVED"
          ? archived
          : !archived && !trashed &&
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
      <div className="sidebar-brand">
        <Logo />
        <button
          type="button"
          className="sidebar-toggle"
          onClick={onToggleSidebar}
          aria-label="Alternar barra lateral"
          title="Alternar barra lateral (Ctrl+B)"
        >
          <Icon name={collapsed ? "chevron-right" : "chevron-left"} />
        </button>
      </div>
      <span className="sidebar-section-label">Centro de trabajo</span>
      <nav className="sidebar-navigation" aria-label="Acciones principales">
        <button type="button" data-tour-id="new-proposal" onClick={onNewProposal} title="Generar nueva propuesta">
          <span className="sidebar-nav-icon"><Icon name="plus" /></span>
          <span className="sidebar-nav-copy"><strong>Crear actividades</strong><small>Minuta o archivo</small></span>
        </button>
        <button type="button" className={settingsActive ? "active" : ""} onClick={onOpenSettings} title="Configurar conexión Jira">
          <span className="sidebar-nav-icon"><Icon name="sliders" /></span>
          <span className="sidebar-nav-copy"><strong>Configuración Jira</strong><small>{jiraConnected ? jiraWriteEnabled ? "Conectada · envío controlado" : "Conectada · sólo lectura" : "Desconectada"}</small></span>
          <span className={`sidebar-connection-dot ${jiraConnected ? "online" : "offline"}`}></span>
        </button>
        <button type="button" className={dashboardActive ? "active" : ""} onClick={onOpenDashboard} title="Abrir Dashboard Jira" aria-current={dashboardActive ? "page" : undefined}>
          <span className="sidebar-nav-icon"><Icon name="dashboard" /></span>
          <span className="sidebar-nav-copy"><strong>Dashboard</strong><small>Indicadores Jira · sólo lectura</small></span>
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
          onChange={(event) => {
            const nextFilter = event.target.value as HistoryFilter;
            setFilter(nextFilter);
            onFilterChange?.(nextFilter);
          }}
          aria-label="Filtrar propuestas"
        >
          <option value="ACTIVE">Activas</option>
          <option value="REVIEW">Con pendientes</option>
          <option value="READY">Sin pendientes</option>
          <option value="ARCHIVED">Archivadas</option>
          <option value="TRASH">Papelera</option>
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
              className={`history-item ${currentId === proposal.proposal_id ? "active" : ""} ${proposal.deleted ? "trashed" : ""}`}
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
                  {proposal.deleted && (
                    <small className="history-trash-note">
                      Papelera · recuperable durante 30 días
                    </small>
                  )}
                </span>
                <span className="history-count">
                  {loadingId === proposal.proposal_id ? "…" : proposal.counts.REVISAR}
                </span>
              </button>
              <div className="history-actions">
                {editingProposalId === proposal.proposal_id ? (
                  <form
                    className="history-rename-form"
                    onSubmit={(event) => {
                      event.preventDefault();
                      const nextName = editingName.trim();
                      if (!nextName || savingName) return;
                      setSavingName(true);
                      void onRename(proposal, nextName)
                        .then(() => setEditingProposalId(null))
                        .catch(() => undefined)
                        .finally(() => setSavingName(false));
                    }}
                  >
                    <input
                      aria-label="Nuevo nombre de la propuesta"
                      value={editingName}
                      onChange={(event) => setEditingName(event.target.value)}
                      maxLength={120}
                      required
                      autoFocus
                    />
                    <button className="history-action" disabled={savingName}>Guardar</button>
                    <button
                      type="button"
                      className="history-action"
                      disabled={savingName}
                      onClick={() => setEditingProposalId(null)}
                    >
                      Cancelar
                    </button>
                  </form>
                ) : (
                  <>
                    <button
                      type="button"
                      className="history-action history-icon-action"
                      onClick={() => {
                        setEditingName(proposal.display_name);
                        setEditingProposalId(proposal.proposal_id);
                      }}
                      aria-label={`Editar nombre ${proposal.display_name}`}
                      title="Editar nombre"
                    >
                      <Icon name="pencil" />
                    </button>
                    {proposal.deleted ? (
                      <>
                        <button
                          type="button"
                          className="history-action"
                          onClick={() => onRestore(proposal)}
                          aria-label={`Restaurar ${proposal.display_name}`}
                          title="Restaurar desde la papelera"
                        >
                          Restaurar
                        </button>
                        <button
                          type="button"
                          className="history-action danger"
                          onClick={() => onPurge(proposal)}
                          aria-label={`Borrar definitivamente ${proposal.display_name}`}
                          title="Borrar definitivamente"
                        >
                          Borrar definitivamente
                        </button>
                      </>
                    ) : (
                      <>
                        <button
                          type="button"
                          className="history-action"
                          onClick={() => proposal.archived ? onRestore(proposal) : onArchive(proposal)}
                          aria-label={proposal.archived ? `Restaurar ${proposal.display_name}` : `Archivar ${proposal.display_name}`}
                          title={proposal.archived ? "Restaurar" : "Archivar"}
                        >
                          {proposal.archived ? "Restaurar" : "Archivar"}
                        </button>
                        <button
                          type="button"
                          className="history-action danger"
                          onClick={() => onTrash(proposal)}
                          aria-label={`Eliminar ${proposal.display_name}`}
                          title="Enviar a la papelera durante 30 días"
                        >
                          Eliminar
                        </button>
                      </>
                    )}
                  </>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
      <div className="sidebar-safety" title="Jira sólo escribe después de tu confirmación">
        <Icon name="shield" />
        <span><strong>Modo controlado</strong><small>Sin escrituras automáticas</small></span>
      </div>
    </aside>
  );
}

function MinutesReviewBoundary({ proposal, token, onUpdated, children }: {
  proposal: Proposal; token: string; onUpdated: (proposal: Proposal) => void; children: ReactNode;
}) {
  return proposal.minutes
    ? <MinutesReview key={proposal.proposal_id} proposal={proposal} token={token} onUpdated={onUpdated}>{children}</MinutesReview>
    : <>{children}</>;
}

export function Workspace({
  session,
  onLogout,
  theme = "light",
  onToggleTheme = () => undefined,
}: {
  session: Session;
  onLogout: () => void;
  theme?: Theme;
  onToggleTheme?: () => void;
}) {
  const [proposals, setProposals] = useState<ProposalSummary[]>([]);
  const [includeTrash, setIncludeTrash] = useState(false);
  const [current, setCurrent] = useState<Proposal | null>(null);
  const [loadingId, setLoadingId] = useState("");
  const [lifecycleError, setLifecycleError] = useState("");
  const [settingsOpen, setSettingsOpen] = useState(
    () => new URLSearchParams(window.location.search).has("atlassian"),
  );
  const [dashboardOpen, setDashboardOpen] = useState(false);
  const [atlassianStatus, setAtlassianStatus] = useState<AtlassianStatus | null>(null);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(
    () => false,
  );

  async function refreshList(requestTrash = includeTrash) {
    try {
      setProposals(await listProposals(session.access_token, requestTrash));
    } catch (reason) {
      if (!(reason instanceof ApiError && reason.status === 401)) {
        setLifecycleError(
          reason instanceof Error ? reason.message : "No fue posible actualizar las propuestas.",
        );
      }
    }
  }

  useEffect(() => {
    void refreshList(includeTrash);
    void getAtlassianStatus(session.access_token)
      .then(setAtlassianStatus)
      .catch(() => setAtlassianStatus(null));
  }, [includeTrash]);

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
    setDashboardOpen(false);
    void refreshList();
  }

  function newProposal() {
    emitOnboardingEvent("view:new-proposal");
    setCurrent(null);
    setSettingsOpen(false);
    setDashboardOpen(false);
    setLifecycleError("");
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  async function openProposal(proposalId: string) {
    setLoadingId(proposalId);
    try {
      setCurrent(await getProposal(session.access_token, proposalId));
      setSettingsOpen(false);
      setDashboardOpen(false);
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

  async function trash(summary: ProposalSummary) {
    if (!window.confirm(`¿Enviar "${summary.display_name}" a la papelera? Podrás recuperarla durante 30 días.`)) {
      return;
    }
    setLifecycleError("");
    try {
      await trashProposal(session.access_token, summary.proposal_id);
      if (current?.proposal_id === summary.proposal_id) setCurrent(null);
      await refreshList();
    } catch (reason) {
      setLifecycleError(reason instanceof Error ? reason.message : "No fue posible enviar a la papelera.");
    }
  }

  async function purge(summary: ProposalSummary) {
    if (!window.confirm(`¿Borrar definitivamente "${summary.display_name}"? Esta acción no se puede deshacer.`)) {
      return;
    }
    setLifecycleError("");
    try {
      await permanentlyDeleteProposal(session.access_token, summary.proposal_id);
      if (current?.proposal_id === summary.proposal_id) setCurrent(null);
      await refreshList();
    } catch (reason) {
      setLifecycleError(reason instanceof Error ? reason.message : "No fue posible borrar definitivamente.");
    }
  }

  async function saveProposalName(proposalId: string, name: string) {
    if (!name.trim()) return;
    setLifecycleError("");
    try {
      await renameProposal(session.access_token, proposalId, name.trim());
      await refreshList();
    } catch (reason) {
      const message = reason instanceof Error ? reason.message : "No fue posible renombrar.";
      setLifecycleError(message);
      throw reason;
    }
  }

  async function rename(name: string) {
    if (!current) return;
    await saveProposalName(current.proposal_id, name);
  }

  async function renameFromHistory(summary: ProposalSummary, name: string) {
    await saveProposalName(summary.proposal_id, name);
  }

  const currentSummary = proposals.find(
    (proposal) => proposal.proposal_id === current?.proposal_id,
  );
  const atlassianIdentity = atlassianStatus?.snapshot?.atlassian_user;
  const accountDisplayName =
    atlassianIdentity?.display_name?.trim() ||
    atlassianIdentity?.email?.trim() ||
    session.user.display_name?.trim() ||
    session.user.email?.trim() ||
    session.user.username;
  const workspaceTitle = settingsOpen
    ? "Conexión con Jira"
    : dashboardOpen
      ? "Dashboard de equipos"
    : current
      ? currentSummary?.display_name ?? current.source_file.name.replace(/\.xlsx$/i, "")
      : "Crear actividades";
  const workspaceSection = settingsOpen
    ? "Administración"
    : dashboardOpen
      ? "Jira · Solo lectura"
    : current
      ? "Propuesta en curso"
      : "Preparar actividades";

  return (
    <div className={`app-shell ${sidebarCollapsed ? "sidebar-collapsed" : ""}`}>
      <header className="topbar">
        <div className="mobile-brand" aria-label="Agente Jira">AJ</div>
        <div className="topbar-context">
          <span>{workspaceSection}</span>
          <strong>{workspaceTitle}</strong>
        </div>
        <div className={`environment-badge ${atlassianStatus?.connected ? atlassianStatus.jira_write_enabled ? "controlled" : "" : "offline"}`}>
          <span></span> Local · {atlassianStatus?.connected ? atlassianStatus.jira_write_enabled ? "Jira conectada" : "Jira conectada en solo lectura" : "Jira desconectada"} · {atlassianStatus?.global_write_lock?.state === "UNLOCKED_TEMPORARY" ? "⚠ Escrituras habilitadas temporalmente" : "🔒 Escrituras bloqueadas"}
        </div>
        <div className="mobile-actions" aria-label="Acciones principales">
          <button type="button" onClick={newProposal} aria-label="Generar nueva propuesta" title="Nueva propuesta"><Icon name="plus" /></button>
          <button type="button" onClick={() => { setSettingsOpen(false); setCurrent(null); setDashboardOpen(true); }} aria-label="Abrir Dashboard Jira" title="Dashboard Jira"><Icon name="dashboard" /></button>
          <button type="button" onClick={() => { setSettingsOpen(true); setCurrent(null); }} aria-label="Configurar Jira" title="Configuración Jira"><Icon name="sliders" /></button>
        </div>
        <div className="user-menu">
          <ThemeToggle theme={theme} onToggle={onToggleTheme} />
          <button type="button" className="button ghost onboarding-repeat" onClick={() => emitOnboardingEvent("repeat")} aria-label="Repetir recorrido guiado" title="Repetir recorrido guiado">Ayuda</button>
          <span className="user-avatar" aria-hidden="true">{userInitials(accountDisplayName)}</span>
          <span className="user-details">
            <strong>{accountDisplayName}</strong>
            <small>{session.user.email || session.user.username}</small>
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
          onTrash={(proposal) => void trash(proposal)}
          onRestore={(proposal) => void restore(proposal)}
          onRename={renameFromHistory}
          onPurge={(proposal) => void purge(proposal)}
          onNewProposal={newProposal}
          onOpenSettings={() => { setSettingsOpen(true); setCurrent(null); }}
          onOpenDashboard={() => { setSettingsOpen(false); setCurrent(null); setDashboardOpen(true); }}
          onFilterChange={(filter) => setIncludeTrash(filter === "TRASH")}
          settingsActive={settingsOpen}
          dashboardActive={dashboardOpen}
          jiraConnected={Boolean(atlassianStatus?.connected)}
          jiraWriteEnabled={Boolean(atlassianStatus?.jira_write_enabled)}
          onToggleSidebar={() => setSidebarCollapsed((value) => !value)}
        />
        <div className="content-area">
          {lifecycleError && <div className="alert error">{lifecycleError}</div>}
          {settingsOpen ? (
            <AtlassianConnectionPanel token={session.access_token} onStatusChange={setAtlassianStatus} />
          ) : dashboardOpen ? (
            <Dashboard token={session.access_token} />
          ) : current ? (
            <MinutesReviewBoundary proposal={current} token={session.access_token} onUpdated={updated}>
            <ProposalReview
              token={session.access_token}
              proposal={current}
              displayName={currentSummary?.display_name ?? current.source_file.name.replace(/\.xlsx$/i, "")}
              onRename={rename}
              onUpdated={updated}
              onNewProposal={newProposal}
            />
            </MinutesReviewBoundary>
          ) : (
            <NewProposal token={session.access_token} displayName={accountDisplayName} telegramUrl={session.radar_telegram_url} onCreated={created} excel={<UploadPanel token={session.access_token} onCreated={created} />} />
          )}
        </div>
      </main>
      <Onboarding token={session.access_token} displayName={accountDisplayName} />
      {VOICE_UI_ENABLED && (
        <VoiceAssistant
          token={session.access_token}
          proposalId={current?.proposal_id ?? null}
        />
      )}
    </div>
  );
}

export default function App() {
  const [session, setSession] = useState<Session | null>(null);
  const [authLoading, setAuthLoading] = useState(true);
  const [theme, setTheme] = useState<Theme>(() => readInitialTheme());

  useEffect(() => applyTheme(theme), [theme]);

  useEffect(() => {
    const expireSession = () => {
      setSession(null);
    };
    window.addEventListener(SESSION_EXPIRED_EVENT, expireSession);
    return () => window.removeEventListener(SESSION_EXPIRED_EVENT, expireSession);
  }, []);

  useEffect(() => {
    getCurrentSession().then(setSession).catch(() => setSession(null)).finally(() => setAuthLoading(false));
  }, []);

  async function logout() {
    await logoutSession().catch(() => undefined);
    setSession(null);
  }

  if (authLoading) return <main className="login-layout"><p className="muted">Verificando sesión…</p></main>;

  return session ? (
    <Workspace
      session={session}
      onLogout={logout}
      theme={theme}
      onToggleTheme={() => setTheme((value) => value === "light" ? "dark" : "light")}
    />
  ) : (
    <LoginScreen />
  );
}
