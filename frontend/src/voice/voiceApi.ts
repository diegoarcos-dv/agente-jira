import type { VoiceCommandResponse, VoiceContextView, VoiceStatusView } from "./types";
import { SESSION_EXPIRED_EVENT } from "../authEvents";

const REQUEST_TIMEOUT_MS = 65_000;

export class VoiceApiError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
  }
}

async function statusRequest(token: string, method: "GET" | "POST"): Promise<VoiceStatusView> {
  const response = await fetch(`/api/voice/${method === "POST" ? "activate" : "status"}`, {
    method,
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new VoiceApiError(
      typeof payload.detail === "string" ? payload.detail : "No fue posible consultar el estado de voz.",
      response.status,
    );
  }
  return response.json() as Promise<VoiceStatusView>;
}

export function getVoiceStatus(token: string): Promise<VoiceStatusView> {
  return statusRequest(token, "GET");
}

export function activateVoice(token: string): Promise<VoiceStatusView> {
  return statusRequest(token, "POST");
}

export async function sendVoiceCommand(
  token: string,
  audio: Blob,
  proposalId: string | null,
  spokenResponse: boolean,
): Promise<VoiceCommandResponse> {
  const form = new FormData();
  const extension = audio.type.includes("ogg")
    ? "ogg"
    : audio.type.includes("mp4")
      ? "m4a"
      : "webm";
  form.append("audio", audio, `voice-command.${extension}`);
  if (proposalId) form.append("proposal_id", proposalId);
  form.append("spoken_response", String(spokenResponse));

  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  try {
    const response = await fetch("/api/voice/command", {
      method: "POST",
      headers: { Authorization: `Bearer ${token}` },
      body: form,
      signal: controller.signal,
    });
    if (!response.ok) {
      if (response.status === 401) {
        window.dispatchEvent(new Event(SESSION_EXPIRED_EVENT));
      }
      const payload = await response.json().catch(() => ({}));
      throw new VoiceApiError(
        typeof payload.detail === "string"
          ? payload.detail
          : "No fue posible procesar el comando de voz.",
        response.status,
      );
    }
    return response.json() as Promise<VoiceCommandResponse>;
  } catch (reason) {
    if (reason instanceof DOMException && reason.name === "AbortError") {
      throw new VoiceApiError("El procesamiento de voz agotó el tiempo de espera.", 504);
    }
    throw reason;
  } finally {
    window.clearTimeout(timeout);
  }
}

async function contextRequest(
  token: string,
  method: "GET" | "DELETE",
): Promise<VoiceContextView> {
  const response = await fetch("/api/voice/context", {
    method,
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!response.ok) {
    if (response.status === 401) {
      window.dispatchEvent(new Event(SESSION_EXPIRED_EVENT));
    }
    const payload = await response.json().catch(() => ({}));
    throw new VoiceApiError(
      typeof payload.detail === "string"
        ? payload.detail
        : "No fue posible recuperar el contexto de voz.",
      response.status,
    );
  }
  return response.json() as Promise<VoiceContextView>;
}

export function getVoiceContext(token: string): Promise<VoiceContextView> {
  return contextRequest(token, "GET");
}

export function clearVoiceContext(token: string): Promise<VoiceContextView> {
  return contextRequest(token, "DELETE");
}

async function jiraConfirmationRequest(
  token: string,
  action: "confirm" | "cancel",
  confirmationId: string,
  payloadHash: string,
  spokenResponse: boolean,
): Promise<VoiceCommandResponse> {
  const response = await fetch(`/api/voice/jira/${action}`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      confirmation_id: confirmationId,
      payload_hash: payloadHash,
      spoken_response: spokenResponse,
    }),
  });
  if (!response.ok) {
    if (response.status === 401) window.dispatchEvent(new Event(SESSION_EXPIRED_EVENT));
    const payload = await response.json().catch(() => ({}));
    throw new VoiceApiError(
      typeof payload.detail === "string"
        ? payload.detail
        : "No fue posible procesar la confirmación Jira.",
      response.status,
    );
  }
  return response.json() as Promise<VoiceCommandResponse>;
}

export function confirmVoiceJiraCreate(
  token: string,
  confirmationId: string,
  payloadHash: string,
  spokenResponse: boolean,
): Promise<VoiceCommandResponse> {
  return jiraConfirmationRequest(
    token,
    "confirm",
    confirmationId,
    payloadHash,
    spokenResponse,
  );
}

export function cancelVoiceJiraCreate(
  token: string,
  confirmationId: string,
  payloadHash: string,
  spokenResponse: boolean,
): Promise<VoiceCommandResponse> {
  return jiraConfirmationRequest(
    token,
    "cancel",
    confirmationId,
    payloadHash,
    spokenResponse,
  );
}
