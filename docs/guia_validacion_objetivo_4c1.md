# Guía de validación manual — Objetivo 4C.1

Esta prueba realiza escrituras reales en Jira. Para la primera validación se recomienda seleccionar **dos Tasks** de bajo riesgo y fácilmente identificables.

## 1. Preparación

1. Detén el servidor actual con `Ctrl+C`.
2. Desde la raíz del proyecto ejecuta:

   ```powershell
   scripts\start-objective-4c1.cmd
   ```

3. Inicia el frontend de la forma habitual si no está activo.
4. Verifica que la cabecera indique conexión Jira con escritura controlada.
5. Abre una propuesta aprobada cuyo Dry run vigente no tenga bloqueos.

El comando de arranque no crea actividades.

## 2. Preparar el lote

1. En **Crear un lote controlado de Tasks**, selecciona dos actividades.
2. Confirma que el contador indique `2 seleccionadas`.
3. Pulsa **Preparar lote de 2 Tasks**.
4. Revisa el orden, responsables y Sprints.
5. Comprueba que se informe: cero reintentos, detención ante la primera anomalía y ausencia de rollback automático.

Hasta este punto no debe existir ninguna Task nueva en Jira.

## 3. Confirmar y ejecutar

1. Escribe exactamente `CREAR 2 TASKS EN AT`.
2. Pulsa **Confirmar lote real**.
3. Lee nuevamente la advertencia de escritura.
4. Pulsa **Crear 2 Tasks reales en AT** una sola vez.
5. Espera el resultado consolidado; no recargues ni repitas la operación mientras se procesa.

## 4. Resultado esperado

- `Éxito: 2 Tasks creadas y verificadas`;
- dos claves Jira diferentes;
- un enlace para abrir cada Task;
- cuatro llamadas MCP —dos por actividad—;
- cero reintentos automáticos;
- Sprint revalidado cuando las actividades lo incluyan.

En Jira verifica manualmente título, responsable, Sprint y etiqueta `agente-test`.

## 5. Si algo falla

- `STOPPED_REJECTED`: Jira rechazó una actividad; las siguientes no se intentaron.
- `STOPPED_UNKNOWN`: no puede confirmarse si Jira creó la última actividad; busca por el título `AgenteTest_Task_` antes de cualquier nueva acción.
- `STOPPED_UNVERIFIED`: Jira devolvió una clave, pero la lectura no confirmó todos los campos; abre la clave y concilia manualmente.
- `NOT_ATTEMPTED`: no existió llamada de creación para esa actividad.

No vuelvas a ejecutar el mismo lote ante un resultado incierto. Descarga primero la evidencia y revisa Jira.

## 6. Cierre

1. Descarga **Evidencia 4C.1**.
2. Conserva las claves Jira generadas y el estado por actividad.
3. Detén el servidor 4C.1 con `Ctrl+C`.
4. Para volver al modo seguro habitual, ejecuta `scripts\start.cmd`.

4C.1 se considera validado cuando las dos Tasks aparecen en Jira con sus campos correctos, la interfaz muestra ambas como `CREATED_VERIFIED` y la evidencia registra cero reintentos.
