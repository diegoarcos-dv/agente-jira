import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import { Objective4C1Panel } from "./App";
import type { JiraDryRun, Objective4C1Batch, Proposal } from "./types";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

it("crea un lote 4C.1 sólo después de selección y confirmación explícitas", async () => {
  const proposal = { proposal_id: "batch-1", version: 8, status: "APPROVED" } as unknown as Proposal;
  const dryRun = {
    dry_run_id: "DRY-batch", proposal_id: "batch-1", proposal_version: 8,
    items: [1, 2, 3].map((number) => ({
      row_id: `ROW-000${number}`, status: "READY", title: `Actividad ${number}`,
      space: "AT", work_type: "Task", errors: [], warnings: [],
      assignee: { display_name: `Persona ${number}`, account_id: `jira-${number}`, email: null, validation: "JIRA_ACCOUNT_MATCH" },
      logical_payload: { summary: `Actividad ${number}` }, idempotency_key: `AJI-${number}`,
    })),
  } as unknown as JiraDryRun;
  const items = dryRun.items.slice(0, 2).map((item, index) => ({
    position: index + 1, row_id: item.row_id, idempotency_key: item.idempotency_key!,
    status: "PENDING" as const, payload_hash: String(index + 1).repeat(64),
    preview: { title: `AgenteTest_${index}`, source_title: item.title, space: "AT" as const, work_type: "Task" as const, assignee: item.assignee },
    issue_key: null, issue_url: null, result: null, error: null, real_mcp_calls: 0, automatic_retries: 0 as const, readback: null,
  }));
  const prepared: Objective4C1Batch = {
    objective: "4C.1", mode: "CONTROLLED_TASK_BATCH", execution_id: "BAT-1", status: "BATCH_PREPARED",
    proposal_id: "batch-1", proposal_version: 8, dry_run_id: "DRY-batch", payload_hash: "a".repeat(64),
    confirmation_phrase: "CREAR 2 TASKS EN AT",
    confirmation: { required: true, expires_at: "2026-07-20T19:00:00Z", confirmed_at: null, confirmed_by: null },
    items, summary: { total: 2, created_verified: 0 }, real_mcp_calls: 0, automatic_retries: 0,
  };
  const confirmed: Objective4C1Batch = { ...prepared, status: "BATCH_CONFIRMED", confirmation: { ...prepared.confirmation, confirmed_at: "2026-07-20T18:01:00Z", confirmed_by: "tester" } };
  const completed: Objective4C1Batch = {
    ...confirmed, status: "COMPLETED", summary: { total: 2, created_verified: 2 }, real_mcp_calls: 4,
    items: confirmed.items.map((item, index) => ({ ...item, status: "CREATED_VERIFIED", issue_key: `AT-${510 + index}`, issue_url: `https://dpti.atlassian.net/browse/AT-${510 + index}`, real_mcp_calls: 2 })),
  };
  let progressCalls = 0;
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, options?: RequestInit) => {
    const url = input.toString();
    if (url.endsWith("/objective-4c1/latest")) return { ok: false, status: 404, json: async () => ({ detail: "Sin lote" }) } as Response;
    if (url.endsWith("/objective-4c2/progress")) {
      progressCalls += 1;
      const afterFirstBatch = progressCalls > 1;
      return { ok: true, json: async () => ({
      objective: "4C.2", mode: "SUCCESSIVE_CONTROLLED_BATCHES", proposal_id: "batch-1", proposal_version: 8,
      dry_run_id: "DRY-batch", max_items_per_batch: 5,
      available_row_ids: afterFirstBatch ? [dryRun.items[2].row_id] : dryRun.items.slice(0, 2).map((item) => item.row_id),
      counts: { eligible: 3, available: afterFirstBatch ? 1 : 2, reserved: 0, created_verified: afterFirstBatch ? 2 : 0, created_unverified: 0, rejected: 0, unknown: 0 },
      batch_count: afterFirstBatch ? 1 : 0, real_mcp_calls: afterFirstBatch ? 4 : 0, automatic_retries: 0,
    }) } as Response;
    }
    if (url.endsWith("/objective-4c1/prepare")) return { ok: true, json: async () => prepared } as Response;
    if (url.endsWith("/confirm") && options?.method === "POST") return { ok: true, json: async () => confirmed } as Response;
    if (url.endsWith("/execute") && options?.method === "POST") return { ok: true, json: async () => completed } as Response;
    return { ok: false, status: 404, json: async () => ({ detail: "Ruta inesperada" }) } as Response;
  }));

  render(<Objective4C1Panel token="token" proposal={proposal} dryRun={dryRun} onNewProposal={() => undefined} />);
  expect(await screen.findByRole("heading", { name: "Crear un lote controlado de Tasks" })).toBeInTheDocument();
  expect(await screen.findByLabelText("Avance del plan")).toHaveTextContent("2 pendientes");
  await userEvent.click(screen.getByRole("button", { name: "Preparar lote de 2 Tasks" }));
  expect(await screen.findByText("Se crearán 2 Tasks reales en AT, en este orden")).toBeInTheDocument();
  await userEvent.type(screen.getByLabelText("Frase de confirmación del lote"), "CREAR 2 TASKS EN AT");
  await userEvent.click(screen.getByRole("button", { name: "Confirmar lote real" }));
  await userEvent.click(await screen.findByRole("button", { name: "Crear 2 Tasks reales en AT" }));
  expect(await screen.findByText("Éxito: 2 Tasks creadas y verificadas")).toBeInTheDocument();
  expect(screen.getByText("4 llamadas MCP · 0 reintentos")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Preparar siguiente lote" }));
  expect(screen.getByRole("button", { name: "Preparar lote de 1 Task" })).toBeInTheDocument();
});

it("prepara un lote 4D mixto con Task, Bug y Story", async () => {
  const proposal = { proposal_id: "mixed-1", version: 9, status: "APPROVED" } as unknown as Proposal;
  const workTypes = ["Task", "Bug", "Story"] as const;
  const dryRun = {
    dry_run_id: "DRY-mixed", proposal_id: "mixed-1", proposal_version: 9,
    items: workTypes.map((workType, index) => ({
      row_id: `ROW-00${index + 1}`, status: "READY", title: `${workType} de prueba`,
      space: "AT", work_type: workType, errors: [], warnings: [],
      assignee: { display_name: `Persona ${index + 1}`, account_id: `jira-${index + 1}`, email: null, validation: "JIRA_ACCOUNT_MATCH" },
      logical_payload: { summary: `${workType} de prueba` }, idempotency_key: `AJI-M-${index + 1}`,
    })),
  } as unknown as JiraDryRun;
  const prepared = {
    objective: "4D", mode: "CONTROLLED_WORK_ITEM_BATCH", execution_id: "BAT-MIXED", status: "BATCH_PREPARED",
    proposal_id: "mixed-1", proposal_version: 9, dry_run_id: "DRY-mixed", payload_hash: "d".repeat(64),
    confirmation_phrase: "CREAR 3 ACTIVIDADES EN AT",
    confirmation: { required: true, expires_at: "2026-07-20T20:00:00Z", confirmed_at: null, confirmed_by: null },
    items: dryRun.items.map((item, index) => ({
      position: index + 1, row_id: item.row_id, idempotency_key: item.idempotency_key!, status: "PENDING",
      payload_hash: String(index + 3).repeat(64),
      preview: { title: `AgenteTest_${item.work_type}_${index}`, source_title: item.title, space: "AT", work_type: item.work_type, assignee: item.assignee },
      issue_key: null, issue_url: null, result: null, error: null, real_mcp_calls: 0, automatic_retries: 0, readback: null,
    })),
    summary: { total: 3, created_verified: 0 }, real_mcp_calls: 0, automatic_retries: 0,
  } as unknown as Objective4C1Batch;
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const url = input.toString();
    if (url.endsWith("/objective-4c1/latest")) return { ok: false, status: 404, json: async () => ({ detail: "Sin lote" }) } as Response;
    if (url.endsWith("/objective-4c2/progress")) return { ok: true, json: async () => ({
      objective: "4D", mode: "SUCCESSIVE_MULTI_TYPE_BATCHES", proposal_id: "mixed-1", proposal_version: 9,
      dry_run_id: "DRY-mixed", max_items_per_batch: 5, available_row_ids: dryRun.items.map((item) => item.row_id),
      counts: { eligible: 3, available: 3, reserved: 0, created_verified: 0, created_unverified: 0, rejected: 0, unknown: 0 },
      batch_count: 0, real_mcp_calls: 0, automatic_retries: 0,
    }) } as Response;
    if (url.endsWith("/objective-4c1/prepare")) return { ok: true, json: async () => prepared } as Response;
    return { ok: false, status: 404, json: async () => ({ detail: "Ruta inesperada" }) } as Response;
  }));

  render(<Objective4C1Panel token="token" proposal={proposal} dryRun={dryRun} onNewProposal={() => undefined} allowedWorkTypes={["Task", "Bug", "Story"]} />);
  await userEvent.click(await screen.findByRole("button", { name: "Preparar lote de 3 actividades" }));
  expect(await screen.findByText("Se crearán 3 actividades reales en AT, en este orden")).toBeInTheDocument();
  expect(screen.getByText("CREAR 3 ACTIVIDADES EN AT")).toBeInTheDocument();
  expect(screen.getByText(/Bug · Persona 2/)).toBeInTheDocument();
  expect(screen.getByText(/Story · Persona 3/)).toBeInTheDocument();
});

it("mantiene juntas las dependencias 4E y muestra el orden padre-hijo antes de confirmar", async () => {
  const proposal = { proposal_id: "hierarchy-1", version: 10, status: "APPROVED" } as unknown as Proposal;
  const definitions = [
    ["ROW-0006", "Epic", "Epic principal", null],
    ["ROW-0007", "Story", "Story hija", "ROW-0006"],
    ["ROW-0008", "Task", "Task principal", null],
    ["ROW-0009", "Subtask", "Subtask hija", "ROW-0008"],
  ] as const;
  const dryRun = {
    dry_run_id: "DRY-hierarchy", proposal_id: "hierarchy-1", proposal_version: 10,
    items: definitions.map(([rowId, workType, title, parentRowId], index) => ({
      row_id: rowId, status: "READY", title, space: "AT", work_type: workType,
      parent_row_id: parentRowId, errors: [], warnings: [],
      assignee: { display_name: `Persona ${index + 1}`, account_id: `jira-${index + 1}`, email: null, validation: "JIRA_ACCOUNT_MATCH" },
      logical_payload: { summary: title, parent_row_id: parentRowId }, idempotency_key: `AJI-H-${index + 1}`,
    })),
  } as unknown as JiraDryRun;
  const prepared = {
    objective: "4E", mode: "CONTROLLED_HIERARCHY_BATCH", execution_id: "BAT-H", status: "BATCH_PREPARED",
    proposal_id: "hierarchy-1", proposal_version: 10, dry_run_id: "DRY-hierarchy", payload_hash: "e".repeat(64),
    confirmation_phrase: "CREAR 4 ACTIVIDADES EN AT",
    confirmation: { required: true, expires_at: "2026-07-21T20:00:00Z", confirmed_at: null, confirmed_by: null },
    items: definitions.map(([rowId, workType, title, parentRowId], index) => ({
      position: index + 1, row_id: rowId, idempotency_key: `AJI-H-${index + 1}`, status: "PENDING",
      payload_hash: String(index + 5).repeat(64),
      preview: {
        title: `AgenteTest_${workType}_${index}`, source_title: title, space: "AT", work_type: workType,
        parent_row_id: parentRowId, parent_issue_key: null,
        assignee: dryRun.items[index].assignee,
      },
      parent_reference: parentRowId ? { row_id: parentRowId, issue_key: null } : null,
      resolved_parent: null, issue_key: null, issue_url: null, result: null, error: null,
      real_mcp_calls: 0, automatic_retries: 0, readback: null,
    })),
    summary: { total: 4, created_verified: 0 }, real_mcp_calls: 0, automatic_retries: 0,
  } as unknown as Objective4C1Batch;
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const url = input.toString();
    if (url.endsWith("/objective-4c1/latest")) return { ok: false, status: 404, json: async () => ({ detail: "Sin lote" }) } as Response;
    if (url.endsWith("/objective-4c2/progress")) return { ok: true, json: async () => ({
      objective: "4E", mode: "SUCCESSIVE_HIERARCHY_BATCHES", proposal_id: "hierarchy-1", proposal_version: 10,
      dry_run_id: "DRY-hierarchy", max_items_per_batch: 5, available_row_ids: definitions.map(([rowId]) => rowId),
      counts: { eligible: 4, available: 4, reserved: 0, created_verified: 0, created_unverified: 0, rejected: 0, unknown: 0 },
      batch_count: 0, real_mcp_calls: 0, automatic_retries: 0,
    }) } as Response;
    if (url.endsWith("/objective-4c1/prepare")) return { ok: true, json: async () => prepared } as Response;
    return { ok: false, status: 404, json: async () => ({ detail: "Ruta inesperada" }) } as Response;
  }));

  render(<Objective4C1Panel
    token="token" proposal={proposal} dryRun={dryRun} onNewProposal={() => undefined}
    allowedWorkTypes={["Task", "Bug", "Story", "Epic", "Subtask"]}
  />);
  expect(await screen.findByRole("heading", { name: "Crear actividades y sus relaciones" })).toBeInTheDocument();
  const epic = screen.getByRole("checkbox", { name: /Epic principal/ });
  const story = screen.getByRole("checkbox", { name: /Story hija/ });
  await userEvent.click(epic);
  expect(epic).not.toBeChecked();
  expect(story).not.toBeChecked();
  await userEvent.click(story);
  expect(epic).toBeChecked();
  expect(story).toBeChecked();
  await userEvent.click(screen.getByRole("button", { name: "Preparar lote de 4 actividades" }));
  expect(await screen.findByText("Se crearán 4 actividades reales en AT, en este orden")).toBeInTheDocument();
  expect(screen.getByText("CREAR 4 ACTIVIDADES EN AT")).toBeInTheDocument();
  expect(screen.getByText(/Story · Persona 2 · Padre ROW-0006/)).toBeInTheDocument();
  expect(screen.getByText(/Subtask · Persona 4 · Padre ROW-0008/)).toBeInTheDocument();
});
