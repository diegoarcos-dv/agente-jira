# GATE G4 — Diagnóstico y cierre de Minutas deterministic-first

Fecha: 2026-09-17. Alcance: G4 únicamente. No se reejecutaron G1–G3, no se inició G5, no se descargaron modelos y no se habilitó ninguna escritura Jira.

## Resultado

**G4: NO APROBADO todavía.** La causa de `MINUTES_AI_DISABLED` quedó corregida y la Proposal, el preflight y el dry-run de solo lectura se completaron en el runtime de puerto 8001. Sin embargo, no quedó guardado el valor de `time_to_first_proposal_ms` de esa corrida, así que no se puede certificar el umbral solicitado de menos de 2 s. Tampoco se reenvió la minuta VIC-GIS completa: por la política de privacidad de G1 el texto original no está persistido; para G4 se reusaron los cinco fragmentos de evidencia literales guardados en la aceptación G2. La deduplicación de una copia completa está registrada en G2, pero no se vuelve a atribuir a la corrida G4.

El bloqueo de integración ya no es OAuth ni `JIRA_READY`: Atlassian estaba listo. Para cerrar G4 falta repetir la medición autenticada del fast path con el texto fuente íntegro disponible y conservar su respuesta/latencia. No se requiere cambiar el lock ni hacer una escritura Jira.

## Causa raíz y cambio

Antes del cambio, `MinutesService.status()` en `backend/app/minutes.py` devolvía `DISABLED / MINUTES_AI_DISABLED` inmediatamente si `minutes_ai_enabled` era falso. La UI sólo habilita “Analizar minuta” con estado `READY`. En `MinutesService.analyze()`, la ruta determinista se elegía sólo cuando `MINUTES_LLM_MODEL` y `MINUTES_ENRICHMENT_MODEL` eran ambos `qwen2.5:1.5b`; con el modelo principal vacío, el análisis alcanzaba el guard de estado y respondía 503. `_analyze_hybrid()` además preparaba enrichment en segundo plano sin distinguir si la IA estaba deshabilitada. Así, una bandera de IA desactivada deshabilitaba todo Minutas (normalización, parser y Proposal), aunque esas fases no requieren Ollama.

Fix mínimo aplicado después de explicar la causa: `status()` ahora informa `READY / MINUTES_DETERMINISTIC_READY / DETERMINISTIC_ONLY` si la IA está deshabilitada; `analyze()` elige el parser determinista en ese caso; y `_analyze_hybrid()` omite persistencia y tarea de enrichment cuando la IA está apagada. Se añadió cobertura para el fast path con Ollama fuera de línea. Archivos: `backend/app/minutes.py`, `backend/tests/test_minutes.py` y `backend/tests/test_minutes_deterministic.py`.

La respuesta de Proposal de esta corrida mostró además el aviso “la IA no pudo mejorar la redacción” aunque el enrichment se había deshabilitado intencionalmente. Es un mensaje impreciso de UX en `build_activities(..., None)`; no inició una llamada ni bloqueó la Proposal. Se deja registrado como observación; no se amplió el cambio de G4 para corregirlo.

## Configuración efectiva y Ollama

En la consola de diagnóstico, las variables relacionadas con Minutas no estaban definidas. Los defaults de `backend/app/config.py` y `.env.example` son:

| Configuración | Valor efectivo/default observado | Resultado |
| --- | --- | --- |
| `MINUTES_AI_ENABLED` | `false` (default si no está definida) | IA opcional apagada; Minutas determinista activa tras el fix |
| `MINUTES_LLM_MODEL` | cadena vacía | No se necesita para deterministic-only |
| `MINUTES_ENRICHMENT_MODEL` | `qwen2.5:1.5b` | Configurado como modelo opcional |
| `OLLAMA_BASE_URL` | `http://127.0.0.1:11434` | Endpoint local por default |
| `MINUTES_PROMPT_VERSION` | `minutes-v1` | Prompt legacy; el parser usa `minutes-enrich-v1` como metadato de Proposal híbrida |
| `MINUTES_ENRICHMENT_TIMEOUT_SECONDS` | `30` | Sin efecto cuando enrichment está apagado |
| `MINUTES_MAX_CHARS` | `30000` | Límite de texto |
| `MINUTES_TIMEOUT_SECONDS` | `120` | Timeout legacy |

No se pudo inspeccionar retrospectivamente el bloque de entorno completo heredado por el proceso Uvicorn; se informa por separado el default de código y el estado devuelto por runtime. `ollama --version` informó cliente 0.33.1. `ollama list` no pudo completarse porque el daemon de Ollama falló al arrancar. El manifiesto default para `qwen2.5:1.5b` no estaba presente. Con la evidencia disponible: **modelo no confirmado como instalado; no se descargó**. Ese fallo no impide el fast path determinista.

## Recorrido G4 y evidencia

| Elemento | Resultado comprobado |
| --- | --- |
| Runtime | Backend local en `127.0.0.1:8001`, reiniciado con el cambio |
| `GET /api/minutes/status` | `READY`, `MINUTES_DETERMINISTIC_READY`, `mode=DETERMINISTIC_ONLY`, `enrichment_state=DISABLED`, `ollama_available=false` |
| Parser/Proposal | Proposal `0897d6c9-6c98-449e-82cd-ad0575de2a05`, versión 1, proyecto VIC-GIS, fecha 2026-05-14, participante Monica Palacios/Líder Usuario, cinco actividades y `DETERMINISTIC_FALLBACK` |
| `source_evidence` | Los cinco fragmentos corresponden literalmente a la evidencia recuperada de la aceptación G2; se conservaron en la Proposal |
| `candidate_id` | El extractor determinista genera identificadores estables `ACT-###` y los mapea a ítems de Proposal. No se validó enrichment en runtime porque estaba desactivado |
| Tiempo fast path | El endpoint creó la Proposal sin esperar a Ollama. La captura cliente perdió el campo exacto; **no se certifica aquí `<2000 ms`**. La prueba backend comprueba el límite `<2000 ms` con TestClient, que no sustituye la medida runtime |
| Catálogo Work Types | Lectura real: Story (10016), Task (10017), Bug (10018), Epic (10019), Subtarea (10020). El preflight propuso Task (10017) para las cinco filas |
| `customfield_10147` | Campo real “Tipo de seguimiento”; opciones observadas: Proyecto estándar (10059), Actividad concreta (10060), Soporte (10061), Tarea extraordinaria (10062), Documentación (10063), Evaluación (10064) |
| Sprint | Catálogo leído: 646 `SPT-SEMANA-28-29-2026` (active) y 649 `SPT-SEMANA-30-31-2026` (future). El dry-run usó dinámicamente el Sprint 646 |
| Responsable | Consulta read-only de `Sistemas GIS` devolvió a Giselle Bello. No se asignó: la minuta sólo menciona el equipo, no una persona responsable |
| Verificar con Jira / dry-run | `POST /api/proposals/{id}/preflight` respondió 200; dry-run `DRY-51c684db18a7704ebc6f0580921bf59f`, versión 1, `stale=false`, `write_performed=false`, estado BLOCKED, 0 listas, 0 advertencias-listas y 5 bloqueadas |
| Causas del dry-run BLOCKED | Falta decisión de Tipo de seguimiento y responsable por fila (`TRACKING_TYPE_REQUIRED`, `ASSIGNEE_NOT_FOUND`). No se seleccionó una opción ni se asignó responsable por inferencia |
| Atlassian | OAuth/MCP listos; cuenta Jose Calleja; sitio `dpti.atlassian.net`; Space AT, Arquitecturas TI, id 10003; `JIRA_READY` |
| Lecturas Jira | Cuatro invocaciones MCP observadas: tres durante preflight y una búsqueda de responsable. La lectura de Sprint usó catálogo en caché |
| Seguridad | Global Write Lock `LOCKED`; `jira_write_enabled=false`; escrituras Jira = 0; llamadas `createJiraIssue` = 0 |

Excel y Minuta convergen en el mismo `ProposalService._build_proposal`, validador, versionamiento y repositorio SQLite. Excel conserva su parser de plantilla; Minuta añade normalización, deduplicación y extracción determinista. `source_evidence`, `candidate_id` y `extraction_mode=DETERMINISTIC_FALLBACK` son parte del camino Minuta; Qwen es opcional y no se ejecutó en este runtime.

## Pruebas y siguientes pasos de G4

`.venv\Scripts\python.exe -m pytest backend/tests/test_minutes.py backend/tests/test_minutes_deterministic.py -q` pasó **34 tests** (un aviso deprecado de Starlette). Las pruebas backend comprueban el estado determinista sin Ollama y un umbral `<2000 ms` en TestClient. Esto no sustituye la medición de la aplicación activa.

Para aprobar G4, repetir en la aplicación autenticada la aceptación read-only con la minuta VIC-GIS original completa, guardar `time_to_first_proposal_ms < 2000`, comprobar una copia duplicada eliminada y dejar evidencia del preflight/dry-run fresco. Mantener durante esa verificación `LOCKED`, cero Jira writes y cero `createJiraIssue`. No avanzar a G5.

## Intento de cierre final — 2026-09-17 19:15:37 -06:00

La interfaz local http://127.0.0.1:8001/ abrió en la pantalla de inicio de sesión; no había sesión autenticada disponible para esta corrida. El archivo de instrucciones apuntaba a la minuta, pero el archivo fuente completo de la aceptación anterior no está disponible en esa ubicación ni en los archivos de texto del workspace revisados. No se usó la fixture ni se sustituyó la minuta por los cinco fragmentos.

Por estas dos condiciones no se envió POST /api/minutes/analyze, no se creó Proposal y no se ejecutó Verificar con Jira ni dry-run en este intento. Lecturas Jira de este intento: 0; escrituras Jira: 0; createJiraIssue: 0. No se volvió a consultar el Global Write Lock, por lo que se conserva como evidencia sólo el estado LOCKED documentado por la corrida anterior. El cierre y el umbral runtime siguen pendientes; **G4 permanece NO APROBADO**.
