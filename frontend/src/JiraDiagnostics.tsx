import type { AtlassianStatus } from './types';

export function JiraDiagnostics({ status, busy, onCheck }: {
  status: AtlassianStatus; busy: boolean; onCheck: () => void;
}) {
  const d = status.diagnostic;
  if (!d) return null;
  const labels: Record<string, string> = {
    backend: 'Backend local', network: 'Red / DNS', mcp: 'MCP Atlassian', oauth: 'OAuth',
    account: 'Cuenta Atlassian', site: 'Sitio Jira', space: 'Space AT', capabilities: 'Permisos de consulta',
  };
  return <section aria-label="Estado del sistema">
    <h3>Estado del sistema</h3>
    <dl className="integration-summary">
      {Object.entries(labels).map(([key, label]) => <div key={key}>
        <dt>{label}</dt><dd>{d.checks[key] === 'OK' ? '✓ Verificado' : d.checks[key] === 'FAILED' ? '✗ No disponible' : '— No comprobado'}</dd>
      </div>)}
      <div><dt>Modo de escritura</dt><dd>{status.jira_write_enabled ? 'Según política actual · confirmación requerida' : 'Bloqueado'}</dd></div>
      {status.global_write_lock && <div><dt>Bloqueo global</dt><dd>{status.global_write_lock.state === 'UNLOCKED_TEMPORARY' ? `⚠ Habilitadas temporalmente${status.global_write_lock.expires_at ? ` · expira ${new Date(status.global_write_lock.expires_at).toLocaleTimeString()}` : ''}` : status.global_write_lock.state === 'EXPIRED' ? '⌛ Autorización vencida' : '🔒 Bloqueadas'}</dd></div>}
    </dl>
    <p role="status">{busy ? 'Comprobando conexión…' : d.message}</p>
    {d.state !== 'JIRA_READY' && <p>{d.action}</p>}
    <button className="button secondary" disabled={busy || d.state === 'OAUTH_IN_PROGRESS'} onClick={onCheck}>
      {['MCP_UNREACHABLE', 'MCP_TIMEOUT', 'NETWORK_UNAVAILABLE'].includes(d.state) ? 'Reintentar' : 'Probar conexión'}
    </button>
      <details><summary>Diagnóstico · Detalles técnicos</summary>
      <dl>
        <dt>Código</dt><dd>{d.error_code || d.state}</dd>
        <dt>Fase</dt><dd>{d.phase}</dd>
        <dt>Request id</dt><dd>{d.request_id}</dd>
        <dt>Endpoint lógico</dt><dd>Atlassian Rovo MCP</dd>
        <dt>Sitio Jira configurado</dt><dd>{status.target_site || 'No informado'}</dd>
        <dt>Space esperado</dt><dd>AT</dd>
        <dt>Última comprobación</dt><dd>{d.checked_at || 'No comprobado'}</dd>
        <dt>Última conexión exitosa</dt><dd>{d.last_success_at || 'No registrada'}</dd>
        <dt>Duración</dt><dd>{d.duration_ms === null ? '—' : `${d.duration_ms} ms`}</dd>
        <dt>Usuario Atlassian</dt><dd>{d.account || 'No identificado'}</dd>
        <dt>Capabilities de lectura</dt><dd>{d.capabilities.join(', ') || 'No comprobadas'}</dd>
        <dt>Error sanitizado</dt><dd>{d.technical || 'Sin error'}</dd>
        {status.performance && <>
          <dt>Última operación</dt><dd>{status.performance.operation}</dd>
          <dt>Duración total</dt><dd>{status.performance.duration_ms} ms</dd>
           <dt>Jira/MCP calls</dt><dd>{status.performance.jira_call_count}</dd>
           <dt>Responsables / Sprints</dt><dd>{status.performance.calls_by_operation?.find_assignees ?? 0} / {status.performance.calls_by_operation?.list_sprints ?? 0}</dd>
          <dt>Cache</dt><dd>{status.performance.cache_hits} hits / {status.performance.cache_misses} misses</dd>
          <dt>Fase más lenta</dt><dd>{status.performance.slowest_phase?.name || '—'} · {status.performance.slowest_phase?.duration_ms ?? 0} ms</dd>
          <dt>Concurrencia máxima</dt><dd>{status.performance.max_concurrency}</dd>
        </>}
      </dl>
      <p>Esta comprobación no crea ni modifica actividades Jira.</p>
    </details>
  </section>;
}
