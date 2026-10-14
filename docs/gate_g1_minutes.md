# GATE G1 — Minuta → propuesta local

## Auditoría y convergencia

El modelo vigente de Proposal se valida con `docs/schemas/jira_proposal_v1_1.schema.json`.
Una actividad es un `item` con `source`, `generated`, `validation`, `review` y `execution`.
La fuente requiere actividad, responsable textual, estado y referencia interna; un responsable
desconocido se representa como «Por definir», nunca como una cuenta Jira inventada.

Excel usa `POST /api/proposals` → `TemplateParser.parse` → `ParsedPlan` →
`ProposalService._build_proposal` → validador → `ProposalRepository.save`.
Minuta usa `POST /api/minutes/analyze` → normalización → Ollama HTTP → Pydantic →
validación de evidencia/deduplicación → `create_from_minutes` → **el mismo constructor,
validador y repositorio**. `ParsedPlan` se reutiliza como contenedor de datos normalizados;
no se invoca el parser ni se crea un XLSX. `template_version=1.2` conserva el contrato
interno compatible; `minutes` identifica inequívocamente el origen nuevo.

Las dos entradas convergen en SQLite `proposal_versions`, UUID y versión inicial 1.
Las correcciones reutilizan `PATCH /api/proposals/{id}/items/{row_id}`, incrementan versión
y conservan evidencia original y versiones previas. Los campos locales nuevos sólo se
admiten para propuestas de minuta. Modificar el candidato invalida su resolución; editar
otros campos conserva una resolución Jira previa si el candidato no cambia.

«Verificar con Jira» invoca el **preflight existente**, exclusivamente de lectura. A
continuación monta `ProposalReview`, con sus catálogos dinámicos, responsables, Sprint,
correcciones, aprobación y dry-run actuales. Ante fallo Jira muestra el error y permite
continuar revisando los campos en la interfaz existente. Nunca confirma ni ejecuta escrituras.
Los estados de revisión/confianza del LLM no autorizan creación.

## Configuración y disponibilidad

Variables de entorno del proceso (el archivo `.env.example` es documentación, no se carga solo):

| Variable | Valor inicial | Límite |
| --- | --- | --- |
| `MINUTES_AI_ENABLED` | `true` | Enrichment opcional tras el parser determinista; independiente de voz |
| `MINUTES_LLM_MODEL` | `qwen2.5:1.5b` | Nombre exacto de un modelo instalado |
| `MINUTES_MAX_CHARS` | 30000 | Configurable entre 100 y 100000 |
| `MINUTES_TIMEOUT_SECONDS` | 120 | Configurable entre 5 y 300 s |
| `OLLAMA_BASE_URL` | `http://127.0.0.1:11434` | Sólo loopback para minutas |

El modelo predeterminado de enrichment es `qwen2.5:1.5b`; no se descarga automáticamente.
Si el modelo local no está disponible, se conserva la Proposal determinista y el estado del enrichment explica el fallo.
Ollama se consume mediante el mismo patrón HTTP local que usa la voz (`httpx`, `/api/tags`,
`/api/chat`, mensajes system/user, JSON schema); no se toca el clasificador, los loaders ni
los locks de voz. No se heredan proxies del entorno para enviar las minutas a Ollama.

`GET /api/minutes/status`, autenticado, distingue `DISABLED`, `UNAVAILABLE` y `READY`.
Incluye nombre configurado, disponibilidad Ollama, existencia de modelo, límite y explicación.
La consulta no carga modelos. El análisis sí puede cargar en Ollama el modelo ya instalado.

`POST /api/minutes/analyze`, autenticado, recibe `{ "text": "..." }` y devuelve
`proposal_id`, `proposal` completo, `document`, `activities` y `warnings`. Rechaza menos
de 40 caracteres útiles, exceso de longitud, análisis simultáneo (409), IA ausente (503),
timeout (504), JSON/evidencia inválidos (422). Un único análisis activo por instancia;
no se reintenta automáticamente una petición fallida. El timeout abarca disponibilidad e inferencia.

## Contrato de IA y revisión

`backend/app/minutes.py` define `MinutesDocument`, `Participant` y `MinutesActivity` con
Pydantic y `extra=forbid`. Incluye tipo/fecha/proyecto/objetivo, participantes, actividades
con título, descripción, candidatos textuales, fecha candidata, sección, cita literal,
evidencias de atribución/plazo, tipo semántico `Task|Bug|Story`, inferencia y revisión.
No admite accountId, Sprint, option IDs, tipo de seguimiento ni padres/keys Jira.

Prompt versionado **`minutes-v1`**, en `backend/app/minutes_prompt.py`. Se envía como
system; la minuta se envía en otro mensaje user delimitado por un objeto JSON `document`.
Prioriza compromisos explícitos y pide deduplicación semántica antes de responder.
JSON inválido produce error: esta primera versión no realiza reparaciones automáticas.

El backend comprueba que cada cita exista en el texto; una cita inventada invalida la
extracción completa. Candidatos sin evidencia de atribución en la propia acción se limpian
y generan advertencia. Se exige evidencia de plazo, no sólo la fecha de reunión. Fechas
ISO, dd/mm/yyyy o «día de mes de año» explícitas se admiten; fechas relativas/otros formatos
no demostrables se dejan vacíos. Personas identificadas sólo como participantes no reciben
tareas. Equipos quedan como texto sin cuenta. Los cinco campos de catálogo se inician vacíos.

Todo queda en revisión, con vigencia y tipo por confirmar. Esto permite mostrar advertencias
y editar actividad, candidato, fecha, proyecto/frente, contexto y comentarios antes de Jira.
«Ver origen» muestra sección y cita; regresar a la minuta permite consultarlas tras preflight.

## Deduplicación y privacidad

1. Unicode NFKC, normalización de espacios y saltos de línea.
2. Eliminación de copias consecutivas del documento y bloques largos exactamente repetidos.
3. Prompt solicita unificar referencias semánticas a la misma acción.
4. Backend elimina sólo actividades con título/evidencia/candidatos/frente idénticos.
5. Evidencia compartida o títulos muy similares conservan ambas actividades con «Posible duplicado».

La similitud textual es una señal conservadora, no una prueba de equivalencia semántica.
La deduplicación de paráfrasis depende de la calidad del modelo y de revisión humana.

No se persiste el texto íntegro, el prompt ni la respuesta libre del modelo. Se persisten
localmente **el documento estructurado y los fragmentos de evidencia necesarios** dentro de
la propuesta JSON versionada. Un fragmento puede contener datos sensibles: recibe el mismo
control local de acceso y ciclo de vida de propuestas/papelera que el resto de la aplicación.
El hash identifica el documento normalizado. Logs sólo incluyen hash, caracteres, duración
y estado; el middleware existente añade request_id y métricas sin cuerpo de petición.

## Archivos

- Nuevos: `backend/app/minutes.py`, `backend/app/minutes_prompt.py`, `frontend/src/Minutes.tsx`.
- Integración: `backend/app/config.py`, `main.py`, `models.py`, `service.py`, esquema Proposal v1.1.
- Interfaz: `frontend/src/App.tsx`, `api.ts`, `types.ts`, `styles.css`.
- Configuración documentada: `.env.example`.
- Pruebas: `backend/tests/test_minutes.py`, `backend/tests/fixtures/minutes_vic_gis.txt`,
  `frontend/src/Minutes.test.tsx`.

## Aceptación y límites pendientes

El adjunto de alcance no incluía el texto original completo VIC-GIS. La fixture es una
**reconstrucción basada en los criterios proporcionados**, no el original del usuario.
La prueba determinista duplica el documento y obtiene cinco actividades únicas con fecha
14/05/2026, proyecto VIC-GIS y Monica Palacios como participante, sin asignación automática:

1. Confirmar implementación de ajustes pendientes por parte de Sistemas GIS.
2. Coordinar sesión conjunta con Soporte, Sistemas GIS, DDP y Equipo VIC.
3. Ejecutar pruebas integrales de los escenarios funcionales y técnicos.
4. Validar resultados finales y formalizar la aceptación del requerimiento.
5. Definir la fecha de liberación a Producción.

Advertencias esperadas: documento repetido, responsable sin resolver, vigencia/tipo por
confirmar. Campos Jira y fechas objetivo no documentadas permanecen vacíos. Son resultados
de fixture, no una afirmación sobre extracción IA del documento original.

Pruebas backend cubren entrada, disponibilidad, modelo ausente, JSON, evidencia, deduplicación,
participantes, equipos, fechas, proyecto, persistencia/versionado, timeout, concurrencia,
privacidad y conservación de Write Lock. Pruebas frontend cubren entrada, Excel, loading,
errores, resultado, warnings, edición, preflight explícito y ausencia de micrófono/escrituras.

La aceptación definitiva requiere la minuta original, selección/benchmark del modelo local
y validación de lectura contra los catálogos reales de AT. No se considera GATE G1 aprobado
por las pruebas con dobles. La extracción semántica nunca garantiza ausencia absoluta de
alucinaciones: las citas, los candidatos conservadores y la revisión obligatoria acotan el riesgo.

No se modificaron funcionalmente OAuth, MCP, Global Write Lock, idempotencia, preflight,
confirmación, Sprint, catálogos, resolución Jira, jerarquías ni voz. No hubo despliegue ni
descarga de modelos. Durante análisis: Jira reads = 0; Jira writes = 0; Write Lock = LOCKED.

## Registro documental al 2026-09-17 (sin reejecutar G1)

Este registro conserva la evidencia histórica y no vuelve a ejecutar el Gate. La aceptación de G2 dejó G1 backend aprobado para la ruta de creación de Proposal, pero dejó pendiente la inspección visual final de esa aceptación porque Jira estaba desconectado entonces. La revisión y el preflight de G4 no se contabilizan como una repetición de G1. Estado comprobable: backend **APROBADO**; cierre visual integral de G1 **PENDIENTE**.
