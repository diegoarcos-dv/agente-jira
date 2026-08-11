# Objetivo 4E · Epic, Subtask y relaciones padre-hijo

Versión de aplicación: 0.20.0  
Ámbito: Jira Cloud, Space AT, ejecución local controlada mediante Rovo MCP.

## Resultado

El agente puede crear lotes de hasta cinco actividades `Task`, `Bug`, `Story`, `Epic` o `Subtask` y conservar dos niveles de relación:

- `Epic → Task`, `Epic → Bug` o `Epic → Story`.
- `Task → Subtask`, `Bug → Subtask` o `Story → Subtask`.

No se admiten Epic con padre, Subtask como padre directo, autorreferencias ni ciclos.

## Flujo

1. El usuario selecciona Work Type y actividad padre en “Origen y propuesta”.
2. `Guardar y volver a validar` crea una sola versión con todos los cambios.
3. El Dry run comprueba existencia, inclusión y compatibilidad del padre sin escribir en Jira.
4. El usuario aprueba la propuesta y selecciona hasta cinco actividades.
5. El lote ordena padres antes que hijos, aunque se hayan seleccionado en otro orden.
6. La confirmación muestra la relación por fila o por clave Jira ya conocida.
7. Después de crear y verificar al padre, su clave —por ejemplo `AT-511`— sustituye la referencia simbólica antes de crear al hijo.
8. `getJiraIssue` debe devolver la misma clave en `fields.parent.key`.
9. Una discrepancia detiene el lote; no hay reintento automático ni envío de las actividades restantes.

## Lotes sucesivos

Un hijo puede enviarse sin su padre en el mismo lote únicamente cuando ese padre ya terminó como `CREATED_VERIFIED` en un lote 4E anterior de la misma propuesta aprobada. La aplicación recupera su clave desde la evidencia local; no la adivina ni la busca por título.

## Controles

- Política separada `config/jira_execution_policy_4e.json`.
- Space permitido: sólo AT.
- Máximo: cinco actividades.
- Herramienta de escritura: sólo `createJiraIssue`.
- Responsable incluido en la creación atómica.
- Confirmación escrita con caducidad.
- Creación secuencial y detención ante la primera anomalía.
- Cero reintentos automáticos.
- Huella del payload confirmado y huella del payload final con la clave padre resuelta.
- Evidencia JSON descargable.

## Contrato MCP/Jira

La relación se envía en `additional_fields.parent` con forma `{"key": "AT-nnn"}`. El contrato de `createJiraIssue` debe exponer `additional_fields`; de lo contrario, la preparación se bloquea antes de escribir.
