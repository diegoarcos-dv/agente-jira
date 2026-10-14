# GATE D — Validación real de observabilidad y rendimiento

Fecha: 2026-09-08  
Entorno: local (`http://127.0.0.1:8000`) con Atlassian OAuth real restaurado.

## Alcance y límites

La validación usa propuestas locales aprobadas y ejecuta únicamente `dry-run`. Las operaciones reales observadas contra Jira/MCP fueron lecturas (`lookupJiraAccountId` y `searchJiraIssuesUsingJql`). No se ejecutó `createJiraIssue`, no se modificó Jira y el Write Lock permaneció `LOCKED`.

No existe una medición real anterior comparable. Por ello, no se presenta un porcentaje de mejora inventado. La comparación sintética antes/después está separada en [gate_d_baseline.md](gate_d_baseline.md); las cifras de este documento son mediciones reales actuales.

## Estado Atlassian y OAuth

- Antes de reconectar: `ERROR`, diagnóstico `OAUTH_INVALID`, lock `LOCKED`.
- Después de que el usuario completó el consentimiento Atlassian: `CONNECTED`, diagnóstico `JIRA_READY`.
- Checks finales: backend, MCP, OAuth, cuenta, sitio, espacio y capacidades = `OK`.
- Si el blob DPAPI guardado no puede leerse, la UI muestra una acción explícita para reconectar. El botón de reconexión limpia únicamente el intento ilegible de ese usuario; no realiza borrado silencioso ni toca Jira.

## Benchmark real (3 corridas por tamaño)

Todas las corridas terminaron sin error de rate limit, sin timeout observado y con `write_performed=false`.

| Filas | Duración mínima (ms) | Mediana (ms) | Promedio (ms) | Máxima (ms) | MCP calls/corrida | Hits / misses | Máx. concurrencia |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 6450.8 | 6532.3 | 6525.7 | 6593.9 | 3 | 3 / 3 | 2 |
| 3 | 8160.5 | 8195.3 | 8274.5 | 8467.6 | 4 | 7 / 4 | 3 |
| 10 | 7743.6 | 8106.6 | 8673.1 | 10169.2 | 4 | 21 / 4 | 3 |
| 25 | 8312.3 | 8538.6 | 8702.5 | 9256.6 | 4 | 51 / 4 | 3 |

Operaciones MCP por corrida de 3, 10 y 25 filas: `lookupJiraAccountId=2` y `searchJiraIssuesUsingJql=2`. En el caso de 1 fila: `lookupJiraAccountId=1` y `searchJiraIssuesUsingJql=2`.

La propuesta de 10 filas (5 Giselle + 5 Jose) confirma que las resoluciones de responsable se hacen por responsable único: 2 llamadas reales, no 10. Las repeticiones se sirven desde caché de solicitud. El caso de 25 filas mantuvo también 2 resoluciones reales.

## Revalidación incremental

Sobre la propuesta local de 3 filas (`bbd3478c-d461-4c9c-80f9-3cc7e9f0e644`):

1. Versión 3 estaba `APPROVED` con dry-run `READY_WITH_WARNINGS`.
2. `reopen` creó la versión 4 (`VALIDATED`) y marcó obsoleto el dry-run anterior.
3. Se editó únicamente `ROW-0006`; la versión pasó a 5.
4. Tras aprobar y ejecutar el nuevo dry-run, la versión quedó en 6, `READY_WITH_WARNINGS`, con `write_performed=false`.
5. Las otras 2 filas conservaron exactamente su `logical_payload`; no había dependencias que revalidar.
6. El lock final siguió `LOCKED`.

La propuesta de 25 filas encontró además un cambio real de catálogo de Jira (`Tipo de seguimiento: Operativo` ya no permitido); quedó protegida en `VALIDATED` y no pudo aprobarse mientras la corrección no se resolviera. Esto confirma que el bloqueo de correcciones funciona.

## Diagnósticos y pruebas

- `GET /api/diagnostics/performance`: request id presente, llamadas, hits/misses, concurrencia y operaciones desglosadas; no se observaron secretos (`access_token`, `refresh_token`, `client_secret` o `Bearer`).
- `jira_write_calls=0` y eventos de escritura Jira = 0 durante toda la validación.
- Backend: suite completa, todos los tests pasan.
- Frontend: suite completa, 5 archivos / 36 tests pasan; build pasa.

## Riesgos pendientes

- No hay baseline real “antes” para calcular una mejora porcentual; sólo existe el baseline sintético separado.
- El endpoint de estado puede reportar `network=NOT_CHECKED` aunque la conexión OAuth/MCP esté lista; no se interpreta como fallo de Jira.
- El middleware registra `http_request` como fase envolvente más lenta; es una medida honesta del request total, no una atribución interna del cuello de botella.
- Un blob DPAPI puede volver a quedar ilegible si cambia el contexto de usuario/máquina; el flujo de reconexión ahora es recuperable.
