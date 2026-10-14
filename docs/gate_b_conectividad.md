# GATE B: conectividad Jira

## Auditoría previa y plan

El health local sólo informa que FastAPI está activo. `/status` usa `connected`,
`phase`, `stage` y un snapshot; no demuestra vigencia actual de OAuth. La carga del
panel recupera `/status`, que restaura credenciales DPAPI con un lock por usuario.
El proveedor MCP gestiona PKCE, refresh y consentimiento. El almacenamiento cifra
tokens y cliente OAuth; no guarda una fecha absoluta de expiración propia.

`begin_connect` elimina la autorización anterior explícitamente; `disconnect` la
borra. La restauración fallida de DPAPI también borra el archivo: se debe conservar
para diagnóstico hasta que el usuario reconecte o desconecte.

Timeouts actuales: URL de autorización 30 s, callback posterior 90 s, HTTP 60 s,
proveedor OAuth 300 s. La espera de la cola del callback no tiene límite propio.
El callback cancela perdiendo el motivo y reduce otros fallos a `atlassian=error`.
El frontend borra el mensaje de cancelación al cargar estado. Fetch no tiene límite.
El refresh consulta todos los metadatos; requiere credenciales y no sirve como prueba
de MCP sin OAuth. No hay reintentos infinitos explícitos en esta capa.

Ya existen sitio, cuenta, spaces, herramientas, etapa y verificación en el snapshot.
No se deben mostrar tokens, cookies, cabeceras, códigos, state, PKCE ni respuestas
externas sin filtrar. `logger.exception` puede divulgar contenido del transporte.

Plan mínimo: diagnóstico independiente con estados por etapa y errores estables;
sonda HTTP/DNS orientativa sin bloquear OAuth; sesión MCP autenticada con únicamente
identidad, recursos y proyectos de lectura; resumen UI y recuperación; timeout de
consentimiento y callbacks diferenciados; pruebas aisladas sin Jira real.
Se preservan contratos funcionales, DPAPI, propuestas y políticas de escritura.

## Implementación y uso

En Configuración de Jira aparece Estado del sistema y la sección Diagnóstico.
`Probar conexión` llama al endpoint autenticado `POST /api/integrations/atlassian/diagnose`.
El resultado añade `diagnostic` al contrato anterior de estado. Cada comprobación
indica OK, FAILED, UNCONFIRMED o NOT_CHECKED, con fecha, duración y request id.
El backend local no basta para marcar Jira listo. Un resultado negativo invalida
el indicador de conexión; un fallo de AT mantiene identificados OAuth y sitio.

Los códigos distinguen red/DNS, MCP inaccesible o timeout, autorización requerida,
pendiente, vencida, inválida, cancelada, timeout de consentimiento, callback/state
inválidos, configuración incorrecta, cuenta no identificada, sitio no visible,
permisos insuficientes, AT no accesible y capabilities faltantes.

La sonda DNS/HEAD es orientativa y jamás bloquea por sí sola un intento OAuth.
401/403 en HEAD significa que el servidor responde, no que haya autorización.
Con credenciales, se inicializa una sesión MCP y se prueban exclusivamente
`atlassianUserInfo`, `getAccessibleAtlassianResources` y `getVisibleJiraProjects`.
Se inspeccionan las herramientas anunciadas, sin invocar ninguna de escritura.
La consulta de proyectos pagina hasta 20 páginas; si no puede demostrar una lista
completa no adivina que AT esté ausente.

Reintentar repite la comprobación de conectividad sin iniciar consentimiento ni
consultar todos los campos Jira. Si la conectividad se recupera pero el snapshot
funcional nunca llegó a cargarse, se ofrece restaurar conexión con la autorización
guardada, reutilizando el refresh existente. Sólo esa recuperación carga los
metadatos funcionales que la sesión necesita.

## OAuth, tiempos y seguridad

Se conserva el formato cifrado DPAPI y la gestión de refresh del SDK. Un archivo
que no se puede descifrar se informa como inválido y se conserva hasta una acción
explícita de reconexión/desconexión. El frontend reconstruye el estado desde backend.
Se muestra una expiración conocida por el SDK; una revocación remota sólo puede
confirmarse contactando Atlassian. Las fechas de comprobación hacen visible la
antigüedad de la evidencia; no se promete supervisión continua.

DNS: 3 s; HEAD: conexión 3 s / lectura 5 s; sesión diagnóstica: conexión 5 s /
lectura 10 s, máximo global MCP 30 s. Consentimiento: 300 s. Restauración/refresh
de metadatos: 90 s. Frontend: diagnóstico 45 s, conectar 40 s, estado/refresh 100 s.
No se agregan reintentos automáticos de escrituras ni llamadas a propuestas.

El callback consume state una sola vez; cancelación y expiración se conservan como
motivos visibles. Se elimina state al terminar. Las consultas OAuth del access log
se ocultan y el log del SDK no emite tracebacks con cuerpos OAuth. El diagnóstico
publica sólo códigos y tipos de excepción, nunca respuestas externas arbitrarias,
tokens, cookies, cabeceras o PKCE. El log de diagnóstico incluye fecha, fase,
duración, resultado, categoría y request id.

## Archivos

- `backend/app/connection_diagnostics.py`: modelo, clasificación, sondas y logs seguros.
- `backend/app/atlassian.py`: integración del diagnóstico, callback acotado y recuperación.
- `backend/app/main.py`: endpoint autenticado y retorno diferenciado de callbacks.
- `frontend/src/api.ts`, `types.ts`, `App.tsx`: contrato, tiempos y acciones.
- `frontend/src/JiraDiagnostics.tsx`: resumen por etapa y detalles.
- `backend/tests/test_connection_diagnostics.py` y `frontend/src/JiraDiagnostics.test.tsx`.

## Evidencia local

Suite backend: 186 pruebas aprobadas (158 existentes y 28 nuevas).
Suite frontend: 36 aprobadas (33 existentes y 3 nuevas).
TypeScript y Vite: compilación correcta en `outputs/gate-b-build`.
La instancia abierta no se reinició y su `frontend/dist` no se reemplazó.

Escenarios E2E simulados mediante transporte MCP falso + API local y panel React:

| Escenario | Resultado | Evidencia |
|---|---|---|
| A: correcto | JIRA_READY | Backend, MCP, OAuth, cuenta, sitio, AT y capabilities OK |
| B: OAuth vencido | OAUTH_EXPIRED | Acción reconectar; no se comunica Jira listo |
| C: MCP inaccesible | MCP_UNREACHABLE | Backend OK, MCP fallido, recuperación sin nuevo OAuth |
| D: AT no visible | SPACE_UNAVAILABLE | OAuth y sitio OK, AT fallido |

También se prueban permisos, callback/state inválidos, cancelación, consentimiento
incompleto con timeout real reducido para la prueba, configuración inválida,
restauración desde archivo cifrado en un manager nuevo, recarga del panel,
Probar conexión/Reintentar, protección de logs y diagnóstico sin secretos.
Las sesiones falsas registran cada herramienta y rechazan `createJiraIssue`;
las aserciones verifican la lista estricta de tres herramientas de lectura.
No se llamó a Jira real ni se desplegó el cambio. La aceptación interactiva con
una cuenta real queda a cargo de una sesión local autorizada posterior.

## Límites conocidos

No se puede deducir que todo Internet esté disponible comprobando sólo un host;
por eso DNS fallido con proxy funcional se presenta como no confirmado.
Las capabilities anunciadas no equivalen a permisos de creación: este Gate sólo
comprueba permisos de consulta y refleja la política de escritura existente.
La suite mantiene un warning preexistente de deprecación de Starlette/AnyIO.
