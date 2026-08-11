# Objetivo 4B: escritura controlada de una Task en Jira

Versión de la aplicación: 0.16.0  
Fecha: 2026-07-20

## Resultado

El Objetivo 4B habilita el primer flujo de escritura real del Agente Jira. Su alcance está limitado a crear exactamente una actividad de tipo `Task` en el Space `AT`. No habilita lotes, Bugs, Stories, Epics, Subtasks, comentarios, transiciones ni ediciones.

No se implementó un Objetivo 4A.1 independiente. Las mejoras de claridad que aportaban valor se incorporaron directamente al flujo 4B para evitar trabajo desechable.

## Estado seguro por defecto

`scripts\start.cmd` y `scripts\dev.cmd` cargan `config/jira_execution_policy_v1.json`, cuya política permanece en `PLANNING_ONLY` y `jira_write_enabled=false`. En este modo la interfaz permite prevalidar y simular, pero no invocar `createJiraIssue`.

El modo de escritura se activa exclusivamente para el proceso iniciado con:

```powershell
scripts\start-objective-4b.cmd
```

Ese script usa temporalmente `config/jira_execution_policy_4b.json`. No cambia la configuración predeterminada y se niega a iniciar si el puerto 8000 ya está ocupado.

## Flujo de usuario

1. Cargar, revisar y aprobar la propuesta.
2. Ejecutar la prevalidación real en modo sin escritura.
3. Seleccionar una sola Task de AT y completar la simulación local.
4. Iniciar el servidor en modo 4B y recuperar la misma propuesta.
5. Pulsar `Preparar envío real`. Esta acción todavía no escribe.
6. Revisar título, destino, responsable, payload y huella.
7. Escribir literalmente `CREAR 1 TASK EN AT` y confirmar.
8. Pulsar `Crear 1 Task real en AT`. Ésta es la única acción que invoca la escritura.
9. Revisar la lectura posterior y abrir la clave `AT-n` reportada.

## Barreras obligatorias

- Propuesta aprobada y versión vigente.
- Dry run vigente con cero bloqueos.
- Una sola actividad.
- Space exacto `AT`.
- Work Type exacto `Task`.
- Cuenta Atlassian activa y resuelta.
- Responsable incluido en la misma llamada de creación.
- `createJiraIssue` y `getJiraIssue` expuestos por Rovo.
- Contrato MCP validado antes de enviar.
- Confirmación escrita con vigencia de diez minutos.
- Cero reintentos automáticos.

## Contrato utilizado

La escritura usa los nombres publicados por Rovo:

- Obligatorios: `cloudId`, `projectKey`, `issueTypeName`, `summary`.
- Utilizados cuando existen: `description`, `assignee_account_id`, `additional_fields`, `contentFormat` y `responseContentFormat`.
- Los campos Jira adicionales se envían dentro de `additional_fields`.
- Las opciones con identificador Jira se convierten a `{ "id": "..." }`.
- El campo Sprint es especial: el usuario trabaja con el nombre y el Objetivo 4B.2 lo resuelve dinámicamente al ID numérico que Jira requiere. Tanto los Sprints activos como los futuros son admisibles si la resolución queda verificada.
- Inmediatamente antes de `createJiraIssue`, el ID y el estado del Sprint se consultan otra vez. Un Sprint cerrado, invisible o ambiguo bloquea la operación antes de cualquier escritura.
- Se agrega la etiqueta `agente-test` para reconocer la actividad de prueba controlada.

La lectura posterior usa `getJiraIssue` con `cloudId` e `issueIdOrKey` y comprueba clave, resumen, Space, Work Type, responsable y, cuando aplique, el ID del Sprint.

## Estados finales

| Estado | Significado | Acción |
|---|---|---|
| `CREATED_VERIFIED` | Jira creó la Task y la lectura confirmó los datos esenciales. | Abrir y revisar la Task. |
| `CREATED_UNVERIFIED` | Jira devolvió una clave, pero la lectura fue incompleta. | Revisar manualmente la clave; no repetir. |
| `REJECTED` | Jira rechazó la solicitud de forma explícita. | Corregir la causa antes de preparar otra versión. |
| `UNKNOWN` | La conexión se interrumpió después de iniciar el envío. | Buscar la huella o el título en Jira; no repetir automáticamente. |

Un `Bad Request` devuelto expresamente por Jira se clasifica como `REJECTED`, porque se sabe que Jira no aceptó la creación. No debe mostrarse como resultado incierto.

## Idempotencia y auditoría

La intención se guarda como `SUBMITTED` antes de llamar a la herramienta de creación de Rovo. Si hay Sprint, su revalidación ocurre antes de ese cambio de estado. Una ejecución terminal reutiliza el resultado persistido y no vuelve a invocar el gateway. La evidencia JSON registra payload, huella, usuario, resolución y revalidación del Sprint, estados, clave Jira, lectura posterior, número de llamadas MCP y `automatic_retries=0`.

Las pruebas automatizadas usan un gateway falso. Por diseño, la suite completa realiza cero escrituras en la instancia Jira real.
