# Plan técnico - Agente de generación controlada de work items en Jira

## Control del documento

| Campo | Valor |
|---|---|
| Versión | 0.3 |
| Fecha | 2026-07-14 |
| Estado | Plan actualizado en revisión |
| Fase inicial | Automatización desde plantilla Excel |
| Plataforma objetivo | Amazon Web Services (AWS) |
| Framework de agentes candidato | Strands Agents sobre Amazon Bedrock AgentCore |
| Modelos iniciales | Gemma mediante Ollama y Gemini mediante API de GCP |
| Jira | Jira Cloud Free |
| Spaces operativos | AT, ASIT y MTTI |
| Fuente normativa prevalente | Normativa general Jira |

## 1. Resumen ejecutivo

El proyecto construirá una aplicación web independiente que transforme un plan de trabajo estructurado en Excel en una propuesta de work items para Jira. La propuesta incluirá título, descripción, responsable, Work Type, Space, jerarquía y los campos normativos que apliquen. Ninguna actividad se escribirá en Jira antes de que el usuario revise y apruebe expresamente una versión final.

La primera fase se limita a una plantilla Excel robustecida. Los equipos realizarán previamente el análisis de sus actividades y capturarán la información en esa plantilla. La lectura de minutas, PDF, Word, Markdown u otros documentos no estructurados queda para evoluciones posteriores.

La solución se desplegará en AWS con un enfoque serverless-first y de pago por uso. Se emplearán servicios administrados solo cuando aporten una capacidad necesaria y medible. Amazon Bedrock AgentCore y Strands Agents se evaluarán para el componente de IA, la conectividad con herramientas y la trazabilidad del agente; las reglas normativas, la aprobación y el executor Jira permanecerán deterministas.

Las credenciales estáticas se administrarán con AWS Secrets Manager. Los documentos y artefactos se almacenarán en Amazon S3; el estado operacional, versiones, idempotencia y metadatos se almacenarán en Amazon DynamoDB. Amazon CloudWatch concentrará logs, métricas, alarmas y trazas, con retención explícita para controlar costo y exposición de datos.

La estrategia de IA será un Model Routing y Model Cascading entre validaciones sin modelo, Gemma mediante Ollama y Gemini mediante la API autorizada de GCP. El envío a Gemini se mantendrá deshabilitado hasta confirmar que el proyecto GCP puede procesar información empresarial bajo las políticas de la organización.

## 2. Objetivo

Implementar una aplicación segura, auditable y costo-consciente que:

1. Reciba una plantilla Excel versionada.
2. Valide estructura, tipos, catálogos y reglas de negocio.
3. Convierta cada fila elegible en un candidato de work item.
4. Utilice IA solo para clasificar, enriquecer o resolver ambigüedades permitidas.
5. Genere una propuesta editable y trazable.
6. Bloquee la escritura hasta una aprobación explícita.
7. Cree los work items mediante Jira MCP conservando jerarquía e idempotencia.
8. Registre el resultado y la trazabilidad técnica en AWS.

## 3. Alcance por horizonte

### 3.1 MVP - Primera fase de automatización

- Entrada exclusiva mediante plantilla `.xlsx`.
- Una plantilla oficial versionada para todos los equipos.
- Validación de hoja, encabezados, tipos, catálogos y filas.
- Mapeo explícito entre filas y campos Jira.
- Clasificación en Epic, Story, Task, Bug o Subtask.
- Resolución de AT, ASIT o MTTI.
- Propuesta editable antes de escribir.
- Un único rol funcional: `ADMIN_EJECUTOR`.
- OAuth 2.1 individual contra Atlassian.
- Escritura controlada mediante MCP.
- Model routing entre reglas, Gemma y Gemini.
- Despliegue, secretos, monitoreo y trazabilidad en AWS.
- Pruebas canario exclusivamente en AT durante el piloto técnico.

### 3.2 Evoluciones posteriores

- Ingesta de minutas, PDF, Word, TXT y Markdown.
- OCR para documentos escaneados.
- Extracción de actividades desde narrativa no estructurada.
- Roles separados de capturista, revisor, aprobador, auditor y administrador.
- DeepSeek, GLM u otros proveedores.
- Aprendizaje a partir de correcciones históricas.
- Expansión a otros Spaces después de una autorización formal.

### 3.3 Fuera del MVP

- Crear actividades directamente desde el Excel sin propuesta.
- Interpretar colores, negritas o posición visual como única evidencia semántica.
- Crear usuarios o modificar permisos Jira.
- Modificar esquemas, workflows, Work Types o campos Jira.
- Asignar responsables inexistentes.
- Escribir en el campo deprecado `Proyecto`.
- Enviar información empresarial a un modelo externo no autorizado.
- Dar al modelo acceso directo e irrestricto a las herramientas de escritura.
- Habilitar DeepSeek o GLM en las primeras fases.

## 4. Decisiones confirmadas

| Tema | Decisión |
|---|---|
| Producto | Aplicación web independiente |
| Primera entrada | Plantilla Excel oficial |
| Evolución documental | PDF, Word, Markdown, TXT y minutas después del MVP |
| Plataforma | AWS |
| Agentes | Evaluar Strands Agents y Amazon Bedrock AgentCore |
| Secretos | AWS Secrets Manager |
| Observabilidad | Amazon CloudWatch y AgentCore Observability |
| Archivos | Amazon S3 |
| Estado y metadatos | Amazon DynamoDB, inicialmente en modo On-Demand |
| Orquestación | AWS Step Functions Standard para flujo con aprobación |
| Procesamiento asíncrono | Amazon SQS con Dead Letter Queue cuando sea necesario |
| Modelos iniciales | Gemma/Ollama y Gemini/GCP |
| Estrategia | Model Routing y Model Cascading |
| Modelos diferidos | DeepSeek y GLM |
| Rol inicial | `ADMIN_EJECUTOR` |
| Jira | Jira Cloud Free |
| Autenticación Jira | OAuth 2.1 por usuario |
| Spaces permitidos | AT, ASIT y MTTI |
| Pruebas de escritura | AT, bajo control canario |
| Proyecto vs Iniciativa | `Iniciativa` activo; `Proyecto` deprecado y no escribible |

## 5. Análisis del Excel de referencia

Archivo revisado: `Plan de trabajo Reclasificación.xlsx`.

### 5.1 Hallazgos estructurales

- Una hoja llamada `PLAN DE TRABAJO`.
- Una tabla declarada de `A1:L188`.
- Ocho columnas principales con encabezado:
  - Actividad.
  - Responsable.
  - Duración (días).
  - Fecha de Inicio.
  - Fecha de Finalización.
  - Estado.
  - ¿Completado?.
  - Comentarios.
- Las columnas `I:K` están vacías.
- Existen cuatro textos aislados en `L2:L5` sin encabezado.
- Los colores verde, amarillo, azul y rojo parecen comunicar agrupación, estado o jerarquía.
- Algunas filas funcionan como agrupadores, módulos o temas, pero comparten la misma estructura que las actividades.
- Hay actividades que contienen prefijos como `BUG:` o `Bug:`, sin un campo formal de Work Type.
- Hay responsables expresados como nombre visible, no como correo ni `accountId` de Jira.
- Varias filas tienen fechas o estados incompletos.
- La información de descripción está distribuida entre Actividad y Comentarios.

### 5.2 Conclusión

El archivo es un buen ejemplo del contenido real, pero no puede ser el contrato de integración definitivo. La automatización no debe inferir jerarquía, Work Type o elegibilidad únicamente por color, orden de fila o texto libre.

Se requiere una plantilla nueva, versionada y validable. La aplicación deberá rechazar o enviar a corrección cualquier archivo que no cumpla el contrato de plantilla.

### 5.3 Mapeo provisional del archivo actual

| Columna actual | Uso provisional | Observación |
|---|---|---|
| Actividad | Título candidato | No permite distinguir agrupador de actividad |
| Responsable | Assignee candidato | Requiere resolver correo o `accountId` |
| Duración | Estimación de origen | No equivale automáticamente a Story Points |
| Fecha de Inicio | Fecha informativa | No siempre es un campo Jira requerido |
| Fecha de Finalización | Due date candidata | Debe validarse contra el calendario y Jira |
| Estado | Estado del plan fuente | No debe forzar una transición Jira al crear |
| ¿Completado? | Indicador histórico | No es un criterio suficiente para crear u omitir |
| Comentarios | Descripción complementaria | Puede contener dependencias y contexto útil |
| L2:L5 | Datos huérfanos | Deben eliminarse o asignarse a una columna formal |

## 6. Contrato de la plantilla Excel v1

### 6.1 Hojas propuestas

| Hoja | Propósito |
|---|---|
| `INSTRUCCIONES` | Reglas de llenado, ejemplos y versión de plantilla |
| `ACTIVIDADES` | Tabla principal editable |
| `CATALOGOS` | Valores permitidos y mapeos controlados |
| `CONTROL` | Equipo, responsable del archivo, versión y fecha de generación |
| `VALIDACION` | Resumen de errores y advertencias, sin ser fuente de verdad |

### 6.2 Columnas de `ACTIVIDADES`

| Campo | Regla inicial |
|---|---|
| `Fila_ID` | Obligatorio, único e inmutable dentro del archivo |
| `Crear_en_Jira` | Obligatorio: Sí o No |
| `Work_Type` | Epic, Story, Task, Bug, Subtask o `AUTO` |
| `Titulo` | Obligatorio; resumen claro y accionable |
| `Descripcion` | Obligatoria; contexto, resultado esperado y criterio de terminación |
| `Responsable_Correo` | Obligatorio para propuesta válida |
| `Space` | AT, ASIT, MTTI o `AUTO` |
| `Parent_Fila_ID` | Obligatorio para Subtask y cuando aplique jerarquía |
| `Fecha_Inicio` | Opcional, fecha real de Excel |
| `Due_Date` | Opcional, fecha real de Excel |
| `Duracion_Dias` | Opcional, numérico mayor que cero |
| `Estado_Origen` | Opcional, informativo; no controla el workflow Jira |
| `Comentarios` | Opcional, contexto adicional |
| `Semaforo` | Catálogo normativo o vacío |
| `Tipo_Seguimiento` | Catálogo normativo o vacío |
| `Sprint` | Valor validable contra Jira o vacío |
| `Linea_Trabajo` | Catálogo normativo o vacío |
| `Iniciativa` | Valor activo o `No aplica`; nunca `Proyecto` |
| `Etiquetas` | Opcional, lista delimitada según especificación |

### 6.3 Reglas de diseño

- No usar celdas combinadas en la tabla de actividades.
- No usar colores como dato de negocio.
- Mantener una sola fila por candidato de work item.
- Usar listas desplegables para catálogos.
- Usar tipos de fecha y número de Excel, no texto formateado.
- Proteger hojas de instrucciones y catálogos contra edición accidental.
- Congelar encabezados y habilitar filtros.
- Incluir ejemplos separados de los datos productivos.
- Incluir una versión de plantilla legible por máquina.
- Rechazar encabezados duplicados, columnas sin nombre y datos fuera de la tabla.
- Calcular una huella SHA-256 del archivo recibido.

### 6.4 Jerarquía explícita

La jerarquía se expresará mediante `Fila_ID` y `Parent_Fila_ID`:

```text
E-001  Epic     sin parent
S-001  Story    parent E-001
T-001  Task     parent E-001, si la configuración Jira lo permite
ST-001 Subtask  parent S-001 o T-001
```

Si la jerarquía propuesta no es compatible con el esquema real del Space, la fila pasará a `NEEDS_INPUT`.

## 7. Flujo funcional del MVP

```text
Usuario ADMIN_EJECUTOR
  -> descarga la plantilla oficial
  -> captura o consolida las actividades
  -> carga el archivo mediante URL prefirmada de S3
  -> validación de archivo y estructura
  -> normalización determinista
  -> Model Router, solo para campos permitidos
  -> reglas normativas y validación Jira de solo lectura
  -> propuesta DRAFT
  -> corrección y nueva versión
  -> validación final
  -> APPROVED con hash inmutable
  -> confirmación de ejecución
  -> executor Jira MCP
  -> resultado por fila y auditoría
```

## 8. Estados de la propuesta

```text
UPLOADED
  -> INVALID_FILE
  -> NORMALIZED
  -> NEEDS_INPUT
  -> DRAFT
  -> VALIDATED
  -> APPROVED
  -> EXECUTING
  -> PARTIAL_SUCCESS
  -> COMPLETED
  -> FAILED
  -> CANCELLED
```

Toda corrección posterior a `APPROVED` genera una nueva versión y requiere otra aprobación.

## 9. Arquitectura AWS propuesta

```text
Navegador
  |
CloudFront + S3 (React/TypeScript)
  |
Amazon Cognito o IdP corporativo
  |
API Gateway HTTP API
  |
Lambda / FastAPI
  |-- URL prefirmada -> S3 documentos
  |-- DynamoDB -> propuestas, filas, versiones, idempotencia
  |-- Step Functions Standard -> flujo y aprobación
  |-- SQS + DLQ -> trabajos asíncronos
  |
  |-- Motor determinista de plantilla y normativa
  |
  `-- Strands Agent en AgentCore Runtime
        |-- Model Router
        |     |-- Gemma mediante Ollama
        |     `-- Gemini mediante API GCP autorizada
        |
        `-- AgentCore Gateway / MCP de solo lectura
              `-- Atlassian Rovo MCP

Executor determinista separado
  `-- Jira MCP de escritura después de APPROVED

Servicios transversales
  |-- Secrets Manager + KMS
  |-- CloudWatch Logs, Metrics, Alarms y trazas OTEL
  |-- AgentCore Observability
  |-- CloudTrail
  `-- AWS Budgets y Cost Anomaly Detection
```

### 9.1 Principio de selección de servicios

No se adoptará un servicio solo por estar disponible en AWS. Cada servicio debe justificar:

- Capacidad requerida.
- Costo esperado.
- Costo operacional evitado.
- Riesgo de dependencia.
- Seguridad y cumplimiento.
- Volumen y patrón de uso.
- Alternativa más simple descartada.

Cada incorporación relevante deberá registrarse mediante una Architecture Decision Record (ADR).

### 9.2 Componentes

#### Frontend

- React y TypeScript.
- Archivos estáticos en S3 y distribución mediante CloudFront.
- Carga directa a S3 mediante URL prefirmada.
- Vista de errores por fila, propuesta, cambios y resultado Jira.

#### API

- Contrato FastAPI/Python conservado.
- Despliegue inicial en Lambda detrás de API Gateway para tráfico bajo o variable.
- Migración a ECS/Fargate solo si las mediciones muestran límites de tiempo, memoria o concurrencia.
- La API no ejecutará inferencia larga dentro de la solicitud HTTP.

#### Orquestación

- Step Functions Standard para procesos que incluyen espera de aprobación humana.
- SQS para desacoplar trabajos y absorber reintentos.
- DLQ para trabajos que excedan la política de reintento.
- EventBridge para eventos operativos o tareas programadas justificadas.

#### Almacenamiento

- S3 para archivos originales, normalizados y payloads aprobados.
- Versionado, cifrado y políticas de ciclo de vida en S3.
- DynamoDB para propuestas, filas, estado, versiones, idempotencia y referencias Jira.
- Modo On-Demand al inicio; evaluar capacidad provisionada solo con datos reales de consumo.
- No usar RDS/PostgreSQL en el MVP salvo que aparezca una necesidad relacional demostrable.

#### Agente

- Strands Agents como SDK Python para unificar proveedores de modelos y herramientas.
- AgentCore Runtime para ejecutar el agente de manera aislada y serverless.
- AgentCore Gateway para exponer o conectar herramientas MCP cuando el PoC valide la cobertura.
- AgentCore Observability para trazas del ciclo del agente integradas con CloudWatch.
- AgentCore Memory no se habilitará inicialmente: la propuesta y sus versiones son estado de negocio, no memoria conversacional.
- Browser y Code Interpreter no se habilitarán en el MVP salvo caso de uso aprobado.

## 10. Model Routing y Model Cascading

### 10.1 Objetivo

Reducir costo, latencia y exposición de datos utilizando el recurso mínimo capaz de resolver cada caso, sin sacrificar calidad ni trazabilidad.

### 10.2 Cascada propuesta

| Nivel | Mecanismo | Uso |
|---|---|---|
| 0 | Reglas deterministas | Esquema, catálogos, fechas, IDs, jerarquía y campos obligatorios |
| 1 | Gemma mediante Ollama | Clasificación o enriquecimiento simple y datos que no deben salir del entorno autorizado |
| 2 | Gemini API en GCP | Casos complejos o de baja confianza, solo si la política de datos lo permite |
| 3 | Revisión humana | Ambigüedad persistente, conflicto normativo o ausencia de evidencia |

### 10.3 Señales del router

- Tipo de operación solicitada.
- Sensibilidad y clasificación del dato.
- Campos faltantes.
- Complejidad y longitud del texto.
- Confianza del nivel anterior.
- Disponibilidad del proveedor.
- Latencia máxima.
- Presupuesto por propuesta.
- Número de tokens estimado.
- Resultado de validación por JSON Schema.

### 10.4 Reglas de seguridad

- Un modelo nunca decide que una propuesta está aprobada.
- Un modelo nunca invoca directamente el executor de escritura.
- El contenido enviado a Gemini se minimiza por fila y propósito.
- No se envía el Excel completo cuando basta una actividad normalizada.
- Se aplican redacción y clasificación antes de cualquier salida a GCP.
- La respuesta de cualquier modelo se trata como no confiable.
- Toda salida debe cumplir un esquema estructurado.
- Los valores de catálogo deben validarse después del modelo.
- Si el router no puede utilizar Gemini, debe degradar a Gemma o revisión humana.

### 10.5 Registro por invocación

- `correlation_id`.
- propuesta y versión.
- fila de origen.
- proveedor, modelo y versión.
- regla que seleccionó el modelo.
- tokens de entrada y salida, cuando el proveedor los reporte.
- latencia.
- estimación de costo.
- confianza.
- resultado de esquema.
- fallback utilizado.
- código de error.

No se registrarán prompts completos, documentos, API keys, tokens OAuth ni datos personales innecesarios en CloudWatch.

### 10.6 Evaluación

Se construirá un conjunto etiquetado con actividades representativas del Excel. Se medirán:

- Exactitud de Work Type.
- Exactitud de Space.
- Precisión de jerarquía.
- Exactitud de responsable.
- Valores inventados.
- Tasa correcta de `NEEDS_INPUT`.
- Costo por propuesta.
- Latencia p50 y p95.
- Diferencia de calidad entre Gemma y Gemini.

Los umbrales de escalamiento no se fijarán por intuición; se calibrarán con este conjunto.

## 11. Uso de Strands Agents y AgentCore

### 11.1 Por qué encajan

Strands soporta proveedores Gemini y Ollama en Python mediante una interfaz común. AgentCore admite Strands, modelos externos a Bedrock, MCP y trazabilidad basada en OpenTelemetry.

### 11.2 Límites de uso

- La importación de Excel será código determinista, no una herramienta autónoma del agente.
- El motor normativo será código versionado y probado.
- El agente podrá proponer Work Type, Space o enriquecimiento dentro de una allowlist.
- Las herramientas disponibles durante propuesta serán de solo lectura.
- La escritura Jira permanecerá en un executor separado.
- AgentCore Gateway y Policy se evaluarán como defensa adicional, no como sustituto del Approval Gate.

### 11.3 PoC obligatorio

Antes de adoptar AgentCore en producción se compararán dos alternativas:

1. Strands en AgentCore Runtime.
2. Strands en Lambda o ECS/Fargate.

La comparación medirá costo, tiempo de arranque, duración, integración MCP, observabilidad, operación y seguridad. AgentCore se adoptará si aporta una ventaja medible.

## 12. Integración con Jira mediante MCP

### 12.1 Separación de capacidades

| Contexto | Capacidades |
|---|---|
| Análisis y propuesta | Metadatos, usuarios, Work Types, campos, JQL y lectura |
| Validación previa | Validar Space, `accountId`, Sprint, jerarquía y campos |
| Executor | Crear, editar, enlazar o transicionar solo después de aprobación |

### 12.2 Controles

- Allowlist de AT, ASIT y MTTI.
- AT no es valor predeterminado ante ambigüedad.
- `Proyecto` bloqueado.
- Payload aprobado inmutable.
- Clave de idempotencia por propuesta, versión y `Fila_ID`.
- Mapeo de `Fila_ID` a Jira key.
- Reintentos solo para fallos transitorios.
- Resultado individual por fila.
- No reintentar errores funcionales sin corrección.

### 12.3 Prueba de capacidades

El MCP oficial deberá probarse con metadatos reales para confirmar:

- Work Types por Space.
- Campos obligatorios y personalizados.
- Creación de Epic, Story, Task, Bug y Subtask.
- Jerarquía y relaciones.
- Búsqueda de usuario y `accountId`.
- Sprint.
- Due date.
- Iniciativa.
- Línea de trabajo.
- Semáforo y tipo de seguimiento.

Si falta una capacidad, se documentará un adaptador complementario detrás de AgentCore Gateway sin exponerlo libremente al modelo.

## 13. OAuth 2.1 con Atlassian

1. El usuario inicia sesión en la aplicación.
2. Selecciona `Conectar con Jira`.
3. La aplicación redirige a Atlassian.
4. El usuario introduce correo, contraseña y MFA únicamente en Atlassian.
5. Atlassian muestra los permisos solicitados.
6. El usuario acepta.
7. Atlassian devuelve un código temporal al callback autorizado.
8. El backend obtiene tokens y los asocia al usuario.
9. Las operaciones MCP usan la identidad y permisos de ese usuario.

La aplicación nunca recibe ni almacena la contraseña Jira.

## 14. Identidad y rol de la aplicación

El MVP tendrá un único rol:

| Rol | Capacidades |
|---|---|
| `ADMIN_EJECUTOR` | Cargar archivo, revisar errores, editar propuesta, aprobar, ejecutar Jira, consultar resultado y auditoría |

Aunque una misma persona pueda aprobar y ejecutar, la interfaz mantendrá dos acciones explícitas:

1. Aprobar la versión final.
2. Confirmar la ejecución en Jira.

Esto evita escrituras accidentales y prepara la separación de funciones futura.

La autenticación podrá integrarse con Cognito o con el IdP corporativo. La autorización Jira continuará siendo OAuth individual.

## 15. Gestión de secretos y tokens

### 15.1 Secrets Manager

Se almacenarán:

- API key de Gemini, mientras sea el mecanismo autorizado.
- Client secrets de integraciones OAuth.
- Secretos de firma o cifrado propios de la aplicación.
- Credenciales técnicas que no puedan sustituirse por IAM Role.

Controles:

- Cifrado con KMS.
- Acceso por IAM de mínimo privilegio.
- Caching para no leer el secreto en cada operación.
- Rotación cuando el proveedor lo permita.
- VPC Endpoint si la arquitectura de red lo justifica.
- Monitoreo con CloudTrail y CloudWatch.
- Prohibición de secretos en repositorio, variables de frontend, Excel o logs.

### 15.2 Tokens OAuth dinámicos

Los access y refresh tokens Jira no deben modelarse automáticamente como un secreto estático por usuario. El PoC evaluará:

1. AgentCore Identity y su token vault.
2. Almacenamiento cifrado con KMS y control de acceso en el backend.

Secrets Manager seguirá almacenando el client secret, pero el mecanismo final de tokens se decidirá después de validar compatibilidad con Atlassian Rovo MCP OAuth 2.1.

## 16. Observabilidad y trazabilidad

### 16.1 CloudWatch

- Logs estructurados JSON.
- Métricas de negocio y técnicas.
- Alarmas por errores, DLQ, latencia, costo y fallos Jira.
- Dashboards para propuestas, routing, modelos y ejecución.
- Trazas OpenTelemetry y AgentCore Observability.

### 16.2 Correlación

El mismo `correlation_id` acompañará:

- carga S3.
- ejecución Step Functions.
- invocación de Lambda.
- sesión AgentCore.
- llamada de modelo.
- llamada MCP.
- creación Jira.

### 16.3 Retención propuesta para validar

| Ambiente | Retención CloudWatch inicial |
|---|---|
| Desarrollo | 14 días |
| Pruebas | 30 días |
| Producción | 90 días |

Los eventos de auditoría funcional se conservarán en DynamoDB/S3 conforme a la política empresarial, no indefinidamente en CloudWatch.

## 17. Seguridad

- Cifrado en tránsito y reposo.
- Bloqueo de acceso público en S3.
- URLs prefirmadas de vida corta.
- IAM de mínimo privilegio.
- Separación de roles de ejecución entre frontend, API, agente y executor.
- Validación MIME, extensión, tamaño y firma del archivo.
- Límite de filas y tamaño por propuesta.
- Análisis antimalware del archivo antes de procesarlo.
- Detección de prompt injection en texto de celdas.
- El contenido del Excel se considera dato, no instrucción del sistema.
- Validación de JSON Schema después de cada modelo.
- Allowlist de herramientas y Spaces.
- Redacción de PII y secretos en logs.
- CloudTrail para acciones administrativas.
- Revisión de dependencias e imágenes de contenedor.
- Ambientes separados al menos para desarrollo y producción.

## 18. Control de costos

### 18.1 Principios

- Etiquetas de costo por proyecto, ambiente y propietario.
- AWS Budgets con alertas tempranas.
- Cost Anomaly Detection.
- DynamoDB On-Demand durante demanda incierta.
- Lambda y AgentCore por consumo, no capacidad ociosa.
- Retención explícita de CloudWatch.
- Ciclo de vida de S3 para originales y artefactos.
- Sin AgentCore Memory, Browser o Code Interpreter por defecto.
- Sin RDS, NAT Gateway, OpenSearch o clústeres permanentes sin justificación.
- Límites de tokens, filas y reintentos por propuesta.
- Registro de costo aproximado por modelo.

### 18.2 Guardas operativas

- Presupuesto mensual por ambiente.
- Límite de invocaciones Gemini por propuesta.
- Concurrencia reservada en Lambda donde aplique.
- Cuotas de SQS y Step Functions observadas.
- Timeouts cortos y reintentos con backoff.
- Alarma por crecimiento de logs y almacenamiento.
- Revisión mensual de servicios sin uso.

## 19. Auditoría mínima

Por propuesta:

- ID, versión y hash.
- archivo S3 y versión de objeto.
- versión de plantilla.
- usuario.
- timestamps.
- estado.
- filas válidas, advertidas y rechazadas.
- modelo y router utilizados.
- versión de reglas normativas.
- aprobación.
- confirmación de ejecución.
- Jira keys creadas.
- errores y reintentos.

Por fila:

- `Fila_ID`.
- valores normalizados.
- evidencia de origen.
- cambios del usuario.
- sugerencias del modelo.
- validaciones.
- payload aprobado.
- resultado Jira.

## 20. Pruebas en Jira

### 20.1 Principios

- Dry-run antes de toda escritura.
- Mocks para pruebas automáticas.
- Metadatos de solo lectura en AT, ASIT y MTTI.
- Escritura inicial únicamente en AT.
- Aprobación explícita antes de cada canario.

### 20.2 Canary test

- Una propuesta con uno a tres work items.
- Título con marca acordada de piloto.
- Descripción con `correlation_id` y propósito de prueba.
- Sin datos sensibles.
- Responsable informado.
- Registro de keys creadas.
- Verificación manual posterior.
- Cierre o limpieza según la política Jira, sin borrado automático.

## 21. Plan por fases

### Fase 0 - Decisiones y gobierno

- Confirmar región AWS y ambientes.
- Confirmar autorización de datos para Gemini.
- Confirmar presupuesto y alertas.
- Confirmar retención.
- Confirmar identidad de la aplicación.
- ADR de AgentCore, cómputo, almacenamiento e IaC.

Salida: decisiones mínimas aprobadas.

### Fase 1 - Plantilla Excel oficial

- Diseñar las cinco hojas.
- Definir columnas y catálogos.
- Agregar validaciones y ejemplos.
- Crear especificación JSON Schema equivalente.
- Crear validador local y casos de prueba.
- Migrar una muestra del Excel de Reclasificación.

Salida: plantilla v1 y conjunto de datos de prueba etiquetado.

### Fase 2 - Fundación AWS

- Infraestructura como código.
- S3, KMS, DynamoDB, Secrets Manager y CloudWatch.
- API Gateway, Lambda y autenticación.
- Presupuestos, etiquetas y alarmas.
- Pipeline de despliegue.

Salida: ambiente de desarrollo reproducible.

### Fase 3 - Ingesta determinista

- Carga prefirmada.
- Validación de archivo.
- Normalización.
- Detección de duplicados y datos huérfanos.
- Propuesta sin IA.
- Persistencia de versiones.

Salida: Excel -> DRAFT sin llamadas de modelo ni Jira.

### Fase 4 - Model Router

- Integrar Strands.
- Integrar Gemma/Ollama.
- Integrar Gemini detrás de feature flag.
- Implementar niveles 0 a 3.
- Evaluar calidad, costo y latencia.
- PoC AgentCore Runtime frente a Lambda/ECS.

Salida: routing medido y política de escalamiento aprobada.

### Fase 5 - Jira MCP de solo lectura

- OAuth 2.1.
- AgentCore Gateway o cliente MCP directo en PoC.
- Metadatos de Spaces.
- Usuarios y `accountId`.
- Work Types, campos, Sprint y jerarquía.
- Pruebas de contrato.

Salida: propuesta validada contra Jira sin escritura.

### Fase 6 - Revisión y aprobación

- UI de errores y advertencias.
- Edición controlada.
- Comparación de versiones.
- Hash de versión aprobada.
- Doble acción aprobar y ejecutar.

Salida: Approval Gate completo.

### Fase 7 - Executor y canario AT

- Idempotencia.
- Orden jerárquico de creación.
- Manejo de fallos parciales.
- Resultado por fila.
- Canario controlado en AT.

Salida: primera escritura Jira validada.

### Fase 8 - UAT y endurecimiento

- Pruebas de seguridad.
- Pruebas de costo y carga.
- Runbooks y alarmas.
- Recuperación ante fallos.
- UAT con los usuarios definidos.
- Aprobación para producción.

Salida: MVP operativo.

## 22. Criterios de aceptación del MVP

- Solo acepta la versión autorizada de la plantilla.
- Detecta columnas sin nombre, datos fuera de tabla y IDs duplicados.
- No depende de colores para identificar jerarquía o estado.
- Cero escrituras Jira antes de aprobación y confirmación.
- Cada work item conserva `Fila_ID` y evidencia de origen.
- No escribe en `Proyecto`.
- Solo escribe en AT, ASIT o MTTI.
- Ambigüedad no resuelta produce `NEEDS_INPUT`.
- Subtasks y relaciones mantienen jerarquía válida.
- Assignee se resuelve a `accountId` válido.
- La propuesta aprobada es inmutable.
- Un reintento no crea duplicados.
- Los fallos parciales son recuperables.
- Modelos externos pueden deshabilitarse sin detener el flujo.
- Toda salida de modelo cumple esquema o se rechaza.
- Cada invocación registra proveedor, modelo, latencia y costo estimado.
- Secrets Manager contiene los secretos estáticos.
- CloudWatch contiene trazas correlacionadas sin secretos ni documentos completos.
- Presupuestos, retención y alarmas están configurados.
- Las pruebas iniciales en AT usan las marcas de piloto.

## 23. Preguntas pendientes antes de implementación

### 23.1 Bloqueantes para producción

1. ¿Qué región AWS y qué cuentas o ambientes estarán autorizados?
2. ¿El proyecto GCP y la API de Gemini están autorizados para información empresarial no anonimizada?
3. ¿La API key corresponde a Gemini Developer API o se utilizará Vertex AI?
4. ¿Dónde se ejecutará Ollama/Gemma en producción: EC2, ECS, SageMaker u otra plataforma aprobada?
5. ¿Cuál es el presupuesto mensual o límite de créditos para desarrollo y producción?
6. ¿Cuál es la política de retención para Excel, propuestas, auditoría y logs?
7. ¿Qué IdP autenticará la aplicación: Cognito, Entra ID, AD/LDAP u otro?
8. ¿Se permite salida HTTPS desde AWS hacia Atlassian y GCP?

### 23.2 Resolubles durante las primeras fases

9. ¿Cuál será el máximo inicial de filas por archivo?
10. ¿Los responsables se capturarán por correo corporativo o por `accountId` Jira?
11. ¿Existe `Iniciativa = No aplica` en AT, ASIT y MTTI?
12. ¿Qué convención identificará los canarios en AT?
13. ¿Qué estándar de IaC utiliza la organización: CDK, Terraform o CloudFormation?
14. ¿Qué datos de las columnas `L2:L5` representan y dónde deben ubicarse?
15. ¿El estado actual del Excel debe conservarse solo como evidencia o filtrar qué actividades crear?
16. ¿Desean que la plantilla v1 sea el siguiente entregable inmediato?

## 24. Riesgos principales

| Riesgo | Mitigación |
|---|---|
| Semántica implícita por color | Campos explícitos, catálogos y migración asistida |
| Datos empresariales enviados a GCP sin autorización | Feature flag apagado y revisión de política |
| Gasto no controlado | Budgets, alertas, límites y routing |
| Complejidad excesiva de AgentCore | PoC comparativo y adopción modular |
| Duplicados Jira | Idempotencia por versión y `Fila_ID` |
| Escritura accidental | Approval Gate y executor separado |
| Credenciales expuestas | Secrets Manager, KMS, IAM y redacción de logs |
| MCP sin cobertura de campos | Prueba de capacidades y adaptador controlado |
| Falta de sandbox Jira | Mocks, dry-run, lectura y canarios AT |
| Inferencias inventadas | Esquema, evidencia, confianza y revisión humana |

## 25. Objetivo propuesto para Codex

Este objetivo no debe activarse hasta aprobar esta versión y responder las preguntas bloqueantes mínimas:

```text
Implementar por fases el MVP descrito en
docs/plan_tecnico_agente_jira_v0.3.md.

Comenzar por la plantilla Excel v1, su contrato y un validador determinista.
Después crear la fundación AWS costo-consciente y el flujo Excel -> propuesta,
sin llamadas de IA ni escrituras Jira. Integrar Strands, AgentCore y el Model
Router solamente después de contar con pruebas y métricas. Mantener Gemini
deshabilitado hasta confirmar autorización para datos empresariales.

No escribir en Jira antes de completar el MCP simulado, las pruebas de contrato,
el Approval Gate y una autorización explícita del usuario para el canario AT.
No escribir en Proyecto ni fuera de AT, ASIT o MTTI. No exponer secretos,
tokens, documentos o prompts completos en logs.

Trabajar por checkpoints verificables, ejecutar pruebas después de cada cambio,
registrar decisiones y costos, y detenerse ante una decisión de seguridad,
infraestructura, datos o Jira que requiera intervención del usuario.
```

## 26. Referencias

### 26.1 Internas

- Normatividad operativa para el seguimiento de actividades, proyectos, soporte y sesiones en Jira, versión preliminar v2.0.
- Guía operativa para registrar actividades en Jira y evidencias en Google Drive, piloto 2026.
- Plan de trabajo Reclasificación.xlsx.
- Plan técnico v0.2 del Agente Jira.

### 26.2 Externas

- Amazon Bedrock AgentCore overview: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/what-is-bedrock-agentcore.html
- Amazon Bedrock AgentCore pricing: https://aws.amazon.com/bedrock/agentcore/pricing/
- Strands Agents model providers: https://strandsagents.com/latest/documentation/docs/user-guide/concepts/model-providers/
- AWS Secrets Manager best practices: https://docs.aws.amazon.com/secretsmanager/latest/userguide/best-practices.html
- Amazon CloudWatch log groups and retention: https://docs.aws.amazon.com/AmazonCloudWatch/latest/logs/Working-with-log-groups-and-streams.html
- Amazon DynamoDB core components: https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/HowItWorks.CoreComponents.html
- Amazon S3: https://docs.aws.amazon.com/AmazonS3/latest/userguide/Welcome.html
- Atlassian Rovo MCP OAuth 2.1: https://support.atlassian.com/atlassian-rovo-mcp-server/docs/configuring-oauth-2-1/
- Atlassian Rovo MCP supported tools: https://support.atlassian.com/atlassian-rovo-mcp-server/docs/supported-tools/
- Gemini API terms: https://ai.google.dev/gemini-api/terms
- Gemma models: https://ai.google.dev/gemma/docs

## 27. Historial

| Versión | Fecha | Cambio |
|---|---|---|
| 0.1 | 2026-07-13 | Propuesta conceptual y revisión normativa |
| 0.2 | 2026-07-14 | Aplicación independiente, Jira Free, OAuth 2.1, Linux interno e IA local |
| 0.3 | 2026-07-14 | Excel como primera fase, arquitectura AWS, AgentCore, Strands, Secrets Manager, CloudWatch y model routing Gemma/Gemini |
