# GATE F — Release readiness

Fecha de ejecución: 2026-09-10  
Alcance: hardening local, E2E read-only, reproducibilidad, documentación y preparación previa a una escritura Jira.  
Escrituras Jira durante esta validación: **0**.

## Resultado

**NOT_READY**.

La auditoría local confirmó que el bloqueo de Subtask no era una ausencia de metadata Jira. El MCP devolvió el tipo localizado `Subtarea` con ID estable y `subtask=true`, pero el descubrimiento local sólo aceptaba los nombres ingleses `subtask`/`sub-task` y nunca solicitaba sus campos. El filtro quedó corregido para identificar la semántica `subtask` y sus nombres localizados. La prueba de contrato ya confirma que se solicita y conserva la metadata de `Subtarea`.

El cierre operativo permanece pendiente de reconectar Atlassian desde la interfaz y repetir el descubrimiento y E2E read-only con el MCP vivo: el diagnóstico real posterior encontró `OAUTH_EXPIRED` en `MCP_INITIALIZE`. No se modificó OAuth ni DPAPI.

La ausencia de `gemma3:1b` en Ollama queda clasificada como **riesgo conocido/funcionalidad opcional**, no como blocker del flujo Jira; no se descargó ni instaló el modelo.

No se autorizó ni ejecutó `createJiraIssue`.

## Matriz de Gates

| Gate | Estado | Evidencia |
|---|---|---|
| A | APROBADO | Doctor local y arranque validado |
| B | APROBADO CON RECONEXIÓN PENDIENTE | La evidencia previa fue `JIRA_READY`; la instancia actual reporta `OAUTH_INVALID` al restaurar la autorización |
| C | APROBADO | Runtime final `LOCKED`; TTL, expiración y kill switch cubiertos por pruebas |
| D | APROBADO CON OBSERVACIONES | Smoke read-only 1/3/10 sin regresión significativa |
| E | APROBADO CON OLLAMA PENDIENTE | Activación aislada sin cargar modelos; Gemma ausente |
| F | **NOT_READY** | Corrección de Subtask implementada; falta reconexión y E2E live. Gemma es riesgo opcional |

## Validación E2E read-only

- Plantilla dinámica v1.2: HTTP 200, workbook válido, hojas `PLAN_DE_TRABAJO` y `CATALOGOS`.
- Catálogo Jira real para `customfield_10147`: estado `verified`, seis opciones y option IDs presentes. No se inventaron valores.
- Sprints reales en `AT`: un Sprint `active` y uno `future`; el preflight seleccionó el activo `646` cuando correspondía.
- Responsables `Giselle Bello` y `Jose Calleja`: coincidencia activa única contra Jira, account IDs persistidos y versión de propuesta incrementada. El dry-run anterior quedó `stale=true`.
- Jerarquía local aceptada: `Epic → Task`, `Epic → Bug`, `Epic → Story`, y cada uno con su `Subtask`.
- Auditoría de Work Types AT: `Subtarea` conserva su ID Jira y `subtask=true`; el fallo era el filtro de localización del descubrimiento, no Jira ni el endpoint MCP.
- Prueba de contrato corregida: `Subtarea` dispara `getJiraIssueTypeMetaWithFields` y conserva `summary`/`parent` sin realizar escrituras.
- Jerarquía Jira live anterior: Epic, Task, Bug y Story quedaron listos con advertencias; el E2E live de Subtask debe repetirse después de reconectar y actualizar el snapshot.
- Casos inválidos bloqueados antes de escritura: padre inexistente, referencia inválida, relación incompatible y ciclo (`422`); Sprint inexistente (`SPRINT_NOT_FOUND`); catálogo obsoleto (`FIELD_VALUE_NOT_ALLOWED`).
- Se validó la preparación mínima de una Task hasta `BATCH_PREPARED`. La segunda preparación devolvió el mismo `execution_id`; no hubo confirmación ni ejecución.
- La evidencia sanitizada quedó en `backend/data/gate_f_validation/readonly_evidence.json`.

## Write Lock e idempotencia

- Estado final: `LOCKED`.
- Cada dry-run confirmó `write_performed=false`.
- La transición temporal `UNLOCKED_TEMPORARY`, expiración, kill switch y rechazo de usuario no autorizado están cubiertos por la suite de `test_jira_write_lock.py`. La validación online mantuvo el lock cerrado; el desbloqueo live fue omitido por la política de seguridad del entorno.
- No se ejecutaron rutas de confirmación ni ejecución real.
- JIRA WRITES: **0**.
- `createJiraIssue` calls: **0**.

## Voz bajo demanda

En un proceso nuevo, antes y después de `POST /api/voice/activate`:

- STT: `NOT_LOADED`.
- TTS: `NOT_LOADED`.
- LLM: comprobación ligera, quedó `ERROR` porque falta `gemma3:1b` (riesgo opcional; no bloquea Jira).
- Carga de modelos provocada por activación: `false`.
- Global Write Lock: `LOCKED`.

Whisper y Piper sólo aparecen como cargados si ya fueron utilizados previamente en ese proceso; la activación aislada no invocó sus loaders.

## Rendimiento read-only

Tres ejecuciones por tamaño, usando Jira real y sin escrituras:

| Actividades | Duración aproximada | Estado |
|---:|---:|---|
| 1 | 5.9–6.2 s | `READY_WITH_WARNINGS` |
| 3 | 7.7–7.8 s | `READY_WITH_WARNINGS` |
| 10 | 7.4–7.7 s | `READY_WITH_WARNINGS` |

Las cifras están dentro de las referencias aproximadas de GATE D. No se observa una regresión consistente.

## Verificaciones finales

- Backend: **200 passed** en las suites ejecutadas tras la corrección, una advertencia de deprecación de Starlette.
- Frontend: **38 passed** en 5 archivos.
- TypeScript/Vite build: **passed**.
- Parseo PowerShell: **10 scripts passed**.
- `doctor.ps1 -SkipPorts`: **passed**.
- Instalación limpia: setup, doctor, build, arranque y plantilla v1.2 aprobados.
- Secrets scan runtime: no se detectaron tokens con formato conocido, refresh tokens materializados, cookies, Authorization Bearer ni client secrets con valor.
- OAuth sigue en almacenamiento `OS_ENCRYPTED`/DPAPI; una nueva instancia pudo descifrar tokens y client info sin modificar el archivo.
- No se inicializó Git ni se desplegó producción.

## Pendientes para cerrar

1. Reconectar Atlassian desde la interfaz para renovar la autorización expirada y repetir el descubrimiento MCP.
2. Repetir preflight y E2E read-only de `Task → Subtask`, `Story → Subtask` y `Bug → Subtask` hasta `BATCH_PREPARED`.
3. Instalar o configurar `gemma3:1b` en Ollama sólo si se requiere voz LLM; no es requisito del flujo Jira.
4. Solicitar autorización explícita antes de confirmar o ejecutar cualquier escritura real.

El resultado permanece **NOT_READY** hasta renovar OAuth y repetir la validación MCP/E2E live. No se debe desplegar ni ejecutar una escritura Jira real mientras esa validación esté pendiente.
