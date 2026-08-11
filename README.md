# Agente Jira - MVP local v0.20.0

## Cambios v0.20 · Objetivo 4E

- La política explícita 4E admite `Task`, `Bug`, `Story`, `Epic` y `Subtask`, sólo en AT y con máximo cinco actividades por lote.
- En “Origen y propuesta” se puede elegir una actividad padre y guardar la relación junto con el resto de los cambios.
- Se permiten las relaciones `Epic → Task/Bug/Story` y `Task/Bug/Story → Subtask`; Epic no puede tener padre y Subtask no puede ser padre.
- Una Subtask exige padre. La aplicación bloquea referencias inexistentes, excluidas, incompatibles, autorreferencias y ciclos.
- Si padre e hijo están en el mismo lote, el orden se corrige automáticamente. En lotes sucesivos, el padre debe haberse creado y verificado primero.
- La clave simbólica de fila se resuelve a la clave Jira real justo antes de crear al hijo, sin reintentos automáticos.
- La lectura posterior comprueba también `parent.key`; una relación ausente o distinta detiene el lote.
- Cada resultado y evidencia muestra la clave del padre resuelta y verificada.

Consulta la [documentación del Objetivo 4E](docs/objetivo_4e_jerarquias.md) y su [guía de validación](docs/guia_validacion_objetivo_4e.md).

## Cambios v0.19 · Objetivo 4D

- La lista positiva de escritura ahora admite `Task`, `Bug` y `Story`, únicamente en AT.
- Un lote puede combinar los tres Work Types, con máximo cinco actividades.
- Cada actividad usa los metadatos y campos publicados por Jira para su propio Work Type.
- Los títulos quedan identificados como `AgenteTest_Task_`, `AgenteTest_Bug_` o `AgenteTest_Story_`.
- La lectura posterior compara el Work Type realmente creado con el solicitado.
- Sprint se resuelve y revalida por Work Type antes de la primera escritura.
- La frase de un lote mixto es `CREAR N ACTIVIDADES EN AT`.
- Epic, Subtask, ASIT y MTTI permanecen bloqueados.

Consulta la [documentación del Objetivo 4D](docs/objetivo_4d_bug_story.md) y su [guía de validación](docs/guia_validacion_objetivo_4d.md).

## Cambios v0.18 · editor atómico y Objetivo 4C.2

- Seleccionar un responsable Jira ya no guarda ni cierra el editor.
- El responsable queda como cambio pendiente junto con título, descripción, Work Type y nota.
- `Guardar y volver a validar` verifica otra vez la cuenta Jira y crea una sola versión con todos los cambios.
- Los planes con más de cinco Tasks pueden continuar en lotes sucesivos, conservando el máximo de cinco por confirmación.
- El avance muestra Tasks verificadas, pendientes y lotes registrados sin realizar llamadas MCP adicionales.
- Las actividades ya preparadas o intentadas no vuelven a ofrecerse; las `NOT_ATTEMPTED` continúan disponibles.

Consulta la [corrección del editor](docs/correccion_editor_responsable_v0_18.md) y el [alcance del Objetivo 4C.2](docs/objetivo_4c_2_continuidad_lotes.md).

## Cambios v0.17 · Objetivo 4C.1

- Selección explícita de una a cinco actividades elegibles `AT / Task`.
- Vista previa del orden, responsable y Sprint antes de escribir.
- Confirmación dinámica: `CREAR N TASKS EN AT`.
- Revalidación de todos los Sprints antes de la primera escritura.
- Creación secuencial seguida de lectura y verificación por actividad.
- Detención inmediata ante rechazo, resultado incierto o lectura incompleta; las restantes quedan `NOT_ATTEMPTED`.
- Idempotencia por selección, cero reintentos automáticos y evidencia consolidada descargable.
- El inicio normal continúa en modo seguro; 4C.1 sólo se habilita con su comando específico.

Consulta la [implementación del Objetivo 4C.1](docs/objetivo_4c_1_lote_tasks_at.md) y la [guía de validación](docs/guia_validacion_objetivo_4c1.md).

Aplicación local para convertir la Plantilla Excel v1.1 en una propuesta revisable, prevalidarla y crear actividades controladas en Jira Cloud mediante OAuth y Atlassian Rovo MCP. El inicio habitual mantiene la escritura deshabilitada; cada modo real debe activarse explícitamente.

## Cambios v0.16 · Objetivo 4B.2

- El usuario selecciona o escribe el nombre del Sprint; nunca necesita conocer su ID.
- Los Sprints activos y futuros se recuperan dinámicamente mediante búsquedas JQL de Rovo MCP y se conservan cinco minutos para la interfaz.
- Si el plan no indica Sprint y Jira muestra exactamente uno activo, se selecciona automáticamente.
- Si existen varios Sprints activos, la aplicación no adivina: bloquea la prevalidación hasta que el usuario seleccione uno.
- El Dry run guarda nombre, ID, estado, tablero, origen y modo de resolución como evidencia.
- Antes de `createJiraIssue`, el catálogo se consulta nuevamente sin caché. Si el Sprint cerró o dejó de ser visible, no se realiza ninguna escritura.
- La consulta JQL es paginada y un catálogo incompleto se considera inseguro; nunca habilita una selección automática parcial.

Consulta la [implementación y criterios del Objetivo 4B.2](docs/objetivo_4b_2_resolucion_sprint.md).

## Correcciones v0.15.1

- Un error HTTP 4xx explícito de Jira ahora termina como `REJECTED`; sólo una interrupción sin respuesta concluyente queda como `UNKNOWN`.
- La simulación local permanece disponible mientras el modo 4B está activo, por lo que ya no es necesario reiniciar en modo 4A después de corregir una propuesta.
- Sprint se validaba como ID numérico antes de escribir; esta captura manual fue sustituida en v0.16 por resolución automática.
- La interfaz identifica claramente si la conexión está en solo lectura o con el envío controlado habilitado.

## Cambios v0.15

- Se omite un Objetivo 4A.1 separado: las mejoras de claridad se integran directamente al flujo final.
- La simulación informa de forma explícita si fue exitosa y conserva evidencia con cero llamadas MCP.
- El modo 4B transforma el payload candidato al contrato real de `createJiraIssue` expuesto por Rovo.
- Sólo permite una `Task` en `AT`, con responsable resuelto, prevalidación vigente y una segunda confirmación escrita.
- La aplicación registra el envío antes del transporte, nunca reintenta automáticamente y consulta la Task creada con `getJiraIssue`.
- El resultado distingue: creada y verificada, creada con verificación incompleta, rechazada o incierta.
- El inicio habitual conserva la política segura y no puede escribir en Jira.

Consulta la [implementación del Objetivo 4B](docs/objetivo_4b_escritura_controlada.md) y su [guía de validación](docs/guia_validacion_objetivo_4b.md).

## Cambios v0.14

- El responsable corregido en Jira prevalece en los controles editables; el nombre del Excel se conserva solo como dato de origen.
- Los valores generales pueden editarse desde cualquier etapa y se propagan a todas las actividades en una version nueva.
- Si la propuesta estaba aprobada, el cambio la reabre y obliga a repetir aprobacion y prevalidacion.
- Iniciativa, Linea de trabajo, Sprint, Tipo de seguimiento y Semaforo usan las opciones que Jira publique en sus metadatos.
- Si Jira no expone opciones, la interfaz lo informa y permite captura manual; la prevalidacion comprueba cualquier catalogo disponible.

Consulta el [ajuste de datos finales v0.14](docs/ajuste_datos_finales_v0_14.md).

## Componentes

- `backend/`: API FastAPI, parser Excel, reglas, versionado SQLite e integración MCP de solo lectura.
- `frontend/`: aplicación React/TypeScript para login, carga y revisión.
- `releases/plantilla_excel_v1_1/`: contrato Excel congelado.
- `docs/`: plan técnico, diseño y esquema JSON.

## Inicio rápido

Requisitos: Python 3.12+, Node.js 20+ y pnpm.

```powershell
scripts\setup.cmd
scripts\dev.cmd
```

Después abre `http://localhost:5173`.

Credenciales locales de demostración:

- Usuario: `admin@agentejira.local`
- Contraseña: `AgenteJira2026!`

Estas credenciales sólo existen para desarrollo local y pueden sustituirse mediante variables de entorno.

### Inicio controlado del Objetivo 4B

El inicio normal continúa sin escritura. Sólo para la prueba real autorizada, detén primero el servidor del puerto 8000 y ejecuta:

```powershell
scripts\start-objective-4b.cmd
```

Este modo no crea nada al arrancar. La escritura ocurre exclusivamente al completar la simulación, preparar el envío, escribir `CREAR 1 TASK EN AT` y pulsar finalmente `Crear 1 Task real en AT`.

## Verificación

```powershell
scripts\test.cmd
```

La verificación ejecuta pruebas del parser, reglas, OAuth cifrado, revalidación, versionado, archivado, Dry run, contrato JSON y API, además de las pruebas y compilación TypeScript/React.

## Flujo vigente v0.13

- La aplicación muestra todos los pendientes de una actividad.
- `Guardar y volver a validar` recalcula la decisión.
- Cuando no quedan pendientes, la actividad pasa automáticamente de `Revisar` a `Listas`.
- La barra de propuestas puede contraerse con el botón superior o `Ctrl+B`.
- El historial permite buscar, filtrar, archivar y restaurar propuestas.
- El archivado es reversible y no elimina las versiones.
- El nombre operativo puede cambiarse sin alterar el nombre ni el hash del Excel fuente.
- Una actividad excluida sólo puede reactivarse con motivo y siempre vuelve primero a revisión.
- Cuando no quedan pendientes, la propuesta queda lista para aprobación.
- Aprobar y ejecutar la prevalidación final ocurre en una sola acción.
- El resultado distingue éxito, advertencias técnicas y bloqueos que requieren corrección.
- La evidencia JSON combina la propuesta aprobada y el Dry run auditable.
- La autorización Atlassian se conserva cifrada al salir o reiniciar en Windows.
- Reabrir crea otra versión editable y conserva la aprobación anterior.
- Una propuesta aprobada con Dry run vigente y cero bloqueos muestra el panel del Objetivo 4A.
- El usuario selecciona una sola actividad AT/Task, revisa la vista previa y confirma su hash.
- La simulación utiliza un gateway local: no invoca herramientas MCP ni crea actividades Jira.
- La intención y sus cambios de estado quedan persistidos para auditoría.
- La evidencia JSON demuestra `real_mcp_calls=0`, `write_performed=false` y `jira_issue_created=false`.
- La conexión Jira se configura desde la barra lateral y ya no ocupa la pantalla de trabajo.
- La carga del Excel sólo aparece al iniciar una propuesta nueva.
- La propuesta muestra el paso actual: revisar actividades, validar con Jira o probar el envío.
- Las actividades, la validación y la prueba segura pueden plegarse para reducir saturación.
- La vista previa muestra nombres de campos Jira; los IDs técnicos quedan ocultos en un detalle opcional.
- El selector de responsables dejó de mostrar el catálogo de ejemplo y consulta coincidencias reales en Jira.
- Al terminar la prueba aparece `Generar nueva propuesta`, que limpia el área de trabajo sin borrar el historial.

## Límites del Objetivo 4A

- Consulta Jira mediante Rovo MCP exclusivamente con herramientas permitidas de lectura.
- El almacenamiento DPAPI es para desarrollo local Windows; AWS requerirá Secrets Manager/KMS.
- No contiene secretos productivos.
- No crea, edita, comenta ni transiciona work items.
- Sólo admite una actividad `Task` del Space `AT` y una confirmación con vigencia de 15 minutos.
- El payload mostrado es candidato hasta confirmar el esquema real de `createJiraIssue`.
- La asignabilidad estricta y el contrato real de creación siguen siendo controles obligatorios antes del Objetivo 4B.
- La clasificación y generación de texto son deterministas y explicables.

Consulta [la documentación de ejecución](docs/ejecucion_local_objetivo_1.md) para detalles.

Consulta también la [guía de validación del Objetivo 1.1](docs/guia_validacion_objetivo_1_1.md).

La validación vigente es la [guía del Objetivo 1.2](docs/guia_validacion_objetivo_1_2.md).

El cierre vigente de Jira es la [documentación del Objetivo 3B.2](docs/objetivo_3b_2_cierre_prevalidacion.md).

La preparación de la primera escritura controlada está en el [plan del Objetivo 4](docs/objetivo_4_preparacion_v1_1.md). El resultado implementado y su validación están en la [evidencia del Objetivo 4A](docs/evidencia_objetivo_4a.md), la [guía de validación](docs/guia_validacion_objetivo_4a.md) y el [ajuste de experiencia v0.13](docs/ajuste_ux_flujo_v0_13.md). La política entregada permanece en `PLANNING_ONLY`; no habilita escrituras.

La versión documental consolidada más reciente es la [Documentación integral Agente Jira v0.20](docs/documentacion_integral_agente_jira_v0.20.md). La [documentación técnica v1.1](docs/documentacion_tecnica_agente_jira_v1.1.md) se conserva como corte histórico anterior.

## Casos de demostración

- [Plan válido derivado del timeline](examples/plan_timeline_referencia_v1_1_valido.xlsx)
- [Plan inválido por encabezado](examples/plan_v1_1_invalido_encabezado.xlsx)
- [Propuesta JSON validada](examples/propuesta_timeline_referencia_v1_1.json)
- [Evidencia del Objetivo 1.1](docs/evidencia_objetivo_1_1.md)
- [Evidencia del Objetivo 1.2](docs/evidencia_objetivo_1_2.md)

## Inicio controlado del Objetivo 4C.1

Detén cualquier servidor que ocupe el puerto 8000 y ejecuta:

```powershell
scripts\start-objective-4c1.cmd
```

El arranque no escribe en Jira. La aplicación sólo crea actividades después de seleccionar entre una y cinco Tasks, revisar el orden, escribir `CREAR N TASKS EN AT` y pulsar el botón final de creación real. Para volver al modo seguro habitual usa `scripts\start.cmd`.

## Inicio controlado del Objetivo 4D

Para habilitar exclusivamente Task, Bug y Story en AT:

```powershell
scripts\start-objective-4d.cmd
```

El arranque no escribe en Jira. Cada lote mantiene el máximo de cinco, confirmación explícita, creación secuencial, lectura posterior y cero reintentos.

## Inicio controlado del Objetivo 4E

Para habilitar Epic, Subtask y relaciones padre-hijo en AT:

```powershell
scripts\start-objective-4e.cmd
```

El arranque no escribe en Jira. La escritura sólo ocurre después de aprobar la propuesta, completar el Dry run, revisar el orden padre-hijo, escribir la frase exacta y confirmar el envío real. Para volver al modo seguro utiliza `scripts\start.cmd`.
