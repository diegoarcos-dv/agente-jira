import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App, { AtlassianConnectionPanel, ProposalHistory, ProposalReview, Workspace } from "./App";
import type { Objective4AIntent, Proposal, ProposalSummary } from "./types";

describe("App", () => {
  beforeEach(() => {
    sessionStorage.clear();
    localStorage.clear();
  });
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("muestra el acceso local antes de iniciar sesión", () => {
    render(<App />);
    expect(screen.getByRole("heading", { name: "Inicia sesión" })).toBeInTheDocument();
    expect(
      screen.getByText("Desarrollo local · autorización Atlassian cifrada para el usuario de Windows"),
    ).toBeInTheDocument();
    expect(screen.getByText(/recuperación de contraseña se habilitará con Cognito/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Mostrar contraseña" })).toBeInTheDocument();
  });

  it("muestra el diagnóstico Jira real sin habilitar escritura", async () => {
    const status = {
      connected: true,
      phase: "CONNECTED",
      oauth_storage: "MEMORY_ONLY",
      jira_write_enabled: false,
      write_tools_blocked: true,
      error: null,
      snapshot: {
        verified_at: "2026-07-17T12:00:00Z",
        site_url: "https://dpti.atlassian.net",
        site_name: "DPTI",
        cloud_id: "cloud-123",
        atlassian_user: { account_id: "account-1", display_name: "Usuario Jira", email: null },
        spaces: ["AT", "ASIT", "MTTI"].map((key) => ({
          key,
          found: true,
          id: `${key}-id`,
          name: key,
          project_type: "software",
          work_types: [{
            id: "10",
            name: "Task",
            subtask: false,
            fields: [{ id: "summary", name: "Summary", required: true }],
          }],
        })),
        read_tools_available: ["getVisibleJiraProjects"],
        write_tools_exposed_by_server: 7,
      },
    };
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = input.toString();
      const payload = url.includes("q=Victor")
        ? []
        : url.includes("q=Jose+Calleja")
          ? [
              { account_id: "jira-jose", display_name: "José Calleja", email: null, active: true },
              { account_id: "jira-gil", display_name: "Jose Gil Navarrete M", email: null, active: true },
            ]
          : url.includes("/assignees?")
            ? [{ account_id: "jira-1", display_name: "Giselle Bello", email: "giselle@example.com", active: true }]
            : status;
      return { ok: true, json: async () => payload } as Response;
    }));

    render(<AtlassianConnectionPanel token="local-token" />);

    expect(await screen.findByText("https://dpti.atlassian.net")).toBeInTheDocument();
    expect(screen.getByText("cloud-123")).toBeInTheDocument();
    expect(screen.getByText("Conectado · solo lectura")).toBeInTheDocument();
    expect(screen.getByText(/7 herramientas no permitidas/)).toBeInTheDocument();

    await userEvent.type(screen.getByLabelText("Nombre o correo del responsable"), "Giselle");
    await userEvent.click(screen.getByRole("button", { name: "Buscar" }));
    expect(await screen.findByText("Giselle Bello")).toBeInTheDocument();

    const lookup = screen.getByLabelText("Nombre o correo del responsable");
    await userEvent.clear(lookup);
    await userEvent.type(lookup, "Jose Calleja");
    await userEvent.click(screen.getByRole("button", { name: "Buscar" }));
    expect(await screen.findByText("José Calleja")).toBeInTheDocument();
    expect(screen.queryByText("Jose Gil Navarrete M")).not.toBeInTheDocument();

    await userEvent.clear(lookup);
    await userEvent.type(lookup, "Victor");
    await userEvent.click(screen.getByRole("button", { name: "Buscar" }));
    expect(await screen.findByText("No encontramos una cuenta Jira")).toBeInTheDocument();
    expect(screen.getByText(/No hubo coincidencias activas para “Victor”/i)).toBeInTheDocument();
  });

  it("separa revisión, listas y excluidas conservando el origen", async () => {
    const proposal: Proposal = {
      proposal_id: "11111111-1111-4111-8111-111111111111",
      version: 1,
      template_version: "1.1",
      status: "NEEDS_INPUT",
      source_file: { name: "plan.xlsx", sha256: "a".repeat(64) },
      defaults: {
        space: "AT",
        iniciativa: null,
        linea_trabajo: null,
        sprint: null,
        tipo_seguimiento: null,
        semaforo: null,
      },
      created_at: "2026-07-16T12:00:00Z",
      created_by: "tester",
      approved_at: null,
      approved_by: null,
      items: ([
        ["INCLUIR", "Actividad lista", "Giselle Bello"],
        ["REVISAR", "Actividad ambigua", "Wilfrido / José"],
        ["EXCLUIR", "Actividad completada", "Raúl Gallardo"],
      ] as const).map(([decision, activity, assignee], index) => ({
        source: {
          source_row: index + 6,
          actividad: activity,
          responsable_display: assignee,
          frente_trabajo_origen: "Piloto",
          contexto_resultado: null,
          fecha_objetivo: null,
          estado_actual: decision === "EXCLUIR" ? "Completada" : "Pendiente",
          comentarios: null,
        },
        generated: {
          row_id: `ROW-${String(index + 6).padStart(4, "0")}`,
          create_in_jira: decision === "INCLUIR",
          decision,
          decision_reason: `Motivo ${decision}`,
          work_type: "Task",
          title: activity,
          description: `Actividad: ${activity}`,
          space: "AT",
          parent_row_id: null,
          assignee: {
            display_name: assignee,
            email: decision === "REVISAR" ? null : "persona@example.com",
            account_id: decision === "REVISAR" ? null : `account-${index}`,
            resolution: decision === "REVISAR" ? "NOT_FOUND" : "RESOLVED",
          },
          fields: {},
          confidence: 0.88,
        },
        validation: { errors: [], warnings: [] },
        review: { user_modified: false, approved: false, review_note: null },
        execution: { result: "NOT_STARTED" },
      })),
    };
    proposal.items[0].source.responsable_display = "Ra\u00fal Gallardo";

    const updatedProposal: Proposal = {
      ...proposal,
      version: 2,
      defaults: { ...proposal.defaults, tipo_seguimiento: "Semanal" },
      items: proposal.items.map((item) => ({
        ...item,
        generated: {
          ...item.generated,
          fields: { ...item.generated.fields, tipo_seguimiento: "Semanal" },
        },
      })),
    };
    const fetchMock = vi.fn(async (input: RequestInfo | URL, options?: RequestInit) => {
      const url = input.toString();
      if (url.endsWith("/dry-run/latest")) {
        return { ok: false, status: 404, json: async () => ({ detail: "Sin validaci\u00f3n" }) } as Response;
      }
      if (url.endsWith("/api/integrations/atlassian/status")) {
        return {
          ok: true,
          json: async () => ({
            connected: true,
            phase: "CONNECTED",
            snapshot: {
              spaces: [{
                key: "AT",
                found: true,
                id: "100",
                name: "AT",
                project_type: "software",
                work_types: [{
                  id: "10",
                  name: "Task",
                  subtask: false,
                  fields: [{
                    id: "customfield_10483",
                    name: "Tipo de seguimiento",
                    required: false,
                    business_key: "tipo_seguimiento",
                    options: [
                      { value: "Semanal", label: "Semanal" },
                      { value: "Mensual", label: "Mensual" },
                    ],
                  }],
                }],
              }],
            },
          }),
        } as Response;
      }
      if (url.includes("/api/integrations/atlassian/sprints?")) {
        return {
          ok: true,
          json: async () => [
            { id: "321", name: "SPT-ACTIVO", state: "active", board_id: "45", source: "ROVO_MCP_JQL" },
            { id: "322", name: "SPT-FUTURO", state: "future", board_id: "45", source: "ROVO_MCP_JQL" },
          ],
        } as Response;
      }
      if (url.endsWith("/defaults") && options?.method === "PATCH") {
        return { ok: true, json: async () => updatedProposal } as Response;
      }
      return { ok: false, status: 404, json: async () => ({ detail: "Ruta inesperada" }) } as Response;
    });
    vi.stubGlobal("fetch", fetchMock);

    const onRename = vi.fn(async () => undefined);
    const onUpdated = vi.fn();
    render(
      <ProposalReview
        token="local-token"
        proposal={proposal}
        displayName="Plan piloto"
        onRename={onRename}
        onUpdated={onUpdated}
        onNewProposal={() => undefined}
      />,
    );

    await userEvent.click(screen.getByRole("button", { name: "Editar nombre" }));
    await userEvent.clear(screen.getByLabelText("Nombre de la propuesta"));
    await userEvent.type(screen.getByLabelText("Nombre de la propuesta"), "Plan AT julio");
    await userEvent.click(screen.getByRole("button", { name: "Guardar nombre" }));
    expect(onRename).toHaveBeenCalledWith("Plan AT julio");

    await userEvent.click(screen.getByRole("button", { name: "Editar valores" }));
    expect(await screen.findByRole("option", { name: "SPT-ACTIVO · Activo" })).toBeInTheDocument();
    expect(screen.getAllByText("2 opciones recuperadas de Jira").length).toBeGreaterThanOrEqual(2);
    await userEvent.selectOptions(screen.getByRole("combobox", { name: /Tipo de seguimiento/ }), "Semanal");
    await userEvent.click(screen.getByRole("button", { name: "Guardar como nueva versi\u00f3n" }));
    expect(onUpdated).toHaveBeenCalledWith(updatedProposal);
    const defaultsCall = fetchMock.mock.calls.find(([input]) => input.toString().endsWith("/defaults"));
    expect(JSON.parse(String(defaultsCall?.[1]?.body))).toMatchObject({ space: "AT", tipo_seguimiento: "Semanal" });

    expect(screen.getAllByText("Actividad ambigua")).toHaveLength(2);
    await userEvent.click(screen.getByRole("tab", { name: /Listas/ }));
    expect(screen.getAllByText("Actividad lista")).toHaveLength(2);
    expect(screen.queryByText("Actividad ambigua")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("row", { name: /Actividad lista/ }));
    expect(screen.getByLabelText("Buscar cuenta Jira para la actividad")).toHaveValue("Giselle Bello");
    expect(screen.getByText("Ra\u00fal Gallardo")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Cancelar" }));
    await userEvent.click(screen.getByRole("tab", { name: /Excluidas/ }));
    expect(screen.getAllByText("Actividad completada")).toHaveLength(2);
  });

  it("muestra pendientes accionables y revalida sin pedir una decisión manual", async () => {
    const proposal: Proposal = {
      proposal_id: "22222222-2222-4222-8222-222222222222",
      version: 1,
      template_version: "1.1",
      status: "NEEDS_INPUT",
      source_file: { name: "revision.xlsx", sha256: "b".repeat(64) },
      defaults: {
        space: "AT",
        iniciativa: null,
        linea_trabajo: null,
        sprint: null,
        tipo_seguimiento: null,
        semaforo: null,
      },
      created_at: "2026-07-16T12:00:00Z",
      created_by: "tester",
      approved_at: null,
      approved_by: null,
      items: [{
        source: {
          source_row: 6,
          actividad: "Definir reglas",
          responsable_display: "Wilfrido / José",
          frente_trabajo_origen: "Backend",
          contexto_resultado: null,
          fecha_objetivo: null,
          estado_actual: "Pendiente",
          comentarios: null,
        },
        generated: {
          row_id: "ROW-0006",
          create_in_jira: false,
          decision: "REVISAR",
          decision_reason: "Responsable pendiente.",
          work_type: "Task",
          title: "Definir reglas",
          description: "Actividad: Definir reglas",
          space: "AT",
          parent_row_id: null,
          assignee: {
            display_name: "Wilfrido / José",
            email: null,
            account_id: null,
            resolution: "NOT_FOUND",
          },
          fields: {},
          confidence: 0.88,
        },
        validation: {
          errors: [],
          warnings: [],
          pending_requirements: [{
            code: "ASSIGNEE_UNRESOLVED",
            field: "assignee_account_id",
            message: "Selecciona un responsable disponible en el catálogo.",
          }],
        },
        review: { user_modified: false, approved: false, review_note: null, confirmed_fields: [] },
        execution: { result: "NOT_STARTED" },
      }],
    };
    const updated: Proposal = {
      ...proposal,
      version: 2,
      status: "VALIDATED",
      items: [{
        ...proposal.items[0],
        generated: {
          ...proposal.items[0].generated,
          title: "Definir reglas ajustadas",
          create_in_jira: true,
          decision: "INCLUIR",
          decision_reason: "La fila cumple los campos mínimos y las reglas deterministas del MVP.",
          assignee: {
            display_name: "Wilfrido Hernández",
            email: "wilfrido@empresa.com",
            account_id: "jira-account-wilfrido",
            resolution: "RESOLVED",
          },
        },
        validation: { errors: [], warnings: [], pending_requirements: [] },
        review: { ...proposal.items[0].review, user_modified: true, review_note: "Cambio combinado" },
      }],
    };
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, options?: RequestInit) => {
      const path = input.toString();
      const payload = path.includes("/integrations/atlassian/assignees")
        ? [{
            display_name: "Wilfrido Hernández",
            email: "wilfrido@empresa.com",
            account_id: "jira-account-wilfrido",
            active: true,
          }]
        : updated;
      return { ok: true, json: async () => payload } as Response;
    }));
    const onUpdated = vi.fn();

    render(<ProposalReview token="local-token" proposal={proposal} displayName="Revisión" onRename={async () => undefined} onUpdated={onUpdated} onNewProposal={() => undefined} />);
    await userEvent.click(screen.getByRole("row", { name: /Definir reglas/ }));
    expect(screen.getByText("Pendientes por resolver")).toBeInTheDocument();
    expect(screen.queryByLabelText("Decisión")).not.toBeInTheDocument();
    expect(screen.getByText("Las opciones se consultan directamente en Jira. Busca el nombre completo o correo y selecciona la cuenta correcta.")).toBeInTheDocument();
    await userEvent.clear(screen.getByLabelText("Título"));
    await userEvent.type(screen.getByLabelText("Título"), "Definir reglas ajustadas");
    await userEvent.type(screen.getByLabelText("Nota de revisión"), "Cambio combinado");
    await userEvent.click(screen.getByRole("button", { name: "Buscar en Jira" }));
    expect(await screen.findByText("wilfrido@empresa.com")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Seleccionar responsable" }));

    expect(screen.getByRole("heading", { name: "Origen y propuesta" })).toBeInTheDocument();
    expect(screen.getByText("Cambio pendiente · se guardará junto con las demás ediciones")).toBeInTheDocument();
    expect(onUpdated).not.toHaveBeenCalled();
    expect(
      vi.mocked(fetch).mock.calls.some(([, options]) => options?.method === "PATCH"),
    ).toBe(false);

    await userEvent.click(screen.getByRole("button", { name: "Guardar y volver a validar" }));
    expect(onUpdated).toHaveBeenCalledWith(updated);
    const patchCall = vi.mocked(fetch).mock.calls.find(([, options]) => options?.method === "PATCH");
    expect(JSON.parse(String(patchCall?.[1]?.body))).toMatchObject({
      title: "Definir reglas ajustadas",
      review_note: "Cambio combinado",
      assignee_account_id: "jira-account-wilfrido",
      assignee_query: "Wilfrido / José",
    });
    expect(
      vi.mocked(fetch).mock.calls.some(([, options]) => options?.method === "PATCH"),
    ).toBe(true);
  });

  it("reactiva una actividad excluida y la devuelve a revisión con auditoría", async () => {
    const proposal: Proposal = {
      proposal_id: "33333333-3333-4333-8333-333333333333",
      version: 1,
      template_version: "1.1",
      status: "VALIDATED",
      source_file: { name: "cerradas.xlsx", sha256: "c".repeat(64) },
      defaults: { space: "AT", iniciativa: null, linea_trabajo: null, sprint: null, tipo_seguimiento: null, semaforo: null },
      created_at: "2026-07-16T12:00:00Z",
      created_by: "tester",
      approved_at: null,
      approved_by: null,
      items: [{
        source: { source_row: 6, actividad: "Actualizar catálogo", responsable_display: "Giselle Bello", frente_trabajo_origen: null, contexto_resultado: null, fecha_objetivo: null, estado_actual: "Completada", comentarios: null },
        generated: { row_id: "ROW-0006", create_in_jira: false, decision: "EXCLUIR", decision_reason: "La actividad está marcada como completada en el archivo fuente.", work_type: "Task", title: "Actualizar catálogo", description: "Actividad: Actualizar catálogo", space: "AT", parent_row_id: null, assignee: { display_name: "Giselle Bello", email: "giselle@example.com", account_id: "local-account-giselle", resolution: "RESOLVED" }, fields: {}, confidence: 0.88 },
        validation: { errors: [], warnings: [], pending_requirements: [] },
        review: { user_modified: false, approved: false, review_note: null, confirmed_fields: [] },
        execution: { result: "NOT_STARTED" },
      }],
    };
    const reactivated: Proposal = {
      ...proposal,
      version: 2,
      status: "NEEDS_INPUT",
      items: [{
        ...proposal.items[0],
        generated: { ...proposal.items[0].generated, decision: "REVISAR", decision_reason: "Pendientes por resolver: Revisa los campos y confirma la reactivación de la actividad." },
        validation: { errors: [], warnings: [], pending_requirements: [{ code: "REACTIVATION_REVIEW_REQUIRED", field: "confirm_reactivation", message: "Revisa los campos y confirma la reactivación de la actividad." }] },
        review: { ...proposal.items[0].review, source_state_override: "ACTIVE", source_state_override_reason: "Continúa vigente por decisión del comité", source_state_override_at: "2026-07-16T13:00:00Z", source_state_override_by: "tester", reactivation_reviewed: false },
      }],
    };
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => ({
      ok: true,
      json: async () => input.toString().includes("/api/assignees") ? [] : reactivated,
    }) as Response));
    const onUpdated = vi.fn();
    render(<ProposalReview token="token" proposal={proposal} displayName="Cerradas" onRename={async () => undefined} onUpdated={onUpdated} onNewProposal={() => undefined} />);
    await userEvent.click(screen.getByRole("tab", { name: /Excluidas/ }));
    await userEvent.click(screen.getByRole("row", { name: /Actualizar catálogo/ }));
    await userEvent.type(screen.getByLabelText("Motivo para recuperar la actividad"), "Continúa vigente por decisión del comité");
    await userEvent.click(screen.getByRole("button", { name: "Reactivar y revisar" }));
    expect(onUpdated).toHaveBeenCalledWith(reactivated);
    expect(await screen.findByText(/pasó a Requieren revisión/i)).toBeInTheDocument();
  });

  it("aprueba, bloquea y muestra las acciones de descarga y reapertura", async () => {
    const proposal: Proposal = {
      proposal_id: "44444444-4444-4444-8444-444444444444", version: 3, template_version: "1.1", status: "VALIDATED",
      source_file: { name: "listo.xlsx", sha256: "d".repeat(64) },
      defaults: { space: "AT", iniciativa: null, linea_trabajo: null, sprint: null, tipo_seguimiento: null, semaforo: null },
      created_at: "2026-07-16T12:00:00Z", created_by: "tester", approved_at: null, approved_by: null,
      items: [{
        source: { source_row: 6, actividad: "Publicar reglas", responsable_display: "Giselle Bello", frente_trabajo_origen: null, contexto_resultado: null, fecha_objetivo: null, estado_actual: "Pendiente", comentarios: null },
        generated: { row_id: "ROW-0006", create_in_jira: true, decision: "INCLUIR", decision_reason: "Lista", work_type: "Task", title: "Publicar reglas", description: "Actividad: Publicar reglas", space: "AT", parent_row_id: null, assignee: { display_name: "Giselle Bello", email: "giselle@example.com", account_id: "local-account-giselle", resolution: "RESOLVED" }, fields: {}, confidence: 0.88 },
        validation: { errors: [], warnings: [], pending_requirements: [] }, review: { user_modified: false, approved: false, review_note: null }, execution: { result: "NOT_STARTED" },
      }],
    };
    const approved = { ...proposal, version: 4, status: "APPROVED", approved_at: "2026-07-16T14:00:00Z", approved_by: "tester" };
    const approvalDryRun = {
      dry_run_id: "DRY-approval", proposal_id: approved.proposal_id, proposal_version: approved.version,
      proposal_hash: "e".repeat(64), generated_at: "2026-07-17T14:00:00Z", generated_by: "tester",
      jira_snapshot_verified_at: "2026-07-17T13:55:00Z", site_url: "https://dpti.atlassian.net",
      status: "READY_WITH_WARNINGS", summary: { ready: 0, ready_with_warnings: 1, blocked: 0, skipped: 0 },
      write_performed: false, reused: false, items: [],
    };
    vi.stubGlobal("fetch", vi.fn(async () => ({
      ok: true,
      json: async () => ({ proposal: approved, dry_run: approvalDryRun }),
    }) as Response));
    const onUpdated = vi.fn();
    render(<ProposalReview token="token" proposal={proposal} displayName="Plan listo" onRename={async () => undefined} onUpdated={onUpdated} onNewProposal={() => undefined} />);
    await userEvent.click(screen.getByRole("button", { name: "Revisar y aprobar propuesta final" }));
    expect(screen.getByRole("dialog", { name: "Aprobar Plan listo" })).toBeInTheDocument();
    await userEvent.click(screen.getByLabelText(/Revisé las actividades incluidas/i));
    await userEvent.click(screen.getByRole("button", { name: "Aprobar y ejecutar prevalidación final" }));
    expect(onUpdated).toHaveBeenCalledWith(approved);
    expect(await screen.findByText(/Validación con Jira completada para la versión 4/)).toBeInTheDocument();

    cleanup();
    const dryRun = {
      dry_run_id: "DRY-test",
      proposal_id: approved.proposal_id,
      proposal_version: approved.version,
      proposal_hash: "e".repeat(64),
      generated_at: "2026-07-17T14:00:00Z",
      generated_by: "tester",
      jira_snapshot_verified_at: "2026-07-17T13:55:00Z",
      site_url: "https://dpti.atlassian.net",
      status: "READY",
      summary: { ready: 1, blocked: 0, skipped: 0 },
      write_performed: false,
      reused: false,
      items: [{
        row_id: "ROW-0006", source_row: 6, status: "READY", title: "Publicar reglas",
        space: "AT", work_type: "Task", errors: [],
        warnings: [{ code: "ASSIGNABILITY_LIMITED_TO_ACCOUNT_LOOKUP", field: "assignee", message: "Cuenta Jira confirmada." }],
        target: { project_name: "AT", project_type: "software", jira_work_type: "Task", required_field_count: 3 },
        assignee: { display_name: "Giselle Bello", email: null, account_id: "jira-giselle", validation: "JIRA_ACCOUNT_MATCH" },
        logical_payload: { summary: "Publicar reglas" }, idempotency_key: "AJI-test",
      }],
    };
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, options?: RequestInit) => {
      if (input.toString().endsWith("/dry-run/latest")) {
        return { ok: false, status: 404, json: async () => ({ detail: "Sin Dry run" }) } as Response;
      }
      if (input.toString().endsWith("/dry-run") && options?.method === "POST") {
        return { ok: true, json: async () => dryRun } as Response;
      }
      return { ok: true, json: async () => approved } as Response;
    }));
    render(<ProposalReview token="token" proposal={approved} displayName="Plan listo" onRename={async () => undefined} onUpdated={() => undefined} onNewProposal={() => undefined} />);
    expect(screen.getByText("Versión aprobada; falta comprobarla contra Jira")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Ejecutar prevalidación final" }));
    expect((await screen.findAllByText("Prevalidación completada")).length).toBeGreaterThan(0);
    await userEvent.click(screen.getByText("Resultado de la validación con Jira"));
    expect(screen.getByText("✓ Cero escrituras Jira")).toBeInTheDocument();
    expect(screen.getByText("AJI-test")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Descargar evidencia JSON" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reabrir para editar" })).toBeInTheDocument();

    cleanup();
    const reopened: Proposal = {
      ...approved,
      version: 5,
      status: "VALIDATED",
      approved_at: null,
      approved_by: null,
    };
    const blockedHistorical = {
      ...dryRun,
      status: "BLOCKED",
      summary: { ready: 0, blocked: 1, skipped: 0 },
      reused: true,
      stale: true,
      correction_workflow: {
        active: true,
        summary: { pending_user: 1, technical: 0, corrected: 0 },
        items: [{
          row_id: "ROW-0006",
          category: "USER_ACTION",
          instruction: "Busca y selecciona una cuenta Jira real para esta actividad.",
          issues: [{ code: "ASSIGNEE_NOT_FOUND", field: "assignee", message: "No se encontró una cuenta Jira exacta." }],
        }],
      },
      items: [{
        ...dryRun.items[0],
        status: "BLOCKED",
        errors: [{ code: "ASSIGNEE_NOT_FOUND", field: "assignee", message: "No se encontró una cuenta Jira exacta." }],
        warnings: [],
        assignee: null,
        logical_payload: null,
        idempotency_key: null,
      }],
    };
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      if (input.toString().endsWith("/dry-run/latest")) {
        return { ok: true, json: async () => blockedHistorical } as Response;
      }
      if (input.toString().includes("/api/assignees")) {
        return { ok: true, json: async () => [] } as Response;
      }
      return { ok: true, json: async () => reopened } as Response;
    }));
    render(<ProposalReview token="token" proposal={reopened} displayName="Plan listo" onRename={async () => undefined} onUpdated={() => undefined} onNewProposal={() => undefined} />);
    const correctionTab = await screen.findByRole("tab", { name: /Por corregir/ });
    expect(correctionTab).toHaveAttribute("aria-selected", "true");
    expect(screen.getByText(/1 actividad requiere una corrección/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /aprobar/i })).not.toBeInTheDocument();
    expect(screen.getAllByText("Por corregir")).toHaveLength(2);
    await userEvent.click(screen.getByRole("button", { name: "Resolver siguiente bloqueo" }));
    expect(await screen.findByLabelText("Corrección requerida")).toBeInTheDocument();
    expect(screen.getByText("Busca y selecciona una cuenta Jira real para esta actividad.")).toBeInTheDocument();
    expect(screen.getByText("Resultado de la validación con Jira")).toBeInTheDocument();
  });

  it("guía la preparación, confirmación y simulación 4A con cero escrituras", async () => {
    const proposal: Proposal = {
      proposal_id: "4a4a4a4a-4444-4444-8444-444444444444",
      version: 7,
      template_version: "1.1",
      status: "APPROVED",
      source_file: { name: "plan_4a.xlsx", sha256: "4".repeat(64) },
      defaults: { space: "AT", iniciativa: "Piloto", linea_trabajo: null, sprint: null, tipo_seguimiento: "Semanal", semaforo: null },
      created_at: "2026-07-20T16:00:00Z",
      created_by: "tester",
      approved_at: "2026-07-20T16:05:00Z",
      approved_by: "tester",
      items: [{
        source: { source_row: 6, actividad: "Validar canario", responsable_display: "Jose Calleja", frente_trabajo_origen: null, contexto_resultado: null, fecha_objetivo: null, estado_actual: "Pendiente", comentarios: null },
        generated: { row_id: "ROW-0006", create_in_jira: true, decision: "INCLUIR", decision_reason: "Lista", work_type: "Task", title: "Validar canario", description: "Validar el flujo controlado.", space: "AT", parent_row_id: null, assignee: { display_name: "Jose Calleja", email: null, account_id: "jira-jose", resolution: "RESOLVED" }, fields: { tipo_seguimiento: "Semanal" }, confidence: .95 },
        validation: { errors: [], warnings: [] },
        review: { user_modified: false, approved: true, review_note: null },
        execution: { result: "NOT_STARTED" },
      }],
    };
    const dryRun = {
      dry_run_id: "DRY-4a", proposal_id: proposal.proposal_id, proposal_version: 7,
      proposal_hash: "a".repeat(64), generated_at: "2026-07-20T16:06:00Z", generated_by: "tester",
      jira_snapshot_verified_at: "2026-07-20T16:05:30Z", site_url: "https://dpti.atlassian.net",
      status: "READY", summary: { ready: 1, ready_with_warnings: 0, blocked: 0, skipped: 0 },
      write_performed: false, reused: false,
      items: [{
        row_id: "ROW-0006", source_row: 6, status: "READY", title: "Validar canario", space: "AT", work_type: "Task", errors: [], warnings: [],
        target: { project_name: "AT", project_type: "software", jira_work_type: "Task", required_field_count: 3 },
        assignee: { display_name: "Jose Calleja", email: null, account_id: "jira-jose", validation: "JIRA_ACCOUNT_MATCH" },
        logical_payload: { summary: "Validar canario" }, idempotency_key: "AJI-4a",
      }],
    };
    const prepared: Objective4AIntent = {
      objective: "4A", mode: "SIMULATION_ONLY", execution_id: "EXE-4a", status: "PREPARED",
      proposal_id: proposal.proposal_id, proposal_version: 7, row_id: "ROW-0006", dry_run_id: "DRY-4a",
      idempotency_key: "AJI-4a", payload_hash: "b".repeat(64),
      payload: { tool: "createJiraIssue", contract_status: "CANDIDATE_UNTIL_REAL_SCHEMA_IS_CONFIRMED", arguments: { projectKey: "AT", summary: "AgenteTest_Task_Validar_canario", fields: { customfield_10483: "Semanal" } } },
      preview: { title: "AgenteTest_Task_Validar_canario", description: "Validar el flujo controlado.", space: "AT", work_type: "Task", assignee: { display_name: "Jose Calleja", account_id: "jira-jose", validation: "JIRA_ACCOUNT_MATCH" }, warnings: [] },
      confirmation: { required: true, expires_at: "2026-07-20T16:20:00Z", confirmed_at: null, confirmed_by: null },
      simulation: { simulated_calls: 0, real_mcp_calls: 0, write_performed: false, result: null },
      audit: [{ state: "PREPARED", event: "SIMULATION_PREPARED", at: "2026-07-20T16:06:00Z", by: "tester", real_mcp_calls: 0, write_performed: false }],
      created_at: "2026-07-20T16:06:00Z", updated_at: "2026-07-20T16:06:00Z", created_by: "tester", reused: false, jira_write_enabled: false,
    };
    const confirmed: Objective4AIntent = { ...prepared, status: "CONFIRMED", confirmation: { ...prepared.confirmation, confirmed_at: "2026-07-20T16:07:00Z", confirmed_by: "tester" } };
    const simulated: Objective4AIntent = {
      ...confirmed,
      status: "SIMULATED",
      simulation: { simulated_calls: 1, real_mcp_calls: 0, write_performed: false, result: { simulation_key: "SIM-AT-4A", accepted: true, transport: "LOCAL_SIMULATOR", mcp_tool_invoked: null, jira_issue_created: false } },
    };
    const realExecution: NonNullable<Objective4AIntent["real_execution"]> = {
      mode: "SINGLE_CONTROLLED_TASK",
      confirmation_phrase: "CREAR 1 TASK EN AT",
      payload: { tool: "createJiraIssue", arguments: { cloudId: "cloud-1", projectKey: "AT", issueTypeName: "Task", summary: "AgenteTest_Task_Validar_canario", assignee_account_id: "jira-jose" } },
      payload_hash: "c".repeat(64),
      prepared_at: "2026-07-20T16:08:00Z", confirmed_at: null, submitted_at: null, completed_at: null,
      real_mcp_calls: 0, automatic_retries: 0, issue_key: null, issue_url: null, result: null, error: null, readback: null,
    };
    const realPrepared: Objective4AIntent = {
      ...simulated, status: "REAL_PREPARED", jira_write_enabled: true, real_execution: realExecution,
      real_confirmation: { expires_at: "2026-07-20T16:18:00Z", confirmed_at: null, confirmed_by: null },
    };
    const realConfirmed: Objective4AIntent = {
      ...realPrepared, status: "REAL_CONFIRMED",
      real_execution: { ...realExecution, confirmed_at: "2026-07-20T16:09:00Z" },
      real_confirmation: { ...realPrepared.real_confirmation!, confirmed_at: "2026-07-20T16:09:00Z", confirmed_by: "tester" },
    };
    const realCreated: Objective4AIntent = {
      ...realConfirmed, status: "CREATED_VERIFIED",
      real_execution: {
        ...realConfirmed.real_execution!, completed_at: "2026-07-20T16:10:00Z", real_mcp_calls: 2,
        issue_key: "AT-9001", issue_url: "https://dpti.atlassian.net/browse/AT-9001", result: "CREATED_AND_VERIFIED",
        readback: { checks: { issue_key: true, summary: true, space: true, work_type: true, assignee: true }, payload: { key: "AT-9001" } },
      },
    };
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, options?: RequestInit) => {
      const url = input.toString();
      if (url.endsWith("/api/integrations/atlassian/status")) return {
        ok: true,
        json: async () => ({
          connected: true,
          phase: "CONNECTED",
          oauth_storage: "OS_ENCRYPTED",
          jira_write_enabled: false,
          write_tools_blocked: true,
          error: null,
          snapshot: {
            verified_at: "2026-07-20T16:00:00Z",
            site_url: "https://dpti.atlassian.net",
            site_name: "DPTI",
            cloud_id: "cloud-1",
            atlassian_user: { account_id: "jira-user", display_name: "Jose", email: null },
            spaces: [{ key: "AT", found: true, id: "100", name: "AT", project_type: "software", work_types: [{ id: "10", name: "Task", subtask: false, fields: [{ id: "customfield_10483", name: "Tipo de seguimiento", required: false }] }] }],
            read_tools_available: [],
            write_tools_exposed_by_server: 0,
          },
        }),
      } as Response;
      if (url.endsWith("/api/objectives/4/readiness")) return {
        ok: true,
        json: async () => ({
          objective: "4A", status: "READY_FOR_CONTROLLED_WRITE", jira_write_enabled: true, simulation_only: false,
          policy_violations: [], mcp_tools: { connected: true, inspection_only: true, tools_invoked: 0, create: { name: "createJiraIssue", exposed: true }, readback: { name: "getJiraIssue", exposed: true } },
          task_contract: { space: "AT", space_id: "100", work_type: "Task", work_type_id: "10", fields: [] },
          real_canary_checks: { atlassian_connected: true, create_tool_exposed: true, readback_tool_exposed: true, at_visible: true, task_metadata_available: true },
          real_canary_ready: true, controlled_write_ready: true, confirmation_phrase: "CREAR 1 TASK EN AT", next_gate: "EXPLICIT_IN_APP_CONFIRMATION",
        }),
      } as Response;
      if (url.endsWith("/dry-run/latest")) return { ok: true, json: async () => dryRun } as Response;
      if (url.endsWith("/objective-4a/latest")) return { ok: false, status: 404, json: async () => ({ detail: "Sin simulación" }) } as Response;
      if (url.endsWith("/objective-4a/prepare") && options?.method === "POST") return { ok: true, json: async () => prepared } as Response;
      if (url.includes("/objectives/4a/") && url.endsWith("/confirm")) return { ok: true, json: async () => confirmed } as Response;
      if (url.endsWith("/simulate")) return { ok: true, json: async () => simulated } as Response;
      if (url.includes("/objectives/4b/") && url.endsWith("/prepare")) return { ok: true, json: async () => realPrepared } as Response;
      if (url.includes("/objectives/4b/") && url.endsWith("/confirm")) return { ok: true, json: async () => realConfirmed } as Response;
      if (url.includes("/objectives/4b/") && url.endsWith("/execute")) return { ok: true, json: async () => realCreated } as Response;
      return { ok: false, status: 404, json: async () => ({ detail: "Ruta inesperada" }) } as Response;
    }));

    const onNewProposal = vi.fn();
    render(<ProposalReview token="token" proposal={proposal} displayName="Plan 4A" onRename={async () => undefined} onUpdated={() => undefined} onNewProposal={onNewProposal} />);
    expect(await screen.findByRole("heading", { name: "Probar una Task sin crearla en Jira" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Minimizar" }));
    expect(screen.queryByRole("button", { name: "Preparar simulación" })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Mostrar" }));
    await userEvent.click(screen.getByRole("button", { name: "Preparar simulación" }));
    expect(await screen.findByText("AgenteTest_Task_Validar_canario")).toBeInTheDocument();
    expect(await screen.findByText("Tipo de seguimiento")).toBeInTheDocument();
    expect(screen.getByText("Semanal")).toBeInTheDocument();
    await userEvent.click(screen.getByLabelText(/Confirmo esta vista previa/i));
    await userEvent.click(screen.getByRole("button", { name: "Confirmar vista previa" }));
    expect(await screen.findByText("La vista previa está lista para ensayarse")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Ejecutar simulación segura" }));
    expect(await screen.findByText("El payload se construyó, confirmó y procesó sin errores locales")).toBeInTheDocument();
    expect(screen.getByText("SIM-AT-4A · EXE-4a")).toBeInTheDocument();
    expect(screen.getByText("0 escrituras en la simulación")).toBeInTheDocument();
    await userEvent.click(await screen.findByRole("button", { name: "Preparar envío real" }));
    expect(await screen.findByText("Se creará exactamente una Task real en AT")).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("Frase de confirmación para crear la Task"), "CREAR 1 TASK EN AT");
    await userEvent.click(screen.getByRole("button", { name: "Confirmar creación real" }));
    expect(await screen.findByText("La siguiente acción sí escribirá en Jira")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Crear 1 Task real en AT" }));
    expect(await screen.findByText("Creación exitosa: AT-9001")).toBeInTheDocument();
    expect(screen.getByText("2 llamadas MCP · 0 reintentos")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Generar nueva propuesta" }));
    expect(onNewProposal).toHaveBeenCalledOnce();
  });

  it("busca, filtra, archiva y restaura propuestas desde la barra lateral", async () => {
    const summaries: ProposalSummary[] = [
      {
        proposal_id: "first",
        version: 2,
        status: "DRAFT",
        source_file: "plan_timeline_referencia_con_nombre_extenso.xlsx",
        display_name: "Plan activo con un nombre operativo suficientemente extenso",
        space: "AT",
        counts: { INCLUIR: 2, REVISAR: 0, EXCLUIR: 0 },
        created_at: "2026-07-16T12:00:00Z",
        archived: false,
        archived_at: null,
        archived_by: null,
        display_name_updated_at: null,
        display_name_updated_by: null,
      },
      {
        proposal_id: "second",
        version: 1,
        status: "NEEDS_INPUT",
        source_file: "plan_archivado.xlsx",
        display_name: "Plan archivado",
        space: "MTTI",
        counts: { INCLUIR: 1, REVISAR: 1, EXCLUIR: 0 },
        created_at: "2026-07-16T12:00:00Z",
        archived: true,
        archived_at: "2026-07-16T13:00:00Z",
        archived_by: "tester",
        display_name_updated_at: null,
        display_name_updated_by: null,
      },
    ];
    const onArchive = vi.fn();
    const onRestore = vi.fn();

    render(
      <ProposalHistory
        proposals={summaries}
        currentId={null}
        loadingId=""
        collapsed={false}
        onOpen={() => undefined}
        onArchive={onArchive}
        onRestore={onRestore}
        onNewProposal={() => undefined}
        onOpenSettings={() => undefined}
        settingsActive={false}
        jiraConnected={true}
        jiraWriteEnabled={false}
      />,
    );

    await userEvent.type(screen.getByLabelText("Buscar propuestas"), "activo");
    expect(screen.getByText("Plan activo con un nombre operativo suficientemente extenso")).toBeInTheDocument();
    expect(screen.getByTitle("plan_timeline_referencia_con_nombre_extenso.xlsx · AT · versión 2")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Archivar Plan activo con un nombre operativo suficientemente extenso" }));
    expect(onArchive).toHaveBeenCalledWith(summaries[0]);

    await userEvent.clear(screen.getByLabelText("Buscar propuestas"));
    await userEvent.selectOptions(screen.getByLabelText("Filtrar propuestas"), "ARCHIVED");
    expect(screen.getByText("Plan archivado")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Restaurar Plan archivado" }));
    expect(onRestore).toHaveBeenCalledWith(summaries[1]);
  });

  it("alterna y conserva la barra lateral con Ctrl+B", () => {
    vi.stubGlobal("fetch", vi.fn(async () => ({ ok: true, json: async () => [] }) as Response));
    const { container } = render(
      <Workspace
        session={{
          access_token: "local-token",
          token_type: "bearer",
          user: { username: "admin@agentejira.local", display_name: "Administrador local" },
        }}
        onLogout={() => undefined}
      />,
    );
    const shell = container.querySelector(".app-shell");
    expect(shell).not.toHaveClass("sidebar-collapsed");

    fireEvent.keyDown(window, { key: "b", ctrlKey: true });

    expect(shell).toHaveClass("sidebar-collapsed");
    expect(localStorage.getItem("agente-jira-sidebar-collapsed")).toBe("true");
  });

  it("abre la configuración Jira desde la barra lateral y mantiene limpia la vista principal", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = input.toString();
      if (url.includes("/api/integrations/atlassian/status")) {
        return { ok: true, json: async () => ({ connected: false, phase: "DISCONNECTED", oauth_storage: "OS_ENCRYPTED", jira_write_enabled: false, write_tools_blocked: true, error: null, snapshot: null }) } as Response;
      }
      return { ok: true, json: async () => [] } as Response;
    }));
    render(
      <Workspace
        session={{ access_token: "local-token", token_type: "bearer", user: { username: "admin@agentejira.local", display_name: "Administrador local" } }}
        onLogout={() => undefined}
      />,
    );

    expect(screen.queryByRole("heading", { name: "Conexión de la aplicación con Jira" })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /Configuración Jira/ }));
    expect(await screen.findByRole("heading", { name: "Conexión de la aplicación con Jira" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Carga el plan de trabajo" })).not.toBeInTheDocument();
  });
});
