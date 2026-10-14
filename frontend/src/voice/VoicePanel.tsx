import type {
  VoiceCommandResponse,
  VoiceJiraPreview,
  VoicePendingConfirmation,
  VoiceTaskDraft,
  VoiceUiState,
} from "./types";

const PROCESSING_COPY: Partial<Record<VoiceUiState, { title: string; detail: string }>> = {
  transcribing: {
    title: "📝 Transcribiendo…",
    detail: "Whisper está convirtiendo tu audio localmente.",
  },
  thinking: {
    title: "🧠 Pensando…",
    detail: "Gemma está interpretando la intención y el contexto.",
  },
  executing: {
    title: "⚙️ Actualizando borrador…",
    detail: "Vic está aplicando una operación local controlada.",
  },
  preparing_jira: {
    title: "⚙️ Preparando Jira…",
    detail: "Vic está validando campos, usuario, política y payload protegido.",
  },
  creating_jira: {
    title: "↗ Creando en Jira…",
    detail: "La confirmación fue validada y la operación se enviará una sola vez.",
  },
  verifying_jira: {
    title: "⌕ Verificando en Jira…",
    detail: "Vic está comprobando la clave y los campos mediante readback.",
  },
  speaking: {
    title: "🔊 Vic está hablando…",
    detail: "El micrófono permanece cerrado durante la reproducción.",
  },
};

const PRIORITY_LABELS: Record<string, string> = {
  Highest: "Máxima",
  High: "Alta",
  Medium: "Media",
  Low: "Baja",
  Lowest: "Mínima",
};

function DraftCard({ draft }: { draft: VoiceTaskDraft }) {
  return (
    <article className="voice-draft-card" aria-label="Tarea preparada">
      <div className="voice-draft-title">
        <strong>Tarea preparada</strong>
        <span>{draft.id}</span>
      </div>
      <dl>
        <div><dt>Tipo</dt><dd>{draft.issue_type}</dd></div>
        <div><dt>Resumen</dt><dd>{draft.summary}</dd></div>
        <div><dt>Responsable</dt><dd>{draft.assignee?.display_name ?? "Sin asignar"}</dd></div>
        <div><dt>Prioridad</dt><dd>{draft.priority ? PRIORITY_LABELS[draft.priority] : "Sin definir"}</dd></div>
      </dl>
      {draft.description && <p className="voice-draft-description">{draft.description}</p>}
      <small>Todavía no enviada a Jira</small>
    </article>
  );
}

function JiraConfirmationCard({
  pending,
  preview,
  busy,
  onConfirm,
  onCancel,
}: {
  pending: VoicePendingConfirmation;
  preview: VoiceJiraPreview;
  busy: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  return (
    <article className="voice-jira-confirmation" aria-label="Confirmar creación en Jira">
      <strong>Confirmar creación en Jira</strong>
      <dl>
        <div><dt>Tipo</dt><dd>{preview.issue_type}</dd></div>
        <div><dt>Resumen</dt><dd>{preview.summary}</dd></div>
        <div><dt>Responsable</dt><dd>{preview.assignee ?? "Sin asignar"}</dd></div>
        <div><dt>Prioridad</dt><dd>{preview.priority ? PRIORITY_LABELS[preview.priority] ?? preview.priority : "Predeterminada de Jira"}</dd></div>
        <div><dt>Space</dt><dd>{preview.space}</dd></div>
      </dl>
      <ul>
        <li>✓ Campos válidos</li>
        <li>✓ Usuario validado</li>
        <li>✓ Jira disponible</li>
      </ul>
      <p>Aún no se ha creado nada.</p>
      <div className="voice-jira-confirmation-actions">
        <button type="button" disabled={busy} onClick={onCancel}>Cancelar</button>
        <button type="button" className="primary" disabled={busy} onClick={onConfirm}>
          {busy ? "Procesando…" : "Crear en Jira"}
        </button>
      </div>
      <small>Confirmación válida hasta {new Date(pending.expires_at).toLocaleTimeString()}</small>
    </article>
  );
}

export function VoicePanel({
  state,
  response,
  draft,
  error,
  audioError,
  onClose,
  onStopAudio,
  onConfirmJira,
  onCancelJira,
  jiraActionBusy,
}: {
  state: VoiceUiState;
  response: VoiceCommandResponse | null;
  draft: VoiceTaskDraft | null;
  error: string;
  audioError: string;
  onClose: () => void;
  onStopAudio: () => void;
  onConfirmJira: () => void;
  onCancelJira: () => void;
  jiraActionBusy: boolean;
}) {
  const processing = PROCESSING_COPY[state];
  const statusClass = response?.status === "blocked"
    ? "blocked"
    : response?.status === "awaiting_confirmation"
      ? "confirmation"
      : response?.status === "needs_clarification"
        ? "clarification"
        : state;
  const pending = response?.context?.pending_confirmation;
  const jiraPreview = response?.jira_operation?.preview ?? pending?.preview;
  const footer = response?.jira_operation?.state === "SUCCESS"
    ? `${response.jira_operation.issue_key} creada y verificada`
    : response?.jira_operation?.state === "UNKNOWN_RESULT"
      ? "Resultado pendiente de verificación"
    : response?.jira_operation?.state === "CANCELLED"
        ? "No se realizó la operación"
        : response?.jira_operation?.state === "EXECUTION_ERROR"
          ? "No se realizó la operación"
        : pending?.action === "create_jira_issue"
          ? "Esperando confirmación"
          : draft
            ? "Tarea preparada · sin enviar"
            : "Consulta y operación controlada";
  return (
    <section
      className={`voice-panel ${statusClass}`}
      aria-live="polite"
      aria-label="Respuesta del asistente de voz"
    >
      <div className="voice-panel-heading">
        <strong>{processing?.title ?? "Vic · asistente local"}</strong>
        {!processing && (
          <button type="button" onClick={onClose} aria-label="Cerrar respuesta de voz">×</button>
        )}
      </div>
      {processing ? (
        <>
          <p>{processing.detail}</p>
          {state === "speaking" && (
            <button type="button" className="voice-stop-audio" onClick={onStopAudio}>
              Detener audio
            </button>
          )}
        </>
      ) : response ? (
        <>
          {response.transcript && <p className="voice-transcript">“{response.transcript}”</p>}
          <p>{response.message}</p>
          <small className={response.risk === "LOCAL_WRITE" ? "local-write" : undefined}>
            {response.status === "blocked" ? "Operación bloqueada por Permission Gate" : footer}
          </small>
          {response.jira_operation?.state === "SUCCESS" && response.jira_operation.issue_url && (
            <a href={response.jira_operation.issue_url} target="_blank" rel="noreferrer">
              Ver {response.jira_operation.issue_key} en Jira
            </a>
          )}
        </>
      ) : error ? (
        <p>{error}</p>
      ) : (
        <p>Puedo consultar la aplicación y Jira, preparar tareas y, con tu confirmación, crearlas de forma controlada.</p>
      )}
      {audioError && <p className="voice-audio-warning">{audioError}</p>}
      {draft && draft.status === "draft" && <DraftCard draft={draft} />}
      {pending?.action === "create_jira_issue" && pending.payload_hash && jiraPreview && (
        <JiraConfirmationCard
          pending={pending}
          preview={jiraPreview}
          busy={jiraActionBusy}
          onConfirm={onConfirmJira}
          onCancel={onCancelJira}
        />
      )}
    </section>
  );
}
