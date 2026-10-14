import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { SESSION_EXPIRED_EVENT } from "../authEvents";
import { SPOKEN_RESPONSES_KEY, VoiceAssistant } from "./VoiceAssistant";
import type {
  VoiceCommandResponse,
  VoiceContextView,
  VoiceJiraOperation,
  VoicePendingConfirmation,
  VoiceStatusView,
  VoiceTaskDraft,
} from "./types";

class MockMediaRecorder {
  static isTypeSupported(type: string) {
    return type.startsWith("audio/webm");
  }

  state: RecordingState = "inactive";
  mimeType: string;
  ondataavailable: ((event: BlobEvent) => void) | null = null;
  onerror: (() => void) | null = null;
  onstop: (() => void) | null = null;

  constructor(_stream: MediaStream, options?: MediaRecorderOptions) {
    this.mimeType = options?.mimeType ?? "audio/webm";
  }

  start() {
    this.state = "recording";
  }

  stop() {
    this.state = "inactive";
    this.ondataavailable?.({ data: new Blob(["voice"], { type: this.mimeType }) } as BlobEvent);
    this.onstop?.();
  }
}

class MockAudio {
  static instances: MockAudio[] = [];
  src: string;
  currentTime = 0;
  onended: ((event: Event) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;
  play = vi.fn(async () => undefined);
  pause = vi.fn();

  constructor(src: string) {
    this.src = src;
    MockAudio.instances.push(this);
  }
}

const EMPTY_CONTEXT: VoiceContextView = {
  active_proposal_id: null,
  active_activity_id: null,
  active_draft_id: null,
  last_intent: null,
  pending_question: null,
  pending_confirmation: null,
  draft: null,
  expires_at: "2026-08-18T18:00:00Z",
};

const DRAFT: VoiceTaskDraft = {
  id: "draft-123",
  issue_type: "Task",
  summary: "Corregir login móvil",
  description: "Validar el flujo completo.",
  assignee: { display_name: "Héctor Ruiz", account_id: "jira-hector", email: null },
  priority: "High",
  space: "AT",
  status: "draft",
};

const JIRA_PREVIEW = {
  issue_type: "Task",
  summary: "Corregir login móvil",
  description: "Validar el flujo completo.",
  assignee: "Héctor Ruiz",
  priority: "High",
  space: "AT",
  parent: null,
  fields_valid: true,
  user_valid: true,
  jira_available: true,
};

const PENDING_JIRA: VoicePendingConfirmation = {
  action: "create_jira_issue",
  confirmation_id: "VCONF-123",
  execution_id: "VOICE-123",
  draft_id: DRAFT.id,
  payload_hash: "a".repeat(64),
  created_at: "2026-08-20T15:00:00Z",
  expires_at: "2026-08-20T15:10:00Z",
  preview: JIRA_PREVIEW,
};

const AWAITING_CONTEXT: VoiceContextView = {
  ...EMPTY_CONTEXT,
  active_draft_id: DRAFT.id,
  pending_confirmation: PENDING_JIRA,
  draft: DRAFT,
};

const DEFAULT_VOICE_STATUS: VoiceStatusView = {
  state: "READY",
  activated: true,
  message: "Voz preparada.",
  stt: {
    name: "STT",
    state: "NOT_LOADED",
    enabled: true,
    configuration: "enabled",
    available: true,
    detail: "Whisper se cargará al primer uso.",
    provider: "faster-whisper",
    model: "small",
  },
  llm: {
    name: "LLM",
    state: "READY",
    enabled: true,
    configuration: "enabled",
    available: true,
    detail: "Ollama disponible.",
    provider: "ollama",
    model: "gemma3:1b",
  },
  tts: {
    name: "TTS",
    state: "NOT_LOADED",
    enabled: true,
    configuration: "enabled",
    available: true,
    detail: "Piper se cargará al primer uso.",
    provider: "piper",
    model: "es_MX-ald-medium",
  },
};

function jiraOperation(
  state: VoiceJiraOperation["state"],
  overrides: Partial<VoiceJiraOperation> = {},
): VoiceJiraOperation {
  return {
    execution_id: "VOICE-123",
    state,
    payload_hash: "a".repeat(64),
    preview: JIRA_PREVIEW,
    issue_key: null,
    issue_url: null,
    readback_checks: {},
    create_elapsed_ms: null,
    readback_elapsed_ms: null,
    reused: false,
    ...overrides,
  };
}

function awaitingResponse(): VoiceCommandResponse {
  return commandResponse({
    transcript: "Envíala a Jira",
    intent: "request_jira_create",
    status: "awaiting_confirmation",
    message: "La tarea está lista para crear en Jira. ¿Confirmas?",
    requires_confirmation: true,
    risk: "JIRA_WRITE",
    draft: DRAFT,
    context: AWAITING_CONTEXT,
    jira_operation: jiraOperation("AWAITING_CONFIRMATION"),
  });
}

function jsonResponse(payload: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => payload,
  } as Response;
}

function commandResponse(
  overrides: Partial<VoiceCommandResponse> = {},
): VoiceCommandResponse {
  return {
    transcript: "estado de jira",
    intent: "get_jira_status",
    status: "completed",
    message: "Jira está conectada en solo lectura.",
    requires_confirmation: false,
    risk: "READ_ONLY",
    draft: null,
    context: EMPTY_CONTEXT,
    audio_available: false,
    audio_base64: null,
    audio_mime_type: null,
    ...overrides,
  };
}

function mockApi(
  command: VoiceCommandResponse | { status: number; detail: string } = commandResponse(),
) {
  return vi.fn(async (input: RequestInfo | URL) => {
    if (String(input).endsWith("/api/voice/status")) return jsonResponse(DEFAULT_VOICE_STATUS);
    if (String(input).endsWith("/api/voice/activate")) return jsonResponse(DEFAULT_VOICE_STATUS);
    if (String(input).endsWith("/api/voice/context")) return jsonResponse(EMPTY_CONTEXT);
    if ("status" in command && typeof command.status === "number") {
      return jsonResponse({ detail: command.detail }, command.status);
    }
    return jsonResponse(command);
  });
}

function postCall(fetchMock: ReturnType<typeof vi.fn>) {
  return fetchMock.mock.calls.find((call) => call[1]?.method === "POST");
}

describe("VoiceAssistant", () => {
  const stopTrack = vi.fn();
  const getUserMedia = vi.fn(async () => ({
    getTracks: () => [{ stop: stopTrack }],
  }) as unknown as MediaStream);

  beforeEach(() => {
    localStorage.clear();
    MockAudio.instances = [];
    vi.stubGlobal("MediaRecorder", MockMediaRecorder);
    vi.stubGlobal("Audio", MockAudio);
    vi.stubGlobal("navigator", { mediaDevices: { getUserMedia } });
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
    vi.unstubAllGlobals();
  });

  it("respeta las capacidades deshabilitadas y no muestra un botón que las salte", async () => {
    const disabled: VoiceStatusView = {
      ...DEFAULT_VOICE_STATUS,
      state: "DISABLED",
      activated: false,
      message: "Las funciones de voz están desactivadas en esta instalación.",
      stt: { ...DEFAULT_VOICE_STATUS.stt, state: "DISABLED", enabled: false },
      llm: { ...DEFAULT_VOICE_STATUS.llm, state: "DISABLED", enabled: false },
      tts: { ...DEFAULT_VOICE_STATUS.tts, state: "DISABLED", enabled: false },
    };
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => (
      String(input).endsWith("/api/voice/status")
        ? jsonResponse(disabled)
        : jsonResponse(EMPTY_CONTEXT)
    )));

    render(<VoiceAssistant token="local-token" proposalId={null} />);

    expect(await screen.findByText("Deshabilitada por configuración")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Iniciar comando de voz" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Activar voz" })).not.toBeInTheDocument();
    expect(getUserMedia).not.toHaveBeenCalled();
  });

  it("activa voz con comprobaciones ligeras y no solicita el micrófono", async () => {
    const notStarted: VoiceStatusView = {
      ...DEFAULT_VOICE_STATUS,
      state: "NOT_STARTED",
      activated: false,
      message: "La voz todavía no ha sido activada.",
    };
    const fetchMock = vi.fn(async (input: RequestInfo | URL, options?: RequestInit) => {
      if (String(input).endsWith("/api/voice/status")) return jsonResponse(notStarted);
      if (String(input).endsWith("/api/voice/activate") && options?.method === "POST") {
        return jsonResponse(DEFAULT_VOICE_STATUS);
      }
      return jsonResponse(EMPTY_CONTEXT);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    render(<VoiceAssistant token="local-token" proposalId={null} />);
    await user.click(await screen.findByRole("button", { name: "Activar voz" }));

    expect(await screen.findByText("Voz preparada")).toBeInTheDocument();
    expect(getUserMedia).not.toHaveBeenCalled();
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/voice/activate",
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("graba sólo entre dos pulsaciones y muestra la respuesta de solo lectura", async () => {
    const fetchMock = mockApi();
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    render(<VoiceAssistant token="local-token" proposalId="proposal-visible" />);
    await user.click(screen.getByRole("button", { name: "Iniciar comando de voz" }));
    expect(getUserMedia).toHaveBeenCalledWith({ audio: true });
    expect(screen.getByRole("button", { name: "Detener grabación de voz" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Detener grabación de voz" }));
    expect(await screen.findByText("Jira está conectada en solo lectura.")).toBeInTheDocument();
    expect(screen.getByText("“estado de jira”")).toBeInTheDocument();
    expect(screen.getByText("Consulta y operación controlada")).toBeInTheDocument();
    expect(stopTrack).toHaveBeenCalledOnce();

    const call = postCall(fetchMock);
    expect(call).toBeDefined();
    const options = call?.[1] as RequestInit;
    expect(options.method).toBe("POST");
    expect(options.headers).toEqual({ Authorization: "Bearer local-token" });
    const form = options.body as FormData;
    expect(form.get("proposal_id")).toBe("proposal-visible");
    expect(form.get("spoken_response")).toBe("true");
    expect(form.get("audio")).toBeInstanceOf(Blob);
  });

  it("explica cuando el navegador rechaza el permiso del micrófono", async () => {
    vi.stubGlobal("fetch", mockApi());
    getUserMedia.mockRejectedValueOnce(new DOMException("denied", "NotAllowedError"));
    const user = userEvent.setup();
    render(<VoiceAssistant token="local-token" proposalId={null} />);

    await user.click(screen.getByRole("button", { name: "Iniciar comando de voz" }));
    expect(await screen.findByText("El navegador no tiene permiso para usar el micrófono.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reintentar comando de voz" })).toBeInTheDocument();
  });

  it("permite cerrar el panel después de un error del backend", async () => {
    vi.stubGlobal("fetch", mockApi({ status: 503, detail: "El reconocimiento de voz está deshabilitado." }));
    const user = userEvent.setup();
    render(<VoiceAssistant token="local-token" proposalId={null} />);
    await user.click(screen.getByRole("button", { name: "Iniciar comando de voz" }));
    await user.click(screen.getByRole("button", { name: "Detener grabación de voz" }));
    expect(await screen.findByText("El reconocimiento de voz está deshabilitado.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Cerrar respuesta de voz" }));
    await waitFor(() => expect(screen.queryByLabelText("Respuesta del asistente de voz")).not.toBeInTheDocument());
    expect(screen.getByRole("button", { name: "Iniciar comando de voz" })).toBeInTheDocument();
  });

  it("avisa una sola vez cuando el comando encuentra la sesión vencida", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => (
      String(input).endsWith("/api/voice/context")
        ? jsonResponse(EMPTY_CONTEXT)
        : jsonResponse({ detail: "Credenciales inválidas." }, 401)
    ));
    vi.stubGlobal("fetch", fetchMock);
    const expired = vi.fn();
    window.addEventListener(SESSION_EXPIRED_EVENT, expired);
    const user = userEvent.setup();
    render(<VoiceAssistant token="expired-token" proposalId={null} />);

    await user.click(screen.getByRole("button", { name: "Iniciar comando de voz" }));
    await user.click(screen.getByRole("button", { name: "Detener grabación de voz" }));
    await waitFor(() => expect(expired).toHaveBeenCalledOnce());

    window.removeEventListener(SESSION_EXPIRED_EVENT, expired);
  });

  it("muestra el borrador local y nunca lo presenta como enviado a Jira", async () => {
    const context = { ...EMPTY_CONTEXT, active_draft_id: DRAFT.id, draft: DRAFT };
    vi.stubGlobal("fetch", mockApi(commandResponse({
      transcript: "Crea una tarea para corregir el login móvil",
      intent: "prepare_local_task",
      status: "needs_clarification",
      message: "Preparé la tarea localmente. ¿A quién la asigno?",
      risk: "LOCAL_WRITE",
      draft: DRAFT,
      context,
    })));
    const user = userEvent.setup();
    render(<VoiceAssistant token="local-token" proposalId={null} />);

    await user.click(screen.getByRole("button", { name: "Iniciar comando de voz" }));
    await user.click(screen.getByRole("button", { name: "Detener grabación de voz" }));
    expect(await screen.findByRole("article", { name: "Tarea preparada" })).toBeInTheDocument();
    expect(screen.getByText("Corregir login móvil")).toBeInTheDocument();
    expect(screen.getByText("Héctor Ruiz")).toBeInTheDocument();
    expect(screen.getByText("Alta")).toBeInTheDocument();
    expect(screen.getByText("Todavía no enviada a Jira")).toBeInTheDocument();
    expect(await screen.findByText("Tarea preparada · sin enviar")).toBeInTheDocument();
  });

  it("persiste el interruptor de respuesta hablada y no reproduce audio al desactivarlo", async () => {
    const fetchMock = mockApi(commandResponse({
      audio_available: true,
      audio_base64: "UklGRg==",
      audio_mime_type: "audio/wav",
    }));
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<VoiceAssistant token="local-token" proposalId={null} />);

    await user.click(screen.getByRole("checkbox", { name: /Respuestas habladas/ }));
    expect(localStorage.getItem(SPOKEN_RESPONSES_KEY)).toBe("false");
    await user.click(screen.getByRole("button", { name: "Iniciar comando de voz" }));
    await user.click(screen.getByRole("button", { name: "Detener grabación de voz" }));
    expect(await screen.findByText("Jira está conectada en solo lectura.")).toBeInTheDocument();
    const form = postCall(fetchMock)?.[1]?.body as FormData;
    expect(form.get("spoken_response")).toBe("false");
    expect(MockAudio.instances).toHaveLength(0);
  });

  it("recorre los estados y permite interrumpir la voz antes de volver a escuchar", async () => {
    let resolveCommand!: (response: Response) => void;
    const commandPending = new Promise<Response>((resolve) => {
      resolveCommand = resolve;
    });
    const context = { ...EMPTY_CONTEXT, active_draft_id: DRAFT.id, draft: DRAFT };
    const fetchMock = vi.fn((input: RequestInfo | URL) => (
      String(input).endsWith("/api/voice/context")
        ? Promise.resolve(jsonResponse(EMPTY_CONTEXT))
        : commandPending
    ));
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<VoiceAssistant token="local-token" proposalId={null} />);

    await user.click(screen.getByRole("button", { name: "Iniciar comando de voz" }));
    await user.click(screen.getByRole("button", { name: "Detener grabación de voz" }));
    expect(screen.getByText("📝 Transcribiendo…")).toBeInTheDocument();
    expect(await screen.findByText("🧠 Pensando…")).toBeInTheDocument();

    resolveCommand(jsonResponse(commandResponse({
      transcript: "Alta",
      intent: "set_task_priority",
      message: "Actualicé la prioridad a Alta.",
      risk: "LOCAL_WRITE",
      draft: DRAFT,
      context,
      audio_available: true,
      audio_base64: "UklGRg==",
      audio_mime_type: "audio/wav",
    })));
    expect(await screen.findByText("⚙️ Actualizando borrador…")).toBeInTheDocument();
    expect(await screen.findByText("🔊 Vic está hablando…")).toBeInTheDocument();
    expect(MockAudio.instances).toHaveLength(1);
    const playing = MockAudio.instances[0];
    expect(playing.play).toHaveBeenCalledOnce();
    expect(screen.getByRole("button", { name: "Detener audio" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Detener respuesta e iniciar grabación" }));
    expect(playing.pause).toHaveBeenCalledOnce();
    expect(getUserMedia).toHaveBeenCalledTimes(2);
    expect(screen.getByRole("button", { name: "Detener grabación de voz" })).toBeInTheDocument();
  });

  it("conserva el texto cuando el navegador no puede reproducir el WAV", async () => {
    vi.stubGlobal("fetch", mockApi(commandResponse({
      audio_available: true,
      audio_base64: "UklGRg==",
      audio_mime_type: "audio/wav",
    })));
    const user = userEvent.setup();
    render(<VoiceAssistant token="local-token" proposalId={null} />);
    await user.click(screen.getByRole("button", { name: "Iniciar comando de voz" }));
    await user.click(screen.getByRole("button", { name: "Detener grabación de voz" }));
    await screen.findByText("🔊 Vic está hablando…");

    MockAudio.instances[0].onerror?.(new Event("error"));
    expect(await screen.findByText("No se pudo reproducir la voz de Vic; la respuesta escrita sigue disponible.")).toBeInTheDocument();
    expect(screen.getByText("Jira está conectada en solo lectura.")).toBeInTheDocument();
  });

  it("muestra preview Jira y espera confirmación sin crear nada", async () => {
    const fetchMock = mockApi(awaitingResponse());
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<VoiceAssistant token="local-token" proposalId={null} />);

    await user.click(screen.getByRole("button", { name: "Iniciar comando de voz" }));
    await user.click(screen.getByRole("button", { name: "Detener grabación de voz" }));

    expect(await screen.findByRole("article", { name: "Confirmar creación en Jira" })).toBeInTheDocument();
    expect(screen.getByText("Esperando confirmación")).toBeInTheDocument();
    expect(screen.getAllByText("Corregir login móvil")).toHaveLength(2);
    expect(screen.getAllByText("Héctor Ruiz")).toHaveLength(2);
    expect(screen.getByText("✓ Campos válidos")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Crear en Jira" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Cancelar" })).toBeEnabled();
    expect(fetchMock.mock.calls.filter((call) => String(call[0]).includes("/api/voice/jira/"))).toHaveLength(0);
  });

  it("protege el doble clic, muestra creación/verificación y anuncia el key", async () => {
    let resolveConfirm!: (value: Response) => void;
    const pendingConfirm = new Promise<Response>((resolve) => {
      resolveConfirm = resolve;
    });
    let confirmationCalls = 0;
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/api/voice/context")) return Promise.resolve(jsonResponse(EMPTY_CONTEXT));
      if (url.endsWith("/api/voice/command")) return Promise.resolve(jsonResponse(awaitingResponse()));
      if (url.endsWith("/api/voice/jira/confirm")) {
        confirmationCalls += 1;
        return pendingConfirm;
      }
      throw new Error(`URL inesperada: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<VoiceAssistant token="local-token" proposalId={null} />);
    await user.click(screen.getByRole("button", { name: "Iniciar comando de voz" }));
    await user.click(screen.getByRole("button", { name: "Detener grabación de voz" }));
    const create = await screen.findByRole("button", { name: "Crear en Jira" });

    fireEvent.click(create);
    fireEvent.click(create);

    expect(await screen.findByText("↗ Creando en Jira…")).toBeInTheDocument();
    expect(confirmationCalls).toBe(1);
    expect(getUserMedia).toHaveBeenCalledTimes(1);
    expect(await screen.findByText("⌕ Verificando en Jira…")).toBeInTheDocument();

    resolveConfirm(jsonResponse(commandResponse({
      transcript: "",
      intent: "confirm_jira_create",
      status: "completed",
      message: "Listo. La tarea AT-9901 fue creada y verificada correctamente.",
      risk: "JIRA_WRITE",
      draft: DRAFT,
      context: { ...AWAITING_CONTEXT, pending_confirmation: null },
      jira_operation: jiraOperation("SUCCESS", {
        issue_key: "AT-9901",
        issue_url: "https://jira.test/browse/AT-9901",
        readback_checks: { issue_key: true, summary: true, space: true, work_type: true },
        create_elapsed_ms: 120,
        readback_elapsed_ms: 35,
      }),
      audio_available: true,
      audio_base64: "UklGRg==",
      audio_mime_type: "audio/wav",
    })));

    await waitFor(() => expect(MockAudio.instances).toHaveLength(1));
    MockAudio.instances[0].onended?.(new Event("ended"));
    expect(await screen.findByText("Listo. La tarea AT-9901 fue creada y verificada correctamente.")).toBeInTheDocument();
    expect(screen.getByText("AT-9901 creada y verificada")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Ver AT-9901 en Jira" })).toHaveAttribute("href", "https://jira.test/browse/AT-9901");
    expect(MockAudio.instances[0].play).toHaveBeenCalledOnce();
  });

  it("cancela desde la tarjeta mediante el endpoint compartido", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/api/voice/context")) return jsonResponse(EMPTY_CONTEXT);
      if (url.endsWith("/api/voice/command")) return jsonResponse(awaitingResponse());
      if (url.endsWith("/api/voice/jira/cancel")) return jsonResponse(commandResponse({
        transcript: "",
        intent: "reject_pending_action",
        status: "cancelled",
        message: "Cancelé la creación. No se hizo ningún cambio en Jira.",
        risk: "JIRA_WRITE",
        draft: DRAFT,
        context: { ...AWAITING_CONTEXT, pending_confirmation: null },
        jira_operation: jiraOperation("CANCELLED"),
      }));
      throw new Error(`URL inesperada: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<VoiceAssistant token="local-token" proposalId={null} />);
    await user.click(screen.getByRole("button", { name: "Iniciar comando de voz" }));
    await user.click(screen.getByRole("button", { name: "Detener grabación de voz" }));
    await user.click(await screen.findByRole("button", { name: "Cancelar" }));

    expect(await screen.findByText("Cancelé la creación. No se hizo ningún cambio en Jira.")).toBeInTheDocument();
    expect(screen.getByText("No se realizó la operación")).toBeInTheDocument();
    expect(fetchMock.mock.calls.filter((call) => String(call[0]).endsWith("/api/voice/jira/cancel"))).toHaveLength(1);
    expect(fetchMock.mock.calls.filter((call) => String(call[0]).endsWith("/api/voice/jira/confirm"))).toHaveLength(0);
  });

  it.each([
    ["unknown_result", "UNKNOWN_RESULT", "No pude verificar el resultado.", "Resultado pendiente de verificación"],
    ["execution_error", "EXECUTION_ERROR", "Jira rechazó la creación.", "No se realizó la operación"],
  ] as const)("presenta el resultado Jira %s sin repetir", async (status, state, message, footer) => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/api/voice/context")) return jsonResponse(EMPTY_CONTEXT);
      if (url.endsWith("/api/voice/command")) return jsonResponse(awaitingResponse());
      if (url.endsWith("/api/voice/jira/confirm")) return jsonResponse(commandResponse({
        transcript: "",
        intent: "confirm_jira_create",
        status,
        message,
        risk: "JIRA_WRITE",
        draft: DRAFT,
        context: { ...AWAITING_CONTEXT, pending_confirmation: null },
        jira_operation: jiraOperation(state),
      }));
      throw new Error(`URL inesperada: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<VoiceAssistant token="local-token" proposalId={null} />);
    await user.click(screen.getByRole("button", { name: "Iniciar comando de voz" }));
    await user.click(screen.getByRole("button", { name: "Detener grabación de voz" }));
    await user.click(await screen.findByRole("button", { name: "Crear en Jira" }));

    expect(await screen.findByText(message)).toBeInTheDocument();
    expect(screen.getByText(footer)).toBeInTheDocument();
    expect(fetchMock.mock.calls.filter((call) => String(call[0]).endsWith("/api/voice/jira/confirm"))).toHaveLength(1);
  });

  it("recupera una confirmación pendiente después de refrescar", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      if (String(input).endsWith("/api/voice/context")) return jsonResponse(AWAITING_CONTEXT);
      throw new Error("No debe enviar nada al cargar el contexto");
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<VoiceAssistant token="local-token" proposalId={null} />);

    expect(await screen.findByRole("article", { name: "Confirmar creación en Jira" })).toBeInTheDocument();
    expect(screen.getByText("La tarea sigue esperando tu confirmación. Aún no se ha creado nada.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Responder a la confirmación pendiente" })).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("acepta la confirmación hablada y muestra el key verificado", async () => {
    let commandCount = 0;
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/api/voice/context")) return jsonResponse(EMPTY_CONTEXT);
      if (url.endsWith("/api/voice/command")) {
        commandCount += 1;
        if (commandCount === 1) return jsonResponse(awaitingResponse());
        return jsonResponse(commandResponse({
          transcript: "Sí, créala",
          intent: "confirm_jira_create",
          status: "completed",
          message: "Listo. La tarea AT-9902 fue creada y verificada correctamente.",
          risk: "JIRA_WRITE",
          draft: DRAFT,
          context: { ...AWAITING_CONTEXT, pending_confirmation: null },
          jira_operation: jiraOperation("SUCCESS", {
            issue_key: "AT-9902",
            issue_url: "https://jira.test/browse/AT-9902",
          }),
        }));
      }
      throw new Error(`URL inesperada: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<VoiceAssistant token="local-token" proposalId={null} />);
    await user.click(screen.getByRole("button", { name: "Iniciar comando de voz" }));
    await user.click(screen.getByRole("button", { name: "Detener grabación de voz" }));
    await screen.findByRole("article", { name: "Confirmar creación en Jira" });

    await user.click(screen.getByRole("button", { name: "Responder a la confirmación pendiente" }));
    await user.click(screen.getByRole("button", { name: "Detener grabación de voz" }));

    expect(await screen.findByText("Listo. La tarea AT-9902 fue creada y verificada correctamente.")).toBeInTheDocument();
    expect(commandCount).toBe(2);
    expect(fetchMock.mock.calls.some((call) => String(call[0]).includes("/api/voice/jira/confirm"))).toBe(false);
  });
});
