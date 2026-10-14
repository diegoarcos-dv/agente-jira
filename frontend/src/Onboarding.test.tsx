import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Onboarding } from "./Onboarding";

describe("Onboarding", () => {
  afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

  it("muestra bienvenida por usuario y guarda el skip", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, options?: RequestInit) => {
      const url = input.toString();
      if (url.endsWith("/api/onboarding/status")) return { ok: true, json: async () => ({ version: 0, current_version: 1, required: true }) } as Response;
      if (url.endsWith("/api/onboarding/skip") && options?.method === "POST") return { ok: true, json: async () => ({ version: 1, current_version: 1, required: false, skipped_at: "now" }) } as Response;
      return { ok: false, status: 404, json: async () => ({ detail: "not found" }) } as Response;
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<Onboarding token="test" displayName="Giselle Bello" />);
    expect(await screen.findByRole("heading", { name: /Hola, Giselle/i })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Omitir tutorial" }));
    expect(fetchMock).toHaveBeenCalledWith("/api/onboarding/skip", expect.objectContaining({ method: "POST" }));
    expect(screen.queryByRole("heading", { name: /Hola, Giselle/i })).not.toBeInTheDocument();
  });

  it("espera eventos reales para mover el spotlight", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => ({ ok: true, json: async () => ({ version: 0, current_version: 1, required: true }) }) as Response));
    render(<><button data-tour-id="new-proposal">Nueva propuesta</button><Onboarding token="test" displayName="Jose" /></>);
    await userEvent.click(await screen.findByRole("button", { name: "Comenzar recorrido" }));
    expect(await screen.findByText("Abre Nueva propuesta para crear un nuevo plan de trabajo.")).toBeInTheDocument();
    window.dispatchEvent(new CustomEvent("agente:onboarding:view:new-proposal"));
    expect(await screen.findByText(/Puedes pegar una minuta completa/)).toBeInTheDocument();
  });

  it("calcula los campos pendientes de la fila activa y no mezcla otra fila", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => ({ ok: true, json: async () => ({ version: 0, current_version: 1, required: true }) }) as Response));
    render(<><button data-tour-id="new-proposal">Nueva propuesta</button><Onboarding token="test" displayName="Jose" /></>);
    await userEvent.click(await screen.findByRole("button", { name: "Comenzar recorrido" }));
    window.dispatchEvent(new CustomEvent("agente:onboarding:view:new-proposal"));
    window.dispatchEvent(new CustomEvent("agente:onboarding:minutes:selected"));
    window.dispatchEvent(new CustomEvent("agente:onboarding:input:minutes"));
    window.dispatchEvent(new CustomEvent("agente:onboarding:analyze:clicked"));
    window.dispatchEvent(new CustomEvent("agente:onboarding:analysis:completed"));
    window.dispatchEvent(new CustomEvent("agente:onboarding:row:needs-review", { detail: { rowId: "ACT-1", missing: ["responsable", "tipo_de_seguimiento"] } }));
    expect(await screen.findByText(/Selecciona al responsable/)).toBeInTheDocument();
    window.dispatchEvent(new CustomEvent("agente:onboarding:responsible:validated", { detail: { rowId: "ACT-1" } }));
    expect(await screen.findByText(/Selecciona el tipo de seguimiento/)).toBeInTheDocument();
    window.dispatchEvent(new CustomEvent("agente:onboarding:row:ready", { detail: { rowId: "ACT-2" } }));
    expect(screen.queryByText("¡Listo!")).not.toBeInTheDocument();
    window.dispatchEvent(new CustomEvent("agente:onboarding:tracking:selected", { detail: { rowId: "ACT-1" } }));
    window.dispatchEvent(new CustomEvent("agente:onboarding:row:ready", { detail: { rowId: "ACT-1" } }));
    expect(await screen.findByText("¡Listo!")).toBeInTheDocument();
  });
});
