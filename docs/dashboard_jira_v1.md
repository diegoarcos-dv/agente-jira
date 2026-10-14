# Dashboard Jira V1

## Arquitectura

`backend/app/dashboard.py` contiene el lector del Dashboard, normalización, agregaciones y snapshots. Su alcance de lectura es `DASHBOARD_READ_SPACE_KEYS = ("ASIT", "AT", "BD", "MTTI", "OPC")`. Cada llamada Jira atraviesa el wrapper de solo lectura existente en `AtlassianIntegrationManager._invoke_with_session`, que comprueba `READ_ONLY_TOOL_ALLOWLIST` antes de usar MCP. El módulo no llama a `createJiraIssue` ni importa los servicios de escritura.

El lector obtiene los proyectos con `action=browse`, descubre Work Types y metadatos de prioridad, Sprint y `customfield_10147`, y pagina los issues por proyecto. La misma lectura genera status, KPIs, workload, fechas, Epics, Sprints y los datos del drill-down. Las gráficas usan la instantánea local; no crean una consulta Jira por cada visualización.

El frontend es `frontend/src/Dashboard.tsx`, enlazado desde la navegación en `frontend/src/App.tsx`. Utiliza gráficas SVG/HTML accesibles y estilos del proyecto; no agrega dependencias. General y las pestañas ASIT, AT, BD, MTTI y OPC usan el mismo formato de snapshot.

## Endpoints

Todos requieren la sesión local autenticada.

| Método | Ruta | Uso |
| --- | --- | --- |
| GET | `/api/dashboard/status` | Snapshot disponible, antigüedad, última duración y estado de refresh. |
| GET | `/api/dashboard/summary` | Métricas globales y las cinco filas por Space. |
| GET | `/api/dashboard/spaces/{key}` | Métricas, catálogos y estado de Sprint/Epic/seguimiento de un Space. |
| GET | `/api/dashboard/issues` | Drill-down paginado desde el snapshot. Filtros: `space`, `category`, `type`, `work_type`, `priority`, `assignee`, `tracking`, `epic`, `overdue`, `unassigned`, `page`, `page_size`. |
| POST | `/api/dashboard/refresh` | Programa lecturas Jira en segundo plano; devuelve `ACTUALIZANDO`. No escribe en Jira. |

`GET /api/dashboard/issues` devuelve Key, Summary, Space, Status original y categoría, Assignee, Priority, Due date y Work Type. Un enlace abre Jira sólo si la Key pasa la comprobación local de formato.

## Snapshot y refresh

Los snapshots JSON se guardan en `database_path.parent/dashboard_snapshots`, separados por hash de usuario. El nombre del archivo no revela el nombre de cuenta. `os.replace` publica la nueva instantánea de manera atómica después de una extracción completa de los cinco espacios.

El Dashboard muestra el snapshot existente de inmediato. El refresh es manual. Si falla una página, un espacio, permisos o Jira responde con rate limit, el backend conserva la última instantánea completa y muestra `STALE`, `PARTIAL`, `NO_PERMISSION`, `RATE_LIMITED` o `ERROR`. Nunca publica una mezcla parcial de edades.

Las consultas se ejecutan secuencialmente y la página de issue tiene hasta 100 items. En HTTP 429 se respeta `Retry-After` sólo si está disponible y está entre 1 y 60 segundos, con un máximo de un reintento por operación. La instantánea anterior permanece en uso si el reintento falla. El refresh no programa actualizaciones periódicas.

## Métricas y normalización

- Los estados conservan el nombre Jira y se agrupan por `statusCategory`: `new` = Por hacer, `indeterminate` = En progreso, `done` = Finalizadas. Otra categoría cuenta por separado y hace visible la cobertura desconocida.
- El vencimiento aplica a issues no finalizadas con `duedate` anterior al día actual en `America/Mexico_City`; próximas incluye hoy y los siguientes siete días.
- Actividad y creación recientes son ventanas móviles de siete y treinta días. Completadas en siete días requiere `resolutiondate`; fechas ausentes o inválidas dejan el dato `PARTIAL`/`N/D` y no se sustituyen por `updated`.
- Work Types conservan su ID, subtask y nivel jerárquico por Space. La vista global reúne nombres y conserva los IDs locales al lado.
- Prioridades conservan el ID y nombre devueltos por Jira. Sin prioridad aparece como categoría explícita.
- Workload cuenta issues activos por accountId internamente, agrupa identidades entre espacios y sólo devuelve `displayName` al Dashboard. No representa capacidad.
- El avance Epic requiere enlaces directos `parent.key`. Usa Done/hijos visibles. Si no hay hijos, el porcentaje es `N/D`. Un alcance visible limitado se etiqueta `PARTIAL`.
- Sprint muestra el estado que Jira reporta y fechas de inicio/fin. Si marca active con fecha fin pasada, se muestra una advertencia sin modificar Jira. El catálogo se limita a Sprints encontrados en issues visibles: MCP no enumera Sprints vacíos.
- `customfield_10147` sólo se muestra si los metadatos del Work Type lo exponen; opciones, cobertura y valores vacíos quedan separados.
- BD y OPC no tienen una regla fija por key. El badge “Sin actividad reciente” se deriva de 30 días sin issues actualizados.

## Seguridad y datos locales

El scope de lectura no modifica `TARGET_SPACES`, `allowed_spaces`, políticas, `jira_write_enabled`, `GlobalJiraWriteLock` ni sus gateways. La interfaz no tiene acciones de escritura Jira. Los IDs de cuenta no salen del agregador ni se guardan en el snapshot; se conservan hashes internos para agrupar responsables entre Spaces. Resúmenes y campos de issues quedan como JSON en el disco local del usuario; no salen hacia otro servicio. No se consultan comentarios, adjuntos ni descripciones completas.

El owner del snapshot debe coincidir con el usuario autenticado antes de cargarlo. `jira_write_enabled` proviene de la política efectiva y el bloqueo se lee del estado del lock existente. Las lecturas siguen siendo de solo lectura incluso cuando se muestre ese estado.

## Estados UX

`ACTUALIZADO`, `ACTUALIZANDO`, `STALE`, `PARTIAL`, `NO_DATA`, `NO_PERMISSION`, `JIRA_DISCONNECTED`, `RATE_LIMITED` y `ERROR` se comunican en texto y no sólo por color. Durante un refresh, las gráficas anteriores continúan visibles. Se informa la última actualización, duración, issues, páginas, lecturas Jira, llamadas MCP, errores, timeouts y 429.

## Pruebas

Backend: `python -m pytest backend/tests/test_dashboard.py -q`. Los tests cubren el scope separado y la política actual de solo lectura, normalización y métricas, cinco Spaces, paginación de refresh, workload y privacidad de identificadores, drill-down, snapshot atómico, 403, 429, fallos parciales y endpoints autenticados.

Frontend: `pnpm test -- src/Dashboard.test.tsx`. Los tests cubren General y cinco pestañas, KPIs, drill-down y enlace seguro, Sprint vencido, Tipo de seguimiento, refresco manual, snapshot existente y estados parciales/sin datos.

Build: `pnpm build`.

## Limitaciones conocidas

No se recupera el lead del proyecto ni se descubren Sprints vacíos con las herramientas MCP disponibles. El historial de transición de Jira no se consulta; la fecha de completado mide la resolución actual y queda parcial si falta `resolutiondate`. Las relaciones Epic cubren issues visibles en cada Space. La cuenta puede no ver issues restringidos. La primera extracción en un sitio con ~1,100 issues tarda cerca de 45 segundos; por eso la V1 depende de un snapshot y refresco manual.

## Validación de cierre — 2026-09-18

- Suite backend completa: pasó. Suite frontend: 54 tests pasaron. `pnpm build`: pasó.
- La interfaz compilada abre en la aplicación local y muestra General, ASIT, AT, BD, MTTI y OPC. El estado de conexión/bloqueo no se declara confirmado hasta que responda el endpoint de status.
- La instancia de `127.0.0.1:8001` todavía atiende la versión previa del backend. La solicitud a `/api/dashboard/status` devuelve la aplicación HTML en vez del JSON del módulo y el frontend explica que se requiere reiniciar el backend.
- No se inició un refresh Dashboard ni se hicieron lecturas Jira desde este módulo en esta corrida; por lo tanto no hay snapshot Dashboard ni métricas live nuevas que reportar. La auditoría previa en `artifacts/dashboard-audit-2026-09-18/AUDITORIA_DASHBOARD_JIRA.md` es sólo el baseline aceptado, no evidencia de aceptación live de esta implementación.
- El proveedor de sesión local mantiene los tokens en memoria del proceso (`LocalAuthProvider._sessions`). Reiniciar el backend invalidará la sesión local actual. El shell de trabajo no tiene configurada `AGENTE_JIRA_LOCAL_PASSWORD`, así que después del reinicio alguien tendrá que iniciar sesión en la interfaz para poder validar el refresh. No se intentó leer ni recuperar esa credencial.
- Jira writes y `createJiraIssue`: 0. Global Write Lock y `jira_write_enabled` están cubiertos como bloqueados/deshabilitados en pruebas y código; el Dashboard live no pudo leer su status hasta reiniciar la instancia.

Resultado: implementación y verificaciones automatizadas completas, aceptación live pendiente del reinicio autenticado del backend, refresh de los cinco Spaces y comprobación final del bloqueo desde la nueva API.
