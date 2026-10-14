# Gate Voz 1 — agente local controlado por botón

Fecha de cierre técnico: 2026-08-17.

## Alcance entregado

La aplicación incorpora un asistente de voz autenticado y local. La grabación empieza sólo
cuando el usuario pulsa `Hablar` y termina al pulsar `Detener` o al alcanzar 60 segundos. No
hay palabra de activación, escucha permanente, TTS ni persistencia intencional de audio.

El flujo implementado es:

```text
Botón React -> MediaRecorder -> POST autenticado -> faster-whisper local
 -> texto -> Gemma local en Ollama -> intent Pydantic
 -> registro determinista -> compuerta READ_ONLY -> servicios de consulta existentes
 -> respuesta textual
```

El modelo no recibe acceso a Jira, MCP, políticas, sistema operativo, comandos ni funciones.
Whisper transcribe y Gemma clasifica; ninguno ejecuta acciones.

## Resultado de Gate Voz 0

Antes de modificar el proyecto se inspeccionaron la API FastAPI, la autenticación Bearer, el
repositorio SQLite, el servicio de propuestas, la integración Atlassian, las políticas de
ejecución 4A–4E, la aplicación React, sus pruebas y los scripts locales.

Línea base registrada antes de cambios:

- backend: 96 pruebas aprobadas;
- frontend: 13 pruebas aprobadas en 2 archivos;
- build TypeScript/Vite: aprobado.

Los servicios de escritura Jira existentes no se modificaron ni se exponen al subsistema de
voz. La compuerta de voz es independiente del modo general: incluso al arrancar con Objetivo
4E, sólo habilita riesgo `READ_ONLY`.

## Comandos habilitados

| Intent | Nivel | Resultado |
|---|---|---|
| `help` | `READ_ONLY` | Explica las consultas disponibles |
| `get_app_status` | `READ_ONLY` | Estado local y cantidad de propuestas activas |
| `get_jira_status` | `READ_ONLY` | Estado de conexión ya conocido por la aplicación |
| `get_current_proposal_summary` | `READ_ONLY` | Resumen de la propuesta visible o más reciente |
| `list_validation_errors` | `READ_ONLY` | Errores y total de advertencias |
| `list_pending_items` | `READ_ONLY` | Actividades pendientes de revisión |

Los niveles preparados son `READ_ONLY`, `LOCAL_WRITE`, `JIRA_WRITE` y `FORBIDDEN`. Sólo el
primero está habilitado. Solicitudes como `prepare_task`, crear, modificar, borrar, confirmar,
enviar a Jira, cambiar políticas o ejecutar comandos se rechazan con un mensaje seguro. La
respuesta siempre declara `requires_confirmation: false` porque la voz no puede llegar a una
operación que necesite confirmación.

## Límites y tratamiento del audio

- Endpoint: `POST /api/voice/command`, protegido por la sesión Bearer existente.
- Formatos: WebM/Opus, Ogg/Opus, MP4/M4A, MP3 y WAV.
- Tamaño predeterminado: 10 MB.
- Duración predeterminada: 30 segundos.
- Tiempo total predeterminado: 60 segundos.
- El navegador detiene la captura al llegar al límite de duración.
- El servidor vuelve a validar tamaño, formato y duración.
- El archivo temporal usado por Whisper se elimina en un bloque `finally`, también ante error.
- El audio y la transcripción no se escriben en logs ni en la base de datos.

## Dependencias locales y arranque

`faster-whisper` está fijado en `1.2.1`, versión publicada en PyPI. Se carga sólo al usar la voz,
por lo que el servidor puede arrancar si STT está deshabilitado o la dependencia todavía no está
disponible. El modelo Whisper se reutiliza después de la primera carga.

El equipo local detectado dispone de Ollama y del modelo `gemma3:1b`. El script usado para este
entorno habilita la voz sin cambiar la compuerta de seguridad:

```powershell
scripts\start-objective-4e.cmd
```

Ese script configura `tiny`, idioma `es`, CPU con `int8`, Ollama local y `gemma3:1b`. La CPU se
fija explícitamente porque la detección automática puede seleccionar CUDA aunque las bibliotecas
`cublas` necesarias no estén instaladas. En esta instalación el
modelo `tiny` quedó precargado en la caché local; en otro equipo el primer uso puede descargarlo.
Las consultas inequívocas y las solicitudes de escritura se clasifican primero mediante reglas
locales cerradas; Gemma queda como respaldo para paráfrasis ambiguas. Así se evita el arranque en
frío del modelo en los comandos habituales sin ampliar las capacidades de solo lectura.
Para el modo normal se pueden definir
las variables de `.env.example` en el entorno antes de ejecutar `scripts\start.cmd`; el archivo
`.env.example` es sólo referencia y no se carga automáticamente.

Si se desea arrancar sin voz, se usa el modo normal sin definir las variables, o se configura:

```powershell
$env:VOICE_STT_ENABLED = "false"
$env:VOICE_AI_ENABLED = "false"
```

## Interfaz

- Botón flotante inferior derecho con estados `IDLE`, `LISTENING`, `PROCESSING`, `SUCCESS` y
  `ERROR`.
- Etiquetas accesibles, foco visible y estado pulsado durante grabación.
- Panel compacto, cerrable y con transcripción, resultado y sello de sólo lectura.
- Tema claro/oscuro antes de la identidad del usuario en el encabezado.
- Preferencia guardada en `localStorage`; en el primer uso respeta `prefers-color-scheme`.
- Colores principales centralizados como variables CSS semánticas, sin cambiar el layout.

## Contrato de respuesta

```json
{
  "transcript": "resume la propuesta",
  "intent": "get_current_proposal_summary",
  "status": "completed",
  "message": "Plan de trabajo, versión 1: ...",
  "requires_confirmation": false
}
```

`status` puede ser `completed` o `needs_clarification`. Una confianza inferior a 0.70 no ejecuta
ni siquiera una lectura y solicita repetir la consulta.

## Pruebas agregadas

Backend:

- esquema Pydantic cerrado y rechazo de campos de tool-calling;
- registro y niveles de riesgo;
- rechazo de escrituras independiente de la política general;
- baja confianza y duración máxima;
- autenticación, formato, subsistema deshabilitado y contrato HTTP;
- dobles de Whisper/Gemma, sin red, Jira, Ollama ni modelos durante las pruebas.

Frontend:

- captura únicamente entre dos pulsaciones;
- envío multipart autenticado con la propuesta visible;
- liberación de pistas del micrófono;
- permiso denegado, error del backend y cierre del panel;
- posición y persistencia del selector de tema.

Validación final ejecutada después de la corrección de duración:

- backend: 116 pruebas aprobadas;
- frontend: 20 pruebas aprobadas en 4 archivos;
- TypeScript y build Vite de producción: aprobados;
- `faster-whisper` 1.2.1 instalado y modelo `tiny` cargado desde caché local;
- dispositivo de Whisper fijado a CPU/int8 para no seleccionar una instalación CUDA incompleta;
- Gemma `gemma3:1b` real clasificó una consulta de Jira con salida JSON válida;
- una solicitud real de escritura se clasificó fuera del registro permitido y la compuerta
  respondió `VOICE_GATE_ALLOWED=False`;
- un WAV silencioso real atravesó autenticación, multipart, PyAV y Whisper, y recibió el error
  controlado esperado sin dejar el archivo temporal;
- revisión visual manual aprobada en temas oscuro y claro.
- un WAV hablado recorrió el endpoint completo en 1.09 segundos y tres solicitudes concurrentes
  terminaron con HTTP 200 entre 0.36 y 0.62 segundos.

## Decisiones y límites deliberados

- No se añadieron escrituras de voz “con confirmación”; quedan fuera de este gate.
- La IA no decide permisos ni construye llamadas Jira.
- `get_jira_status` lee el estado que la aplicación ya mantiene; no dispara una llamada MCP.
- Los argumentos producidos por Gemma no seleccionan la propuesta. El identificador confiable
  procede de la interfaz autenticada; sin él se usa la propuesta activa más reciente.
- No se incorporó memoria conversacional. Cada grabación es una solicitud independiente.

Gate Voz 1 termina aquí. Cualquier ampliación de intents o nivel de permiso requiere un gate
posterior, revisión explícita del registro y pruebas nuevas.
