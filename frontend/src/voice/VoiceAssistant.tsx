import { useEffect, useRef, useState } from "react";
import { VoiceButton } from "./VoiceButton";
import { VoicePanel } from "./VoicePanel";
import {
  cancelVoiceJiraCreate,
  activateVoice,
  confirmVoiceJiraCreate,
  getVoiceContext,
  getVoiceStatus,
  sendVoiceCommand,
} from "./voiceApi";
import type {
  VoiceCommandResponse,
  VoiceComponentStatus,
  VoiceStatusView,
  VoiceTaskDraft,
  VoiceUiState,
} from "./types";
import { useVoiceRecorder } from "./useVoiceRecorder";

const MAX_DURATION_SECONDS = 30;
const SPOKEN_RESPONSES_KEY = "agente-jira-spoken-responses";

function readableError(reason: unknown): string {
  if (reason instanceof DOMException && reason.name === "NotAllowedError") {
    return "El navegador no tiene permiso para usar el micrófono.";
  }
  return reason instanceof Error ? reason.message : "No fue posible usar el asistente de voz.";
}

function wait(milliseconds: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, milliseconds));
}

function initialSpokenPreference(): boolean {
  return localStorage.getItem(SPOKEN_RESPONSES_KEY) !== "false";
}

function componentStateLabel(component: VoiceComponentStatus): string {
  if (component.state === "DISABLED") return "Deshabilitado";
  if (component.state === "NOT_LOADED") {
    return component.available === false ? component.detail : "Se cargará al primer uso";
  }
  if (component.state === "LOADING") return "Comprobando…";
  if (component.state === "READY") return "Disponible";
  return component.detail;
}

function componentIcon(component: VoiceComponentStatus): string {
  if (component.state === "ERROR") return "❌";
  if (component.state === "READY") return "✅";
  if (component.state === "LOADING") return "⏳";
  return "○";
}

function overallVoiceLabel(status: VoiceStatusView): string {
  if (status.state === "DISABLED") return "Deshabilitada por configuración";
  if (status.state === "NOT_STARTED") return "No iniciada";
  if (status.state === "LOADING") return "Comprobando componentes…";
  if (status.state === "PARTIAL") return "Voz parcialmente disponible";
  if (status.state === "ERROR") return "Voz no disponible";
  return "Voz preparada";
}

function isVoiceStatus(value: VoiceStatusView | null | undefined): value is VoiceStatusView {
  return Boolean(
    value
      && typeof value.state === "string"
      && typeof value.activated === "boolean"
      && value.stt
      && value.llm
      && value.tts,
  );
}

function resultState(result: VoiceCommandResponse): VoiceUiState {
  const operation = result.jira_operation;
  if (operation?.state === "AWAITING_CONFIRMATION" || result.status === "awaiting_confirmation") {
    return "awaiting_confirmation";
  }
  if (operation?.state === "UNKNOWN_RESULT" || result.status === "unknown_result") {
    return "unknown_result";
  }
  if (operation?.state === "CANCELLED" || result.status === "cancelled") return "cancelled";
  if (operation?.state === "EXECUTION_ERROR" || result.status === "execution_error") {
    return "execution_error";
  }
  if (operation?.state === "VALIDATION_ERROR" || result.status === "validation_error") {
    return "validation_error";
  }
  return "success";
}

export function VoiceAssistant({
  token,
  proposalId,
}: {
  token: string;
  proposalId: string | null;
}) {
  const [state, setState] = useState<VoiceUiState>("idle");
  const [response, setResponse] = useState<VoiceCommandResponse | null>(null);
  const [draft, setDraft] = useState<VoiceTaskDraft | null>(null);
  const [error, setError] = useState("");
  const [audioError, setAudioError] = useState("");
  const [panelOpen, setPanelOpen] = useState(false);
  const [spokenResponses, setSpokenResponses] = useState(initialSpokenPreference);
  const [jiraActionBusy, setJiraActionBusy] = useState(false);
  const [voiceStatus, setVoiceStatus] = useState<VoiceStatusView | null>(null);
  const [voiceActivationBusy, setVoiceActivationBusy] = useState(false);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const jiraActionGuard = useRef(false);

  useEffect(() => {
    let active = true;
    void getVoiceStatus(token)
      .then((status) => {
        if (active && isVoiceStatus(status)) setVoiceStatus(status);
      })
      .catch(() => undefined);
    void getVoiceContext(token)
      .then((context) => {
        if (!active) return;
        const currentDraft = context.draft?.status === "draft" ? context.draft : null;
        setDraft(currentDraft);
        const pending = context.pending_confirmation;
        if (pending?.action === "create_jira_issue" && pending.payload_hash && pending.preview) {
          setResponse({
            transcript: "",
            intent: "request_jira_create",
            status: "awaiting_confirmation",
            message: "La tarea sigue esperando tu confirmación. Aún no se ha creado nada.",
            requires_confirmation: true,
            risk: "JIRA_WRITE",
            draft: currentDraft,
            context,
            jira_operation: {
              execution_id: pending.execution_id ?? "pending",
              state: "AWAITING_CONFIRMATION",
              payload_hash: pending.payload_hash,
              preview: pending.preview,
              issue_key: null,
              issue_url: null,
              readback_checks: {},
              create_elapsed_ms: null,
              readback_elapsed_ms: null,
              reused: true,
            },
            audio_available: false,
            audio_base64: null,
            audio_mime_type: null,
          });
          setState("awaiting_confirmation");
          setPanelOpen(true);
        } else if (currentDraft) setPanelOpen(true);
      })
      .catch(() => undefined);
    return () => {
      active = false;
    };
  }, [token]);

  function releaseAudio() {
    const audio = audioRef.current;
    if (!audio) return;
    audio.onended = null;
    audio.onerror = null;
    audio.pause();
    try {
      audio.currentTime = 0;
      audio.src = "";
    } catch {
      // El elemento ya puede haber liberado su recurso.
    }
    audioRef.current = null;
  }

  function stopAudio(nextState: VoiceUiState = "success") {
    releaseAudio();
    setState(nextState);
  }

  function playResponse(result: VoiceCommandResponse, nextState = resultState(result)) {
    if (!result.audio_available || !result.audio_base64 || !result.audio_mime_type) {
      setState(nextState);
      return;
    }
    releaseAudio();
    const audio = new Audio(
      `data:${result.audio_mime_type};base64,${result.audio_base64}`,
    );
    audioRef.current = audio;
    audio.onended = () => {
      releaseAudio();
      setState(nextState);
    };
    audio.onerror = () => {
      releaseAudio();
      setAudioError("No se pudo reproducir la voz de Vic; la respuesta escrita sigue disponible.");
      setState(nextState);
    };
    setState("speaking");
    void Promise.resolve(audio.play()).catch(() => audio.onerror?.(new Event("error")));
  }

  function applyResult(result: VoiceCommandResponse) {
    setResponse(result);
    const activeDraft = result.context?.active_draft_id && result.draft?.status === "draft"
      ? result.draft
      : null;
    setDraft(activeDraft);
    setAudioError(result.audio_error ?? "");
    void getVoiceStatus(token).then((status) => {
      if (isVoiceStatus(status)) setVoiceStatus(status);
    }).catch(() => undefined);
    const nextState = resultState(result);
    if (spokenResponses) playResponse(result, nextState);
    else setState(nextState);
  }

  async function processAudio(audio: Blob) {
    setState("transcribing");
    setPanelOpen(true);
    setAudioError("");
    try {
      const pending = sendVoiceCommand(
        token,
        audio,
        proposalId,
        spokenResponses,
      ).then(
        (result) => ({ result, reason: null as unknown }),
        (reason: unknown) => ({ result: null, reason }),
      );
      await wait(120);
      setState("thinking");
      const outcome = await pending;
      if (outcome.reason) throw outcome.reason;
      const result = outcome.result;
      if (!result) throw new Error("El asistente no devolvió una respuesta válida.");
      if (result.intent === "request_jira_create") {
        setState("preparing_jira");
        await wait(120);
      }
      if (result.risk === "LOCAL_WRITE") {
        setState("executing");
        await wait(120);
      }
      applyResult(result);
    } catch (reason) {
      setResponse(null);
      setError(readableError(reason));
      setState("error");
    }
  }

  const recorder = useVoiceRecorder({
    maxDurationSeconds: MAX_DURATION_SECONDS,
    onStopped: (audio) => void processAudio(audio),
    onError: (message) => {
      setResponse(null);
      setError(message);
      setPanelOpen(true);
      setState("error");
    },
  });

  async function handleActivateVoice() {
    if (voiceActivationBusy) return;
    setVoiceActivationBusy(true);
    setError("");
    try {
      setVoiceStatus((current) => current
        ? { ...current, state: "LOADING", activated: true, message: "Comprobando componentes de voz..." }
        : current);
      const status = await activateVoice(token);
      if (isVoiceStatus(status)) setVoiceStatus(status);
    } catch (reason) {
      setError(readableError(reason));
      setPanelOpen(true);
    } finally {
      setVoiceActivationBusy(false);
    }
  }

  async function handleClick() {
    if (state === "listening") {
      setState("transcribing");
      if (!recorder.stop()) {
        setError("No había una grabación activa. Inténtalo de nuevo.");
        setState("error");
      }
      return;
    }
    if (["transcribing", "thinking", "executing", "preparing_jira", "creating_jira", "verifying_jira"].includes(state)) return;
    if (state === "speaking") {
      stopAudio("idle");
    }
    if (state !== "awaiting_confirmation") setResponse(null);
    setError("");
    setAudioError("");
    setPanelOpen(Boolean(draft));
    try {
      await recorder.start();
      setState("listening");
    } catch (reason) {
      setError(readableError(reason));
      setPanelOpen(true);
      setState("error");
    }
  }

  async function handleJiraAction(action: "confirm" | "cancel") {
    if (jiraActionGuard.current) return;
    const pending = response?.context?.pending_confirmation;
    if (!pending?.payload_hash) return;
    jiraActionGuard.current = true;
    setJiraActionBusy(true);
    releaseAudio();
    setAudioError("");
    setError("");
    try {
      if (action === "confirm") setState("creating_jira");
      const request = action === "confirm"
        ? confirmVoiceJiraCreate(
            token,
            pending.confirmation_id,
            pending.payload_hash,
            spokenResponses,
          )
        : cancelVoiceJiraCreate(
            token,
            pending.confirmation_id,
            pending.payload_hash,
            spokenResponses,
          );
      if (action === "confirm") {
        await wait(120);
        setState("verifying_jira");
      }
      const result = await request;
      applyResult(result);
    } catch (reason) {
      setError(readableError(reason));
      setState("execution_error");
    } finally {
      jiraActionGuard.current = false;
      setJiraActionBusy(false);
    }
  }

  function close() {
    releaseAudio();
    setResponse(null);
    setError("");
    setAudioError("");
    setPanelOpen(false);
    setState("idle");
  }

  function toggleSpokenResponses(value: boolean) {
    localStorage.setItem(SPOKEN_RESPONSES_KEY, String(value));
    setSpokenResponses(value);
    if (!value && state === "speaking") stopAudio("success");
  }

  useEffect(
    () => () => releaseAudio(),
    [],
  );

  const voiceDisabled = voiceStatus?.state === "DISABLED";
  const voiceActivated = voiceStatus === null || voiceStatus.activated;
  const showVoiceControls = !voiceDisabled && voiceActivated;
  const components = voiceStatus ? [voiceStatus.stt, voiceStatus.llm, voiceStatus.tts] : [];

  return (
    <div className="voice-assistant">
      {panelOpen && (
        <VoicePanel
          state={state}
          response={response}
          draft={draft}
          error={error}
          audioError={audioError}
          onClose={close}
          onStopAudio={() => stopAudio(response ? resultState(response) : "success")}
          onConfirmJira={() => void handleJiraAction("confirm")}
          onCancelJira={() => void handleJiraAction("cancel")}
          jiraActionBusy={jiraActionBusy}
        />
      )}
      {voiceStatus && (
        <section className={`voice-status-card ${voiceStatus.state.toLowerCase()}`} aria-label="Estado de voz">
          <div className="voice-status-heading">
            <strong>Voz</strong>
            <span>{overallVoiceLabel(voiceStatus)}</span>
          </div>
          <p>{voiceStatus.message}</p>
          {components.length > 0 && (
            <ul>
              {components.map((component) => (
                <li key={component.name}>
                  <span>{componentIcon(component)} {component.name}</span>
                  <small>{componentStateLabel(component)}</small>
                </li>
              ))}
            </ul>
          )}
          {!voiceDisabled && !voiceActivated && (
            <button type="button" className="voice-activate-button" disabled={voiceActivationBusy} onClick={() => void handleActivateVoice()}>
              {voiceActivationBusy ? "Comprobando…" : "Activar voz"}
            </button>
          )}
        </section>
      )}
      {showVoiceControls && (
        <div className="voice-controls">
          <label className="voice-spoken-toggle">
            <input
              type="checkbox"
              checked={spokenResponses}
              onChange={(event) => toggleSpokenResponses(event.target.checked)}
            />
            <span className="spoken-label">
              <svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M5 10v4h3l4 3V7l-4 3H5Z" /><path d="M16 9.5a4 4 0 0 1 0 5M18.5 7a7 7 0 0 1 0 10" /></svg>
              Respuestas habladas
            </span>
          </label>
          <VoiceButton state={state} onClick={() => void handleClick()} />
        </div>
      )}
    </div>
  );
}

export { SPOKEN_RESPONSES_KEY };
