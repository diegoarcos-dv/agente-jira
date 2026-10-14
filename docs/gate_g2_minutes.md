# GATE G2 — Auditoría de extracción estructurada

Estado: **NOT_READY** (sin modelo aprobado para producción).

## Causa del 503 anterior

La aceptación VIC-GIS terminó en 503 después de 186.188 s (la traza HTTP
registró 186188.5 ms). El timeout configurado entonces era 300 s, por lo que
no fue el timeout del backend. La entrada normalizada tenía 6,696 caracteres,
se había pedido `num_predict=8192` y el contexto era 16,384. La implementación
anterior convertía cualquier `httpx.HTTPError` en el mismo 503 y no conservaba
el código de Ollama, así que el código HTTP de esa ejecución histórica no puede
recuperarse de sus registros.

La reproducción directa contra el mismo modelo y el mismo schema reveló el
fallo determinista: Ollama devuelve HTTP 400 (`failed to parse grammar`) al
inicializar el sampler para el JSON Schema de Pydantic. Por separado, Gemma4
también activa “thinking” por defecto; con `num_predict` pequeño consumió el
límite y dejó `message.content` vacío. Con `think:false` y JSON mode responde,
pero la extracción sigue siendo demasiado lenta para esta PC.

## Inventario local y equipo

| Elemento | Resultado |
|---|---|
| Ollama | 0.32.14 |
| Modelos instalados | `gemma4:e2b` únicamente |
| Familia / tamaño | gemma4 / 5.1B |
| Cuantización | Q4_K_M |
| Tamaño en disco | 7,162,405,886 bytes (7.16 GB) |
| Hardware observado | Windows 11 Home, 8 procesadores lógicos, 23.9 GB RAM, 11.5 GB libres |
| Aceleración | `ollama ps` mostró 100% CPU y 0 bytes VRAM |

No se ejecutó `ollama pull` ni se instaló otro modelo.

## Benchmark read-only

Se usó `scripts/benchmark_minutes.py`, el mismo `minutes-v1`, JSON mode,
`think:false`, temperatura 0, `num_predict=4096` y `num_ctx=16384`. No llama al
backend, no crea propuestas y no toca Jira.

| Dataset | Cold | Warm | JSON | Pydantic | Cobertura | Resultado |
|---|---:|---:|---|---|---:|---|
| A — VIC-GIS real duplicada | timeout 120 s | timeout 120 s | — | — | 0/5 | No operativo |
| B — 3 pendientes explícitos | 45 s: timeout; prueba extendida 65.8 s | — | sí | no | 0/3 | JSON sin estructura válida |
| C — participantes sin responsable | 45 s: timeout | — | — | — | 0/2 | No operativo |
| D — contexto largo | 45 s: timeout | — | — | — | 0/2 | No operativo |
| E — sin pendientes claros | 45 s: timeout | — | — | — | 0/0 | No operativo |

La medición simple de control (respuesta JSON de 6 tokens, sin extracción) fue
~2.5 s con `think:false`, frente a ~9.2 s con thinking activado. La diferencia
confirma que la demora pertenece a la inferencia estructurada, no a DNS,
conectividad o Jira. No se selecciona modelo: no cumple latencia ni Pydantic,
y la cobertura VIC-GIS no es evaluable.

## Cambios aplicados

- `MinutesError` ahora conserva categoría, reintento y código HTTP seguro de
  Ollama; no se mezclan timeout, indisponibilidad, JSON inválido, validación y
  contexto.
- La API devuelve `code` y `retryable` sin exponer cuerpos de Ollama.
- La interfaz traduce esas categorías a mensajes accionables.
- Gemma4 usa `think:false` y `format:"json"`; Pydantic y la verificación de
  evidencia siguen siendo la autoridad final. El schema grammar incompatible no
  se envía.
- El límite de salida se redujo a 4096 tokens para evitar una reserva excesiva;
  no se cambió el prompt versionado `minutes-v1`.
- Se añadió un benchmark reproducible read-only.

## Verificaciones y seguridad

- Backend: tests completos pasan; pruebas de minutos pasan (22).
- Frontend: 46 tests pasan; build Vite pasa.
- `GET /api/health`: `ok`.
- Estado de minutos: `READY` sólo significa que Ollama y el nombre del modelo
  existen; no implica que el modelo sea apto para extracción.
- Global Write Lock: `LOCKED`.
- Jira reads: 0 durante análisis/benchmark.
- Jira writes: 0; `createJiraIssue`: 0.

## Decisión

G2 queda **NOT_READY**. No se revalida ni se cierra G1 todavía. Se recomiendan
modelos locales con mejor rendimiento CPU y salida JSON estable para una futura
instalación autorizada, pero no se descarga ninguno en esta ejecución. No se
avanza a G3.

## Baseline adicional: `gemma3:1b`

La auditoría posterior confirmó que `gemma3:1b` ya estaba instalado (815 MB),
por lo que se probó sin descargar nada. Se mantuvieron `minutes-v1`,
`think:false`, `format:"json"`, temperatura 0, `num_ctx=16384`,
`num_predict=4096`, `keep_alive=0` para cold y valor por defecto para warm.

En VIC-GIS (6,575 caracteres originales → 3,284 normalizados, un bloque
duplicado removido), cold y warm agotaron 90 s sin respuesta. En B–E produjo
JSON HTTP 200 en aproximadamente 19–44 s, pero el objeto devuelto no contenía
la clave `activities` (devolvió campos de una actividad aislada), por lo que
Pydantic fue inválido y la cobertura fue 0. C también agotó 45 s en la pasada
warm. No se creó ninguna Proposal.

| Dataset | Cold | Warm | JSON | Pydantic | Correctas | Inventadas | Evidencia | Resultado |
|---|---:|---:|---|---|---:|---:|---|---|
| A — VIC-GIS real duplicada | timeout 90 s | timeout 90 s | — | — | 0/5 | — | — | NO APTO |
| B — 3 pendientes explícitos | 19.3 s | 19.1 s | sí | no | 0/3 | 0 contables | no evaluable | NO APTO |
| C — sin responsable | 25.9 s | timeout 45 s | sí/— | no/— | 0/2 | 0 contables | no evaluable | NO APTO |
| D — contexto largo | 33.8 s | 44.1 s | sí | no | 0/2 | 0 contables | no evaluable | NO APTO |
| E — sin pendientes | 24.6 s | 19.3 s | sí | no | 0/0 | 0 contables | no evaluable | NO APTO |

Conclusión de la baseline: **GEMMA3:1B_NO_APTO**. La calidad estructurada no
es utilizable y VIC-GIS no termina dentro de un límite UX razonable. La próxima
ronda recomendada es `qwen2.5:3b`, pendiente de autorización explícita para
descargarlo; no se ejecutó ningún `ollama pull`.

## `minutes-v2` — primera prueba de envelope

La auditoría de `minutes-v1` encontró una instrucción de “conforme al esquema”
sin enumerar la raíz ni todos sus campos, y el uso repetido de “acciones” como
concepto principal. `minutes-v2` reduce el prompt de 1,892 a 1,599 caracteres
(~473 a ~400 tokens estimados) y fija explícitamente la raíz
`document_type/date/project/objective/participants/activities`, prohibiendo
`actions`, `tasks`, `items`, `results` y `data` como raíces. Incluye skeleton
genérico y reglas compactas de evidencia/anti-alucinación. No incluye datos de
VIC-GIS.

Se detectó una incompatibilidad entre la solicitud del skeleton con `warnings`
y el Pydantic real (`MinutesDocument` usa `extra="forbid"` y no tiene ese campo).
Para no modificar G1 ni falsear la validación, v2 usa únicamente los campos del
modelo real; los warnings siguen siendo metadata generada por backend.

Con Qwen2.5 3B se probaron primero B y se detuvo antes de C/E: con
`num_ctx=8192`, `num_predict=1536`, `think:false`, `format:"json"`, temperatura 0
y timeout 90 s, B agotó cold y warm sin respuesta. Por regla de la fase no se
ejecutaron VIC-GIS ni una nueva ronda Gemma.

Resultado provisional: **QWEN_V2_NO_APTO** por latencia ya en el dataset corto;
la adherencia del envelope queda sin evidencia positiva porque no hubo respuesta.

## Tercera ronda: `qwen2.5:1.5b` + `minutes-v2`

Se descargó únicamente con autorización explícita. Ollama registró
`qwen2.5:1.5b`, 986 MB, familia qwen2, 1.5B y Q4_K_M (contexto del modelo
32,768). La prueba de corte B usó `num_ctx=8192`, `num_predict=1536`,
temperatura 0, `think:false`, `format:"json"`, cold `keep_alive=0`, warm por
defecto y timeout de 60 s.

| Dataset | Cold | Warm | Raíz | JSON | Pydantic | Actividades | Evidencia | Resultado |
|---|---:|---:|---|---|---:|---:|---|---|
| B — 3 pendientes explícitos | 25.8 s | 29.0 s | correcta | válida | válida | **1 (esperadas 3)** | 0 inválidas | NO APTO |

La respuesta es estructuralmente válida y contiene las tres frases esperadas,
pero las agrupa en una sola actividad. Eso no satisface “3 pendientes
detectados” como actividades separadas; no se aplicó ninguna expansión o
reparación. Por la regla de corte no se ejecutaron C, E, VIC-GIS ni D.

Conclusión: **QWEN1_5B_V2_NO_APTO**. El modelo es el más rápido de los
probados y respeta el envelope/evidencia en B, pero falla la granularidad mínima
de extracción. No se recomienda declararlo candidato sin una estrategia nueva
(otro modelo pequeño o extracción híbrida determinista + LLM), que queda para
una decisión posterior.

## Gemma3 + `minutes-v2` — prueba de corte B

Se ejecutó únicamente B, como exige la regla de corte, con Gemma3 1B,
`num_ctx=8192`, `num_predict=1536`, temperatura 0, `think:false`,
`format:"json"` y timeout 60 s.

| Dataset | Cold | Warm | Raíz | JSON | Pydantic | Evidencia |
|---|---:|---:|---|---|---|---|
| B — 3 pendientes explícitos | 49.9 s | 25.0 s | correcta | válida | **FAIL** | 3 citas no literales |

La raíz recibida sí fue `document_type/date/project/objective/participants/activities`
y se detectaron 3 actividades/cobertura lexical 3/3, pero las tres
`source_evidence` no existían literalmente en el texto normalizado. La validación
determinista las rechaza; no se reparó ni flexibilizó la evidencia. Por esta
falla se detuvieron C, E, A y D.

Conclusión: **GEMMA3_V2_NO_APTO**.

### Diagnóstico de Qwen v2 sin repetir benchmark

Los resultados ya capturados no muestran error HTTP ni caída del proceso: Qwen
respondía con tokens a baja velocidad en v1 (aprox. 2–5 tokens/s) y en v2 B no
alcanzó respuesta antes de 90 s. El patrón es compatible con inferencia CPU muy
lenta y generación que no finaliza a tiempo, no con un fallo de red; no hay
evidencia suficiente para afirmar un bloqueo de Ollama. No se repitió la corrida
larga.

## Segunda ronda: `qwen2.5:3b`

Se descargó únicamente con autorización explícita. Ollama registró
`qwen2.5:3b`, 1,929,912,432 bytes (1.93 GB), familia qwen2, 3.1B y Q4_K_M;
el contexto del modelo es 32,768. El benchmark mantuvo exactamente el contrato
base: `minutes-v1`, `think:false`, `format:"json"`, temperatura 0,
`num_ctx=16384`, `num_predict=4096`, cold con `keep_alive=0`, warm con el valor
predeterminado y timeout de 90 s.

VIC-GIS volvió a agotar 90 s en cold y warm. B–E respondieron JSON HTTP 200,
pero en los cuatro casos la raíz fue `actions` (no `activities`) y faltaron los
campos requeridos por `MinutesDocument`; Pydantic falló. No se transformó esa
salida para forzar un falso positivo.

| Dataset | Cold | Warm | JSON | Pydantic | Correctas | Inventadas | Evidencia | Resultado |
|---|---:|---:|---|---|---:|---:|---|---|
| A — VIC-GIS real duplicada | timeout 90 s | timeout 90 s | — | — | 0/5 | no evaluable | no evaluable | NO APTO |
| B — 3 pendientes explícitos | 65.3 s | timeout 90 s | sí (`actions`) | no | 0/3 evaluable | no evaluable | no evaluable | NO APTO |
| C — sin responsable | 25.7 s | 62.6 s | sí (`actions`) | no | 0/2 evaluable | no evaluable | no evaluable | NO APTO |
| D — contexto largo | 48.6 s | 82.2 s | sí (`actions`) | no | 0/2 evaluable | no evaluable | no evaluable | NO APTO |
| E — sin pendientes | 46.7 s | 59.0 s | sí (`actions`) | no | 0/0 evaluable | no evaluable | no evaluable | NO APTO |

Comparación con Gemma3 confirma que Qwen mejora la obediencia parcial a JSON y
la latencia en textos cortos, pero no cumple el contrato estructurado ni termina
VIC-GIS dentro del límite UX. No se declara `QWEN2.5:3B_APTO`, no se ejecuta una
segunda corrida VIC-GIS y no se crea Proposal. El fallo de forma es consistente
(`actions` vs `activities` más metadata ausente); debe decidirse después si es
insuficiencia del modelo o si `minutes-v1` necesita una versión explícita, pero
no se modifica el prompt en esta fase.

## Implementación G2: determinista primero + enriquecimiento

Se añadió `backend/app/minutes_deterministic.py`. El parser reconoce de forma
tolerante las secciones Pendientes, Acuerdos, Compromisos, Acciones, Próximos
pasos, Tareas y Seguimiento. Divide viñetas, numeración y líneas independientes;
una línea terminada en dos puntos conserva sus sublistas de equipos como una
sola acción. La evidencia y sus offsets se copian del texto normalizado y los
IDs `ACT-###` son estables. Las copias exactas se eliminan; las similares se
conservan marcadas para revisión.

El contrato `minutes-enrich-v1` (`backend/app/minutes_enrichment.py`) recibe
únicamente candidatos y exige exactamente un resultado por `candidate_id`.
Nunca puede modificar sección, evidencia ni cardinalidad. Un JSON inválido,
timeout (30 s), Ollama fuera de línea o discrepancia de IDs activa el mensaje:
“Las actividades fueron detectadas, pero la IA no pudo mejorar la redacción.”
En ese caso se conservan los candidatos deterministas. El modelo de enriquecimiento
por defecto es `qwen2.5:1.5b`; no se descargan modelos adicionales.

El endpoint usa `HYBRID_ENRICHED` cuando el enriquecimiento pasa validación y
`DETERMINISTIC_FALLBACK` cuando no. Una minuta sin sección explícita no inventa
tareas y puede producir una propuesta vacía para revisión (`activities: []`).

La prueba read-only `scripts/benchmark_minutes_hybrid.py` no usa la API de la
aplicación, no persiste propuestas y no toca Jira/MCP. En el benchmark local de
los datasets A–E, la fase determinista produjo 5/5, 3/3, 2/2, 2/2 y 0 tareas,
respectivamente; la evidencia fue válida y tardó 0–7 ms por dataset. A incluye
la minuta duplicada y eliminó un bloque repetido antes de extraer candidatos.

Corrida de enriquecimiento con el modelo ya instalado `qwen2.5:1.5b` (sin
descarga): A agotó el timeout de 30 s y quedó en `DETERMINISTIC_FALLBACK` con
5/5; B, C y D terminaron en `HYBRID_ENRICHED` con 3/3, 2/2 y 2/2 (26.2 s,
14.9 s y 9.5 s); E no llamó al LLM y quedó en 0/0.

## Aceptación final G2 — VIC-GIS real

Se ejecutó una única aceptación con el contenido completo proporcionado y sus
dos copias. La normalización eliminó 1 duplicado documental y el parser produjo
5 candidatos. El enrichment `qwen2.5:1.5b` agotó 30 s; el fallback conservó las
5 actividades y su evidencia literal. `POST /api/minutes/analyze` terminó en
30.6 s (normalización/dedupe 1 ms, parser 7 ms, enrichment/fallback 30.0 s).

La propuesta `6be1267f-1f1a-4896-81e7-a808f96aa8e3` se construyó con
`ProposalService._build_proposal`, quedó en versión 1 y persistió en SQLite.
La edición del primer ítem respondió 200 y creó versión 2; las otras cuatro
actividades permanecieron intactas. Se preservaron proyecto, fecha
`2026-05-14`, participante Monica Palacios/Líder Usuario, sección y evidencia;
no se asignaron responsables ni `accountId` automáticamente.

El botón de verificación invocó el flujo read-only existente y respondió 409 por
Atlassian desconectado; no se intentó reconectar. Durante analyze y verificación:
Jira reads 0, Jira writes 0, `createJiraIssue` 0. Global Write Lock permaneció
`LOCKED`. G2 queda **APROBADO**. G1 queda **APROBADO en backend** para esta
aceptación; la inspección visual interactiva de la UI no se ejecutó sobre la
base temporal y Atlassian permaneció desconectado, por lo que su cierre visual
final queda pendiente de abrir la propuesta en la interfaz activa.
Riesgo pendiente para G4: el enrichment en CPU puede consumir los 30 s antes de
activar el fallback.

## Registro documental al 2026-09-17 (sin reejecutar G2)

G2 conserva el resultado **APROBADO** de su aceptación histórica. En la auditoría/cierre de G4 no se repitió G2. El bloqueo de Minutas causado por `MINUTES_AI_ENABLED=false` se corrigió en G4 separando el parser determinista del enriquecimiento opcional; el detalle y las pruebas de ese cambio están en [gate_g4_minutes.md](gate_g4_minutes.md).
