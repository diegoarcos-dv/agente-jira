# Checklist de entrada — Objetivo 4A

El Objetivo 4A prepara el ejecutor y valida capacidades; no crea actividades Jira.

## Conexión y permisos

- [ ] La conexión OAuth Atlassian se conserva después de salir y reiniciar.
- [ ] El usuario autorizado puede ver el Space AT.
- [ ] Rovo expone `createJiraIssue` y `getJiraIssue` en la conexión del usuario del piloto.
- [x] El diagnóstico puede capturar nombre, entradas requeridas y hash del esquema anunciado sin invocar herramientas.
- [ ] La administración de Rovo permite `write_jira` para el usuario del piloto.

## Contrato Task de AT

- [ ] Se identificó el ID real de Task en AT.
- [ ] Se identificaron los campos obligatorios reales.
- [ ] Se confirmó el formato de Description requerido por Rovo.
- [ ] Se identificaron los IDs/opciones de Tipo de seguimiento y Due date.
- [ ] Se confirmó que Assignee puede enviarse dentro de la creación.
- [ ] Se seleccionó una sola actividad no productiva para la prueba.

## Seguridad del ejecutor

- [x] La política está en `PLANNING_ONLY` y `jira_write_enabled=false` durante 4A.
- [x] Sólo `createJiraIssue` podrá habilitarse posteriormente.
- [x] Comment, Worklog, Edit y Transition permanecen bloqueados.
- [x] El límite es exactamente una actividad Task y sólo en AT.
- [x] Existe segunda confirmación con título, responsable, Space y payload candidato.
- [x] No existe reintento automático de una creación con resultado desconocido.
- [x] Existe un kill switch de política probado localmente.

## Auditoría propia

- [x] Se registra la intención antes de ejecutar la simulación.
- [x] Se registra propuesta, versión, fila, Dry run, usuario y clave idempotente.
- [x] Se registra el payload lógico sin tokens.
- [x] Se registra el resultado simulado y sus tiempos.
- [x] Los estados de 4A `PREPARED`, `CONFIRMED`, `SIMULATED`, `EXPIRED`, `INVALIDATED` y `CANCELLED` están definidos.
- [x] Los tokens, cookies y cabeceras Authorization nunca aparecen en la evidencia.

## Verificación de cierre de 4A

- [x] El gateway de 4A es local y no dispone de transporte MCP.
- [x] La evidencia demuestra `real_mcp_calls=0` y `write_performed=false`.
- [x] La suite rechaza Dry runs bloqueados y tipos distintos de Task.
- [x] La suite invalida confirmaciones caducadas o con un hash diferente.
- [ ] El usuario completó la guía de validación manual del flujo.

## Autorización para 4B

- [ ] El usuario revisó la vista previa final.
- [ ] El usuario confirmó que AT es un Space productivo y aceptó crear una prueba identificable.
- [ ] Se acordó quién cerrará o eliminará manualmente la actividad de prueba.
- [ ] Se aprobó activar temporalmente `SINGLE_CANARY`.
