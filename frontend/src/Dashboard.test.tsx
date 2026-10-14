import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Dashboard } from "./Dashboard";
import type { DashboardSpace, DashboardSpaceSummary, DashboardStatus, DashboardSummary } from "./dashboardTypes";

vi.mock("./api", () => ({
  ApiError: class ApiError extends Error { constructor(message: string, readonly status: number) { super(message); } },
  getDashboardIssues: vi.fn(), getDashboardSpace: vi.fn(), getDashboardStatus: vi.fn(),
  getDashboardSummary: vi.fn(), refreshDashboard: vi.fn(),
}));
import { getDashboardIssues, getDashboardSpace, getDashboardStatus, getDashboardSummary, refreshDashboard } from "./api";

const keys = ["ASIT", "AT", "BD", "MTTI", "OPC"] as const;
function makeSpace(key: string, total: number): DashboardSpaceSummary {
  return {
    key, name: `Space ${key}`, id: key, access: "YES", total, todo: 1, in_progress: 1,
    done: Math.max(0, total - 2), unassigned: 1, active: 2, overdue: key === "BD" ? 2 : 0,
    due_next_7d: 0, has_due_date: 1, no_due_date: Math.max(0, total - 1), created_7d: 1,
    updated_7d: 1, updated_30d: key === "BD" ? 0 : 1, recent_activity: key !== "BD",
    completed_7d: { value: null, known_count: 0, missing_resolutiondate: 1, state: "PARTIAL" },
    last_issue_updated: null, freshness: key === "BD" ? "Sin actividad reciente" : null,
    unknown_status_category: 0, active_assignees: 1,
    statuses: [{ id: "1", name: "En progreso", category: "indeterminate", count: 1 },
      { id: "2", name: "To Do", category: "new", count: 1 }],
    work_types: [{ id: `${key}-10`, name: "Task", subtask: false, hierarchy_level: 0, count: total, percent: 100 }],
    priorities: [{ id: "3", name: "Medium", count: total }],
    workload: [{ display_name: "Jose", active: 2, todo: 1, in_progress: 1, overdue: 1 }],
    sprint: { supported: true, state: "ACTUALIZADO", active: [{ id: "646", name: "Sprint actual", state: "active", end_date: "2026-07-18T01:00:00Z" }], future: [], issues_in_active: 2, note: "Sprints con issues visibles." },
    epics: { supported: true, state: "ACTUALIZADO", items: [{ key: `${key}-20`, summary: "Epic de prueba", total_children: 2, done: 1, in_progress: 1, todo: 0, progress_percent: 50, state: "ACTUALIZADO" }], children_visible: 2, parent_relationship_confidence: "ACTUALIZADO" },
    tracking: { available: true, state: "ACTUALIZADO", name: "Tipo de seguimiento", available_types: [`${key}-10`], options: [{ id: "11", name: "Soporte", count: 2 }], populated: 2, empty: 0, context_note: "Metadatos reales." },
  };
}
function makeSummary(): DashboardSummary {
  const spaces = keys.map((key, index) => makeSpace(key, index + 2));
  const total = spaces.reduce((sum, space) => sum + space.total, 0);
  return {
    created_at: "2026-09-18T06:00:00Z", duration_ms: 45480,
    performance: { issues_read: total, pages: 13, jira_reads: 44, mcp_calls: 46, errors: 0, timeouts: 0, rate_limits: 0, cache_hits: 0 },
    spaces,
    global: {
      total, todo: 5, in_progress: 5, done: total - 10, unassigned: 5, active: 10,
      overdue: 2, due_next_7d: 0, has_due_date: 5, no_due_date: total - 5,
      created_7d: 5, updated_7d: 4, updated_30d: 4, recent_activity: true,
      completed_7d: { value: null, known_count: 0, missing_resolutiondate: 3, state: "PARTIAL" },
      work_types: [{ name: "Task", count: total, spaces: [...keys], space_types: keys.map((space) => ({ space, id: `${space}-10`, count: total / 5 })) }],
      priorities: [{ id: "3", name: "Medium", count: total }],
      statuses: [{ name: "To Do", category: "new", id: "1", count: 5 }],
      workload: [{ display_name: "Jose", active: 5, todo: 3, in_progress: 2, overdue: 2 }],
    },
  };
}
function makeStatus(state: DashboardStatus["state"] = "ACTUALIZADO", hasSnapshot = true): DashboardStatus {
  return { state, has_snapshot: hasSnapshot, last_updated: hasSnapshot ? "2026-09-18T06:00:00Z" : null,
    last_duration_ms: hasSnapshot ? 45480 : null, issues_read: hasSnapshot ? 1146 : null,
    jira_reads: hasSnapshot ? 44 : null, mcp_calls: hasSnapshot ? 46 : null, errors: 0, timeouts: 0,
    rate_limits: 0, cache_hits: 0, refresh_started_at: state === "ACTUALIZANDO" ? "2026-09-18T07:00:00Z" : null,
    error: state === "PARTIAL" ? "No se pudo leer OPC" : null,
    failed_spaces: state === "PARTIAL" ? [{ key: "OPC", state: "NO_PERMISSION", message: "No autorizado" }] : [],
    jira_write_enabled: false, write_lock: "LOCKED" };
}

describe("Dashboard Jira", () => {
  beforeEach(() => {
    vi.mocked(getDashboardStatus).mockResolvedValue(makeStatus());
    vi.mocked(getDashboardSummary).mockResolvedValue(makeSummary());
    vi.mocked(getDashboardSpace).mockImplementation(async (_token, key) => ({
      summary: makeSpace(key, 10), work_types: makeSpace(key, 10).work_types,
    } satisfies DashboardSpace));
    vi.mocked(getDashboardIssues).mockResolvedValue({ total: 1, page: 1, page_size: 50,
      snapshot_at: "2026-09-18T06:00:00Z", issues: [{ key: "BD-1", space: "BD", summary: "Issue filtrado",
        status: { id: "1", name: "To Do", category: "new" }, assignee: null,
        priority: { id: "3", name: "Medium" }, duedate: "2026-09-01", issuetype: { id: "10", name: "Task" } }] });
    vi.mocked(refreshDashboard).mockResolvedValue(makeStatus("ACTUALIZANDO"));
  });
  afterEach(() => { cleanup(); vi.clearAllMocks(); });

  it("presenta General y las cinco pestañas, y hace drill-down local a una tabla con enlace Jira", async () => {
    const user = userEvent.setup();
    render(<Dashboard token="session" />);
    expect(await screen.findByRole("heading", { name: "Dashboard de equipos" })).toBeInTheDocument();
    expect(screen.getAllByText(/Jira · Solo lectura/).length).toBeGreaterThan(0);
    expect(screen.getByText(/Escrituras bloqueadas/)).toBeInTheDocument();
    expect(screen.getByText("Total actividades")).toBeInTheDocument();
    for (const name of ["General", ...keys]) expect(screen.getByRole("tab", { name })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Vencidas: 2" }));
    expect(await screen.findByRole("heading", { name: "Issues filtrados" })).toBeInTheDocument();
    expect(await screen.findByRole("link", { name: /BD-1/ })).toHaveAttribute("href", "https://dpti.atlassian.net/browse/BD-1");
    expect(vi.mocked(getDashboardIssues).mock.calls.at(-1)?.[1].toString()).toContain("overdue=true");
    await user.click(screen.getByRole("tab", { name: "BD" }));
    expect(await screen.findByText("Sin actividad reciente")).toBeInTheDocument();
    expect(await screen.findByText("Jira lo reporta activo, pero su fecha de fin ya pasó.")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Tipo de seguimiento" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /BD-20 · Epic de prueba/ }));
    await waitFor(() => expect(getDashboardIssues).toHaveBeenCalled());
    expect(vi.mocked(getDashboardIssues).mock.calls.at(-1)?.[1].toString()).toContain("epic=BD-20");
  });

  it("conserva las gráficas durante un refresh y muestra estado parcial", async () => {
    const user = userEvent.setup();
    vi.mocked(getDashboardStatus).mockResolvedValue(makeStatus("PARTIAL"));
    render(<Dashboard token="session" />);
    expect(await screen.findByText("Lectura parcial. Se conserva el último snapshot completo.")).toBeInTheDocument();
    expect(screen.getByText("Total actividades")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Actualizar datos de Jira" }));
    expect(await screen.findByRole("status")).toHaveTextContent("Actualizando datos de Jira");
    expect(screen.getByText("Total actividades")).toBeInTheDocument();
    expect(refreshDashboard).toHaveBeenCalledWith("session");
  });

  it("muestra estado vacío, no consulta Jira hasta pulsar actualizar y explica la demora", async () => {
    const user = userEvent.setup();
    vi.mocked(getDashboardStatus).mockResolvedValue(makeStatus("NO_DATA", false));
    render(<Dashboard token="session" />);
    expect(await screen.findByRole("heading", { name: "Aún no hay snapshot" })).toBeInTheDocument();
    expect(screen.getByText(/alrededor de 45 segundos/)).toBeInTheDocument();
    expect(refreshDashboard).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Cargar datos reales de Jira" }));
    expect(refreshDashboard).toHaveBeenCalledOnce();
  });

  it("no afirma que Jira está conectada ni que el bloqueo fue validado si la API aún no responde", async () => {
    vi.mocked(getDashboardStatus).mockRejectedValue(new SyntaxError("Unexpected token '<'"));
    render(<Dashboard token="session" />);
    expect(await screen.findByText(/El backend local todavía no reconoce las rutas del Dashboard/)).toBeInTheDocument();
    expect(screen.getByText(/Bloqueo sin validar/)).toBeInTheDocument();
    expect(screen.queryByText(/Escrituras bloqueadas/)).not.toBeInTheDocument();
  });

  it("aplica cross-filtering local acumulativo sin consultar Jira al cambiar visuales", async () => {
    const user = userEvent.setup();
    const summary = makeSummary();
    summary.issues = [
      { key: "AT-1", space: "AT", summary: "Planificar", status: { id: "1", name: "To Do", category: "new" }, assignee: { displayName: "Jose" }, priority: { id: "2", name: "High" }, duedate: null, issuetype: { id: "10", name: "Task" } },
      { key: "AT-2", space: "AT", summary: "Construir", status: { id: "2", name: "In Progress", category: "indeterminate" }, assignee: { displayName: "Jose" }, priority: { id: "2", name: "High" }, duedate: null, issuetype: { id: "10", name: "Task" } },
      { key: "AT-3", space: "AT", summary: "Cerrar", status: { id: "3", name: "Done", category: "done" }, assignee: null, priority: { id: "3", name: "Medium" }, duedate: null, issuetype: { id: "11", name: "Bug" } },
      { key: "MTTI-1", space: "MTTI", summary: "Revisar", status: { id: "2", name: "In Progress", category: "indeterminate" }, assignee: { displayName: "Ana" }, priority: { id: "3", name: "Medium" }, duedate: null, issuetype: { id: "10", name: "Task" } },
    ];
    vi.mocked(getDashboardSummary).mockResolvedValue(summary);
    render(<Dashboard token="session" />);
    await screen.findByRole("button", { name: "Total actividades: 4" });
    await user.click(screen.getByRole("button", { name: "AT3" }));
    expect(await screen.findByRole("heading", { name: "Issues filtrados" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "AT-1" })).toBeInTheDocument();
    await user.click(screen.getAllByRole("button", { name: "En progreso: 1" })[0]);
    expect(screen.getByRole("link", { name: "AT-2" })).toBeInTheDocument();
    await user.click(screen.getAllByRole("button", { name: "Limpiar filtros" })[0]);
    expect(screen.getByRole("button", { name: "Total actividades: 4" })).toBeInTheDocument();
    expect(getDashboardIssues).not.toHaveBeenCalled();
  });

  it("conserva los filtros analíticos al cambiar de pestaña y permite quitar un chip", async () => {
    const user = userEvent.setup();
    const summary = makeSummary();
    summary.issues = [
      { key: "AT-1", space: "AT", summary: "Alta", status: { id: "2", name: "In Progress", category: "indeterminate" }, assignee: { displayName: "Jose" }, priority: { id: "2", name: "High" }, duedate: null, issuetype: { id: "10", name: "Task" } },
      { key: "MTTI-1", space: "MTTI", summary: "Otra", status: { id: "2", name: "In Progress", category: "indeterminate" }, assignee: { displayName: "Jose" }, priority: { id: "2", name: "High" }, duedate: null, issuetype: { id: "10", name: "Task" } },
    ];
    vi.mocked(getDashboardSummary).mockResolvedValue(summary);
    render(<Dashboard token="session" />);
    await screen.findByRole("button", { name: "Total actividades: 2" });
    await user.click(screen.getAllByRole("button", { name: "En progreso: 2" })[0]);
    await user.click(screen.getByRole("tab", { name: "MTTI" }));
    expect(screen.getByRole("button", { name: "Quitar filtro En progreso" })).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "En progreso: 1" })[0]).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Quitar filtro En progreso" }));
    expect(screen.getByRole("button", { name: "Total actividades: 1" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Quitar filtro En progreso" })).not.toBeInTheDocument();
  });
});
