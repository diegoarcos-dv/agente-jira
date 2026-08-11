# Plan técnico - Agente de generación controlada de work items en Jira

## Control del documento

| Campo | Valor |
|---|---|
| Versión | 0.6 |
| Fecha | 2026-07-16 |
| Estado | Objetivo 1 implementado y verificado |
| Entrada inicial | Plantilla Excel v1.1 congelada |
| Plataforma objetivo | Amazon Web Services (AWS) |
| Agente | Strands Agents sobre Amazon Bedrock AgentCore |
| Modelos | Reglas, Gemma y Gemini mediante Vertex AI |
| Jira | Jira Cloud Free |
| Sitio | `https://dpti.atlassian.net` |
| Spaces permitidos | AT, ASIT y MTTI |
| Integración Jira preferida | Atlassian Rovo MCP Server mediante OAuth 2.1 |

## 1. Resumen ejecutivo

El proyecto construirá una aplicación web independiente que convierta un plan de trabajo en Excel en una propuesta revisable de work items para Jira. El usuario capturará intención de trabajo, no identificadores ni formularios técnicos de Jira. La aplicación generará título, descripción, Work Type, jerarquía y campos normativos, y mostrará su interpretación antes de cualquier escritura.

La plantilla v1.1 mantiene sólo dos campos obligatorios por fila: `Actividad` y `Responsable`. `Frente_de_trabajo_o_Proyecto`, contexto, fecha, estado y comentarios son opcionales. Un plan corresponde normalmente a un solo Space, elegido una vez al cargar el archivo. Esta versión queda congelada: su archivo, estructura, encabezados y reglas de validación constituyen el contrato de entrada del Objetivo 1. Cualquier cambio incompatible se publicará como una versión posterior.

El archivo `TIMELINE IA 150726 V.2.xlsx` fue evaluado como referencia de planes reales. Su contenido confirma que la plantilla mínima puede representar las actividades relevantes sin copiar la complejidad de un Gantt. El timeline no sustituye la plantilla v1.1; se utilizará como caso de prueba para normalización, jerarquías y responsables heredados.

La aplicación utilizará un catálogo controlado para relacionar el nombre capturado con correo corporativo y `accountId` Jira. Las actividades claras quedarán listas; las ambiguas se concentrarán en revisión; las completadas o rechazadas se propondrán excluidas y podrán reactivarse.

La infraestructura objetivo se alojará en AWS. Amazon Cognito administrará usuarios y contraseñas de la aplicación. AgentCore y Strands ejecutarán el componente agente. S3 almacenará archivos; DynamoDB conservará propuestas, versiones e idempotencia; CloudWatch concentrará trazabilidad; Secrets Manager almacenará secretos estáticos.

Jira se integrará inicialmente con el Atlassian Rovo MCP Server oficial mediante OAuth 2.1 por usuario. Gemini se consumirá preferentemente mediante Vertex AI y autenticación federada desde AWS, evitando claves permanentes. La clave GCP revisada durante la planeación está restringida a Speech-to-Text y Text-to-Speech y no se modificará.

## 2. Principio de producto

> La plantilla captura la intención del trabajo; la aplicación traduce esa intención a Jira y permite revisar la traducción antes de ejecutarla.

La solución se divide en tres contratos:

1. **Captura humana:** lenguaje natural, mínima y fácil de completar.
2. **Propuesta interna:** normalización, inferencias, advertencias, decisiones y versiones.
3. **Payload Jira:** IDs y campos técnicos generados exclusivamente por la aplicación.

## 3. Alcance del MVP

### Incluido

- Aplicación web independiente.
- Login con usuarios administrados.
- Entrada `.xlsx` mediante plantilla v1.1.
- Contrato de entrada v1.1 congelado y verificable por huella SHA-256.
- Validación estructural y por fila.
- Catálogo de responsables.
- Propuesta de Epic, Story, Task, Bug o Subtask.
- Descripción generada desde actividad, contexto y comentarios.
- Revisión por excepciones.
- Versionado, aprobación e idempotencia.
- AgentCore y Strands para tareas asistidas.
- Model routing entre reglas, Gemma, Gemini y revisión humana.
- Jira Rovo MCP con OAuth 2.1.
- Prueba controlada de escritura en AT.

### Diferido

- PDF, Word, Markdown, TXT y minutas.
- OCR.
- Roles separados de capturista, revisor y aprobador.
- DeepSeek, GLM u otros proveedores.
- Múltiples Spaces frecuentes por archivo.
- Importación universal de libros externos con múltiples formatos de hoja.
- Interpretación automática de todas las hojas del timeline de referencia.
- Aprendizaje automático a partir de correcciones históricas.

### Fuera del MVP

- Crear en Jira al cargar el archivo.
- Solicitar IDs técnicos en Excel.
- Usar colores como fuente única de significado.
- Modificar workflows, permisos o campos Jira.
- Escribir en el campo deprecado `Proyecto`.
- Compartir contraseñas, API keys o tokens con el modelo.
- Permitir que el agente invoque escritura sin aprobación.

## 4. Decisiones confirmadas

| Tema | Decisión v0.6 |
|---|---|
| Producto | Aplicación web independiente |
| Clave correcta | `MTTI`; se elimina la variante `MITT` |
| Plantilla | Versión 1.1 congelada; cambios incompatibles requieren v1.2 |
| Obligatorios por fila | Actividad y Responsable |
| Agrupación opcional | `Frente_de_trabajo_o_Proyecto` |
| Campo Jira Proyecto | Deprecado y no escribible |
| Space | Uno por plan; AT, ASIT o MTTI |
| Login | Cognito User Pool con usuarios creados por administrador |
| Responsable | Nombre en Excel; catálogo nombre-correo-accountId |
| Agente | AgentCore + Strands |
| Step Functions | Diferido hasta justificar flujo durable |
| Gemma | Ollama local y PoC inicial en EC2 GPU |
| Gemini | Preferir Vertex AI desde AWS mediante identidad federada |
| Jira MCP | Rovo MCP oficial como primera opción |
| Autenticación Jira | OAuth 2.1 por usuario |
| Prueba Jira | Prueba controlada de escritura en AT |

## 5. Plantilla Excel v1.1

### 5.0 Estado del contrato

La plantilla v1.1 queda congelada el 2026-07-16 como contrato oficial de entrada del Objetivo 1.

| Propiedad | Valor |
|---|---|
| Archivo canónico | `releases/plantilla_excel_v1_1/plantilla_plan_trabajo_jira_v1_1.xlsx` |
| Versión de plantilla | `1.1` |
| Hoja de captura | `PLAN_DE_TRABAJO` |
| Encabezados | Fila 5, columnas A:G |
| Filas reservadas | 6 a 55 |
| Huella SHA-256 | `9a4b913d55a27afdbee04efbc011ed134b394190eeaf968e94b2150b010f4204` |
| Política de cambios | Una modificación incompatible produce una versión nueva; no se reemplaza silenciosamente la v1.1 |

La aplicación verificará la versión, los encabezados y la estructura. La huella permitirá identificar el archivo canónico, pero no será requisito que los archivos llenados por los usuarios conserven la misma huella, porque sus datos cambiarán.

### 5.1 Columnas

| Columna | Obligatoria | Finalidad |
|---|---:|---|
| `Actividad *` | Sí | Qué necesita realizarse |
| `Responsable *` | Sí | Nombre de la persona principal |
| `Frente_de_trabajo_o_Proyecto` | No | Agrupación natural del plan |
| `Contexto_o_Resultado` | No | Propósito, resultado esperado, entregable o condición de término |
| `Fecha_Objetivo` | No | Fecha objetivo si existe |
| `Estado_Actual` | No | Estado del plan fuente |
| `Comentarios` | No | Dependencias, restricciones o antecedentes |

### 5.2 Aclaración de Proyecto

`Frente_de_trabajo_o_Proyecto` es una agrupación de origen. No se mapea al campo deprecado `Proyecto` de Jira. Internamente se normalizará como `frente_trabajo_origen`.

### 5.3 Datos generales del plan

La aplicación solicitará una vez:

- Space obligatorio.
- Iniciativa si aplica.
- Línea de trabajo si aplica.
- Sprint si aplica.
- Tipo de seguimiento según normativa.
- Semáforo si aplica.

### 5.4 Métrica de utilidad

La meta de 80 % no significa aceptar actividades incompletas. Significa que al menos 80 % de las filas válidas debería producir una propuesta sin pregunta individual. Es una hipótesis que se medirá con usuarios y no una condición de validez del archivo.

### 5.5 Evaluación del timeline de referencia

El libro `TIMELINE IA 150726 V.2.xlsx` contiene siete hojas con tres finalidades diferentes:

- cuatro cronogramas tipo Gantt;
- dos hojas de agenda o seguimiento;
- una hoja de acuerdos e incidencias.

El libro aporta evidencia de formatos reales, pero no constituye un contrato estable: el significado de `Actividad` y `Descripción` cambia entre hojas, existen responsables informados sólo en filas agrupadoras, y las columnas semanales son elementos de presentación.

#### Equivalencias de normalización

| Campo del timeline | Campo o concepto v1.1 | Tratamiento |
|---|---|---|
| `Actividad` o `Descripción` | `Actividad` | Elegir el texto accionable según el perfil de hoja |
| `Responsable` | `Responsable` | Resolver persona; heredar de la agrupación sólo cuando sea inequívoco |
| `Fase` | `Frente_de_trabajo_o_Proyecto` | Normalizar como agrupación de origen |
| `Agente/Componente` | `Frente_de_trabajo_o_Proyecto` | Utilizar como agrupación alternativa |
| `Entregable` | `Contexto_o_Resultado` | Incorporar al resultado esperado |
| `Fecha Fin`, `Nueva Fecha` o `Fecha de entrega` | `Fecha_Objetivo` | Elegir la fecha vigente y advertir contradicciones |
| `Estatus` | `Estado_Actual` | Normalizar al catálogo v1.1 |
| `Observaciones` | `Comentarios` | Conservar como antecedentes o restricciones |
| `Dependencia` e ID jerárquico | Relación propuesta | Utilizar para inferir dependencia o parent sin exigir IDs al usuario |
| `Avance` | Seguimiento | No requerido para crear una propuesta Jira |
| `Fecha Inicio` | Cronograma | Diferido; no se agrega a la plantilla v1.1 |
| Semanas del Gantt | Presentación | Ignorar como campos de negocio |

#### Decisión de alcance

- La plantilla v1.1 continúa como única entrada oficial del Objetivo 1.
- Una hoja representativa del timeline se transformará en un caso de prueba compatible con v1.1.
- La selección de hoja, los perfiles de importación externa y la herencia automática de responsables quedan preparados en diseño, pero no forman parte del criterio obligatorio de término del Objetivo 1.
- No se agregarán columnas a la plantilla por información que ya puede representarse mediante agrupación, contexto, fecha, estado o comentarios.

## 6. Catálogo de responsables

El Excel conserva el nombre por facilidad de captura. La aplicación utiliza un catálogo central:

| Campo interno | Uso |
|---|---|
| `nombre_captura` | Nombre esperado en el archivo |
| `correo_corporativo` | Identidad corporativa |
| `jira_account_id` | Identificador estable para Jira Cloud |
| `aliases` | Variaciones conocidas del nombre |
| `activo` | Evitar nuevas asignaciones a usuarios inactivos |
| `spaces_permitidos` | Restricción opcional por Space |

El catálogo se almacenará cifrado en DynamoDB o en una fuente corporativa aprobada. No es un secreto, pero contiene información personal y debe tener acceso restringido.

Resolución:

1. Normalizar nombre y espacios.
2. Buscar coincidencia exacta o alias.
3. Consultar Jira mediante lectura MCP.
4. Resolver un único `accountId`.
5. Si existen cero o varias coincidencias, enviar la fila a revisión.

## 7. Flujo funcional

1. Usuario inicia sesión en la aplicación.
2. Carga plantilla v1.1.
3. La API valida archivo, versión, hoja y encabezados.
4. El usuario selecciona Space y valores generales.
5. El sistema normaliza filas y resuelve responsables.
6. Las reglas excluyen completadas y rechazadas por defecto.
7. El router decide reglas, Gemma, Gemini o revisión humana.
8. Se genera una propuesta versionada.
9. El usuario resuelve excepciones y corrige contenido.
10. La versión final se aprueba.
11. Una confirmación separada habilita la ejecución Jira.
12. El executor valida de nuevo, crea con idempotencia y registra resultados.

## 8. Arquitectura AWS inicial

```text
React/TypeScript
       |
Amazon Cognito
       |
FastAPI
  |-- S3: archivos y artefactos
  |-- DynamoDB: propuestas, versiones, catálogo e idempotencia
  |-- CloudWatch: logs, métricas y alarmas
  |-- Secrets Manager: secretos estáticos
  |-- AgentCore + Strands: agente y herramientas
  |-- Vertex AI: Gemini mediante federación
  |-- Endpoint Gemma: Ollama/EC2 en PoC
  `-- Atlassian Rovo MCP: Jira Cloud
```

### 8.1 AgentCore

AgentCore se adopta para acelerar despliegue del agente, aislamiento de sesiones, escalamiento, herramientas MCP y observabilidad. Las reglas normativas, la aprobación, el versionado y la idempotencia continúan siendo deterministas.

### 8.2 Step Functions

No se incorpora en el Objetivo 1. Se evaluará si aparecen aprobaciones de larga duración, reintentos distribuidos, lotes complejos o recuperación que justifique una máquina de estados administrada. Inicialmente FastAPI y DynamoDB conservarán el estado.

## 9. Autenticación de la aplicación

Se usará Cognito User Pool con:

- Correo corporativo como identificador.
- Usuarios creados únicamente por administrador.
- Autorregistro deshabilitado.
- Contraseña administrada por Cognito.
- Tokens JWT verificados por FastAPI.
- Recuperación de contraseña controlada.
- MFA habilitable en una fase posterior.

La autenticación de la aplicación y la autorización Jira son independientes. Ninguna contraseña se reutiliza o se almacena en el backend.

## 10. Estrategia de modelos

### 10.1 Cascada

1. Reglas y validaciones sin modelo.
2. Gemma para transformaciones autorizadas de bajo riesgo.
3. Gemini cuando la complejidad o calidad lo requieran.
4. Revisión humana cuando haya ambigüedad, contradicción o baja confianza.

### 10.2 Gemma

- Desarrollo: Ollama local.
- PoC AWS: EC2 GPU de duración controlada.
- Evolución: SageMaker Asynchronous Inference si el uso es intermitente y se acepta arranque en frío.
- Producción constante: evaluar SageMaker Real-Time o ECS sobre EC2 GPU.

AgentCore hospeda el agente y llama al endpoint del modelo; no se utilizará como sustituto de un servidor GPU de Gemma.

### 10.3 Gemini y conclusión de credenciales

La clave revisada está restringida a:

- Cloud Speech-to-Text API.
- Cloud Text-to-Speech API.

No es una credencial Gemini y no se modificará, para evitar ampliar permisos de una integración existente.

Ruta preferida:

1. Habilitar Vertex AI API en un proyecto autorizado.
2. Crear una cuenta de servicio dedicada al Agente Jira con mínimo privilegio.
3. Crear un Workload Identity Pool y proveedor AWS.
4. Autorizar sólo el rol AWS de la aplicación.
5. Intercambiar credenciales AWS por tokens Google de corta duración.
6. Evitar claves JSON y API keys permanentes en producción.

Para desarrollo local podrán usarse credenciales de usuario autorizadas o una credencial temporal aprobada. Nunca se guardarán claves en código, Excel, repositorio o frontend.

## 11. Jira Cloud y Rovo MCP

### 11.1 Evidencia administrativa

Las capturas revisadas confirman:

- Rovo MCP Server disponible para la organización.
- Dominios soportados por Atlassian habilitados.
- Cero dominios personalizados registrados.
- Read: 7/7 permitido.
- Write: 7/7 permitido.
- Search: 3/3 permitido.
- Nuevos toolsets permitidos automáticamente.

### 11.2 Evaluación de riesgo

La configuración es funcionalmente suficiente, pero actualmente es amplia. Antes de conectar la aplicación se revisará el impacto organizacional de restringir permisos, porque son controles de la organización y pueden afectar otras integraciones.

Recomendaciones:

- No cambiar permisos globales sin inventario de consumidores.
- Usar OAuth 2.1 interactivo por usuario.
- Mantener API tokens deshabilitados salvo caso máquina-a-máquina aprobado.
- Para el Objetivo 3 comenzar sólo con Read y Search desde la aplicación.
- Habilitar Write en la aplicación únicamente durante la prueba controlada.
- Revisar si `New toolsets allowed` debe permanecer automático.
- Agregar sólo el dominio exacto de la aplicación cuando exista.

### 11.3 Dominio y callback

No se agregará todavía un dominio. Durante desarrollo se validará el callback local permitido; antes de producción se registrará exclusivamente el dominio HTTPS definitivo. No se utilizarán patrones globales como `https://**`.

### 11.4 Metadatos Jira

El sitio base es `https://dpti.atlassian.net`. El `cloudId` se obtendrá mediante `getAccessibleAtlassianResources` durante el Objetivo 3.

- AT: Team-managed software.
- ASIT: Company-managed software.
- MTTI: Company-managed software.

Los campos núcleo conceptuales son título/summary, descripción, responsable, Space, Due Date cuando exista y Tipo de seguimiento. Los IDs, opciones y obligatoriedad se consultarán por Space y Work Type mediante MCP.

## 12. Seguridad

- Mínimo privilegio en AWS, GCP y Atlassian.
- Cifrado en tránsito y reposo.
- Autorregistro deshabilitado.
- API keys, contraseñas y tokens fuera de logs y prompts.
- Documentos completos fuera de logs.
- Separación entre propuesta y executor.
- Aprobación ligada a versión y hash.
- Idempotencia por fila.
- Kill switch para Jira Write y proveedores externos.
- Catálogos con acceso restringido.
- Correlación entre CloudWatch, auditoría GCP y Jira.

## 13. Prueba controlada de escritura en AT

El término funcional reemplaza a “prueba canario”. La actividad usará una convención inequívoca:

```text
AgenteTest_<WorkType>_<FechaHora>_<ProposalId>_<Resumen>
```

Ejemplo:

```text
AgenteTest_Task_20260715_1730_P004_Validar_creacion_controlada
```

También incluirá etiqueta `agente-test`, ID de propuesta y una advertencia de que no representa trabajo productivo.

Secuencia:

1. Lectura de metadatos.
2. Dry run sin escritura.
3. Aprobación de propuesta.
4. Creación de un único Task.
5. Verificación de campos y auditoría.
6. Reintento con la misma clave para confirmar no duplicación.
7. Cierre de la actividad de prueba según proceso autorizado.

## 14. Objetivos verificables

### Objetivo 1 - Aplicación local sin Jira ni secretos

**Estado:** Cumplido y verificado el 2026-07-16. La evidencia reproducible se encuentra en `docs/evidencia_objetivo_1.md`.

Construir y verificar una aplicación web ejecutable localmente que cargue la Plantilla Excel v1.1 congelada, valide y normalice sus actividades, resuelva responsables mediante un catálogo ficticio y genere una propuesta versionada de actividades Jira clasificadas como Incluir, Revisar o Excluir, sin conectarse a AWS, GCP ni Jira.

#### Criterios de término

- React y FastAPI se ejecutan localmente.
- Existe pantalla de login de desarrollo detrás de una interfaz compatible con Cognito.
- Se carga y valida la plantilla v1.1 congelada.
- Se rechazan versiones, hojas o encabezados incompatibles con un mensaje comprensible.
- Sólo Actividad y Responsable son obligatorios.
- `Frente_de_trabajo_o_Proyecto` se normaliza como agrupación, no como campo Jira.
- Un catálogo ficticio resuelve nombre, correo y accountId de prueba.
- Se genera JSON válido contra el esquema de propuesta v1.1.
- Cada propuesta incluye título, descripción, Work Type, responsable resuelto, agrupación o parent propuesto, fecha objetivo cuando exista, decisión, motivo y fila de origen.
- La interfaz separa Listas, Requieren revisión y Excluidas.
- Se muestra origen frente a propuesta.
- El usuario puede corregir la propuesta y producir una versión nueva sin alterar el archivo fuente.
- Una hoja representativa del timeline queda documentada o transformada como caso de prueba de compatibilidad con el contrato v1.1.
- Existen pruebas automatizadas de parser, reglas y API.
- No existen llamadas reales a AWS, GCP o Jira.

#### Evidencia requerida para declarar el objetivo cumplido

- Instrucciones reproducibles de ejecución local.
- Resultado de pruebas automatizadas.
- Ejemplo de archivo v1.1 aceptado.
- Ejemplos controlados de archivo inválido y mensajes de rechazo.
- JSON de propuesta validado contra `docs/schemas/jira_proposal_v1_1.schema.json`.
- Capturas o demostración de las vistas Listas, Requieren revisión y Excluidas.
- Registro explícito de que no se utilizaron credenciales ni conexiones reales.

#### Exclusiones del Objetivo 1

- Despliegue AWS.
- Cognito real.
- AgentCore, Strands, Gemma o Gemini.
- Rovo MCP y OAuth Atlassian.
- Lectura o escritura real en Jira.
- Importador universal de archivos Excel externos.
- Procesamiento de PDF, Word, Markdown, TXT u OCR.

### Objetivo 2 - AWS, identidad, AgentCore y modelos

- Cognito real.
- S3, DynamoDB, CloudWatch y Secrets Manager.
- AgentCore y Strands.
- Gemma de PoC y Vertex AI mediante federación.
- Sin escritura Jira.

### Objetivo 3 - Rovo MCP de sólo lectura

- OAuth 2.1.
- `cloudId`.
- Metadatos AT, ASIT y MTTI.
- Resolución de responsables.
- Verificación de campos por Work Type.

### Objetivo 4 - Escritura controlada

- Propuesta aprobada.
- Un único `AgenteTest_...` en AT.
- Idempotencia y auditoría verificadas.
- Expansión gradual sólo con aprobación.

## 15. Datos pendientes por etapa

### No bloquean el Objetivo 1

- Proyecto GCP definitivo para Vertex AI.
- Workload Identity Pool.
- Dominio productivo de la aplicación.
- Callback productivo.
- `cloudId` Atlassian.
- Catálogo real de usuarios.

### Requeridos antes del Objetivo 2

- Cuenta y región AWS autorizadas.
- Proyecto GCP y región Vertex AI.
- Responsable administrativo de IAM GCP.
- Límites iniciales de costo.

### Requeridos antes del Objetivo 3

- Dominio/callback del ambiente.
- Revisión de Authentication en Rovo MCP.
- Autorización para conexión OAuth.
- Usuarios piloto.

### Nunca deben compartirse en documentación o conversación

- Contraseñas.
- API keys completas.
- Tokens OAuth.
- Claves JSON de cuentas de servicio.
- Cookies o sesiones.

## 16. Referencias oficiales

- Amazon Bedrock AgentCore: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/
- Google Workload Identity Federation: https://docs.cloud.google.com/iam/docs/workload-identity-federation
- Buenas prácticas WIF: https://docs.cloud.google.com/iam/docs/best-practices-for-using-workload-identity-federation
- Atlassian Rovo MCP OAuth: https://support.atlassian.com/atlassian-rovo-mcp-server/docs/configuring-oauth-2-1/
- Permisos Rovo MCP: https://support.atlassian.com/security-and-access-policies/docs/Configure-Atlassian-Rovo-MCP-server-permission/
- Dominios Rovo MCP: https://support.atlassian.com/security-and-access-policies/docs/control-atlassian-rovo-mcp-server-settings/

## 17. Historial

| Versión | Cambio principal |
|---|---|
| 0.1 | Definición inicial |
| 0.2 | Jira Cloud Free, Spaces e Iniciativa |
| 0.3 | AWS, AgentCore, Strands y model routing |
| 0.4 | Plantilla mínima y revisión por excepciones |
| 0.5 | MTTI confirmado, plantilla v1.1, Cognito, Vertex AI federado y Rovo MCP validado |
| 0.6 | Plantilla v1.1 congelada, timeline incorporado como referencia y Objetivo 1 activado con criterios y evidencias de término |
