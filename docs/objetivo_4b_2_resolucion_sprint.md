# Objetivo 4B.2: resolución automática y validación de Sprint

Versión de la aplicación: 0.16.0  
Fecha: 2026-07-20

## Resultado

La aplicación dejó de solicitar el ID técnico del Sprint. El usuario trabaja con nombres legibles y el backend aplica la política `PLAN_VALUE_THEN_ACTIVE` para resolver un ID verificable antes de construir el payload Jira.

## Política de resolución

1. Si el plan contiene un Sprint, se busca una coincidencia exacta normalizada por nombre entre los Sprints activos y futuros visibles.
2. Si el plan no contiene Sprint y existe exactamente uno activo, se selecciona automáticamente.
3. Si existen varios activos, la prevalidación queda bloqueada hasta que el usuario seleccione uno.
4. Si no existe ninguno activo y el plan no eligió uno futuro, la actividad continúa sin Sprint con una advertencia.
5. Si el nombre no existe, está cerrado o produce más de una coincidencia, la actividad queda bloqueada.

La compatibilidad con un ID existente se conserva para propuestas históricas, pero la interfaz ya no pide ni muestra el ID como dato de captura.

## Recuperación mediante MCP

El adaptador Jira consulta `searchJiraIssuesUsingJql` de Rovo MCP con dos búsquedas de solo lectura:

```jql
project = "AT" AND sprint in openSprints() ORDER BY updated DESC
project = "AT" AND sprint in futureSprints() ORDER BY updated DESC
```

El resultado se normaliza como:

```json
{
  "id": "321",
  "name": "SPT-ACTIVO",
  "state": "active",
  "board_id": "45",
  "source": "ROVO_MCP_JQL"
}
```

Las páginas se recorren hasta terminar. Si el servidor indica más páginas después del límite de seguridad, el catálogo se rechaza como incompleto. La caché de interfaz dura cinco minutos; el Dry run y la escritura solicitan una actualización forzada.

## Barrera previa a escritura

Después de la confirmación final y antes de cambiar la intención a `SUBMITTED`, el backend vuelve a consultar Jira y busca el mismo ID. Sólo acepta estados `active` o `future`.

Si no puede demostrarlo:

- no invoca `createJiraIssue`;
- no genera una escritura parcial;
- conserva la intención como `REAL_CONFIRMED`;
- solicita actualizar la prevalidación;
- registra el motivo en la respuesta al usuario.

Cuando la comprobación es exitosa, la evidencia registra `sprint_revalidated_at` y el evento `SPRINT_ID_AND_STATE_CONFIRMED`. La lectura posterior de la Task solicita también el campo Sprint y verifica que conserve el mismo ID.

## Interfaz

- La carga inicial y el editor de valores generales muestran `Nombre · Activo/Futuro`.
- El valor guardado en la propuesta es el nombre legible.
- El Dry run muestra el Sprint resuelto y si fue seleccionado automáticamente.
- La confirmación real muestra el nombre y estado, mientras el detalle técnico conserva el ID en el payload.

## Limitación conocida de Rovo JQL

JQL devuelve actividades y no un catálogo administrativo completo de tableros. Por ello, un Sprint vacío puede no aparecer. Esta limitación falla de forma segura: nunca se inventa un ID ni se escribe con un Sprint no verificado. Una evolución posterior puede sustituir el adaptador por un MCP interno respaldado por Jira Software Agile REST sin modificar la política ni la interfaz.

## Evidencia automatizada

La suite cubre:

- resolución del nombre al ID;
- selección automática de un único Sprint activo;
- bloqueo ante múltiples activos;
- exclusión de Sprints cerrados;
- extracción de respuestas Jira modernas y legadas;
- revalidación forzada inmediatamente antes de crear;
- comprobación posterior del ID de Sprint en la Task creada;
- cero llamadas de creación cuando el Sprint dejó de ser válido.
