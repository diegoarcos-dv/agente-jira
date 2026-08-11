# Guía de validación manual del Objetivo 4B

## Antes de comenzar

- Usa una propuesta aprobada con Dry run vigente y cero bloqueos.
- Selecciona una actividad de prueba que pueda permanecer en AT.
- Confirma que el título empiece con `AgenteTest_Task_`.
- No ejecutes esta prueba dos veces con la misma propuesta.
- Si usarás Sprint, selecciona su nombre en el catálogo Jira. La aplicación resolverá el ID internamente; también puede seleccionar automáticamente el único Sprint activo.
- Si aparecen varios Sprints activos, selecciona uno expresamente. La aplicación nunca elegirá entre varios de forma silenciosa.

## 1. Comprobar el modo seguro

1. Inicia normalmente con `scripts\start.cmd`.
2. Abre la propuesta y completa la simulación.
3. Debe aparecer `Simulación local exitosa` y `0 escrituras en la simulación`.
4. Debe mostrarse que la escritura real está deshabilitada.

Resultado esperado: no existe botón capaz de crear la Task.

## 2. Activar temporalmente 4B

1. Detén el servidor con `Ctrl+C`.
2. Ejecuta `scripts\start-objective-4b.cmd`.
3. Inicia sesión y confirma que Atlassian está conectado.
4. Recupera la propuesta simulada.

Resultado esperado: aparece `Preparar envío real`. Pulsarlo no crea nada.

Si Jira rechaza algún valor, puedes reabrir la propuesta, corregirlo, aprobar, prevalidar y repetir la simulación sin salir del modo 4B. La simulación continúa siendo local y realiza cero llamadas MCP.

## 3. Revisar y confirmar

1. Comprueba título, `AT`, `Task`, responsable y, si aplica, el nombre/estado del Sprint resuelto.
2. Abre opcionalmente `Ver payload real y huella`.
3. Escribe `CREAR 1 TASK EN AT`.
4. Pulsa `Confirmar creación real`.

Resultado esperado: la pantalla advierte que el siguiente botón sí escribirá, que primero revalidará el Sprint y que no habrá reintentos.

## 4. Ejecutar una sola vez

Pulsa una sola vez `Crear 1 Task real en AT` y espera el resultado.

No recargues ni repitas si aparece `Resultado incierto`. En ese caso busca en Jira el título exacto o la etiqueta `agente-test` antes de cualquier decisión.

## 5. Resultado esperado

El caso satisfactorio muestra:

- `Task creada y verificada en Jira`;
- una clave similar a `AT-1234`;
- cinco comprobaciones aprobadas;
- dos llamadas MCP: una creación y una lectura;
- Sprint revalidado inmediatamente antes de la creación, cuando se haya seleccionado uno;
- cero reintentos;
- botones para abrir Jira y descargar evidencia 4B.

La Task real permanecerá en AT. La aplicación no la elimina, edita ni transiciona automáticamente.

Si el Sprint se cerró o dejó de ser visible después de la prevalidación, el envío debe detenerse con un mensaje claro y cero llamadas a `createJiraIssue`. En ese caso actualiza la prevalidación; no fuerces ni repitas el payload anterior.

## 6. Regresar al modo seguro

1. Detén el servidor 4B con `Ctrl+C`.
2. Inicia de nuevo con `scripts\start.cmd`.
3. Consulta `/api/health` si deseas confirmar `jira_write_enabled=false`.
