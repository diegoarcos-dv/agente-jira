# GATE E — Voz bajo demanda

Fecha de validación: 2026-09-09  
Entorno: local (`http://127.0.0.1:8000`). No se desplegó.

## Alcance implementado

GATE E se implementó como estado, activación UX, diagnóstico y manejo de errores. No se reescribieron los loaders existentes, no se sustituyeron sus locks y no se creó un `VoiceResourceManager` paralelo. `VoiceCommandService` expone el estado ligero de sus recursos existentes.

## Estados

Cada capacidad expone:

`DISABLED` · `NOT_LOADED` · `LOADING` · `READY` · `ERROR`

El estado general adicional es `DISABLED`, `NOT_STARTED`, `LOADING`, `READY`, `PARTIAL` o `ERROR`.

- `DISABLED`: la variable `VOICE_*_ENABLED` está en `false`.
- `NOT_LOADED`: la capacidad está habilitada, pero todavía no se ha usado.
- `LOADING`: se está realizando una comprobación o carga.
- `READY`: el recurso está cargado o, para LLM, Ollama y el modelo configurado respondieron correctamente.
- `ERROR`: la capacidad no está disponible; el detalle incluye una acción recomendada.

## Activación y diagnóstico

`POST /api/voice/activate` sólo ejecuta comprobaciones ligeras:

- no carga Whisper;
- no carga Piper;
- no solicita micrófono;
- no descarga modelos;
- no ejecuta `ollama pull`;
- no sintetiza audio;
- no cambia el Global Jira Write Lock.

`GET /api/voice/status` es side-effect free. Incluye configuración, estado, disponibilidad, proveedor y modelo/voz de STT, LLM y TTS.

Medición real en el servidor local:

```text
GET /api/voice/status: 11.4 ms
POST /api/voice/activate: 43.2 ms
STT después de activar: NOT_LOADED
TTS después de activar: NOT_LOADED
Global Write Lock: LOCKED
```

En el entorno de validación, Ollama responde HTTP 200 pero no contiene `gemma3:1b`. El diagnóstico informa exactamente:

`Ollama está disponible, pero no se encontró el modelo gemma3:1b.`

Si Ollama no responde, el diagnóstico informa:

`Ollama no está disponible.`

## Carga real de modelos

Whisper conserva `_get_model()` y su sincronización actuales. Sólo se invoca durante una transcripción real. La comprobación de activación no descarga el modelo `small`; indica que se cargará al primer uso y que la comprobación no descarga modelos. No se ejecutó un benchmark STT porque el modelo no está cacheado localmente y no se autorizó una descarga automática.

Piper conserva su carga lazy y lock actuales:

```text
Primera síntesis: 13,129.1 ms / +135.69 MB
Segunda síntesis: 247.1 ms / reutiliza la voz cargada
```

Si Piper falla, la respuesta escrita se conserva y se informa:

`No fue posible reproducir la respuesta por voz. La respuesta escrita sigue disponible.`

Para LLM, `READY` significa que Ollama es accesible y que el modelo configurado existe; Gemma vive fuera del backend y no se considera cargado permanentemente en la memoria del proceso.

## Frontend

- Todas las capacidades deshabilitadas: `Voz · Deshabilitada por configuración`, sin botón que pueda saltarse la configuración.
- Alguna capacidad habilitada: `Voz · No iniciada` y botón `Activar voz`.
- Activación: muestra comprobación ligera y no solicita micrófono.
- Degradación: muestra `Voz parcialmente disponible` y el componente concreto con error.
- El montaje de `VoiceAssistant` sólo recupera contexto y estado; no solicita permisos ni inicia grabación.

## Seguridad y compatibilidad

Activar voz, inicializar STT, verificar LLM o cargar TTS no desbloquea Jira. Las rutas de confirmación siguen pasando por la autoridad backend del Global Write Lock. No hubo escrituras Jira durante esta validación.

## Pruebas

- Backend: suite completa aprobada.
- Frontend: 5 archivos / 38 tests aprobados.
- Nuevas pruebas: estados `DISABLED`/`NOT_LOADED`, activación sin carga pesada, Ollama caído distinto de modelo Gemma faltante, error TTS con fallback de texto y UI sin micrófono antes de activar.

## Benchmark de arranque

La auditoría anterior midió el backend general, no una mejora atribuible a GATE E:

```text
import app.main: 5715.9 ms
create_app:       157.3 ms
modelos pesados cargados al arranque: ninguno
```

No se declara una aceleración de startup que la evidencia no demuestre.

## Dictamen

**GATE E: APROBADO localmente.**  
La validación de cierre y release readiness continúa en GATE F.

Riesgos pendientes: Whisper `small` aún requiere disponibilidad local o una descarga explícitamente aceptada durante el primer uso; `network=NOT_CHECKED` sigue siendo un estado posible del diagnóstico Atlassian y no se interpreta como fallo Jira.
