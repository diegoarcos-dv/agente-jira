import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { afterEach, expect, it, vi } from "vitest";
import { MinuteDraftPreview } from "./Minutes";
import type { JiraAssignee, MinuteDraftRow, MinuteExcelDraft, Proposal } from "./types";

const row = {
  candidate_id: "ACT-001", actividad: "Validar entrega", responsable: "Por definir", responsable_account_id: null,
  area_responsable: null, area_source: "LOCAL" as const, area_status: "UNSPECIFIED" as const, area_candidates: [], area_mentions: [],
  row_status: "NEEDS_REVIEW" as const, row_errors: [{ field: "responsable", code: "REQUIRED_REVIEW", message: "Responsable por definir." }], row_warnings: [],
  responsable_source: "UNRESOLVED" as const, tipo_de_seguimiento: "Semanal", tipo_de_seguimiento_id: "1",
  fecha_objetivo: null, proyecto_o_frente: "VIC-GIS", contexto_o_resultado: "Validar el resultado", comentarios: null,
  source_section: "Pendientes", source_evidence: "Validar entrega del proyecto VIC-GIS.", extraction_mode: "DETERMINISTIC_EXPLICIT",
  touched_fields: [], suggestions: [{ field: "actividad", value: "Validar entrega final" }], ignored_suggestions: [],
  field_status: { actividad: "VALID", responsable: "REVIEW", tipo_de_seguimiento: "VALID", fecha_objetivo: "EMPTY_ALLOWED",
    proyecto_o_frente: "VALID", contexto_o_resultado: "VALID", comentarios: "EMPTY_ALLOWED" } as const,
  validation_errors: [{ field: "responsable", code: "REQUIRED_REVIEW", message: "Responsable por definir." }],
};
const draft: MinuteExcelDraft = {
  draft_id: "draft-1", source: "MINUTA", version: 1, state: "NEEDS_REVIEW", created_at: "2026-09-18T00:00:00Z",
  updated_at: "2026-09-18T00:00:00Z", extraction_mode: "DETERMINISTIC_EXPLICIT", duplicates_removed: 0,
  warnings: [], rows: [row], tracking_options: [{ value: "Semanal", label: "Semanal", jira_id: "1" }],
  validation_summary: { activities: 1, complete: 0, needs_review: 1, technical_errors: 0 },
  enrichment: { state: "READY", base_version: 1, suggestions: [], message: "Sugerencia disponible" }, proposal_id: null,
};

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

function view(overrides: Partial<Parameters<typeof MinuteDraftPreview>[0]> = {}) {
  const props = { token: "token", draft, setDraft: vi.fn(), onSave: vi.fn(async () => undefined),
    onCreated: vi.fn(), onReanalyze: vi.fn(), ...overrides };
  render(<MinuteDraftPreview {...props} />);
  return props;
}

function StatefulPreview({ onSave }: { onSave?: (candidateId: string, changes: Partial<MinuteDraftRow>) => Promise<void> }) {
  const [current, setCurrent] = useState(draft);
  return <MinuteDraftPreview token="token-stateful" draft={current} setDraft={setCurrent}
    onSave={onSave ?? (async () => undefined)} onCreated={vi.fn()} onReanalyze={vi.fn()} />;
}

const areaOptions = [{ key: "AT", value: "Arquitecturas TI", label: "AT · Arquitecturas TI" }];

function mockJiraReads(assignees: JiraAssignee[] = [], options = [{ value: "Actividad concreta", label: "Actividad concreta", jira_id: "10060" }], failCatalogCount = 0) {
  let failures = 0;
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.includes("/catalog")) {
      if (failures < failCatalogCount) { failures += 1; return { ok: false, status: 409, json: async () => ({ detail: "offline" }) } as Response; }
      const rowResult = { ...row, tipo_de_seguimiento: "Por definir", tipo_de_seguimiento_id: null };
      const catalogDraft = { ...draft, catalog_status: "READY" as const, tracking_options: options, tracking_field_id: "customfield_10147",
        rows: [rowResult] };
      return { ok: true, status: 200, json: async () => ({ state: "READY", space: "AT", work_type: "Task",
        field_id: "customfield_10147", options, area_options: areaOptions, draft: catalogDraft }) } as Response;
    }
    if (url.includes("/assignees")) return { ok: true, status: 200, json: async () => assignees } as Response;
    return { ok: false, status: 404, json: async () => ({}) } as Response;
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

it("renderiza las ocho columnas, estados, evidencia y permite editar cada tipo de celda", async () => {
  const onSave = vi.fn(async () => undefined);
  mockJiraReads();
  view({ onSave });
  for (const heading of ["Actividad *", "Área responsable", "Responsable *", "Tipo de seguimiento *", "Fecha objetivo", "Proyecto o frente", "Contexto o resultado", "Comentarios"]) {
    expect(screen.getByRole("columnheader", { name: heading })).toBeInTheDocument();
  }
  fireEvent.change(screen.getByLabelText("Actividad ACT-001"), { target: { value: "Actividad editada" } });
  fireEvent.blur(screen.getByLabelText("Actividad ACT-001"));
  const area = await screen.findByLabelText("Área responsable ACT-001");
  await userEvent.selectOptions(area, "Arquitecturas TI");
  fireEvent.change(screen.getByLabelText("Fecha objetivo ACT-001"), { target: { value: "2026-09-25" } });
  fireEvent.blur(screen.getByLabelText("Fecha objetivo ACT-001"));
  fireEvent.change(screen.getByLabelText("Proyecto o frente ACT-001"), { target: { value: "Frente GIS" } });
  fireEvent.blur(screen.getByLabelText("Proyecto o frente ACT-001"));
  fireEvent.change(screen.getByLabelText("Contexto o resultado ACT-001"), { target: { value: "Resultado editado" } });
  fireEvent.blur(screen.getByLabelText("Contexto o resultado ACT-001"));
  fireEvent.change(screen.getByLabelText("Comentarios ACT-001"), { target: { value: "Comentario" } });
  fireEvent.blur(screen.getByLabelText("Comentarios ACT-001"));
  await userEvent.click(screen.getByText("Ver evidencia"));
  expect(screen.getByText(row.source_evidence)).toBeVisible();
  await waitFor(() => expect(onSave).toHaveBeenCalledWith("ACT-001", { actividad: "Actividad editada" }));
  expect(onSave).toHaveBeenCalledWith("ACT-001", { area_responsable: "Arquitecturas TI", area_source: "USER_SELECTED" });
  expect(onSave).toHaveBeenCalledWith("ACT-001", { fecha_objetivo: "2026-09-25" });
  expect(onSave).toHaveBeenCalledWith("ACT-001", { proyecto_o_frente: "Frente GIS" });
  expect(onSave).toHaveBeenCalledWith("ACT-001", { contexto_o_resultado: "Resultado editado" });
  expect(onSave).toHaveBeenCalledWith("ACT-001", { comentarios: "Comentario" });
});

it("muestra Por definir como placeholder y no como texto del responsable", async () => {
  mockJiraReads();
  view();
  const responsible = screen.getByLabelText("Responsable ACT-001");
  expect(responsible).toHaveValue("");
  expect(responsible).toHaveAttribute("placeholder", "Por definir");
});

it("muestra sólo las áreas asociadas al responsable cuando hay varias", async () => {
  const mapped = { ...row, responsable: "Erick", responsable_account_id: "jira-erick",
    responsable_resolution_status: "VALIDATED_JIRA" as const, area_candidates: ["Arquitecturas TI", "Big Data"],
    area_status: "AMBIGUOUS" as const, area_source: "UNRESOLVED" as const };
  mockJiraReads();
  view({ draft: { ...draft, rows: [mapped] } });
  const area = await screen.findByLabelText("Área responsable ACT-001");
  expect(within(area).getByRole("option", { name: "Arquitecturas TI" })).toBeInTheDocument();
  expect(within(area).getByRole("option", { name: "Big Data" })).toBeInTheDocument();
  expect(screen.getByText(/Selecciona el área responsable: Arquitecturas TI, Big Data/)).toBeInTheDocument();
});

it("consulta responsables Jira y guarda sólo una selección verificada", async () => {
  const onSave = vi.fn(async () => undefined);
  mockJiraReads([
    { account_id: "jira-1", display_name: "Jose Calleja", email: null, active: true },
    { account_id: "jira-2", display_name: "Jose Pérez", email: null, active: true },
  ]);
  view({ onSave, token: "token-manual" });
  fireEvent.change(screen.getByLabelText("Responsable ACT-001"), { target: { value: "Jose" } });
  await userEvent.click(screen.getByRole("button", { name: "Buscar en Jira" }));
  const select = await screen.findByLabelText("Resultados responsable ACT-001");
  await userEvent.selectOptions(select, "jira-1");
  await waitFor(() => expect(onSave).toHaveBeenCalledWith("ACT-001", expect.objectContaining({
    responsable: "Jose Calleja", responsable_account_id: "jira-1", responsable_resolution_status: "VALIDATED_JIRA",
  })));
});

it("resuelve automáticamente una coincidencia única tras el debounce", async () => {
  const onSave = vi.fn(async () => undefined);
  const fetchMock = mockJiraReads([{ account_id: "jira-jose", display_name: "Jose Calleja", email: null, active: true }]);
  view({ onSave, token: "token-auto" });
  fireEvent.change(screen.getByLabelText("Responsable ACT-001"), { target: { value: "Jose" } });
  await new Promise(resolve => setTimeout(resolve, 180));
  expect(fetchMock.mock.calls.some(([url]) => String(url).includes("/assignees"))).toBe(false);
  await waitFor(() => expect(onSave).toHaveBeenCalledWith("ACT-001", expect.objectContaining({
    responsable: "Jose Calleja", responsable_account_id: "jira-jose", responsable_resolution_status: "AUTO_RESOLVED",
  })), { timeout: 2000 });
  expect(screen.getByText("✓ Resuelto automáticamente con Jira")).toBeInTheDocument();
  const lookup = fetchMock.mock.calls.find(([url]) => String(url).includes("/assignees"));
  expect(String(lookup?.[0])).toContain("space=AT");
});

it("invalida el ID anterior al editar y bloquea Continuar mientras valida el texto nuevo", async () => {
  const onSave = vi.fn(async () => undefined);
  mockJiraReads([{ account_id: "jira-new", display_name: "Jose Gómez", email: null, active: true }]);
  const verifiedRow = { ...row, responsable: "Jose Calleja", responsable_account_id: "jira-old",
    responsable_resolution_status: "VALIDATED_JIRA" as const, responsable_source: "JIRA" as const };
  const readyDraft = { ...draft, state: "READY" as const, rows: [{ ...verifiedRow, row_status: "READY" as const }] };
  view({ onSave, token: "token-invalidate", draft: readyDraft });
  await userEvent.click(screen.getByRole("checkbox", { name: "Seleccionar ACT-001 para preparar" }));
  fireEvent.change(screen.getByLabelText("Responsable ACT-001"), { target: { value: "Jose G" } });
  await waitFor(() => expect(screen.getByRole("button", { name: "Preparar seleccionadas (1)" })).toBeDisabled());
  await waitFor(() => expect(onSave).toHaveBeenCalledWith("ACT-001", expect.objectContaining({
    responsable: "Jose G", responsable_account_id: null, responsable_resolution_status: "RESOLVING",
  })), { timeout: 2000 });
  await waitFor(() => expect(onSave).toHaveBeenCalledWith("ACT-001", expect.objectContaining({
    responsable: "Jose Gómez", responsable_account_id: "jira-new", responsable_resolution_status: "AUTO_RESOLVED",
  })), { timeout: 2000 });
  await waitFor(() => expect(screen.getByRole("button", { name: "Preparar seleccionadas (1)" })).toBeEnabled());
});

it("muestra varias coincidencias y no elige responsable por cuenta propia", async () => {
  const onSave = vi.fn(async () => undefined);
  mockJiraReads([
    { account_id: "jose-1", display_name: "Jose Calleja", email: null, active: true },
    { account_id: "jose-2", display_name: "Jose Pérez", email: null, active: true },
  ]);
  view({ onSave, token: "token-multiple" });
  fireEvent.change(screen.getByLabelText("Responsable ACT-001"), { target: { value: "Jose" } });
  const select = await screen.findByLabelText("Resultados responsable ACT-001", {}, { timeout: 2000 });
  expect(select.querySelectorAll("option")).toHaveLength(3);
  expect(await screen.findByText("⚠ Hay varias coincidencias Jira. Selecciona una.")).toBeInTheDocument();
  expect(onSave).toHaveBeenCalledWith("ACT-001", expect.objectContaining({ responsable_resolution_status: "MULTIPLE_MATCHES" }));
  expect(onSave).not.toHaveBeenCalledWith("ACT-001", expect.objectContaining({ responsable_account_id: "jose-1" }));
  await userEvent.selectOptions(select, "jose-2");
  await waitFor(() => expect(onSave).toHaveBeenCalledWith("ACT-001", expect.objectContaining({
    responsable: "Jose Pérez", responsable_account_id: "jose-2", responsable_resolution_status: "VALIDATED_JIRA",
  })));
});

it("conserva el texto cuando Jira no encuentra al responsable", async () => {
  const onSave = vi.fn(async () => undefined);
  mockJiraReads([]);
  view({ onSave, token: "token-none" });
  fireEvent.change(screen.getByLabelText("Responsable ACT-001"), { target: { value: "Nombre Inventado" } });
  expect(await screen.findByText("⚠ Responsable no encontrado en Jira. Se conserva el texto.", {}, { timeout: 2000 })).toBeInTheDocument();
  expect(onSave).toHaveBeenCalledWith("ACT-001", expect.objectContaining({ responsable: "Nombre Inventado", responsable_account_id: null, responsable_resolution_status: "NOT_FOUND" }));
});

it("carga el catálogo dinámico de customfield_10147 y envía nombre e ID al editar", async () => {
  const onSave = vi.fn(async () => undefined);
  const fetchMock = mockJiraReads();
  render(<StatefulPreview onSave={onSave} />);
  await waitFor(() => expect(screen.getByRole("option", { name: "Actividad concreta" })).toBeInTheDocument());
  const type = screen.getByLabelText("Tipo de seguimiento ACT-001");
  await userEvent.selectOptions(type, "Actividad concreta");
  expect(onSave).toHaveBeenCalledWith("ACT-001", { tipo_de_seguimiento: "Actividad concreta", tipo_de_seguimiento_id: "10060" });
  expect(fetchMock.mock.calls.some(([url]) => String(url).includes("/catalog"))).toBe(true);
});

it("permite reintentar el catálogo si la lectura Jira falla", async () => {
  const fetchMock = mockJiraReads([], undefined, 1);
  const StatefulRetry = () => {
    const [current, setCurrent] = useState(draft);
    return <MinuteDraftPreview token="token-retry" draft={current} setDraft={setCurrent}
      onSave={async () => undefined} onCreated={vi.fn()} onReanalyze={vi.fn()} />;
  };
  render(<StatefulRetry />);
  expect(await screen.findByText("No se pudieron actualizar las opciones de Jira. Se conservan las opciones guardadas.")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Reintentar catálogo" }));
  await waitFor(() => expect(screen.queryByRole("button", { name: "Reintentar catálogo" })).not.toBeInTheDocument());
  expect(fetchMock.mock.calls.filter(([url]) => String(url).includes("/catalog"))).toHaveLength(2);
});

it("mantiene disponible la edición manual de Tipo de seguimiento sin catálogo", async () => {
  const onSave = vi.fn(async () => undefined);
  mockJiraReads([], [], 1);
  view({ draft: { ...draft, tracking_options: [], catalog_status: "LOADING" }, onSave, token: "token-manual-type" });
  const type = screen.getByLabelText("Tipo de seguimiento ACT-001");
  fireEvent.change(type, { target: { value: "Valor local" } });
  fireEvent.blur(type);
  await waitFor(() => expect(onSave).toHaveBeenCalledWith("ACT-001", {
    tipo_de_seguimiento: "Valor local", tipo_de_seguimiento_id: null,
  }));
});

it("aplica o ignora sugerencias sin alterar la evidencia", async () => {
  const onSave = vi.fn(async () => undefined);
  view({ onSave });
  const suggestion = screen.getByText("Sugerencia IA disponible").parentElement!;
  await userEvent.click(within(suggestion).getByRole("button", { name: "Aplicar" }));
  expect(onSave).toHaveBeenCalledWith("ACT-001", { actividad: "Validar entrega final" });
  await userEvent.click(within(suggestion).getByRole("button", { name: "Ignorar" }));
  expect(screen.queryByText("Sugerencia IA disponible")).not.toBeInTheDocument();
  expect(row.source_evidence).toBe("Validar entrega del proyecto VIC-GIS.");
});

it("permite preparar una sola fila lista sin invocar acciones Jira", async () => {
  const ready = { ...draft, state: "READY" as const, rows: [{ ...row, row_status: "READY" as const,
      responsable: "Jose Calleja", responsable_resolution_status: "EXPLICIT_MINUTES" as const,
      field_status: { ...row.field_status, responsable: "VALID" as const } }],
    validation_summary: { activities: 1, complete: 1, created: 0, needs_review: 0, technical_errors: 0 } };
  const proposal = { proposal_id: "p1" } as Proposal;
  const fetchMock = vi.fn(async (input: RequestInfo | URL, _init?: RequestInit) => {
    const url = String(input);
    if (url.includes("/catalog")) return { ok: true, status: 200, json: async () => ({
      state: "READY", space: "AT", work_type: "Task", field_id: "customfield_10147",
      options: ready.tracking_options, draft: ready,
    }) } as Response;
    if (url.includes("/assignees")) return { ok: true, status: 200, json: async () => [] } as Response;
    if (url.endsWith("/rows")) return { ok: true, status: 200, json: async () => ready } as Response;
    if (url.includes("/rows/ACT-001")) return { ok: true, status: 200, json: async () => ({ ...ready, rows: [] }) } as Response;
    if (url.endsWith("/proposal")) return { ok: true, status: 200, json: async () => proposal } as Response;
    if (url.endsWith("/draft-1")) return { ok: true, status: 200, json: async () => ({ ...ready, rows: [{ ...ready.rows[0], proposal_id: "p1" }] }) } as Response;
    return { ok: true, status: 200, blob: async () => new Blob(["xlsx"]), headers: new Headers() } as Response;
  });
  vi.stubGlobal("fetch", fetchMock); vi.stubGlobal("confirm", vi.fn(() => true));
  vi.stubGlobal("URL", { createObjectURL: vi.fn(() => "blob:test"), revokeObjectURL: vi.fn() });
  const setDraft = vi.fn(); const onCreated = vi.fn();
  view({ draft: ready, setDraft, onCreated });
  await waitFor(() => expect(screen.getByRole("button", { name: "Preparar esta tarea" })).toBeEnabled(), { timeout: 2000 });
  await userEvent.click(screen.getByRole("button", { name: "Agregar actividad" }));
  await waitFor(() => expect(setDraft).toHaveBeenCalled());
  await userEvent.click(screen.getByRole("button", { name: "Eliminar fila" }));
  expect(confirm).toHaveBeenCalled();
  await userEvent.click(screen.getByRole("button", { name: "Preparar esta tarea" }));
  await waitFor(() => expect(onCreated).toHaveBeenCalledWith(proposal));
  const body = JSON.parse(String(fetchMock.mock.calls.find(([url]) => String(url).endsWith("/proposal"))?.[1]?.body));
  expect(body).toEqual({ candidate_ids: ["ACT-001"] });
  expect(fetchMock.mock.calls.every(([url]) => !String(url).includes("createJiraIssue"))).toBe(true);
});

it("sólo permite seleccionar filas listas para preparar un lote", async () => {
  const readyOne = { ...row, candidate_id: "ACT-001", row_status: "READY" as const,
    responsable: "Jose Calleja", responsable_resolution_status: "EXPLICIT_MINUTES" as const,
    field_status: { ...row.field_status, responsable: "VALID" as const } };
  const readyTwo = { ...readyOne, candidate_id: "ACT-002", actividad: "Entregar informe" };
  const review = { ...row, candidate_id: "ACT-003", row_status: "NEEDS_REVIEW" as const };
  mockJiraReads([]);
  view({ draft: { ...draft, rows: [readyOne, readyTwo, review], validation_summary: { activities: 3, complete: 2, created: 0, needs_review: 1, technical_errors: 0 } } });
  const checks = ["ACT-001", "ACT-002", "ACT-003"].map(id => screen.getByRole("checkbox", { name: `Seleccionar ${id} para preparar` }));
  await waitFor(() => expect(checks[0]).toBeEnabled(), { timeout: 2000 });
  await waitFor(() => expect(checks[1]).toBeEnabled(), { timeout: 2000 });
  expect(checks[0]).toBeEnabled();
  expect(checks[1]).toBeEnabled();
  expect(checks[2]).toBeDisabled();
  await userEvent.click(checks[0]);
  await userEvent.click(checks[1]);
  await waitFor(() => expect(screen.getByRole("button", { name: "Preparar seleccionadas (2)" })).toBeEnabled(), { timeout: 2000 });
});
