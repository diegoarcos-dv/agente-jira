# Objetivo 4D: escritura controlada de Task, Bug y Story

Versión de la aplicación: 0.19.0  
Estado: implementado y verificado con pruebas locales; pendiente de una validación real pequeña para Bug y Story.

## Alcance

El Objetivo 4D amplía la lista positiva del ejecutor para admitir:

- `Task`;
- `Bug`;
- `Story`.

El destino continúa limitado al Space `AT`. Se permiten lotes homogéneos o mixtos de una a cinco actividades.

No se habilitan `Epic`, `Subtask`, ASIT, MTTI, comentarios, transiciones, edición ni eliminación.

## Controles conservados

- propuesta aprobada y Dry run vigente;
- cero bloqueos antes de preparar;
- responsable Jira exacto;
- confirmación escrita `CREAR N ACTIVIDADES EN AT`;
- revalidación de Sprint antes de la primera creación;
- ejecución secuencial;
- `createJiraIssue` seguido de `getJiraIssue` por actividad;
- detención ante el primer rechazo, resultado incierto o lectura incompleta;
- cero reintentos automáticos;
- idempotencia por actividad y lote;
- máximo cinco actividades por confirmación.

## Resolución por Work Type

El payload ya no reutiliza los metadatos de Task. Para cada fila se localiza en el snapshot Jira el contrato de su Work Type y se transforman sus campos con ese catálogo.

| Work Type | Título identificable | Verificación posterior |
|---|---|---|
| Task | `AgenteTest_Task_...` | Jira debe devolver Task o Tarea |
| Bug | `AgenteTest_Bug_...` | Jira debe devolver Bug |
| Story | `AgenteTest_Story_...` | Jira debe devolver Story |

Si Jira no publica los campos de cualquiera de los tres tipos, el modo 4D queda bloqueado antes de permitir la preparación.

## Sprint

Sprint se consulta dentro del contrato del Work Type correspondiente. Cuando la propuesta incluye Sprint:

1. el Dry run resuelve nombre e ID;
2. la preparación ubica el campo Sprint para Task, Bug o Story;
3. antes de escribir se actualiza el catálogo una sola vez para AT;
4. todos los IDs del lote deben seguir activos o futuros;
5. si uno falla, no se crea ninguna actividad del lote.

## Consumo esperado

Una validación real mínima con un Bug y una Story requiere cuatro llamadas MCP: dos creaciones y dos lecturas posteriores. Las pruebas automatizadas utilizan dobles locales y no consumen Jira.
