import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { AtlassianConnectionPanel } from './App';
import type { AtlassianStatus } from './types';

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

function status(state: string): AtlassianStatus {
  return { connected: false, phase: 'DISCONNECTED', oauth_storage: 'OS_ENCRYPTED',
    jira_write_enabled: false, write_tools_blocked: true, error: null, snapshot: null,
    diagnostic: { state, message: state === 'JIRA_READY' ? 'Jira listo para trabajar.' : state === 'OAUTH_EXPIRED' ? 'La autorización Atlassian venció.' : 'No se puede contactar con Atlassian MCP.',
      action: 'Reconectar cuenta', phase: 'MCP_INITIALIZE', request_id: 'request-test',
      checked_at: null, last_success_at: null, duration_ms: 20, error_code: state,
      technical: state, checks: { backend: 'OK', mcp: state === 'MCP_UNREACHABLE' ? 'FAILED' : 'OK', oauth: state === 'OAUTH_EXPIRED' ? 'FAILED' : 'OK', site: 'NOT_CHECKED', space: 'NOT_CHECKED' },
      capabilities: [], account: null, write_performed: false, tools_invoked: [] } };
}

it('Probar conexión usa diagnóstico read only y reconstruye el panel', async () => {
  const fetch = vi.fn(async (url: string) => ({ok: true, json: async () => status(url.endsWith('/diagnose') ? 'JIRA_READY' : 'OAUTH_EXPIRED')}));
  vi.stubGlobal('fetch', fetch);
  render(<AtlassianConnectionPanel token="test" />);
  expect(await screen.findByText('OAuth')).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Probar conexión' }));
  expect(await screen.findAllByText('Jira listo para trabajar.')).toHaveLength(1);
  expect(fetch.mock.calls.some(([url]) => url.endsWith('/diagnose'))).toBe(true);
  expect(fetch.mock.calls.every(([url]) => !url.includes('/execute'))).toBe(true);
});

it('Reintentar consulta MCP sin iniciar otro consentimiento OAuth', async () => {
  const fetch = vi.fn(async () => ({ok: true, json: async () => status('MCP_UNREACHABLE')}));
  vi.stubGlobal('fetch', fetch);
  render(<AtlassianConnectionPanel token="test" />);
  fireEvent.click(await screen.findByRole('button', {name: 'Reintentar'}));
  await screen.findByRole('button', {name: 'Reintentar'});
  expect(fetch.mock.calls.length).toBeGreaterThanOrEqual(2);
});

it('recargar mantiene el estado vigente del backend y muestra detalles seguros', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => ({ok: true, json: async () => status('JIRA_READY')})));
  const first = render(<AtlassianConnectionPanel token="test" />);
  await screen.findAllByText('Jira listo para trabajar.');
  first.unmount();
  render(<AtlassianConnectionPanel token="test" />);
  await screen.findAllByText('Jira listo para trabajar.');
  expect(screen.getByText('request-test')).toBeInTheDocument();
  expect(screen.getByText('Backend local')).toBeInTheDocument();
});
