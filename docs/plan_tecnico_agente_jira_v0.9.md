# Plan técnico - Agente de generación controlada de work items en Jira

| Dato | Valor |
|---|---|
| Versión | 0.9 |
| Fecha | 17 de julio de 2026 |
| Estado | Objetivo 3A cumplido y verificado con Jira real |
| Plantilla de entrada | Excel v1.1 congelada |
| Ejecución actual | Local, Jira Cloud mediante Rovo MCP en solo lectura |

## 1. Objetivo 3A cumplido y verificable

Implementar una conexión local por usuario con el servidor oficial Atlassian Rovo MCP mediante OAuth 2.1 y transporte Streamable HTTP, descubrir el sitio `dpti.atlassian.net` y su `cloudId`, y consultar sin modificar Jira:

- los Spaces `AT`, `ASIT` y `MTTI`;
- sus Work Types;
- los campos disponibles y obligatorios de Epic, Story, Task, Bug y Subtask;
- responsables asignables mediante búsqueda;
- la identidad Atlassian que autorizó la conexión.

El Objetivo 3A **no crea, modifica, transiciona ni elimina actividades**. La escritura en Jira continúa fuera de alcance.

## 2. Arquitectura implementada

```text
Navegador React
  └─ sesión local de la aplicación
       └─ FastAPI
            ├─ coordinador OAuth 2.1 por usuario
            ├─ tokens y registro DCR sólo en memoria
            ├─ cliente MCP Streamable HTTP
            ├─ lista positiva de herramientas de lectura
            └─ Atlassian Rovo MCP
                 └─ Jira Cloud dpti.atlassian.net
```

El navegador nunca recibe el access token ni el refresh token de Atlassian. La aplicación conserva temporalmente dichos datos en memoria del proceso FastAPI; desconectar, cerrar sesión o reiniciar el proceso los elimina.

## 3. Autenticación OAuth 2.1

La aplicación usa el flujo interactivo recomendado para un escenario dirigido por usuario:

1. el usuario ya autenticado en la aplicación selecciona **Conectar mi cuenta Atlassian**;
2. FastAPI inicia descubrimiento OAuth y registro dinámico del cliente;
3. el navegador abre el consentimiento de Atlassian;
4. Atlassian devuelve `code` y `state` al callback local;
5. el backend valida `state`, intercambia el código con PKCE y mantiene los tokens en memoria;
6. el cliente inicializa una sesión MCP y ejecuta únicamente el diagnóstico de lectura.

Configuración predeterminada:

| Variable | Valor predeterminado |
|---|---|
| `AGENTE_JIRA_ATLASSIAN_MCP_URL` | `https://mcp.atlassian.com/v1/mcp/authv2` |
| `AGENTE_JIRA_ATLASSIAN_SITE_URL` | `https://dpti.atlassian.net` |
| `AGENTE_JIRA_ATLASSIAN_CALLBACK_URL` | `http://localhost:8000/api/integrations/atlassian/callback` |

La aplicación debe abrirse como `http://localhost:8000`; no se recomienda alternar con `127.0.0.1` durante el flujo, porque el almacenamiento de sesión del navegador depende del origen.

El flujo Dynamic Client Registration conserva sin modificaciones los parámetros y scopes emitidos por Atlassian, como exige el servidor de autorización. En el consentimiento el usuario puede desmarcar **Search** y **Write** y conservar **Read**. Independientemente de esa selección, el backend sólo expone su lista positiva de herramientas de lectura y rechaza cualquier nombre de escritura antes del transporte MCP.

## 4. Política de solo lectura

Existe una lista positiva en backend. Sólo pueden invocarse:

- `atlassianUserInfo`;
- `getAccessibleAtlassianResources`;
- `getVisibleJiraProjects`;
- `getJiraProjectIssueTypesMetadata`;
- `getJiraIssueTypeMetaWithFields`;
- `findAssignableUsers` o `lookupJiraAccountId`.

Cualquier otro nombre de herramienta se rechaza antes de alcanzar el transporte MCP. Las pruebas negativas cubren las cinco herramientas de escritura Jira publicadas por Atlassian: `addCommentToJiraIssue`, `addWorklogToJiraIssue`, `createJiraIssue`, `editJiraIssue` y `transitionJiraIssue`. Aunque Rovo las anuncie por los permisos generales de la organización, la aplicación no puede invocarlas durante el Objetivo 3A.

`localhost` y `127.0.0.1` forman parte de los dominios admitidos por Atlassian cuando **Allow Atlassian supported domains** está habilitado. Si la organización deshabilita esa opción, el administrador puede autorizar explícitamente `http://localhost:8000/**` o el patrón `http://localhost:*/**`.

## 5. API incorporada

| Operación | Propósito |
|---|---|
| `GET /api/integrations/atlassian/status` | Estado y diagnóstico sin tokens |
| `POST /api/integrations/atlassian/connect` | Iniciar OAuth 2.1 |
| `GET /api/integrations/atlassian/callback` | Recibir y validar el callback |
| `POST /api/integrations/atlassian/refresh` | Repetir el diagnóstico de lectura |
| `GET /api/integrations/atlassian/assignees` | Buscar responsables asignables |
| `POST /api/integrations/atlassian/disconnect` | Borrar credenciales en memoria |

## 6. Interfaz

El panel **Conexión Atlassian Rovo MCP** muestra:

- estado desconectado, conectando, consentimiento pendiente, conectado o error;
- sitio, `cloudId` e identidad autorizada;
- presencia de AT, ASIT y MTTI;
- Work Types y conteo de campos;
- buscador de responsables reales;
- acciones de actualizar diagnóstico y desconectar;
- aviso visible de que la escritura permanece bloqueada.

## 7. Verificación automatizada

- 30 pruebas de backend aprobadas.
- 8 pruebas de frontend aprobadas.
- TypeScript y compilación Vite de producción aprobados.
- Prueba negativa que intenta `createJiraIssue` y demuestra que el transporte recibe cero llamadas.
- Prueba de descubrimiento con transporte simulado para sitio, Spaces, Work Types y campos.
- Prueba de rutas OAuth que confirma que las respuestas no exponen `access_token` ni `refresh_token`.
- Handshake real previo al consentimiento aprobado: Atlassian devolvió una URL HTTPS en `auth.atlassian.com` con `state` y fase `AWAITING_USER_CONSENT`.
- El callback vuelve siempre a la interfaz; los fallos de grupos de tareas se aplanan, indican la etapa MCP y redactan códigos, estados y tokens.
- Si OAuth ya entregó tokens y falla el diagnóstico, **Reintentar diagnóstico** reutiliza exclusivamente las credenciales en memoria.

## 8. Evidencia de cierre del objetivo

El 17 de julio de 2026 se completó la prueba interactiva con un usuario autorizado:

1. completar el consentimiento OAuth;
2. confirmar que el sitio devuelto es `https://dpti.atlassian.net`;
3. confirmar que existe un `cloudId` no vacío;
4. confirmar visibilidad de AT, ASIT y MTTI;
5. comprobar Work Types y campos;
6. localizar al menos un responsable real;
7. se conservó disponible la acción de desconexión que elimina las credenciales mantenidas en memoria.

El diagnóstico final reportó fase `CONNECTED`, etapa `COMPLETE`, `cloudId` presente, cinco Work Types en cada uno de AT, ASIT y MTTI y búsqueda satisfactoria de responsables reales. La escritura permaneció deshabilitada y bloqueada. Esta prueba no creó actividades y fue segura para los Spaces productivos.

Hallazgo para el siguiente objetivo: el Work Type **Subtarea** de AT fue visible, pero Rovo devolvió cero campos para él; los otros catorce Work Types sí devolvieron metadatos. Debe resolverse antes de habilitar la creación de subtareas en AT.

## 9. Referencias técnicas

- [Getting started with Atlassian Rovo MCP](https://developer.atlassian.com/cloud/rovo-mcp/guides/getting-started/)
- [Configuring OAuth 2.1](https://developer.atlassian.com/cloud/rovo-mcp/guides/configuring-oauth-2-1/)
- [Supported tools](https://developer.atlassian.com/cloud/rovo-mcp/guides/supported-tools/)
- [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)
