# Agente Jira - Documentación técnica consolidada

| Dato | Valor |
|---|---|
| Versión documental | 1.1 |
| Fecha de corte | 20 de julio de 2026 |
| Estado del producto | MVP local v0.11; Objetivo 3B.2 concluido; Objetivo 4 preparado |
| Entrada vigente | Plantilla Excel v1.1 congelada |
| Jira | Jira Cloud Free, sitio dpti.atlassian.net |
| Spaces autorizados | AT, ASIT y MTTI; prueba inicial sólo en AT |
| Integración | Atlassian Rovo MCP mediante OAuth 2.1 por usuario |
| Escritura Jira | Deshabilitada (`PLANNING_ONLY`) |

## 1. Resumen ejecutivo

Agente Jira es una aplicación independiente que transforma un plan de trabajo en Excel en una propuesta de actividades Jira revisable, versionada y auditable. Su propósito no es ser otro importador masivo: reduce la captura manual, genera descripciones a partir del contexto disponible, clasifica Work Types, resuelve responsables y obliga a revisar las excepciones antes de cualquier interacción con Jira.

La primera fase utiliza exclusivamente la Plantilla Excel v1.1. Los documentos PDF, Word, Markdown, TXT y otros formatos quedan para evoluciones posteriores. Un plan normalmente corresponde a un solo Space.

El MVP local ya permite cargar, validar, corregir, versionar, aprobar y prevalidar propuestas contra Jira real mediante Rovo MCP, sin escribir en Jira. La autorización Atlassian se conserva cifrada localmente en Windows. La siguiente etapa será el Objetivo 4A: completar el ejecutor simulado, la auditoría de intenciones y la confirmación final. La primera escritura real se reserva para el Objetivo 4B y será una única Task identificable en AT.

## 2. Principios del producto

- Reducir la información que el usuario captura manualmente.
- Pedir correcciones únicamente cuando una actividad presenta una excepción real.
- Mantener siempre una propuesta editable antes de aprobarla.
- Separar generación, revisión, prevalidación y ejecución.
- Aplicar reglas deterministas a controles normativos, permisos e idempotencia.
- No entregar herramientas de escritura al LLM.
- Conservar evidencia suficiente para reconstruir cada decisión.
- Fallar en modo seguro: ante duda no se escribe en Jira.

## 3. Alcance vigente

### 3.1 Incluido

- Aplicación web independiente con backend Python/FastAPI y frontend React/TypeScript.
- Login local de desarrollo con un rol administrador.
- Plantilla Excel v1.1 congelada.
- Space general por plan y Spaces permitidos AT, ASIT y MTTI.
- Generación de título y descripción revisables.
- Clasificación inicial de Task, Bug, Story, Epic y Subtask cuando los metadatos lo permiten.
- Catálogo local y selección de responsables Jira reales.
- Historial, búsqueda, renombrado y archivado de propuestas.
- Estados Incluir, Revisar y Excluir, con recuperación de actividades excluidas.
- Aprobación versionada e inmutable.
- OAuth 2.1 por usuario y conexión al servidor oficial Atlassian Rovo MCP.
- Prevalidación Dry run contra metadatos reales de Jira.
- Evidencia JSON con garantía `write_performed=false`.
- Política y kill switch iniciales para preparar el Objetivo 4.

### 3.2 Diferido

- Entrada desde PDF, Word, Markdown, TXT y minutas.
- Gestión completa de usuarios y recuperación de contraseña.
- Despliegue productivo en AWS.
- AgentCore, Strands Agents y model routing.
- Gemini mediante Vertex AI y Gemma mediante infraestructura dedicada.
- Procesamiento por lotes en Jira.
- Escritura en ASIT y MTTI.
- Creación controlada de Epic, Story, Bug y Subtask.
- MCP interno para controles que Rovo no exponga.

### 3.3 Fuera del MVP actual

- Modificar, transicionar o eliminar issues existentes.
- Ejecutar escrituras autónomas decididas por un modelo.
- Reintentar automáticamente una creación de resultado incierto.
- Almacenar contraseñas, tokens OAuth o API keys en documentación o logs.

## 4. Plantilla Excel v1.1 congelada

La plantilla v1.1 es el contrato de entrada de la primera fase. Busca evitar que el usuario replique en Excel la complejidad de Jira.

### Datos generales del plan

- Space: normalmente uno por plan.
- Iniciativa: sustituye al campo Proyecto, considerado deprecado.
- Tipo de seguimiento, cuando aplique al conjunto.

### Datos mínimos por actividad

- Actividad.
- Responsable escrito por nombre.
- Frente de trabajo o proyecto.
- Contexto.
- Due date, si ya se conoce.
- Estado o decisión de origen cuando corresponda.
- Comentarios opcionales.

La aplicación compone la descripción y normaliza los datos. El responsable se mapea de nombre a correo o account ID de Jira y siempre queda sujeto a revisión cuando la coincidencia no es inequívoca.

## 5. Flujo funcional implementado

```text
Plantilla Excel v1.1
  -> validación estructural
  -> normalización y reglas
  -> propuesta versionada
  -> corrección de excepciones
  -> aprobación e inmutabilidad
  -> prevalidación Jira por Rovo MCP
  -> evidencia Dry run sin escritura
```

Una propuesta bloqueada por Jira se reabre para corregir únicamente las actividades afectadas. Después de resolverlas, el usuario revisa y aprueba las correcciones; la aplicación vuelve a ejecutar la prevalidación final. Los detalles técnicos permanecen disponibles como evidencia, pero no compiten con la acción principal.

## 6. Estado de objetivos

| Objetivo | Estado | Resultado principal |
|---|---|---|
| 1 | Concluido | Carga y transformación local de Plantilla Excel v1.1 |
| 1.1 | Concluido | Flujo práctico de correcciones y navegación de propuestas |
| 1.2 | Concluido | Renombrado, archivado y recuperación de actividades excluidas |
| 2 | Diferido | AWS, identidad productiva, AgentCore y modelos |
| 3A | Concluido | OAuth 2.1 y lectura real mediante Rovo MCP |
| 3B | Concluido | Prevalidación Dry run sin escritura |
| 3B.1 | Concluido | Correcciones Jira guiadas y acción principal clara |
| 3B.2 | Concluido | OAuth persistente cifrado, aprobación y Dry run unificados |
| 4 | Preparado | Política segura y diseño de escritura controlada |
| 4A | Siguiente | Simulador, auditoría de intenciones y confirmación final |
| 4B | No autorizado | Una única Task canario real en AT |
| 4C | Futuro | Expansión controlada a lotes, tipos y Spaces adicionales |

## 7. Arquitectura implementada localmente

```text
Usuario
  -> React + TypeScript
  -> FastAPI
       -> reglas y normalización deterministas
       -> SQLite: propuestas, versiones y Dry runs
       -> almacenamiento OAuth cifrado con Windows DPAPI
       -> cliente Atlassian Rovo MCP
            -> Jira Cloud: AT, ASIT y MTTI
```

El backend conserva una lista positiva de herramientas de lectura. Cualquier herramienta no autorizada se rechaza antes de alcanzar el transporte MCP. El diagnóstico del Objetivo 4 puede inspeccionar si Rovo anuncia `createJiraIssue` y `getJiraIssue`, pero no las invoca.

## 8. Integración Atlassian Rovo MCP

La conexión utiliza OAuth 2.1 interactivo por usuario. La aplicación descubre el sitio, cloudId, Spaces, Work Types, campos y cuentas Jira visibles con los permisos del usuario conectado.

La autorización se guarda localmente cifrada mediante Windows DPAPI. Salir de la aplicación no desconecta Atlassian; la opción Desconectar elimina explícitamente la autorización guardada. En Linux/AWS deberá sustituirse DPAPI por un mecanismo compatible con Secrets Manager y KMS.

### Herramientas de lectura permitidas

- `atlassianUserInfo`
- `getAccessibleAtlassianResources`
- `getVisibleJiraProjects`
- `getJiraProjectIssueTypesMetadata`
- `getJiraIssueTypeMetaWithFields`
- `lookupJiraAccountId`
- `findAssignableUsers`, sólo si el servidor la anuncia

## 9. Prevalidación Jira - Objetivo 3B.2

Una propuesta aprobada se valida contra el snapshot real de Jira. Cada actividad obtiene uno de estos resultados:

- `READY`: superó las validaciones disponibles.
- `BLOCKED`: requiere una corrección antes de continuar.
- `SKIPPED`: fue excluida por el usuario.

La evidencia incluye identificador `DRY-...`, huella de propuesta, clave idempotente por fila, usuario, versión y problemas accionables. Repetir la prevalidación sin cambios recupera el mismo registro.

Rovo puede confirmar una cuenta exacta y activa sin entregar evidencia suficiente de que sea asignable en un Space y Work Type. En 3B.2 esto aparece como advertencia técnica porque no existe escritura. Antes de procesar lotes deberá incorporarse una comprobación estricta equivalente a la búsqueda de usuarios asignables de Jira.

## 10. Preparación del Objetivo 4

### 10.1 División de la etapa

- 4A: preparación segura, diagnóstico, simulación y auditoría; cero escrituras.
- 4B: una sola Task real en AT, con autorización explícita inmediata.
- 4C: expansión posterior a otras actividades y Spaces.

### 10.2 Primera prueba controlada

La convención del título será:

```text
AgenteTest_Task_<FechaHora>_<ProposalIdCorto>_<Resumen>
```

Se utilizará la etiqueta `agente-test` únicamente si el esquema real confirma que está soportada.

### 10.3 Creación atómica

El responsable se enviará dentro de la misma llamada `createJiraIssue`. Si Jira rechaza el responsable o cualquier campo, la operación completa deberá fallar y no debe quedar una Task creada sin asignación. No se creará primero para editarla después.

### 10.4 Kill switch

La llamada real requerirá simultáneamente:

1. Política `SINGLE_CANARY`.
2. `jira_write_enabled=true`.
3. Space AT.
4. Work Type Task.
5. Exactamente una actividad.
6. Propuesta aprobada y Dry run vigente sin bloqueos.
7. Cuenta Atlassian exacta y activa.
8. Responsable incluido en la creación atómica.
9. Segunda confirmación del usuario.
10. Herramienta exacta `createJiraIssue`.

Actualmente la política permanece en `PLANNING_ONLY` y `jira_write_enabled=false`.

### 10.5 Idempotencia práctica

- Registrar una intención única antes de contactar Jira.
- No permitir dos intenciones activas para propuesta, versión y fila.
- No realizar reintentos automáticos.
- Marcar como `UNKNOWN` cualquier timeout posterior al envío.
- Reconciliar manualmente por prefijo, marcador o issue key antes de repetir.
- Leer la Task creada con `getJiraIssue` y comparar los campos aprobados.

## 11. Auditoría requerida

La aplicación debe registrar:

- execution ID y correlation ID;
- propuesta, versión, fila, Dry run e idempotency key;
- usuario local y usuario Atlassian;
- política y confirmación aplicadas;
- herramienta MCP y hash del payload;
- tiempos de preparación, envío y respuesta;
- resultado, issue key, URL y lectura posterior;
- error sanitizado y estado de reconciliación.

Estados previstos:

```text
PREPARED -> CANCELLED
PREPARED -> SUBMITTED -> CREATED_VERIFIED
                      -> REJECTED
                      -> UNKNOWN
UNKNOWN  -> RECONCILED_CREATED
         -> RECONCILED_NOT_FOUND
```

Tokens OAuth, cookies y cabeceras Authorization nunca deben almacenarse.

## 12. Arquitectura AWS objetivo

El despliegue corporativo continúa planeado para AWS, pero no está implementado en el MVP local.

```text
Acceso web protegido
  -> aplicación FastAPI + React
  -> almacenamiento S3 para archivos y artefactos
  -> DynamoDB para propuestas, versiones e idempotencia
  -> CloudWatch para logs, métricas y alarmas
  -> Secrets Manager + KMS para secretos y credenciales protegidas
  -> AgentCore + Strands para capacidades agentes justificadas
  -> Atlassian Rovo MCP para Jira Cloud
```

Step Functions no se incorpora inicialmente. Se reevaluará si aparecen procesos distribuidos, aprobaciones de larga duración o recuperación compleja que lo justifiquen.

## 13. Estrategia de modelos futura

La cascada prevista es:

1. Reglas deterministas para validación, normativa y campos obligatorios.
2. Gemma para tareas locales o de costo controlado que realmente necesiten lenguaje natural.
3. Gemini mediante Vertex AI cuando la complejidad o calidad lo requiera.
4. Revisión humana obligatoria antes de ejecutar cambios externos.

Ningún modelo decidirá permisos, aprobación, idempotencia o escritura Jira. La primera fase Excel funciona principalmente con reglas y no depende de un LLM para ser útil.

## 14. Seguridad y operación

- OAuth 2.1 por usuario para Atlassian.
- Mínimo privilegio y listas positivas de herramientas.
- Una sola escritura canario antes de cualquier lote.
- AT debe tratarse como productivo.
- Auditoría propia porque Jira Free no ofrece audit log administrativo.
- No exponer tokens, contraseñas ni API keys.
- Secrets Manager/KMS para el futuro despliegue AWS.
- CloudWatch con sanitización y correlación, sin contenido sensible innecesario.
- Presupuesto y alarmas de costos antes del despliegue productivo.

## 15. Verificación vigente

Al corte de esta versión se verificó:

- 46 pruebas automatizadas de backend aprobadas.
- 8 pruebas automatizadas de frontend aprobadas.
- Compilación TypeScript/Vite de producción aprobada.
- Política Jira validada contra JSON Schema.
- Rechazo de `PLANNING_ONLY` con escritura habilitada.
- Kill switch de política probado sin transporte MCP.
- Diagnóstico de Objetivo 4 con cero invocaciones de herramientas.
- Ausencia de endpoint de creación Jira.

## 16. Criterios para activar 4A

### Ya disponibles

- Política en `PLANNING_ONLY`.
- Escritura deshabilitada.
- Space limitado a AT y Work Type limitado a Task para el canario.
- Límite de una actividad.
- Sin reintento automático.
- Herramientas de edición, comentario, worklog y transición bloqueadas.

### Pendientes dentro de 4A

- Verificar en la sesión real que Rovo anuncia `createJiraIssue` y `getJiraIssue`.
- Capturar sus esquemas sin invocarlas.
- Confirmar ID y campos reales de Task en AT.
- Implementar el registro de intenciones y estados de ejecución.
- Implementar el gateway MCP simulado.
- Implementar la segunda confirmación y su caducidad.
- Seleccionar la actividad no productiva que funcionará como canario.

## 17. Próximo paso recomendado

Activar e implementar el Objetivo 4A. Esta acción seguirá sin escribir en Jira. Al finalizar y validar 4A, el usuario deberá autorizar explícitamente el Objetivo 4B, seleccionar una única actividad de prueba y acordar quién cerrará o eliminará manualmente la Task canario después de validarla.

## 18. Referencias internas vigentes

- `docs/plan_tecnico_agente_jira_v1.0.md`
- `docs/objetivo_3b_2_cierre_prevalidacion.md`
- `docs/objetivo_4_preparacion_v1_1.md`
- `docs/checklist_objetivo_4a.md`
- `config/jira_execution_policy_v1.json`
- `docs/schemas/jira_execution_policy_v1.schema.json`

## 19. Historial documental

| Versión | Cambio principal |
|---|---|
| 0.6 | Plantilla v1.1, arquitectura AWS y objetivos iniciales |
| 0.9 | Conexión OAuth y Rovo MCP en solo lectura |
| 1.0 | Dry run real y auditable contra Jira |
| 1.1 | Cierre 3B.2 y preparación segura del Objetivo 4 |
