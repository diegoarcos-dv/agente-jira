# Plan técnico - Agente de generación controlada de work items en Jira

## Control del documento

| Atributo | Valor |
|---|---|
| Proyecto | Agente Jira |
| Estado | Borrador técnico para revisión |
| Versión | 0.2 |
| Fecha | 2026-07-14 |
| Plataforma Jira | Jira Cloud Free |
| Spaces operativos | AT, ASIT y MTTI |
| Fuente normativa principal | Normatividad operativa para el seguimiento de actividades, proyectos, soporte y sesiones en Jira |

## 1. Resumen ejecutivo

El proyecto construirá una aplicación web independiente que transforme documentos de trabajo en propuestas estructuradas de work items de Jira. La aplicación aceptará documentos TXT, Markdown, PDF, Word y Excel; extraerá actividades; propondrá su jerarquía y Work Type; resolverá campos normativos, responsable y Space; y presentará el resultado para revisión humana.

La aplicación no escribirá en Jira durante el análisis. Una versión explícitamente aprobada se congelará y será entregada a un ejecutor determinista, que realizará las operaciones mediante Model Context Protocol (MCP). Las primeras pruebas de escritura se realizarán de forma controlada en el Space AT. Las configuraciones de ASIT y MTTI se validarán inicialmente mediante consultas de solo lectura y pruebas de contrato.

La aplicación será independiente de Codex para que pueda ser utilizada por los diez usuarios de Jira Cloud Free. Codex podrá emplearse como herramienta de desarrollo y, en el futuro, como un cliente opcional de la API, pero la lógica de negocio no dependerá de una skill o plugin de Codex.

Debido a que no existe una cuenta institucional autorizada de OpenAI y una cuenta gratuita/personal de Gemini no ofrece el tratamiento de datos apropiado para documentación empresarial, el diseño prioriza un modelo open-weight desplegado en el servidor interno. La primera opción a evaluar será Gemma 4, sin acoplar el sistema a un modelo concreto.

## 2. Objetivo

Construir una aplicación que:

1. Reciba uno o varios documentos de entrada.
2. Extraiga texto, tablas y referencias de origen.
3. Identifique actividades, entregables, incidencias, dependencias y responsables.
4. Clasifique cada actividad conforme a la normativa vigente.
5. Genere una propuesta editable y trazable.
6. Valide la propuesta contra la configuración real de Jira.
7. Solicite aclaraciones cuando existan datos ambiguos o faltantes.
8. Exija aprobación explícita de una versión inmutable.
9. Cree los work items mediante MCP en el orden jerárquico correcto.
10. Mantenga una bitácora auditable de todo el proceso.

## 3. Alcance

### 3.1 Incluido en el MVP

- Aplicación web para los diez usuarios definidos en Jira.
- Ingesta de TXT, Markdown, PDF, DOCX y XLSX.
- Extracción de texto nativo de PDFs y OCR como ruta secundaria.
- Identificación de Epic, Story, Task, Bug y Subtask.
- Descripciones conformes a las plantillas normativas.
- Resolución de los Spaces AT, ASIT y MTTI.
- Resolución de assignee mediante `accountId` de Jira.
- Campos normativos comunes y campos condicionales por tipo de actividad.
- Propuesta editable con advertencias, confianza y referencias de origen.
- Validación humana antes de cualquier escritura.
- OAuth 2.1 individual contra Atlassian.
- Integración con Jira mediante MCP.
- Auditoría propia de la aplicación.
- Modo simulación y pruebas canario en AT.

### 3.2 Fuera del MVP

- Automatización de cierres sin revisión humana.
- Eliminación automática de work items.
- Administración de usuarios de Jira.
- Modificación de esquemas, Work Types, workflows o campos Jira.
- Escritura en Spaces históricos.
- Automatización masiva sin límites de lote.
- Fine-tuning de modelos.
- Aplicación móvil nativa.
- Dependencia obligatoria de Codex, ChatGPT o Gemini en línea.

## 4. Decisiones confirmadas

| Decisión | Resultado |
|---|---|
| Tipo de producto | Aplicación web independiente |
| Backend | Python con FastAPI |
| Frontend | React con TypeScript |
| Hospedaje | Servidor interno RHEL o Ubuntu |
| Jira | Jira Cloud Free |
| Usuarios | Diez usuarios Jira definidos |
| Autenticación Jira | OAuth 2.1 por usuario |
| Spaces permitidos | AT, ASIT y MTTI |
| Space inicial de pruebas | AT, con controles de canario |
| Normativa predominante | Normativa general |
| Campo de agrupación vigente | Iniciativa |
| Campo Proyecto | Deprecado y de solo lectura |
| IA externa | No autorizada para documentos reales en el MVP |
| IA recomendada | Modelo open-weight ejecutado localmente |

## 5. Fuentes normativas y precedencia

Las fuentes iniciales son:

1. `normativa_operativa_seguimiento_jira_v1.pdf`.
2. `guia_operativa_registro_jira_drive.pdf`.

Cuando exista una diferencia, se aplicará esta precedencia:

1. Configuración real y campos técnicamente obligatorios de Jira.
2. Normativa general aprobada.
3. Regla explícita de sustitución de `Proyecto` por `Iniciativa`.
4. Guía operativa del piloto.
5. Información explícita del documento de entrada.
6. Configuración versionada de la aplicación.
7. Solicitud de aclaración al usuario.

La aplicación nunca inventará un valor para satisfacer una validación.

### 5.1 Proyecto e Iniciativa

- `Iniciativa` será el campo vigente.
- `Proyecto` se considerará deprecado.
- La aplicación no escribirá en `Proyecto`.
- Si un documento utiliza la palabra proyecto como concepto, el agente podrá extraer el valor y proponerlo como `Iniciativa` únicamente si coincide con una opción válida.
- Si no coincide, la propuesta quedará en `NEEDS_INPUT`.

## 6. Reglas de clasificación de Work Type

| Work Type | Regla principal |
|---|---|
| Epic | Frente o iniciativa que agrupa varias actividades independientes |
| Story | Necesidad funcional o de usuario con valor y criterios de aceptación |
| Task | Actividad concreta, soporte, documentación, evaluación, gestión o tarea extraordinaria |
| Bug | Comportamiento observado incorrecto frente a un comportamiento esperado |
| Subtask | Paso específico cuyo padre Task, Story o Bug está identificado |

Restricciones:

- No se crea una Subtask sin padre.
- No se crean hijos antes que sus padres.
- Una Task de soporte puede enlazarse con varios work items, pero no se duplica por cada afectado.
- Los enlaces de bloqueo, relación o duplicidad se muestran en la propuesta.
- La clasificación del modelo debe ser validada por reglas deterministas.

## 7. Campos y validaciones

### 7.1 Núcleo de una propuesta válida

- Work Type.
- Summary o título.
- Descripción estructurada.
- Assignee resuelto o marcado como pendiente.
- Space resuelto.
- Tipo de seguimiento.
- Iniciativa o `No aplica`, cuando la opción exista.
- Línea de trabajo.
- Fecha compromiso.
- Prioridad.
- Criterio de cierre.
- Semáforo.
- Evidencia o referencia de origen.

### 7.2 Campos condicionales

- Descripción del semáforo si no es verde.
- Complejidad si el Space o Work Type la requiere.
- Origen del soporte, causa raíz y acción preventiva para soporte.
- Parent para Subtask.
- Epic o Parent para elementos pertenecientes a un frente.
- Sprint solo cuando la actividad cumple los criterios de entrada.
- Dependencias y linked work items cuando se identifican.
- Original estimate si puede inferirse de forma explícita o el usuario lo captura.

### 7.3 Plantilla de descripción

La descripción se generará con las secciones aplicables:

1. Contexto.
2. Objetivo.
3. Alcance.
4. Resultado esperado.
5. Criterio de cierre o criterios de aceptación.
6. Dependencias.
7. Evidencia o referencia.

## 8. Resolución del Space

La resolución seguirá esta secuencia:

1. Space o Key indicado explícitamente en el documento.
2. Regla controlada por Iniciativa, gerencia o línea de trabajo.
3. Space habitual del assignee como evidencia secundaria.
4. Validación mediante MCP de que el Space existe y está permitido.
5. Comparación del Work Type y campos disponibles en el Space.
6. Solicitud de confirmación si existe empate, contradicción o baja confianza.

Reglas invariables:

- Solo AT, ASIT y MTTI son destinos operativos.
- Los Spaces históricos son de consulta.
- AT no es el valor predeterminado cuando la resolución falla.
- La ambigüedad genera `NEEDS_INPUT`.

## 9. Arquitectura propuesta

```text
Navegador
  |
  v
React / TypeScript
  |
  v
FastAPI
  |-- Autenticación y roles de la aplicación
  |-- Ingesta y normalización documental
  |-- Servicio de extracción de actividades
  |-- Motor normativo determinista
  |-- Servicio de propuestas y versiones
  |-- Approval Gate
  |-- Auditoría
  |-- Jira Gateway
  |     |-- Cliente Atlassian Rovo MCP
  |     `-- MCP complementario, si es necesario
  |
  |-- LLM Provider
  |     |-- Gemma local
  |     `-- Proveedores futuros autorizados
  |
  `-- PostgreSQL

Servicios internos
  |-- Ollama para desarrollo
  |-- vLLM o SGLang para servidor
  |-- Almacenamiento temporal cifrado
  `-- Reverse proxy HTTPS
```

### 9.1 Componentes

#### Ingesta documental

- TXT y Markdown: lectura de texto con preservación de secciones.
- DOCX: párrafos, encabezados y tablas.
- XLSX: hojas, tablas, celdas y coordenadas.
- PDF nativo: extracción por página y bloques.
- PDF escaneado: OCR y conservación de la página de origen.

Cada fragmento conservará un localizador, por ejemplo:

```json
{
  "source_file": "plan_trabajo.pdf",
  "locator": "pagina 12, seccion 4.2",
  "content": "Validar acceso al ambiente de pruebas"
}
```

#### Motor de IA

El modelo propondrá actividades y campos en un JSON validado por esquema. No ejecutará operaciones Jira ni decidirá por sí solo que una propuesta está aprobada.

#### Motor normativo

Aplicará reglas deterministas sobre la salida del modelo:

- Valores permitidos.
- Campos requeridos.
- Reglas por Work Type.
- Jerarquía válida.
- Spaces permitidos.
- Regla de Iniciativa.
- Reglas de entrada a Sprint.

#### Executor Jira

El executor no recibirá texto libre. Recibirá únicamente una propuesta aprobada y validada.

## 10. Estrategia de IA

### 10.1 Recomendación

Se implementará una interfaz `LLMProvider` para evitar acoplamiento. La primera evaluación será con Gemma 4 local.

Justificación:

- Pesos abiertos y despliegue local.
- Soporte multilingüe, incluido español.
- Contexto amplio.
- Capacidades de comprensión documental y OCR multimodal.
- Function calling y respuestas estructuradas.
- Variantes de varios tamaños y cuantizaciones.
- Integración con Ollama, llama.cpp, vLLM y SGLang.

Configuración inicial sugerida, sujeta al hardware:

| Escenario | Modelo inicial |
|---|---|
| Desarrollo sin GPU | Gemma 4 E4B Q4 o 12B Q4 con baja concurrencia |
| Servidor con GPU de 16 GB | Gemma 4 12B Q4 |
| Servidor con GPU de 24 GB o más | Gemma 4 26B A4B Q4 como candidato de mayor calidad |

La selección final se hará con evaluaciones y no por reputación del modelo.

### 10.2 Gemini

La cuenta web de Gemini no equivale automáticamente a una integración de API. Para integrar Gemini se requiere una API key y un proyecto de Google AI Studio o Google Cloud.

La cuota gratuita no se utilizará con documentos empresariales reales. Solo se permitiría con información sintética o anonimizada para comparar calidad. Un futuro uso con datos reales requeriría autorización institucional y condiciones de servicio pagadas o empresariales.

### 10.3 DeepSeek y GLM

- Los modelos completos de DeepSeek suelen exigir infraestructura considerable para despliegue local.
- Las variantes GLM de mayor capacidad también son demasiado grandes para asumirlas como opción local sin conocer el hardware.
- Sus APIs alojadas implicarían enviar información a un tercero y requieren evaluación legal, contractual y de seguridad.
- Podrán incorporarse al benchmark si se identifica una variante local viable y su licencia es aprobada.

### 10.4 Evaluación de modelos

Se construirá un conjunto dorado con documentos sintéticos o autorizados y resultados esperados. Métricas:

- Porcentaje de JSON válido.
- Precisión y recall de actividades detectadas.
- Precisión de Work Type.
- Exactitud de assignee, Space y campos controlados.
- Tasa de valores inventados.
- Tasa de casos enviados correctamente a `NEEDS_INPUT`.
- Latencia.
- Memoria y GPU consumidas.
- Consistencia entre ejecuciones.

## 11. OAuth 2.1 con Atlassian

### 11.1 Flujo para el usuario

1. El usuario inicia sesión en la aplicación.
2. Selecciona `Conectar con Jira`.
3. La aplicación redirige el navegador a Atlassian.
4. Si no existe una sesión de Atlassian, el usuario introduce su correo y contraseña exclusivamente en la página de Atlassian.
5. Atlassian muestra una pantalla de consentimiento con los permisos solicitados.
6. El usuario acepta.
7. Atlassian redirige a una URL de callback de la aplicación con un código temporal.
8. El backend intercambia el código por un access token.
9. El token se asocia únicamente con ese usuario.
10. Las llamadas MCP utilizan `Authorization: Bearer <access_token>` y el `cloudId` autorizado.

La aplicación nunca recibe ni almacena la contraseña de Jira.

### 11.2 Seguridad de tokens

- Tokens cifrados en reposo.
- Tokens nunca expuestos al frontend después del intercambio.
- Cookies de sesión `HttpOnly`, `Secure` y `SameSite` apropiado.
- Rotación y expiración de sesión.
- Reautorización cuando cambien los scopes.
- Posibilidad de desconectar Jira y eliminar tokens.
- Un token nunca se comparte entre usuarios.
- Los secretos no se registran en logs.

### 11.3 Scopes y separación de lectura/escritura

- Durante exploración y propuesta se habilitan solo operaciones de lectura y búsqueda.
- Las herramientas MCP de escritura no se exponen al modelo.
- El executor usa escritura únicamente después del Approval Gate.
- Cada acción conserva usuario, propuesta, versión, payload normalizado y resultado.

### 11.4 Requisitos de infraestructura

- Registrar el dominio HTTPS interno en la allowlist de Atlassian Rovo MCP.
- Configurar la URL de callback.
- Permitir salida HTTPS desde el servidor a `mcp.atlassian.com` y endpoints de autorización Atlassian.
- Validar proxy corporativo, DNS y certificados.
- Confirmar que el dominio interno es accesible desde los navegadores de los usuarios.

## 12. Autenticación y roles de la aplicación

La autenticación de la aplicación es distinta de la autorización MCP de Jira.

Roles propuestos:

| Rol | Capacidades |
|---|---|
| LECTOR | Consultar propuestas y resultados |
| PROPONENTE | Cargar documentos y generar propuestas |
| REVISOR | Modificar, aceptar o rechazar elementos |
| APROBADOR | Aprobar una versión completa |
| EJECUTOR_JIRA | Autorizar la ejecución MCP |
| ADMIN_APP | Configurar catálogos, usuarios y reglas |

Para el piloto se deberá elegir entre:

1. OIDC/LDAP corporativo, opción preferida.
2. Usuarios locales provisionados por un administrador, con contraseñas cifradas mediante Argon2id, si no existe integración corporativa disponible.

## 13. Ciclo de vida de la propuesta

```text
DRAFT
  -> NEEDS_INPUT
  -> VALIDATED
  -> APPROVED
  -> COMMITTING
  -> COMMITTED
  -> PARTIAL_FAILURE

Cualquier estado previo a APPROVED puede terminar en REJECTED.
```

La aprobación deberá referirse a una versión específica:

```text
APROBAR PROPUESTA P-2026-001 V3
```

Al aprobar:

1. Se calcula un hash de la propuesta.
2. La versión se vuelve inmutable.
3. El executor verifica nuevamente los metadatos de Jira.
4. Se crean Epics.
5. Se crean Tasks, Stories y Bugs.
6. Se crean Subtasks.
7. Se aplican relaciones y actualizaciones complementarias.
8. Se registra cada clave retornada.

## 14. Idempotencia y fallos parciales

- Cada propuesta tendrá `proposal_id` y `version`.
- Cada work item local tendrá `client_item_id` estable.
- Se agregará una marca consultable, por ejemplo una label o campo autorizado.
- Antes de reintentar, el executor buscará si el item ya existe.
- Un fallo parcial no desencadenará eliminación automática.
- Se mostrará qué elementos fueron creados, cuáles fallaron y cuáles no se intentaron.
- Los reintentos operarán solo sobre elementos pendientes.

## 15. Integración MCP

### 15.1 Capacidades esperadas del MCP oficial

- Descubrir el `cloudId`.
- Listar Spaces visibles.
- Consultar Work Types por Space.
- Consultar metadatos y campos de creación.
- Resolver `accountId` por nombre o correo.
- Consultar JQL.
- Crear y editar work items.
- Agregar comentarios y worklogs.
- Ejecutar transiciones.

### 15.2 Prueba de capacidades

La lista pública actual del MCP oficial no expone de forma inequívoca todas las operaciones requeridas para Sprints, enlaces y algunas jerarquías. Antes de construir el executor completo se realizará un spike técnico.

Si faltan operaciones, se construirá un MCP complementario y limitado sobre las APIs autorizadas de Jira Cloud. La aplicación seguirá accediendo a Jira exclusivamente mediante MCP.

## 16. Restricciones de Jira Cloud Free

| Restricción | Respuesta de arquitectura |
|---|---|
| Diez usuarios | Los diez usuarios serán provisionados explícitamente |
| Roles Jira no configurables | RBAC dentro de la aplicación |
| Sin seguridad por work item | No publicar información sensible en Jira |
| Sin audit log completo | Auditoría propia de la aplicación |
| Sin sandbox | Dry-run, mocks, pruebas de contrato y canarios en AT |
| 100 automatizaciones mensuales | No depender de Jira Automation |
| 2 GB de archivos | Evidencia en Drive; Jira conserva enlaces |
| 500 llamadas MCP por hora | Cache, paginación y límites de lote |

## 17. Estrategia de pruebas en AT

### 17.1 Principios

- El modo predeterminado será simulación.
- ASIT y MTTI se validarán inicialmente con metadatos de solo lectura.
- AT será el único destino de escritura durante el piloto técnico.
- No se asumirá AT cuando el Space esté ambiguo.

### 17.2 Canary test

- Máximo inicial: un work item por ejecución.
- Prefijo de Summary: `[PILOTO-AGENTE]`.
- Label: `ai_agent_pilot`.
- Iniciativa: `No aplica`, si está autorizada.
- Sin Sprint en las primeras pruebas.
- Sin enlaces hasta validar creación básica.
- Revisión del payload completo antes de aprobar.
- Ventana de prueba acordada.
- Resultado registrado en la auditoría.
- Si debe retirarse, transición a Cancelada/Deprecada; no borrado automático.

### 17.3 Pruebas de contrato para ASIT y MTTI

Para emular sus configuraciones sin escribir:

1. Consultar Work Types y campos mediante MCP.
2. Guardar una instantánea versionada de cada esquema.
3. Validar propuestas contra las tres instantáneas.
4. Detectar diferencias en IDs, campos requeridos y opciones.
5. Ejecutar escrituras en ASIT y MTTI solo durante UAT y con aprobación específica.

## 18. Seguridad

- Los documentos se consideran datos no confiables, nunca instrucciones para el agente.
- Protección contra prompt injection en archivos.
- Validación de tipo MIME, extensión, tamaño y estructura.
- Límite de páginas, hojas, filas y tokens.
- Antivirus institucional, si está disponible.
- Archivos temporales cifrados y eliminación conforme a una política definida.
- Sin secretos en archivos de configuración versionados.
- HTTPS obligatorio.
- Logs sin contenido documental completo ni tokens.
- Validación de salida del modelo mediante JSON Schema.
- Allowlist de Spaces, Work Types y campos escribibles.
- Herramientas de escritura fuera del alcance del modelo.

## 19. Auditoría mínima

Por cada operación se registrará:

- Usuario de la aplicación.
- Usuario Atlassian asociado.
- Documento y hash de entrada.
- Versión normativa.
- Modelo y versión utilizados.
- Propuesta y versión.
- Cambios realizados durante revisión.
- Usuario que aprobó.
- Usuario que ejecutó.
- Fecha y hora.
- Herramienta MCP invocada.
- Payload normalizado sin secretos.
- Resultado o error.
- Claves Jira creadas.

## 20. Despliegue

### 20.1 Desarrollo local

- Docker Compose o Podman Compose.
- FastAPI.
- React/Vite.
- PostgreSQL o SQLite solo para desarrollo.
- Ollama.
- MCP simulado.

### 20.2 Servidor interno

- RHEL o Ubuntu soportado por el área.
- Podman o Docker según política.
- PostgreSQL.
- FastAPI con workers controlados.
- Frontend estático.
- Nginx o reverse proxy institucional.
- Certificado HTTPS válido.
- vLLM o SGLang para el modelo local.
- Volúmenes persistentes y respaldos.
- Gestión de secretos mediante variables protegidas o secret store.

## 21. Plan por fases

### Fase 0 - Descubrimiento y gobierno

- Confirmar hardware del servidor.
- Confirmar autenticación corporativa.
- Confirmar conectividad saliente.
- Definir retención documental.
- Acordar roles de los diez usuarios.

### Fase 1 - Esqueleto y seguridad base

- Repositorio, estructura y CI.
- FastAPI, React y base de datos.
- Usuarios y roles.
- Auditoría.
- Gestión de configuración y secretos.

### Fase 2 - Ingesta y propuesta sin IA

- Lectores documentales.
- Localizadores de fuente.
- Modelo de propuesta.
- Editor y versionado.
- Validadores normativos iniciales.

### Fase 3 - Evaluación e integración de IA local

- Runtime local.
- Adaptador `LLMProvider`.
- Esquema de salida.
- Dataset dorado.
- Comparación de variantes.

### Fase 4 - Jira MCP de solo lectura

- OAuth 2.1.
- `cloudId`.
- Descubrimiento de AT, ASIT y MTTI.
- Metadatos, usuarios y campos.
- Instantáneas de configuración.

### Fase 5 - Revisión y aprobación

- Ciclo `DRAFT` a `APPROVED`.
- Hash e inmutabilidad.
- Diff entre versiones.
- Approval Gate.

### Fase 6 - Executor y canario AT

- Spike de herramientas MCP.
- Executor idempotente.
- Dry-run.
- Creación canario en AT.
- Fallo parcial y reintento.

### Fase 7 - UAT y endurecimiento

- Casos normativos completos.
- Pruebas de seguridad.
- Pruebas de carga.
- Manual operativo.
- Despliegue interno.

## 22. Criterios de aceptación del MVP

- Cero llamadas Jira de escritura antes de aprobación.
- Todos los work items conservan referencia a su fuente.
- La salida del modelo cumple el esquema o se rechaza.
- No se escribe en `Proyecto`.
- Solo se escribe en AT, ASIT o MTTI.
- Una ambigüedad no resuelta produce `NEEDS_INPUT`.
- Subtasks y relaciones mantienen jerarquía válida.
- Los assignees se convierten a `accountId` válido.
- La propuesta aprobada es inmutable.
- Un reintento no crea duplicados.
- Los fallos parciales son recuperables.
- Todos los eventos críticos quedan auditados.
- Las pruebas iniciales en AT usan las marcas de piloto.

## 23. Preguntas abiertas antes de iniciar implementación

1. ¿Qué hardware tendrá el servidor interno: CPU, RAM, GPU, VRAM y almacenamiento?
2. ¿Existe un IdP corporativo OIDC, LDAP, Active Directory o Entra ID para autenticar la aplicación?
3. ¿El servidor podrá salir por HTTPS a Atlassian o necesita proxy corporativo?
4. ¿Cuál será el dominio y certificado HTTPS de la aplicación?
5. ¿Cuánto tiempo deben conservarse los documentos originales, textos extraídos, propuestas y logs?
6. ¿Quiénes de los diez usuarios tendrán los roles APROBADOR y EJECUTOR_JIRA?
7. ¿Qué límite inicial se desea por propuesta: 10, 25 o 50 work items?
8. ¿Existe la opción `No aplica` en Iniciativa para AT, ASIT y MTTI?
9. ¿Qué Epic, componente o convención deberá agrupar los canarios dentro de AT?
10. ¿Se permite instalar Ollama durante desarrollo y vLLM/SGLang en el servidor interno?

Las preguntas 1, 2, 3 y 5 son bloqueantes para el diseño físico y de seguridad. Las demás pueden resolverse durante las primeras fases antes de escribir en Jira.

## 24. Borrador de objetivo de Codex para la siguiente etapa

Este objetivo no debe activarse hasta aprobar este documento y resolver las preguntas bloqueantes:

```text
Implementar el MVP descrito en docs/plan_tecnico_agente_jira.md por fases verificables.

Restricciones:
- No conectarse a Jira con permisos de escritura hasta completar el MCP simulado,
  las pruebas de contrato y el Approval Gate.
- No enviar documentos empresariales a servicios externos de IA.
- No escribir en el campo Proyecto.
- No crear work items fuera de AT, ASIT y MTTI.
- No realizar pruebas reales en Jira sin aprobación explícita del usuario.

Trabajar por checkpoints, ejecutar pruebas después de cada cambio y mantener
un registro de decisiones, riesgos y resultados. Detenerse cuando el MVP cumpla
todos los criterios de aceptación o cuando una decisión de infraestructura,
seguridad o Jira requiera intervención del usuario.
```

## 25. Referencias

### Internas

- Normatividad operativa para el seguimiento de actividades, proyectos, soporte y sesiones en Jira, versión preliminar v2.0.
- Guía operativa para registrar actividades en Jira y evidencias en Google Drive, piloto 2026.

### Externas

- Atlassian Rovo MCP - Configuring OAuth 2.1: https://support.atlassian.com/atlassian-rovo-mcp-server/docs/configuring-oauth-2-1/
- Atlassian Rovo MCP - Supported tools: https://support.atlassian.com/atlassian-rovo-mcp-server/docs/supported-tools/
- Atlassian - Jira Cloud plans: https://support.atlassian.com/jira-cloud-administration/docs/explore-jira-cloud-plans/
- Atlassian - Jira Free plan: https://support.atlassian.com/jira-cloud-administration/docs/what-is-the-free-jira-cloud-plan/
- Google - Gemma models: https://ai.google.dev/gemma/docs
- Google - Gemma 4 model overview: https://ai.google.dev/gemma/docs/core
- Google - Run Gemma: https://ai.google.dev/gemma/docs/run
- Google - Gemini API terms: https://ai.google.dev/gemini-api/terms

## 26. Historial

| Versión | Fecha | Cambio |
|---|---|---|
| 0.1 | 2026-07-13 | Propuesta conceptual y revisión de normativa |
| 0.2 | 2026-07-14 | Aplicación independiente, Jira Free, OAuth 2.1, Linux interno y estrategia de IA local |
