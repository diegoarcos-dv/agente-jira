# Agente Jira — aplicación local

Agente Jira convierte una minuta o plantilla Excel en actividades revisables para Jira Cloud. Consulta catálogos, responsables y sprints mediante Atlassian OAuth/Rovo MCP y conserva versiones en SQLite. La escritura real se limita al Space `AT`, exige revisión y confirmación explícita dentro de la aplicación, y no tiene reintentos automáticos.

La plantilla operativa actual es la v1.3. El producto conserva compatibilidad de lectura con versiones anteriores; la versión de plantilla y la versión del producto son conceptos distintos.

## Requisitos

- Windows o Linux local.
- Python 3.12+.
- Node.js 20+ (Node 24 también es compatible).
- pnpm.
- Una cuenta Atlassian con acceso al sitio y al Space `AT` para los flujos Jira.
- OAuth Atlassian configurado para `http://localhost:8000/api/integrations/atlassian/callback`.

La voz es opcional y está deshabilitada por defecto. Whisper, Piper y Gemma se cargan o consultan sólo cuando la configuración y el uso real lo requieren.

## Configuración local

El flujo normal inicia sesión con Atlassian OAuth y crea una sesión HttpOnly por usuario. No requiere una contraseña local.

`.env.example` es una referencia. Para el enlace opcional del Radar, `scripts\start.ps1` lee únicamente `NEWS_TELEGRAM_URL` desde `.env`. La recuperación local es una compatibilidad de emergencia, deshabilitada de forma predeterminada; si se habilita explícitamente con `AGENTE_JIRA_EMERGENCY_LOCAL_AUTH_ENABLED=true`, entonces requiere `AGENTE_JIRA_LOCAL_PASSWORD`.

## Instalación y arranque

Desde la raíz del proyecto:

```powershell
scripts\setup.cmd
scripts\doctor.ps1
scripts\dev.cmd
```

`setup` prepara `.venv` e instala backend/frontend. `doctor` valida Python, Node, pnpm, dependencias, SQLite, configuración, credencial local y puertos. `dev` inicia backend y frontend en modo desarrollo.

Para el arranque compilado:

```powershell
scripts\start.cmd
```

El inicio compilado usa la política `CONTROLLED_HIERARCHY_BATCH`: permite hasta cinco actividades reales en `AT` después de una confirmación explícita. El `Global Write Lock` inicia bloqueado y el botón **Escribir en Jira** abre una ventana temporal sólo para ese envío.

## Flujo de uso

1. Inicia sesión con tu cuenta corporativa de Atlassian.
2. La autorización se guarda cifrada para el usuario actual de Windows mediante DPAPI.
3. Descarga la plantilla dinámica v1.2 desde `/api/template/v1.2`. El catálogo `Tipo de seguimiento` se obtiene de Jira; si Jira no está disponible, el resultado queda marcado como `unavailable` y no inventa opciones.
4. Carga el Excel, corrige los pendientes y guarda cada corrección como una nueva versión de propuesta.
5. Ejecuta la prevalidación y el Dry run de sólo lectura. Una corrección posterior invalida el Dry run anterior.
6. Revisa responsables, Sprint, catálogos, Work Type y relaciones padre-hijo.
7. El flujo termina en una confirmación visible. Sin política y desbloqueo explícitos no se llama `createJiraIssue`.

La política 4E permite, en el modo controlado correspondiente, `Task`, `Bug`, `Story`, `Epic` y `Subtask` en `AT`, con máximo cinco elementos. Las relaciones válidas son `Epic → Task/Bug/Story` y `Task/Bug/Story → Subtask`. Referencias inexistentes, ciclos y tipos incompatibles se bloquean antes de escribir.

## Modos controlados

Detén cualquier instancia que use el puerto 8000 antes de cambiar de modo:

```powershell
scripts\start-objective-4b.cmd   # una Task canaria
scripts\start-objective-4c1.cmd  # lote de Tasks
scripts\start-objective-4d.cmd   # Task/Bug/Story
scripts\start-objective-4e.cmd   # jerarquías y voz bajo demanda
```

El arranque de un modo no escribe en Jira. La escritura requiere propuesta aprobada, Dry run vigente, preflight limpio, Write Lock desbloqueado por un usuario autorizado y confirmación final dentro de la aplicación. No se reintenta automáticamente.

## Diagnóstico y recuperación

La pantalla de diagnóstico muestra backend, MCP, OAuth, cuenta, sitio, Space, capacidades, Write Lock, rendimiento y voz. Los endpoints útiles son:

- `GET /api/health`
- `GET /api/integrations/atlassian/status`
- `POST /api/integrations/atlassian/diagnose`
- `GET /api/jira/write-lock`
- `GET /api/diagnostics/performance`
- `GET /api/voice/status`
- `POST /api/voice/activate`

Problemas frecuentes:

- Python o `.venv` incorrectos: ejecuta `scripts\setup.cmd` y luego `scripts\doctor.ps1`.
- Node/pnpm ausente: instala Node.js 20+ y pnpm, y vuelve a ejecutar `setup`.
- Puerto ocupado: detén el proceso indicado por `doctor`.
- OAuth vencido o DPAPI ilegible: usa **Reconectar cuenta**; no borres credenciales manualmente.
- MCP o Space `AT` inaccesible: revisa red, VPN, sitio y permisos Atlassian.
- Responsable no encontrado, Sprint inválido o catálogo obsoleto: corrige el valor y guarda una nueva versión.
- Write Lock bloqueado: confirma el envío desde **Escribir en Jira**; la aplicación abre la ventana temporal y vuelve a bloquear al terminar.
- Ollama apagado o Gemma ausente: la voz queda degradada y Jira sigue funcionando.
- Whisper no cacheado o Piper faltante: el primer uso de voz puede quedar no disponible; activar voz no descarga modelos.

## Seguridad y límites

- `.env`, OAuth DPAPI, SQLite, modelos, caches, logs y salidas generadas están excluidos por `.gitignore`.
- Los logs de OAuth se sanitizan y conservan request IDs sin tokens, cookies, cabeceras `Authorization` ni payloads sensibles.
- GATE F no despliega ni ejecuta una escritura Jira real automáticamente.
- El almacenamiento y autenticación local no sustituyen un IAM productivo.
- El workspace validado no contiene metadata Git; no hay release diff ni commit reproducible.

## Estructura

- `backend/`: API FastAPI, parser, reglas, SQLite, OAuth/MCP y servicios de voz.
- `frontend/`: React/TypeScript.
- `config/`: políticas 4B–4E y política segura por defecto.
- `releases/plantilla_excel_v1_2/`: plantilla v1.2 congelada de referencia.
- `docs/gate_*.md`: evidencia detallada de Gates A–F.
- `scripts/`: setup, doctor, arranque y pruebas.

## Pruebas

```powershell
scripts\test.cmd
```

El comando ejecuta la suite backend, Vitest frontend y el build TypeScript. Las pruebas de voz y los smoke tests no descargan modelos ni escriben en Jira.

La evidencia y el estado final de release se mantienen en [docs/gate_f_release_readiness.md](docs/gate_f_release_readiness.md).
