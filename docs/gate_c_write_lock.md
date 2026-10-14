# GATE C — Global Jira Write Lock

## Alcance y auditoría

La escritura real converge en `AtlassianIntegrationManager.create_single_task_and_readback()`.
Ese gateway es compartido por 4B, 4C/4D/4E y la creación Jira por voz. La única invocación
MCP de escritura del producto es `createJiraIssue`; la lectura posterior usa la lista positiva
`call_read_only_tool`. Los campos de relación padre/hijo viajan dentro del mismo create.

Las políticas `jira_execution_policy_4b.json` a `4e.json` habilitan el modo funcional, pero no
son el permiso global. Dry-run, preflight, confirmación, idempotencia, creación secuencial y
readback permanecen en sus servicios originales.

## Arquitectura

`GlobalJiraWriteLock` es la única fuente runtime del permiso global. Se crea al arrancar en
`LOCKED`, vive en memoria y por eso un reinicio vuelve a bloquear. El TTL predeterminado es de
15 minutos (`AGENTE_JIRA_WRITE_LOCK_TTL_SECONDS`, acotado entre 60 y 3600 segundos).

Sólo el usuario local configurado (`AGENTE_JIRA_LOCAL_USER`) puede desbloquear. El modelo local
actual sólo distingue ese administrador; no se inventa un RBAC nuevo. Cualquier usuario
autenticado puede activar el kill switch. La autorización temporal no sustituye la política
funcional ni la confirmación final.

Antes de `session.call_tool("createJiraIssue", ...)`, el gateway comprueba atómicamente el
lock. Si está bloqueado o vencido, no se abre una llamada MCP de escritura y se registra un
evento sanitizado (`JIRA_WRITE_GLOBALLY_LOCKED` o `JIRA_WRITE_LOCK_EXPIRED`).

## API local

- `GET /api/jira/write-lock`
- `POST /api/jira/write-lock/unlock`
- `POST /api/jira/write-lock/lock`

Las respuestas sólo incluyen estado, TTL, actor y fechas; nunca OAuth, tokens ni payloads.

## Comportamiento

- Lecturas, catálogos, responsables, propuestas y dry-run funcionan en `LOCKED`.
- `UNLOCKED_TEMPORARY` expira automáticamente y pasa a `EXPIRED`.
- El bloqueo manual es inmediato y no elimina propuestas, dry-runs ni OAuth.
- La expiración o el kill switch no intentan revertir una escritura que ya comenzó; queda
  registrada en la auditoría existente como resultado real o incierto.

## Evidencia

La suite nueva cubre arranque bloqueado, desbloqueo autorizado, rechazo no autorizado, TTL,
kill switch, API y exposición del estado en conectividad. Los flujos 4B–4E conservan sus
políticas y gates funcionales; no se modificaron parser, OAuth, catálogos, dry-run ni voz.
