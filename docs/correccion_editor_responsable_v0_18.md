# Corrección del editor de responsable — v0.18

## Problema

La acción **Seleccionar responsable** persistía inmediatamente la cuenta Jira, creaba una versión y cerraba el drawer **Origen y propuesta**. Si el usuario también había editado título, descripción, Work Type o nota, esos cambios locales se perdían.

## Comportamiento corregido

1. Buscar en Jira sigue siendo una consulta de lectura.
2. **Seleccionar responsable** sólo actualiza el borrador local del drawer.
3. La interfaz muestra `Cambio pendiente · se guardará junto con las demás ediciones`.
4. El drawer permanece abierto y conserva todos los demás campos.
5. **Guardar y volver a validar** envía una única operación con todos los cambios.
6. El backend vuelve a buscar la cuenta Jira con la consulta original y comprueba que el `account_id` continúe activo.
7. Sólo después de esa comprobación se crea una nueva versión de la propuesta y se recalculan sus reglas.

La selección no se considera persistida hasta el guardado final. **Cancelar** descarta tanto el responsable pendiente como las demás modificaciones locales.

## Verificación

La prueba de regresión modifica simultáneamente título, nota y responsable, comprueba que no exista `PATCH` al seleccionar la cuenta y valida que los tres valores viajen juntos al guardar.
