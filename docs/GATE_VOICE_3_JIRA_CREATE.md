# Gate Voz 3 — creación Jira controlada

## Alcance

Gate Voz 3 permite preparar y confirmar localmente la creación de una `Task` en Jira desde Vic. La aplicación, Whisper `small` en CPU/int8, Gemma y Piper continúan ejecutándose en la computadora local. Solo la integración Jira/MCP ya configurada puede comunicarse con Atlassian. El modelo `small` mejora la precisión en español y mantiene el mismo runtime `faster-whisper` compatible con Windows y Linux.

No se habilitan edición, eliminación, transiciones, comentarios, worklogs, administración, ejecución de código ni cambios de política por voz.

## Arquitectura

```text
Navegador -> audio -> Whisper -> Gemma -> intent estructurado
                                           |
                                           v
                                  Voice Command Router
                                           |
                                           v
                                  Permission Gate fijo
                                           |
                                           v
WEB 4B/4E ----------------> ControlledJiraCreateCore <---------------- VOICE
                                           |
                             PREPARE / VALIDATE / CONFIRM
                                           |
                             claim atómico / idempotencia
                                           |
                                  MCP create (una vez)
                                           |
                                     readback Jira
```

Gemma interpreta lenguaje y llena un intent. No recibe credenciales, no decide el riesgo y no tiene acceso a Jira, MCP, shell ni Python dinámico. La política determinista decide si la solicitud puede avanzar.

`ControlledJiraCreateCore` es el núcleo común usado por la interfaz web existente y por voz. El adaptador de voz no contiene una segunda implementación de escritura.

## Integración con Objective 4E

La preparación reutiliza la configuración y las restricciones activas de Objective 4E:

- escritura habilitada previamente por el operador;
- Space permitido (`AT` en la configuración actual);
- tipo permitido (`Task` para este Gate de voz);
- usuario Atlassian activo y responsable resuelto de forma inequívoca;
- contrato real de `createJiraIssue` y herramienta de readback disponible;
- campos requeridos obtenidos de metadatos Jira;
- una única invocación de creación y posterior consulta de verificación.

La voz no puede activar Objective 4E, ampliar espacios/tipos ni modificar el archivo de política.

## Preparación

Los intents `request_jira_create` y `confirm_jira_create` son los únicos intents de escritura Jira admitidos por voz. Una solicitud de creación:

1. valida draft, summary, Space y `Task`;
2. resuelve el responsable consultando Jira y rechaza cero o múltiples coincidencias;
3. valida la prioridad con una consulta Jira de solo lectura;
4. respeta los campos requeridos publicados por Jira y no obliga campos opcionales;
5. construye el payload MCP, incluida la prioridad mediante `additional_fields`;
6. calcula un hash SHA-256 canónico;
7. persiste un intent `VOICE_PREPARED` y crea una confirmación pendiente ligada a usuario, sesión y draft.

En este Gate solo `Task` puede llegar a escritura desde voz. Otros tipos pueden seguir existiendo como drafts locales o en el flujo web 4E, pero no se improvisan escrituras de voz.

## Confirmación pendiente y payload hash

La respuesta pública contiene una vista segura de la confirmación:

```json
{
  "confirmation_id": "identificador aleatorio",
  "action": "create_jira_issue",
  "draft_id": "VOICE-DRAFT-...",
  "payload_hash": "sha256...",
  "created_at": "fecha ISO-8601",
  "expires_at": "fecha ISO-8601",
  "preview": {
    "space": "AT",
    "issue_type": "Task",
    "summary": "...",
    "assignee": "...",
    "priority": "High"
  }
}
```

Internamente también se vincula a identificadores seguros (hashes) de usuario y sesión y al fingerprint del draft. La expiración se configura con `VOICE_JIRA_CONFIRMATION_TTL_SECONDS` (600 segundos por defecto).

El `payload_hash` se calcula sobre JSON canónico: claves ordenadas, separadores estables y codificación UTF-8. Cualquier cambio relevante del draft invalida la confirmación anterior; una nueva preparación produce una autorización nueva y, cuando cambia el payload, un hash diferente.

La confirmación puede llegar por una frase afirmativa exacta o por el botón visual. Ambos caminos llaman al mismo método del servicio. Un “sí” sin confirmación pendiente y una frase condicional como “si falla…” no ejecutan nada.

## Idempotencia y ejecución

Antes de llamar MCP se hace una transición SQL condicional y atómica:

```text
VOICE_PREPARED -> VOICE_CONFIRMED -> SUBMITTED
```

Solo la solicitud que reclama correctamente cada estado puede continuar. Doble clic, doble confirmación, repetición HTTP o refresh no pueden volver a reclamar el intent ni producir una segunda llamada. La restricción única existente en `jira_execution_intents` complementa este control.

El núcleo común invoca `createJiraIssue` exactamente una vez. No existe retry automático de escritura.

## Readback y resultado incierto

Después de una respuesta de creación, el núcleo consulta Jira una vez y valida como mínimo key, Space, tipo y summary; también valida responsable, prioridad y parent cuando están presentes. Solo una coincidencia verificada produce éxito y expone el issue key.

Un timeout, una respuesta ambigua, un issue no encontrado o una discrepancia posterior al envío produce `UNKNOWN_RESULT`. La operación permanece sometida y no se reenvía automáticamente, para evitar duplicados. El usuario recibe un mensaje breve indicando que el resultado no pudo verificarse.

## Estados del frontend

La máquina visual amplía el flujo existente con:

```text
PREPARING_JIRA -> AWAITING_CONFIRMATION -> CREATING_JIRA
               -> VERIFYING_JIRA -> SPEAKING -> SUCCESS
```

Y los estados terminales `VALIDATION_ERROR`, `EXECUTION_ERROR`, `UNKNOWN_RESULT` y `CANCELLED`.

La tarjeta de confirmación muestra tipo, resumen, responsable, prioridad y Space, además de “Aún no se ha creado nada”. Los botones Cancelar y Crear en Jira comparten el mecanismo backend de la confirmación por voz. La confirmación pendiente se recupera al refrescar. Un guard síncrono y el estado deshabilitado protegen el doble clic. Micrófono, ejecución y TTS continúan siendo mutuamente excluyentes.

## Seguridad y auditoría

- El Permission Gate es determinista y solo permite preparar/confirmar una creación si la política ya era válida.
- Gemma no recibe tokens, contraseñas, cookies ni contratos MCP y no puede invocar herramientas.
- Audio y prompts completos no se persisten.
- Se registran identificadores seguros de usuario/sesión, draft, intent, operación, hash, timestamps, estado, key y tiempos.
- Credenciales, cookies, audio y secretos no se registran.
- Confirmaciones expiradas, de otro usuario/sesión, con hash distinto o draft modificado son rechazadas.
- Una baja confianza no llega a escritura.
- Cambios de política, edición/eliminación de issues y ejecución arbitraria permanecen bloqueados.

## Pruebas

La suite backend usa dobles de Jira/MCP: preparación válida/inválida, responsable/tipo/parent, estabilidad y cambio de hash, expiración, aislamiento por usuario/sesión, hash incorrecto, frases fuera de contexto, policy gate, llamada única, concurrencia, timeout, errores, resultado desconocido, readback y auditoría segura.

La suite frontend cubre preview, tarjeta y botones, estados de confirmación/creación/verificación, éxito con key, cancelación, error, resultado incierto, confirmación hablada, doble clic, recuperación tras refresh, TTS y cierre del micrófono.

## Prueba manual local

Condiciones previas:

1. ejecutar toda la suite backend y frontend y el build;
2. iniciar localmente con `scripts\start-objective-4e.cmd`;
3. comprobar la conexión Jira, policy 4E, Space y responsable mediante consultas de solo lectura;
4. preparar por voz `Prueba controlada de Vic Voice Gate 3`;
5. revisar la tarjeta y confirmar una sola vez;
6. registrar key, tiempo de create y tiempo de readback.

Si Jira no está conectado, no hay permisos o el responsable no puede resolverse de manera inequívoca, se detiene la prueba sin crear nada. Ante timeout o resultado incierto, no se repite.

## Limitaciones

- Voz crea únicamente `Task` en este Gate.
- No hay escucha permanente ni wake word.
- No se modifica ningún issue existente.
- No se despliega ni se prueba en Linux, HTTPS remoto o producción.
- La disponibilidad final depende de la conexión Jira/MCP y de permisos reales configurados por el operador.
