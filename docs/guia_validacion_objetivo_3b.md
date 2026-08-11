# Guía de validación del Objetivo 3B

Esta prueba consulta Jira mediante Rovo MCP, pero no crea ni modifica actividades.

## Preparación

1. Abre `http://localhost:8000`.
2. Inicia sesión en la aplicación.
3. Conecta Atlassian si aparece como desconectado.
4. Selecciona una propuesta aprobada. Para la primera prueba se recomienda **Plan de prueba**.

## Prueba principal

1. Pulsa **Prevalidar contra Jira**.
2. Espera el panel **Objetivo 3B · Sin escritura**.
3. Verifica el estado general y los tres conteos.
4. Abre cada actividad bloqueada y revisa su código.
5. Comprueba que las excluidas aparecen como **Excluida** y no tienen clave de ejecución.
6. Comprueba que las listas muestran responsable Jira y una clave `AJI-...`.
7. Confirma la leyenda **Cero escrituras Jira**.

## Prueba de idempotencia

1. Pulsa **Actualizar Dry run** sin modificar ni reabrir la propuesta.
2. Comprueba que el identificador `DRY-...` no cambia.
3. La interfaz debe indicar que recuperó un resultado idempotente.

## Resultados esperados

- Un dato faltante bloquea la fila y explica cómo corregirlo.
- Un responsable sin coincidencia exacta genera `ASSIGNEE_NOT_FOUND`.
- Una cuenta encontrada sin evidencia de asignabilidad genera `ASSIGNEE_ASSIGNABILITY_UNVERIFIED`.
- Una Subtarea de AT genera `WORK_TYPE_FIELDS_UNAVAILABLE` mientras Jira no entregue sus campos.
- Ninguna operación crea, modifica o transiciona un work item.

No compartas `cloudId`, account IDs, códigos OAuth, tokens ni URLs completas del callback en capturas.
