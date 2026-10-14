import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import App from "./App";
import { SESSION_EXPIRED_EVENT } from "./authEvents";
import { THEME_KEY } from "./theme";

beforeEach(() => {
  localStorage.clear();
  vi.stubGlobal("matchMedia", vi.fn(() => ({ matches: false })));
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => ({
    ok: true,
    json: async () => input.toString().endsWith("/api/auth/me")
      ? { access_token: "", token_type: "bearer", user: { username: "admin@agentejira.local", display_name: "Administrador local", role: "ADMIN" } }
      : input.toString().endsWith("/api/proposals") ? [] : {
          connected: false,
          phase: "DISCONNECTED",
          jira_write_enabled: false,
          write_tools_blocked: true,
          error: null,
          snapshot: null,
        },
  }) as Response));
});

afterEach(() => {
  cleanup();
  document.documentElement.removeAttribute("data-theme");
  document.documentElement.style.removeProperty("color-scheme");
  vi.unstubAllGlobals();
});

it("alterna el tema antes del usuario y conserva la preferencia", async () => {
  const user = userEvent.setup();
  render(<App />);
  const toggle = await screen.findByRole("button", { name: "Cambiar a modo oscuro" });
  const userName = screen.getByText("Administrador local");
  expect(toggle.compareDocumentPosition(userName) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();

  await user.click(toggle);
  await waitFor(() => expect(document.documentElement.dataset.theme).toBe("dark"));
  expect(localStorage.getItem(THEME_KEY)).toBe("dark");
  expect(screen.getByRole("button", { name: "Cambiar a modo claro" })).toBeInTheDocument();
});

it("vuelve al acceso cuando el servidor informa que la sesión venció", async () => {
  render(<App />);
  expect(await screen.findByText("Administrador local")).toBeInTheDocument();

  window.dispatchEvent(new Event(SESSION_EXPIRED_EVENT));

  expect(await screen.findByRole("heading", { name: "Accede con tu cuenta corporativa" })).toBeInTheDocument();
});

it("descarta una sesión anterior cuando una consulta autenticada recibe 401", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => ({
    ok: false,
    status: 401,
    json: async () => ({ detail: "Sesión inválida o vencida." }),
  }) as Response));

  render(<App />);

  expect(await screen.findByRole("heading", { name: "Accede con tu cuenta corporativa" })).toBeInTheDocument();
});
