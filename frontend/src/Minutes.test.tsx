import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { MinutesReview, NewProposal } from "./Minutes";
import { UploadPanel } from "./App";
import type { Proposal } from "./types";

const text = "Pendientes: Confirmar implementación de ajustes pendientes de Sistemas GIS.";
const proposal: Proposal = {
  proposal_id: "minutes-test", version: 1, template_version: "1.2", status: "NEEDS_INPUT",
  source_file: { name: "Minuta Portal VIC-GIS", sha256: "a".repeat(64) },
  defaults: { space: "AT", iniciativa: null, linea_trabajo: null, sprint: null, tipo_seguimiento: null, semaforo: null },
  created_at: "2026-05-14T00:00:00Z", created_by: "local", approved_at: null, approved_by: null,
  minutes: { prompt_version: "minutes-v1", document: { project: "Portal VIC-GIS", date: "2026-05-14", objective: null,
    participants: [{ name: "Monica Palacios", role: "Líder Usuario" }] }, warnings: ["Se omitieron bloques repetidos."] },
  items: [{ source: { source_row: 6, actividad: "Confirmar implementación", responsable_display: "Por definir",
    frente_trabajo_origen: "GIS", contexto_resultado: "Validar ajustes pendientes.", fecha_objetivo: null,
    estado_actual: "Por confirmar", comentarios: null, source_section: "Pendientes", source_evidence: text },
    generated: { row_id: "ROW-0006", create_in_jira: false, decision: "REVISAR", decision_reason: "Por revisar",
      work_type: "Task", title: "Confirmar implementación", description: "Validar ajustes pendientes.", space: "AT", parent_row_id: null,
      assignee: { display_name: "Por definir", email: null, account_id: null, resolution: "NOT_FOUND" }, fields: {}, confidence: .7 },
    review: { user_modified: false, approved: false, review_note: null }, execution: { result: "NOT_STARTED" },
    validation: { errors: [], warnings: ["Posible duplicado; revisar."], pending_requirements: [] },
  }],
};
let fetchMock: ReturnType<typeof vi.fn>;
beforeEach(() => {
  fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url === "/api/minutes/status") return response({ state: "READY", model: "test-local", detail: "Disponible", max_chars: 30000 });
    if (url === "/api/minutes/analyze") return response({ proposal });
    if (url.endsWith("/preflight")) return response({ write_performed: false });
    if (url.endsWith("/items/ROW-0006")) return response({ ...proposal, version: 2 });
    return response({ connected: false, phase: "DISCONNECTED", snapshot: null });
  });
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
function response(value: unknown, status = 200) { return { ok: status === 200, status, json: async () => value } as Response; }
function entry(onCreated = vi.fn(), telegramUrl: string | null = null) {
  return render(<NewProposal token="test" telegramUrl={telegramUrl} onCreated={onCreated} excel={<UploadPanel token="test" onCreated={onCreated} />} />);
}

it("permite elegir minuta o el importador Excel existente y conserva el texto", async () => {
  entry();
  fireEvent.change(screen.getByRole("textbox", { name: /Pega aquí/ }), { target: { value: text } });
  await userEvent.click(screen.getByRole("button", { name: "Cargar archivo" }));
  expect(screen.getByText("Prepara tu archivo")).toBeInTheDocument();
  expect(document.querySelector('input[type="file"]')).toHaveAttribute("accept", ".xlsx");
  await userEvent.click(screen.getByRole("button", { name: "Pegar minuta" }));
  expect(screen.getByRole("textbox", { name: /Pega aquí/ })).toHaveValue(text);
});

it("analiza texto, entrega la propuesta y no llama Jira ni micrófono", async () => {
  const onCreated = vi.fn();
  const microphone = vi.fn();
  vi.stubGlobal("navigator", { ...navigator, mediaDevices: { getUserMedia: microphone } });
  entry(onCreated);
  expect(screen.getByRole("button", { name: "Analizar minuta" })).toBeDisabled();
  fireEvent.change(screen.getByRole("textbox", { name: /Pega aquí/ }), { target: { value: text } });
  await waitFor(() => expect(screen.getByRole("button", { name: "Analizar minuta" })).toBeEnabled());
  await userEvent.click(screen.getByRole("button", { name: "Analizar minuta" }));
  await waitFor(() => expect(onCreated).toHaveBeenCalledWith(proposal));
  expect(fetchMock.mock.calls.map(call => String(call[0])).filter(url => url.startsWith("/api/minutes"))).toEqual(["/api/minutes/status", "/api/minutes/analyze"]);
  expect(microphone).not.toHaveBeenCalled();
});

it("muestra Radar IA estático con un enlace Telegram seguro cuando está configurado", () => {
  const deepLink = "https://t.me/+_rDVHhg-5vk3NDRh";
  entry(vi.fn(), deepLink);
  expect(screen.getByLabelText("Radar IA en Telegram")).toBeInTheDocument();
  const link = screen.getByRole("link", { name: /Abrir Radaria IA en Telegram/ });
  expect(link).toHaveAttribute("href", deepLink);
  expect(link).toHaveAttribute("target", "_blank");
  expect(link).toHaveAttribute("rel", "noopener noreferrer");
  expect(fetchMock.mock.calls.map(call => String(call[0]))).not.toContain("/api/radar/featured");
});

it("mantiene el CTA Radar visible pero deshabilitado cuando Telegram no está configurado", () => {
  entry();
  expect(screen.getByLabelText("Radar IA en Telegram")).toBeInTheDocument();
  expect(screen.queryByRole("link", { name: /Abrir Radaria IA en Telegram/ })).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: /Abrir Radaria IA en Telegram/ })).toBeDisabled();
});

it("no habilita el CTA con una URL Telegram inválida", () => {
  entry(vi.fn(), "javascript:alert(1)");
  expect(screen.queryByRole("link", { name: /Abrir Radaria IA en Telegram/ })).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: /Abrir Radaria IA en Telegram/ })).toBeDisabled();
});

it("muestra loading e impide solicitudes duplicadas", async () => {
  let finish!: (value: Response) => void;
  fetchMock.mockImplementation(async (input: RequestInfo | URL) => String(input).endsWith("analyze")
    ? new Promise<Response>(resolve => { finish = resolve; })
    : response({ state: "READY", model: "test", max_chars: 30000 }));
  entry();
  fireEvent.change(screen.getByRole("textbox", { name: /Pega aquí/ }), { target: { value: text } });
  await waitFor(() => expect(screen.getByRole("button", { name: "Analizar minuta" })).toBeEnabled());
  await userEvent.click(screen.getByRole("button", { name: "Analizar minuta" }));
  expect(screen.getByRole("button", { name: "Analizando minuta..." })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Cargar archivo" })).toBeDisabled();
  finish(response({ proposal }));
  await waitFor(() => expect(screen.queryByText("Analizando minuta...")).not.toBeInTheDocument());
});

it.each(["DISABLED", "UNAVAILABLE"])("explica IA %s sin simular resultados", async state => {
  fetchMock.mockResolvedValue(response({ state, model: "modelo-ausente", detail: "El análisis inteligente de minutas no está disponible.", max_chars: 30000 }));
  entry();
  expect(await screen.findByText(/El análisis inteligente/)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Analizar minuta" })).toBeDisabled();
  expect(screen.getByText(/Modelo configurado: modelo-ausente/)).toBeInTheDocument();
});

it("muestra error JSON y conserva la minuta para corregir", async () => {
  fetchMock.mockImplementation(async input => String(input).endsWith("analyze")
    ? response({ detail: "No pude estructurar esta minuta con suficiente seguridad." }, 422)
    : response({ state: "READY", max_chars: 30000 }));
  entry();
  fireEvent.change(screen.getByRole("textbox", { name: /Pega aquí/ }), { target: { value: text } });
  await waitFor(() => expect(screen.getByRole("button", { name: "Analizar minuta" })).toBeEnabled());
  await userEvent.click(screen.getByRole("button", { name: "Analizar minuta" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("suficiente seguridad");
  expect(screen.getByRole("textbox", { name: /Pega aquí/ })).toHaveValue(text);
});

it("resultado conserva evidencia y warnings y entra a revisión Jira sólo al pulsar verificar", async () => {
  render(<MinutesReview token="test" proposal={proposal} onUpdated={vi.fn()}><p>Flujo Jira existente</p></MinutesReview>);
  expect(screen.getByText("1 actividades detectadas")).toBeInTheDocument();
  expect(screen.getByText("14/05/2026")).toBeInTheDocument();
  expect(screen.getByText(/Posible duplicado/)).toBeInTheDocument();
  await userEvent.click(screen.getByText("Ver origen"));
  expect(screen.getByText(text)).toBeVisible();
  expect(fetchMock).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole("button", { name: "Verificar con Jira" }));
  expect(await screen.findByText("Flujo Jira existente")).toBeInTheDocument();
  expect(fetchMock.mock.calls.map(call => call[0])).toEqual(["/api/proposals/minutes-test/preflight"]);
});

it("edita campos localmente, bloquea verificar mientras hay cambios y usa versionado existente", async () => {
  const updated = vi.fn();
  render(<MinutesReview token="test" proposal={proposal} onUpdated={updated}><p>Jira</p></MinutesReview>);
  await userEvent.click(screen.getByRole("button", { name: "Editar" }));
  expect(screen.getByRole("button", { name: "Verificar con Jira" })).toBeDisabled();
  fireEvent.change(screen.getByLabelText("Responsable candidato"), { target: { value: "Equipo GIS" } });
  fireEvent.change(screen.getByLabelText("Fecha objetivo"), { target: { value: "2026-06-01" } });
  await userEvent.click(screen.getByRole("button", { name: "Guardar cambios" }));
  await waitFor(() => expect(updated).toHaveBeenCalledWith(expect.objectContaining({ version: 2 })));
  const body = JSON.parse(fetchMock.mock.calls[0][1].body);
  expect(body).toMatchObject({ responsible_candidate_text: "Equipo GIS", due_date_candidate: "2026-06-01" });
  expect(body).not.toHaveProperty("assignee_account_id");
  expect(fetchMock.mock.calls[0][0]).toBe("/api/proposals/minutes-test/items/ROW-0006");
});

function proposalWithPendingEnrichment(): Proposal {
  return { ...proposal, minutes: { ...proposal.minutes!, enrichment: {
    base_version: 1, state: "PENDING", suggestions: [], message: "La mejora opcional con IA está en curso.",
  } } };
}
const suggestion = { row_id: "ROW-0006", title: "Revisar los filtros de consulta disponibles",
  description: "Validar y revisar los filtros de consulta disponibles.", base_title: "Confirmar implementación",
  base_description: text };

it("muestra sugerencias reales, permite aplicarlas y conserva la evidencia de origen", async () => {
  const updated = vi.fn();
  fetchMock.mockImplementation(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.endsWith("/enrichment")) return response({ base_version: 1, state: "READY", suggestions: [suggestion],
      message: "Hay mejoras de redacción disponibles." });
    if (url.endsWith("/items/ROW-0006")) return response({ ...proposal, version: 2 });
    return response({ connected: false, phase: "DISCONNECTED", snapshot: null });
  });
  render(<MinutesReview token="test" proposal={proposalWithPendingEnrichment()} onUpdated={updated}><p>Jira</p></MinutesReview>);
  expect(await screen.findByText(/Hay mejoras de redacción disponibles/)).toBeInTheDocument();
  expect(screen.getByText("Revisar los filtros de consulta disponibles")).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "Confirmar implementación" })).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Aplicar sugerencia" }));
  await waitFor(() => expect(updated).toHaveBeenCalledWith(expect.objectContaining({ version: 2 })));
  const call = fetchMock.mock.calls.find(([url]) => String(url).endsWith("/items/ROW-0006"));
  expect(call?.[0]).toBe("/api/proposals/minutes-test/items/ROW-0006");
  const body = JSON.parse(String(call?.[1]?.body));
  expect(body).toMatchObject({ title: suggestion.title, description: suggestion.description });
  expect(body).not.toHaveProperty("source_evidence");
  expect(body).not.toHaveProperty("source_section");
});

it("permite ignorar una sugerencia sin enviar cambios al backend", async () => {
  fetchMock.mockImplementation(async input => String(input).endsWith("/enrichment")
    ? response({ base_version: 1, state: "READY", suggestions: [suggestion], message: "Hay mejoras de redacción disponibles." })
    : response({ connected: false, phase: "DISCONNECTED", snapshot: null }));
  render(<MinutesReview token="test" proposal={proposalWithPendingEnrichment()} onUpdated={vi.fn()}><p>Jira</p></MinutesReview>);
  await userEvent.click(await screen.findByRole("button", { name: "Ignorar" }));
  expect(await screen.findByText(/Sugerencia ignorada/)).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Aplicar sugerencia" })).not.toBeInTheDocument();
  expect(fetchMock.mock.calls.map(([url]) => String(url))).toEqual(["/api/proposals/minutes-test/enrichment"]);
});

it("muestra éxito discreto cuando el enrichment es válido y no propone cambios", async () => {
  const ready: Proposal = { ...proposalWithPendingEnrichment(), minutes: { ...proposal.minutes!, enrichment: {
    base_version: 1, state: "READY", suggestions: [], message: "Las actividades ya tienen una redacción adecuada.",
  } } };
  render(<MinutesReview token="test" proposal={ready} onUpdated={vi.fn()}><p>Jira</p></MinutesReview>);
  expect(screen.getByText(/Las actividades ya tienen una redacción adecuada/)).toBeInTheDocument();
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});

it("expone el diagnóstico sólo si el enrichment falló técnicamente", () => {
  const failed: Proposal = { ...proposalWithPendingEnrichment(), minutes: { ...proposal.minutes!, enrichment: {
    base_version: 1, state: "FAILED", failure_code: "MINUTES_MODEL_NOT_INSTALLED", suggestions: [],
    message: "El modelo qwen2.5:1.5b no está instalado en Ollama.",
  } } };
  render(<MinutesReview token="test" proposal={failed} onUpdated={vi.fn()}><p>Jira</p></MinutesReview>);
  expect(screen.getByText(/El modelo qwen2.5:1.5b no está instalado en Ollama/)).toBeInTheDocument();
});
