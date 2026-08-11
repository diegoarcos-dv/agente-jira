# Evidencia del Objetivo 3B

Fecha: 17 de julio de 2026  
Estado: aceptación real en curso; primera prevalidación completada y bloqueos accionables identificados.

## Verificación automatizada

- backend: `37 passed`;
- frontend: `8 passed`;
- TypeScript y build de producción: aprobados;
- escritura Jira: deshabilitada;
- respuesta Dry run: `write_performed=false`;
- guardas MCP: sólo herramientas incluidas en la lista positiva de lectura.

## Primera prevalidación real

La propuesta aprobada versión 6 generó un registro `DRY-...` con:

- Listas: 0;
- Bloqueadas: 5;
- Excluidas: 0;
- escrituras Jira: 0.

Los resultados observados fueron:

- tres filas con `ASSIGNEE_NOT_FOUND`;
- dos filas con `ASSIGNEE_ASSIGNABILITY_UNVERIFIED`;
- ninguna llamada de creación, edición o transición Jira.

No se registran nombres, correos, account IDs ni `cloudId` en este documento.

## Ajustes derivados de la aceptación

1. Una búsqueda sin resultados muestra un mensaje explícito y sugiere usar nombre completo o correo corporativo.
2. Si existe una coincidencia exacta, se ocultan las coincidencias aproximadas.
3. Se eliminan duplicados y cuentas inactivas en el backend.
4. Una propuesta reabierta permite buscar y guardar una cuenta Jira real por actividad.
5. La selección se vuelve a verificar contra Rovo antes de crear una nueva versión; la API no confía sólo en el account ID enviado por el navegador.
6. Una cuenta existente sin evidencia suficiente de asignabilidad continúa bloqueada; no se degrada a una advertencia.

7. Al reabrir una propuesta, el último Dry run permanece visible como evidencia histórica: se muestra su versión, se marca como desactualizado y se habilita la vista `Bloqueadas por Jira` sin convertir esos bloqueos en decisiones locales de revisión.

La validación local del caso real confirmó: propuesta versión 7, Dry run versión 6, cinco actividades bloqueadas, `stale=true` y `write_performed=false`.

## Evidencia pendiente para cierre

El Objetivo 3B.1 agregó un flujo guiado de corrección. En el caso real de la propuesta v7, la aplicación separa tres acciones de usuario y dos validaciones técnicas, oculta la aprobación mientras existan acciones pendientes y conserva `write_performed=false`. Véase `objetivo_3b_1_flujo_correcciones.md`.

- corregir al menos los responsables no encontrados en una versión reabierta;
- aprobar la nueva versión;
- repetir el Dry run;
- comprobar que repetirlo sin cambios devuelve el mismo `DRY-...` con `reused=true`;
- definir una evidencia técnicamente válida de asignabilidad para los casos donde Rovo sólo expone `lookupJiraAccountId`.
