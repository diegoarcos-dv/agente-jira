# Gate Voz 2 — conversación estructurada, borrador local y TTS

Fecha de cierre técnico: 2026-08-18.

## Alcance

Vic mantiene ahora una conversación breve y controlada para preparar una tarea local en varios
turnos. Whisper transcribe, Gemma clasifica una intención tipada y el código de la aplicación
actualiza el contexto y el borrador. Gemma no modifica estado, decide permisos, invoca Jira/MCP
ni redacta libremente las respuestas operativas.

```text
Botón React -> MediaRecorder -> POST autenticado -> Whisper local (CPU/int8)
 -> Gemma local / reglas cerradas -> VoiceIntent Pydantic
 -> Command Router -> Permission Gate -> servicio determinista
 -> SQLite: contexto y Voice Task Draft -> respuesta breve
 -> Piper local opcional (SAPI5 sólo en Windows) -> WAV en memoria -> navegador
```

Los niveles habilitados son `READ_ONLY` y `LOCAL_WRITE`. `JIRA_WRITE` y `FORBIDDEN` permanecen
bloqueados por un registro definido en código. Esta compuerta es independiente de la política
general 4A–4E: arrancar el modo 4E no permite que la voz escriba en Jira.

## Contexto conversacional

`VoiceContextStore` conserva un documento pequeño en la tabla SQLite `voice_contexts`, separado
por el hash de la sesión Bearer y el usuario autenticado. La expiración predeterminada es 30
minutos y cada lectura purga registros vencidos. No existe historial de conversación.

```json
{
  "session_id": "sha256-de-la-sesion-local",
  "username": "admin@agentejira.local",
  "active_proposal_id": null,
  "active_activity_id": null,
  "active_draft_id": "VOICE-DRAFT-A1B2C3D4E5F6",
  "last_intent": "set_draft_priority",
  "pending_question": "review",
  "pending_confirmation": null,
  "selected_items": [],
  "assignee_candidates": [],
  "draft": {},
  "updated_at": "ISO-8601",
  "expires_at": "ISO-8601"
}
```

Los arreglos están acotados: 20 elementos seleccionados y cinco candidatos de responsable. El
contexto enviado a Gemma omite usuario, sesión, correo y `account_id`. SQLite no recibe audio,
transcripciones, prompts, tokens ni una memoria libre del modelo. `DELETE /api/voice/context` o
la frase “Olvida lo anterior” eliminan el estado de esa sesión.

Dos órdenes de una misma sesión se serializan con un lock por sesión. Las demás sesiones siguen
en paralelo; no existe un lock global del procesamiento de voz.

## Voice Task Draft

El borrador es un modelo local explícitamente distinto de un issue Jira y de un payload MCP:

```json
{
  "id": "VOICE-DRAFT-A1B2C3D4E5F6",
  "issue_type": "Task",
  "summary": "Corregir el login",
  "description": null,
  "assignee": {
    "display_name": "Héctor Hernández",
    "account_id": "id devuelto por Jira",
    "email": null
  },
  "priority": "High",
  "space": "AT",
  "status": "draft"
}
```

Los tipos válidos son `Epic`, `Story`, `Task`, `Bug` y `Subtask`; las prioridades son `Highest`,
`High`, `Medium`, `Low` y `Lowest`. Resumen, descripción, listas e identificadores tienen límites
de tamaño. El responsable se resuelve exclusivamente con el buscador Jira ya existente. Cero o
varias coincidencias producen aclaración; nunca se inventa un `account_id`. La resolución sólo
completa el borrador local.

## Intents y riesgos

| Riesgo | Intents |
|---|---|
| `READ_ONLY` | `help`, `get_app_status`, `get_jira_status`, `get_current_proposal_summary`, `list_validation_errors`, `list_pending_items`, `show_current_draft` |
| `LOCAL_WRITE` | `prepare_local_task`, `set_draft_summary`, `set_draft_description`, `set_draft_assignee`, `set_draft_priority`, `set_draft_issue_type`, `cancel_current_draft`, `clear_voice_context`, `confirm_pending_action`, `reject_pending_action` |
| `JIRA_WRITE` bloqueado | `prepare_task`, `create_task`, `create_jira_issue`, `update_task`, `delete_task`, `send_to_jira` |
| `FORBIDDEN` bloqueado | `change_policy`, `run_command` |

“Crea una tarea” se clasifica como `prepare_local_task`; “Envíala/Créala en Jira”, “Publícala” y
“Sube la tarea” se clasifican como `create_jira_issue` y la compuerta responde `blocked`. No se
construye ni invoca una operación Jira.

“Sí”, “no”, “cancelar” y “continúa” sólo adquieren significado cuando hay una pregunta o
confirmación explícita. Cancelar un borrador significativo requiere confirmación. Una confianza
inferior a `VOICE_MIN_CONFIDENCE` devuelve aclaración sin guardar ningún cambio.

## TTS local

El proveedor principal es Piper mediante `piper-tts`, con la voz mexicana
`es_MX-ald-medium`. Se eligió porque funciona offline mediante ONNX Runtime tanto en Linux x86-64
y ARM64 como en Windows, e incluye fonemización local con espeak-ng. El modelo y su archivo JSON
se descargan explícitamente una vez durante la preparación del servidor; no hay descarga en el
arranque ni envío de texto/audio durante la síntesis. SAPI5/Helena se conserva sólo como adaptador
opcional para desarrollo en Windows.

Piper genera el WAV directamente en memoria mediante su API Python. SAPI5 usa un temporal que se
elimina en `finally`. El endpoint sólo sintetiza cuando el cliente envía `spoken_response=true`.
Un fallo, ausencia o timeout de TTS conserva la misma respuesta textual y no afecta FastAPI,
Whisper, Gemma, Jira ni las propuestas. La capa `VoiceSynthesizer` mantiene ambos proveedores
fuera del router y del contrato de negocio.

Variables nuevas:

| Variable | Predeterminado | Uso |
|---|---:|---|
| `VOICE_WHISPER_HOTWORDS` | vocabulario de Vic/Jira | Mejora órdenes cortas sin cambiar CPU/int8 |
| `VOICE_CONTEXT_TTL_SECONDS` | `1800` | TTL del contexto por sesión |
| `VOICE_TTS_ENABLED` | `false` | Habilita síntesis; el script 4E la establece en `true` |
| `VOICE_TTS_PROVIDER` | `piper` | Adaptador TTS local; `sapi5` sólo en Windows |
| `VOICE_TTS_VOICE` | `es_MX-ald-medium` | Nombre de voz Piper |
| `VOICE_TTS_MODEL_PATH` | `backend/data/voices/es_MX-ald-medium.onnx` | Modelo ONNX local |
| `VOICE_TTS_LENGTH_SCALE` | `1.0` | Velocidad relativa de Piper, de 0.5 a 2.0 |
| `VOICE_TTS_RATE` | `0` | Velocidad usada sólo por SAPI5, de -10 a 10 |
| `VOICE_TTS_TIMEOUT_SECONDS` | `10` | Timeout por síntesis |
| `VOICE_TTS_MAX_CHARS` | `500` | Límite enviado al motor |

Las dependencias directas añadidas son `piper-tts==1.6.0` y
`pywin32==312; sys_platform == "win32"`. No se introdujo ningún servicio de TTS externo. El modo
normal deja TTS, STT e IA apagados de forma segura. Tanto `scripts\start-objective-4e.cmd` como
`scripts/start-objective-4e.sh` activan Piper; SAPI5 se conserva como opción explícita de
desarrollo Windows. La preparación de la voz se realiza con
`bash scripts/setup-piper-voice.sh`.

## API

- `POST /api/voice/command`: continúa autenticado y multipart. Añade el campo opcional
  `spoken_response`; devuelve `risk`, `draft`, vista segura de `context`, disponibilidad y WAV en
  base64. No duplica la lógica TTS.
- `GET /api/voice/context`: recupera la vista segura del contexto de la sesión autenticada.
- `DELETE /api/voice/context`: elimina únicamente el contexto de esa sesión autenticada.

Los tres endpoints requieren Bearer. Tamaño de audio, formatos, duración máxima de 30 segundos,
timeout total de 60 segundos y temporales de Whisper conservan los límites del Gate anterior.

## Interfaz y máquina de estados

```text
IDLE -> LISTENING -> TRANSCRIBING -> THINKING -> EXECUTING -> SPEAKING -> SUCCESS
  ^                                                              |
  +-------------------- nueva pulsación / fin --------------------+
```

`EXECUTING` sólo representa una operación local controlada. Mientras el estado es `SPEAKING`, el
grabador está cerrado. Pulsar el micrófono en ese estado pausa y libera primero el elemento de
audio y sólo después solicita otra captura. El usuario también puede pulsar “Detener audio”. No
hay escucha permanente ni posibilidad de `LISTENING + SPEAKING`.

La tarjeta compacta muestra tipo, resumen, responsable, prioridad y “Todavía no enviada a Jira”.
El selector “Respuestas habladas” se conserva en `localStorage`; al apagarlo, el cliente solicita
respuesta de texto sin síntesis ni reproducción. Los temas claro y oscuro y el diseño general no
cambiaron.

## Seguridad

- Whisper, Gemma/Ollama, Piper y el adaptador opcional SAPI5 apuntan a recursos locales.
- Gemma recibe un contexto reducido y devuelve JSON Pydantic con campos extra prohibidos.
- El modelo no obtiene tokens, herramientas, MCP, Jira, shell, Python, configuración ni permisos.
- Las respuestas operativas proceden de plantillas deterministas del router.
- El Permission Gate ignora cualquier nivel sugerido por el modelo.
- `JIRA_WRITE` y `FORBIDDEN` no tienen handler ejecutable en la voz.
- No se persiste audio ni una conversación/transcripción acumulativa.
- Los temporales Whisper y TTS se eliminan.
- TTS es opcional y falla de forma segura a texto.
- La baja confianza no muta el contexto ni confirma cancelaciones.

## Verificación automatizada

Las pruebas usan dobles de Whisper, Gemma/Ollama, TTS y Jira/MCP; no requieren Internet. Cubren la
conversación completa, todas las modificaciones del borrador, responsables inexistentes o
ambiguos, aislamiento/TTL/limpieza, baja confianza, bloqueo Jira, privacidad, TTS opcional y lock
por sesión. En frontend cubren captura, estados, tarjeta, preferencia, reproducción, interrupción,
fallback textual y exclusión mutua micrófono/audio.

Resultado de cierre:

- backend: 134 pruebas aprobadas;
- frontend: 24 pruebas aprobadas en cuatro archivos;
- TypeScript y build Vite de producción: aprobados.

## Prueba manual

1. Detener cualquier servidor que ocupe el puerto 8000.
2. Ejecutar `scripts\start-objective-4e.cmd` y abrir `http://localhost:8000/`.
3. Iniciar sesión, dejar activo “Respuestas habladas” y decir por turnos:
   “Crea una tarea para corregir el login”, “A Héctor”, “Alta” y “Sí”.
4. Verificar la tarjeta de borrador. La resolución de Héctor requiere una conexión Jira vigente;
   si no existe o es ambigua, Vic debe pedir precisión sin inventarlo.
5. Decir “Envíala a Jira”. El resultado obligatorio es `blocked` y el borrador debe seguir local.
6. Desactivar “Respuestas habladas” y repetir una consulta: debe conservarse el texto sin WAV.

La prueba real automatizada con audio recorrió Whisper, contexto, router, Permission Gate y Piper.
Creó el draft, cambió prioridad, lo mostró y bloqueó el envío Jira. En el sitio Jira conectado la
búsqueda de “Héctor” devolvió cero coincidencias; Vic respondió con aclaración y no inventó una
cuenta, que es el resultado de seguridad requerido para ese dato. La conversación exacta con una
coincidencia única está cubierta por el doble Jira en la prueba de integración.

## Limitaciones deliberadas

No se implementaron wake word, escucha permanente, envío/edición real Jira por voz, transiciones,
comentarios, worklogs, control de Windows, navegación arbitraria, shell ni ejecución de código.
Piper requiere instalar previamente los dos archivos de la voz. SAPI5 requiere Windows y una voz
instalada. Ante cualquiera de esas ausencias, el contrato vuelve a texto. En un servidor remoto,
el navegador exige HTTPS para otorgar acceso al micrófono; véase
`docs/DESPLIEGUE_LINUX_VOZ.md`. El contexto vive mientras exista la sesión y hasta su TTL; no
pretende ser memoria histórica.

Gate Voz 2 termina aquí. No se habilita ni se inicia el siguiente gate.
