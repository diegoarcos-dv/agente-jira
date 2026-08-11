# Evidencia de implementación — Objetivo 4A

| Dato | Resultado |
|---|---|
| Versión de la aplicación | 0.12 |
| Fecha | 20 de julio de 2026 |
| Estado funcional | Implementado y verificado |
| Modo de ejecución | `SIMULATION_ONLY` |
| Escritura Jira | Deshabilitada |
| Alcance | Una actividad `Task` en `AT` |

## Resultado verificable

La aplicación puede preparar, confirmar y simular una intención de creación a partir de una propuesta aprobada y de su Dry run vigente. El flujo persiste la intención y su auditoría, pero utiliza un gateway local que no tiene transporte MCP y no puede crear una actividad Jira.

La simulación concluye con estas evidencias:

- `real_mcp_calls=0`;
- `write_performed=false`;
- `jira_issue_created=false`;
- `mcp_tool_invoked=null`;
- identificador simulado con prefijo `SIM-AT-`;
- política `PLANNING_ONLY` y `jira_write_enabled=false`.

## Flujo implementado

1. Selección de una actividad elegible de la propuesta aprobada.
2. Validación determinista de Space `AT`, Work Type `Task`, Dry run vigente y cero bloqueos.
3. Creación persistente de una intención `PREPARED` con clave de idempotencia y hash del payload.
4. Vista previa con título `AgenteTest_Task_...`, responsable y datos candidatos.
5. Confirmación explícita del mismo hash antes de que caduque.
6. Revalidación de la propuesta y el Dry run.
7. Ejecución contra el gateway local simulado.
8. Estado `SIMULATED` y descarga de evidencia JSON.

## Controles implementados

- Una sola intención activa por propuesta, versión, fila y Dry run.
- Confirmación con caducidad de 15 minutos.
- Invalidación si cambia el hash, la propuesta o el Dry run.
- Rechazo de propuestas no aprobadas, Dry runs bloqueados, Spaces distintos de AT y tipos distintos de Task.
- Sin reintentos automáticos.
- Auditoría de cada transición: `PREPARED`, `CONFIRMED`, `SIMULATED`, `CANCELLED`, `EXPIRED` o `INVALIDATED`.
- Diagnóstico de herramientas Rovo basado únicamente en sus esquemas anunciados; no invoca ninguna herramienta.
- La herramienta `createJiraIssue` no fue agregada a la lista de herramientas MCP invocables.

## Persistencia y API

Se agregó la tabla local `jira_execution_intents` y los endpoints autenticados:

- `POST /api/proposals/{proposal_id}/objective-4a/prepare`;
- `POST /api/objectives/4a/executions/{execution_id}/confirm`;
- `POST /api/objectives/4a/executions/{execution_id}/simulate`;
- `POST /api/objectives/4a/executions/{execution_id}/cancel`;
- `GET /api/proposals/{proposal_id}/objective-4a/latest`;
- `GET /api/objectives/4a/executions/{execution_id}/evidence`.

## Verificación automatizada

Resultados al cierre:

```text
Backend:  52 pruebas aprobadas
Frontend: 9 pruebas aprobadas
Build:    TypeScript y Vite aprobados
```

La prueba integral del frontend recorre preparar, confirmar y simular, y verifica la evidencia final de cero escrituras. Las pruebas del backend cubren el flujo exitoso, alteración del hash, caducidad, re-preparación y rechazo de entradas no elegibles.

## Fuera de alcance

El Objetivo 4A no llama a `createJiraIssue`, no crea una Task real, no cambia la política a `SINGLE_CANARY` y no prueba lectura posterior. Estas acciones pertenecen al Objetivo 4B y requerirán autorización explícita independiente.
