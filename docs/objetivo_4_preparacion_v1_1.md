# Plan del Objetivo 4 — escritura controlada en Jira

| Dato | Valor |
|---|---|
| Versión | 1.1 |
| Fecha | 20 de julio de 2026 |
| Estado | Objetivo 4A implementado; escritura deshabilitada |
| Destino inicial | AT |
| Work Type inicial | Task |
| Máximo inicial | Una actividad |
| Integración | Atlassian Rovo MCP con OAuth 2.1 por usuario |

## 1. Resultado esperado

Crear exactamente una Task de prueba controlada en AT a partir de una versión aprobada y prevalidadada, verificarla mediante lectura posterior y conservar evidencia completa, sin permitir ninguna otra operación de escritura ni reintentos automáticos.

El título seguirá la convención:

```text
AgenteTest_Task_<FechaHora>_<ProposalIdCorto>_<Resumen>
```

La actividad incluirá la etiqueta `agente-test` cuando el esquema real de Rovo confirme que el campo puede enviarse.

## 2. División recomendada

### Objetivo 4A — preparación segura, sin escritura

1. Reconectar Atlassian y verificar persistencia OAuth.
2. Detectar que Rovo expone `createJiraIssue` y `getJiraIssue`.
3. Capturar el esquema real de ambas herramientas sin invocarlas.
4. Resolver el mapeo de campos de Task en AT.
5. Implementar el registro local de intenciones y resultados.
6. Implementar el kill switch y la lista positiva de una sola herramienta.
7. Construir la confirmación final y probarla con un gateway MCP simulado.
8. Mantener `jira_write_enabled=false`.

### Objetivo 4B — una prueba controlada real

1. Seleccionar una sola fila aprobada.
2. Generar un Dry run vigente con cero bloqueos.
3. Mostrar el payload final y solicitar una segunda confirmación.
4. Cambiar temporalmente la política a `SINGLE_CANARY`.
5. Invocar una sola vez `createJiraIssue`.
6. Leer la actividad creada mediante `getJiraIssue`.
7. Comparar título, descripción, Space, Work Type, responsable y campos opcionales.
8. Registrar el issue key y volver inmediatamente a `PLANNING_ONLY`.

### Objetivo 4C — expansión posterior

Procesamiento de varias actividades, Epic/Story/Bug/Subtask, ASIT y MTTI quedan fuera de la primera escritura. Requerirán validación estricta previa de asignabilidad, jerarquía, manejo de resultados parciales y aprobación independiente.

## 3. Decisiones técnicas

### 3.1 Ejecutor determinista

El LLM no tendrá acceso a herramientas de escritura. Un servicio determinista recibirá únicamente la versión aprobada, la fila elegida y su Dry run vigente. El ejecutor validará la política y construirá los argumentos MCP con reglas explícitas.

### 3.2 Lista positiva mínima

Durante 4B sólo podrá habilitarse `createJiraIssue`. Permanecerán bloqueadas:

- `addCommentToJiraIssue`;
- `addWorklogToJiraIssue`;
- `editJiraIssue`;
- `transitionJiraIssue`.

`getJiraIssue` continuará disponible para la lectura posterior.

### 3.3 Responsable en operación atómica

Rovo ofrece `lookupJiraAccountId`, pero no una herramienta específica de asignabilidad. Para una sola prueba se enviará Assignee dentro de la misma creación:

- si Jira acepta todos los campos, se crea una Task correctamente asignada;
- si el responsable no es asignable, Jira rechaza la operación y se crean cero actividades;
- nunca se creará primero para asignar después.

Esta solución es suficiente para una prueba única. Antes de lotes se deberá incorporar una comprobación separada equivalente a `GET /rest/api/3/user/assignable/search`, posiblemente mediante un MCP interno de validación.

### 3.4 Idempotencia práctica

Rovo no documenta una clave de idempotencia para `createJiraIssue`. Por eso:

- se crea una intención local única antes de llamar a MCP;
- una combinación propuesta-versión-fila sólo puede tener una intención activa;
- no hay reintento automático;
- si la conexión se corta después de enviar, el estado queda `UNKNOWN`;
- un operador reconcilia por prefijo, marcador e issue key antes de decidir cualquier repetición.

No se probará la idempotencia repitiendo una escritura real. Esa propiedad se verificará con pruebas automatizadas y simuladores.

### 3.5 Auditoría propia obligatoria

Jira Free no ofrece el audit log administrativo. La aplicación almacenará como mínimo:

- execution ID y correlation ID;
- propuesta, versión, fila, Dry run e idempotency key;
- usuario local y usuario Atlassian;
- política aplicada y confirmación;
- herramienta MCP y hash de sus argumentos;
- fechas de preparación, envío y respuesta;
- resultado, issue key, URL y lectura posterior;
- error sanitizado y estado de reconciliación.

Nunca se guardarán tokens OAuth, cookies ni cabeceras de autorización.

## 4. Máquina de estados

```text
PREPARED
  -> CANCELLED
  -> SUBMITTED
       -> CREATED_VERIFIED
       -> REJECTED
       -> UNKNOWN

UNKNOWN
  -> RECONCILED_CREATED
  -> RECONCILED_NOT_FOUND
```

`UNKNOWN` nunca permite un reintento automático.

## 5. Kill switch

La escritura requerirá simultáneamente:

1. política `mode=SINGLE_CANARY`;
2. `jira_write_enabled=true`;
3. Space `AT`;
4. Work Type `Task`;
5. exactamente una fila;
6. Dry run vigente sin bloqueos;
7. segunda confirmación válida;
8. herramienta exacta `createJiraIssue`.

Si falla una condición, la llamada MCP no debe ocurrir. El valor predeterminado y el archivo actualmente entregado permanecen en `PLANNING_ONLY` y `false`.

## 6. Datos que debemos obtener de Jira antes de 4B

- esquema real de entrada de `createJiraIssue`;
- ID de Task en AT;
- campos obligatorios y formatos aceptados;
- field ID y opción para Tipo de seguimiento;
- field ID/formato de Due date;
- soporte para labels;
- forma exacta de Description;
- respuesta real de creación y campos necesarios para `getJiraIssue`.

Estos datos no son secretos. No deben compartirse tokens, API keys, cookies ni contraseñas.

## 7. Criterios de aceptación de 4A

- El diagnóstico de capacidades no invoca herramientas de escritura.
- La política segura valida contra su esquema.
- El ejecutor simulado sólo acepta AT, Task y una fila.
- Toda operación distinta de `createJiraIssue` se rechaza antes del transporte.
- La confirmación caduca si cambia la propuesta, el Dry run o el payload.
- Un timeout produce `UNKNOWN`, nunca un reintento.
- La suite demuestra cero llamadas reales a Jira.

## 8. Criterios de aceptación de 4B

- Existe una autorización explícita inmediatamente antes de la llamada.
- Se invoca exactamente una vez `createJiraIssue`.
- Se crea como máximo una Task con prefijo `AgenteTest_Task_` en AT.
- La lectura posterior coincide con la vista previa aprobada.
- La aplicación conserva la evidencia local completa.
- El kill switch vuelve a modo seguro al terminar.

## 9. Riesgos específicos de Jira Free

- No hay sandbox incluido.
- El audit log administrativo no está disponible.
- Los permisos y roles no son personalizables en cuentas que siempre han sido Free.

Por lo anterior, AT debe tratarse como productivo: una sola creación, identificable, confirmada y verificable.

## 10. Siguiente acción

Validar manualmente el **Objetivo 4A** con una propuesta aprobada y un Dry run vigente sin bloqueos. Después se podrá diseñar y autorizar por separado el Objetivo 4B. La primera llamada real continúa reservada para 4B y requerirá una nueva instrucción explícita del usuario.

## 11. Base técnica implementada

La preparación inicial ya incluye:

- política versionada en `config/jira_execution_policy_v1.json`;
- esquema estricto en `docs/schemas/jira_execution_policy_v1.schema.json`;
- carga y validación obligatoria de la política al iniciar el backend;
- rechazo de la combinación insegura `PLANNING_ONLY` con escritura habilitada;
- evaluación determinista de las barreras del canario, sin transporte MCP;
- diagnóstico autenticado `GET /api/objectives/4/readiness`, que sólo inspecciona las herramientas anunciadas y reporta cero invocaciones;
- pruebas automatizadas de los controles anteriores.

Además, el Objetivo 4A ya incluye:

- registro persistente de intenciones y auditoría;
- selección de una sola actividad `AT`/`Task`;
- vista previa candidata con prefijo `AgenteTest_Task_`;
- confirmación explícita ligada al hash del payload y con caducidad de 15 minutos;
- revalidación de la propuesta y el Dry run antes de simular;
- gateway local simulado sin transporte MCP;
- descarga de evidencia con cero llamadas MCP y cero escrituras Jira;
- pruebas de backend, interfaz y compilación.

Esta base no contiene un endpoint de creación real, no amplía la lista de herramientas MCP invocables y no habilita escritura en Jira.
