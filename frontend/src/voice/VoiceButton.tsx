import type { VoiceUiState } from "./types";

const LABELS: Record<VoiceUiState, string> = {
  idle: "Hablar",
  listening: "Detener",
  transcribing: "Transcribiendo",
  thinking: "Pensando",
  executing: "Actualizando",
  preparing_jira: "Preparando Jira",
  awaiting_confirmation: "Responder",
  creating_jira: "Creando",
  verifying_jira: "Verificando",
  speaking: "Interrumpir y hablar",
  success: "Nueva consulta",
  error: "Reintentar",
  validation_error: "Corregir",
  execution_error: "Reintentar consulta",
  unknown_result: "Consultar después",
  cancelled: "Nueva consulta",
};

const ACCESSIBLE_LABELS: Record<VoiceUiState, string> = {
  idle: "Iniciar comando de voz",
  listening: "Detener grabación de voz",
  transcribing: "Transcribiendo comando de voz",
  thinking: "Interpretando comando de voz",
  executing: "Actualizando borrador local",
  preparing_jira: "Preparando creación controlada en Jira",
  awaiting_confirmation: "Responder a la confirmación pendiente",
  creating_jira: "Creando Task en Jira",
  verifying_jira: "Verificando Task en Jira",
  speaking: "Detener respuesta e iniciar grabación",
  success: "Iniciar otro comando de voz",
  error: "Reintentar comando de voz",
  validation_error: "Corregir borrador mediante voz",
  execution_error: "Iniciar otra consulta de voz",
  unknown_result: "Iniciar una consulta sin reenviar la operación",
  cancelled: "Iniciar otro comando de voz",
};

function VoiceGlyph({ state }: { state: VoiceUiState }) {
  const busy = ["transcribing", "thinking", "executing", "preparing_jira", "creating_jira", "verifying_jira"].includes(state);
  if (busy) return <span className="voice-spinner" />;
  if (state === "listening" || state === "speaking") {
    return <span className="voice-wave"><i></i><i></i><i></i></span>;
  }
  if (state === "success") {
    return <svg viewBox="0 0 24 24" fill="none"><path d="m6 12.5 4 4L18 8" /></svg>;
  }
  if (["error", "validation_error", "execution_error"].includes(state)) {
    return <svg viewBox="0 0 24 24" fill="none"><path d="M12 7v6" /><path d="M12 17h.01" /></svg>;
  }
  if (state === "awaiting_confirmation" || state === "unknown_result") {
    return <svg viewBox="0 0 24 24" fill="none"><path d="M9.5 9a2.6 2.6 0 1 1 4 2.2c-1 .6-1.5 1.2-1.5 2.3" /><path d="M12 17h.01" /></svg>;
  }
  if (state === "cancelled") {
    return <svg viewBox="0 0 24 24" fill="none"><path d="m8 8 8 8M16 8l-8 8" /></svg>;
  }
  return <svg viewBox="0 0 24 24" fill="none"><rect x="9" y="3" width="6" height="11" rx="3" /><path d="M6.5 11.5a5.5 5.5 0 0 0 11 0M12 17v4M9 21h6" /></svg>;
}

export function VoiceButton({
  state,
  onClick,
}: {
  state: VoiceUiState;
  onClick: () => void;
}) {
  const busy = [
    "transcribing",
    "thinking",
    "executing",
    "preparing_jira",
    "creating_jira",
    "verifying_jira",
  ].includes(state);
  return (
    <button
      type="button"
      className={`voice-button ${state}`}
      onClick={onClick}
      disabled={busy}
      aria-label={ACCESSIBLE_LABELS[state]}
      aria-pressed={state === "listening"}
    >
      <span className="voice-button-icon" aria-hidden="true"><VoiceGlyph state={state} /></span>
      <span>{LABELS[state]}</span>
    </button>
  );
}
