# Plan técnico - Agente de generación controlada de work items en Jira

## Control del documento

| Campo | Valor |
|---|---|
| Versión | 0.4 |
| Fecha | 2026-07-15 |
| Estado | Diseño simplificado listo para piloto de plantilla |
| Fase inicial | Automatización desde plantilla Excel |
| Plataforma objetivo | Amazon Web Services (AWS) |
| Framework candidato | Strands Agents sobre Amazon Bedrock AgentCore |
| Modelos iniciales | Gemma mediante Ollama y Gemini mediante API de GCP |
| Jira | Jira Cloud Free |
| Spaces operativos | AT, ASIT y MTTI |
| Fuente normativa prevalente | Normativa general Jira |

## 1. Resumen ejecutivo

El proyecto construirá una aplicación web independiente que convierta un plan de trabajo en Excel en una propuesta revisable de work items para Jira. La aplicación generará títulos, descripciones, Work Types, jerarquías y campos normativos; el usuario no tendrá que reproducir en Excel el formulario técnico de Jira.

La versión 0.4 cambia el contrato de entrada: por cada actividad sólo serán obligatorios **Actividad** y **Responsable**. Grupo o módulo, contexto o resultado, fecha objetivo, estado actual y comentarios serán opcionales. Como normalmente un plan corresponde a un solo Space, AT, ASIT o MTTI se seleccionará una sola vez al cargar el archivo. Los valores de iniciativa, línea de trabajo, sprint, tipo de seguimiento y semáforo también se administrarán a nivel del plan cuando sean comunes.

La propuesta se revisará por excepciones. Las filas claras quedarán listas; las ambiguas se agruparán como dudas; las completadas o rechazadas se propondrán excluidas, con opción de reactivarlas. Ningún elemento se escribirá en Jira antes de aprobar una versión y confirmar la ejecución.

La solución objetivo continúa en AWS, con almacenamiento en S3, estado e idempotencia en DynamoDB, secretos estáticos en Secrets Manager, trazabilidad en CloudWatch y una evaluación acotada de Strands Agents y AgentCore. El acceso a Jira será individual mediante OAuth y las operaciones se expondrán al agente por MCP con permisos y validaciones separados.

## 2. Problema y principio de producto

La plantilla anterior propuesta trasladaba casi toda la complejidad de Jira al usuario. Eso reducía el proyecto a un importador masivo y generaba retrabajo.

El principio corregido es:

> La plantilla captura la intención del trabajo; la aplicación traduce esa intención a Jira y muestra su interpretación antes de ejecutar.

Este principio implica tres capas separadas:

1. **Captura humana simple:** lenguaje natural y pocos campos.
2. **Propuesta interna enriquecida:** inferencias, resolución de identidades, reglas y advertencias.
3. **Payload Jira:** IDs y campos técnicos producidos sólo por el sistema.

## 3. Objetivo

Implementar una aplicación segura, auditable y costo-consciente que:

1. Reciba la plantilla Excel v1.
2. Solicite una sola vez el Space y los valores generales del plan.
3. Valide filas y normalice su contenido.
4. Genere títulos y descripciones sin inventar hechos.
5. Proponga Work Type, jerarquía y campos normativos.
6. Resuelva el responsable visible a una identidad Jira.
7. Separe filas listas, dudosas y excluidas.
8. Permita corregir y versionar la propuesta.
9. Bloquee la escritura hasta aprobación y confirmación explícitas.
10. Cree mediante Jira MCP con idempotencia y auditoría.

## 4. Alcance por horizonte

### 4.1 MVP

- Entrada exclusiva mediante plantilla `.xlsx` v1.
- Un Space por plan, con excepciones resueltas en la aplicación.
- Dos campos obligatorios por fila.
- Generación de descripción desde actividad, contexto y comentarios.
- Epic, Story, Task, Bug y Subtask como Work Types candidatos.
- Propuesta editable con revisión por excepciones.
- Un rol funcional inicial: `ADMIN_EJECUTOR`.
- OAuth individual contra Atlassian.
- Integración Jira mediante MCP.
- Model routing entre reglas, Gemma y Gemini autorizado.
- Despliegue y trazabilidad en AWS.
- Pruebas canario únicamente en AT.

### 4.2 Evoluciones posteriores

- PDF, Word, Markdown, TXT y minutas.
- OCR para documentos escaneados.
- Múltiples Spaces frecuentes dentro del mismo plan.
- Roles separados de captura, revisión, aprobación y auditoría.
- DeepSeek, GLM u otros proveedores.
- Aprendizaje controlado a partir de correcciones aprobadas.

### 4.3 Fuera del MVP

- Copiar el formulario de Jira al Excel.
- Crear directamente al cargar un archivo.
- Inferir datos críticos únicamente por color o posición visual.
- Crear usuarios o modificar permisos, workflows o campos Jira.
- Escribir el campo deprecado `Proyecto`; se usará `Iniciativa`.
- Dar a un modelo acceso irrestricto a escritura.
- Enviar información empresarial a un proveedor no autorizado.

## 5. Decisiones confirmadas

| Tema | Decisión |
|---|---|
| Producto | Aplicación web independiente |
| Entrada inicial | Plantilla Excel oficial y versionada |
| Obligatorios por fila | Actividad y Responsable |
| Descripción | Generada por la aplicación y revisada por el usuario |
| Space | Uno por plan normalmente; se selecciona al cargar |
| Spaces permitidos | AT, ASIT y MTTI |
| Jira | Jira Cloud Free, 10 usuarios definidos |
| Pruebas de escritura | AT con canario y precauciones productivas |
| Plataforma | AWS |
| Agente | Evaluar Strands Agents y AgentCore mediante PoC |
| Archivos | S3 |
| Estado, versiones e idempotencia | DynamoDB On-Demand inicialmente |
| Secretos estáticos | AWS Secrets Manager |
| Observabilidad | CloudWatch y, si procede, AgentCore Observability |
| Modelos iniciales | Gemma/Ollama y Gemini/GCP |
| Estrategia | Model Routing y Model Cascading |
| Rol inicial | `ADMIN_EJECUTOR` |
| Autenticación Jira | OAuth por usuario |
| Campo vigente | `Iniciativa`; `Proyecto` deprecado |

## 6. Aprendizajes del Excel real

El archivo `Plan de trabajo Reclasificación.xlsx` contiene una hoja `PLAN DE TRABAJO`, actividades, responsables, fechas, estados, indicadores de completado y comentarios. También usa orden, colores y filas agrupadoras para comunicar estructura.

Los hallazgos relevantes son:

- La actividad y el nombre visible del responsable son los datos más constantes.
- La descripción útil está distribuida entre actividad y comentarios.
- Existen agrupadores o módulos que no siempre deben convertirse en Epic.
- Prefijos como `BUG:` ayudan, pero no constituyen un contrato formal.
- Hay contradicciones posibles entre estado, completado y comentarios.
- Los colores sirven como ayuda humana, pero no deben ser la única evidencia.
- El nombre visible no es el `accountId` requerido por Jira Cloud.

El archivo es una buena fuente para validar la solución, pero no debe copiarse como contrato técnico.

## 7. Contrato de la plantilla Excel v1

### 7.1 Hoja de captura

La única hoja que el usuario necesita editar es `PLAN_DE_TRABAJO`.

| Columna | Obligatoria | Uso |
|---|---:|---|
| `Actividad *` | Sí | Qué necesita realizarse, en lenguaje natural |
| `Responsable *` | Sí | Una persona principal, por nombre visible |
| `Grupo_o_Modulo` | No | Frente natural de trabajo |
| `Contexto_o_Resultado` | No | Propósito, resultado o condición de término |
| `Fecha_Objetivo` | No | Fecha objetivo cuando exista |
| `Estado_Actual` | No | Pendiente, En curso, En pausa, Completada, Rechazada o Por confirmar |
| `Comentarios` | No | Dependencias, restricciones o antecedentes |

### 7.2 Datos que no se capturan por fila

- Space.
- `accountId` de Jira.
- Work Type.
- Descripción Jira terminada.
- Jira key o field ID.
- Parent ID.
- Iniciativa, sprint, línea de trabajo, semáforo o tipo de seguimiento cuando sean generales.

### 7.3 Reglas

- Una actividad por fila.
- Un responsable principal; varios nombres generan revisión.
- No se usa el color como dato obligatorio.
- Una fila sin Actividad o Responsable es inválida, no se envía al modelo.
- Las filas completadas o rechazadas se proponen excluidas.
- Los valores opcionales vacíos no provocan que el modelo los invente.

### 7.4 Hojas auxiliares entregadas

- `AYUDA`: instrucciones, significado de campos y comportamiento de la aplicación.
- `EJEMPLO_MIGRADO`: muestra representativa del archivo real y decisión esperada Incluir, Revisar o Excluir.

## 8. Valores generales del plan

Después de cargar el archivo, la aplicación solicita:

| Campo | Regla |
|---|---|
| Space | Obligatorio: AT, ASIT o MTTI |
| Iniciativa | Opcional o requerido por configuración del Space |
| Línea de trabajo | Opcional o requerido por configuración |
| Sprint | Opcional; debe resolverse contra Jira |
| Tipo de seguimiento | Opcional según normativa |
| Semáforo | Opcional según normativa |

Una excepción de Space por fila sólo se habilitará si el piloto demuestra una necesidad real. No se incorporará a la plantilla base.

## 9. Contrato interno de propuesta

El contrato JSON interno se define en `docs/schemas/jira_proposal_v1.schema.json`. Conserva:

- Identidad, versión y estado de la propuesta.
- Nombre y hash SHA-256 del archivo fuente.
- Valores generales del plan.
- Fila original normalizada.
- Resultado generado y su nivel de confianza.
- Errores y advertencias.
- Cambios y aprobación del usuario.
- Clave de idempotencia y resultado Jira.

Cada elemento recibe un `row_id` estable. El origen nunca se sobrescribe; la propuesta editable vive en otra sección. Esto permite explicar, versionar y auditar cada decisión.

## 10. Generación de la propuesta

### 10.1 Orden de procesamiento

1. Verificar versión, hoja y encabezados.
2. Ignorar filas totalmente vacías.
3. Validar Actividad y Responsable.
4. Normalizar espacios, fechas y estados.
5. Aplicar reglas deterministas de exclusión y clasificación.
6. Resolver catálogos y usuarios Jira mediante lectura.
7. Usar un modelo sólo si una transformación permitida lo necesita.
8. Validar el resultado contra el esquema y la normativa.
9. Asignar Incluir, Revisar o Excluir con motivo.
10. Crear la versión borrador de la propuesta.

### 10.2 Descripción generada

La descripción se compone, cuando haya evidencia, con:

- Actividad solicitada.
- Contexto o propósito.
- Resultado esperado.
- Comentarios o dependencias.
- Fecha objetivo como dato estructurado, no como hecho inventado.

Si falta información, se omite la sección o se marca una duda. Nunca se completa con una suposición presentada como hecho.

### 10.3 Work Type y jerarquía

Reglas iniciales:

- Prefijo inequívoco `BUG:` y evidencia de defecto: candidato a Bug.
- Grupo amplio con varias actividades hijas y valor de seguimiento: candidato a Epic.
- Entrega funcional con valor para usuario: candidato a Story.
- Trabajo operativo o técnico autónomo: candidato a Task.
- Trabajo dependiente que requiere parent: candidato a Subtask.

`Grupo_o_Modulo` puede usarse sólo como agrupación visual. La aplicación no debe crear un Epic vacío por cada grupo.

## 11. Revisión por excepciones

La interfaz muestra pestañas de `Requieren revisión`, `Listas`, `Excluidas` y `Todas`. El panel de detalle compara origen y propuesta.

Se requiere revisión cuando:

- el responsable no coincide de forma unívoca;
- el Work Type o la jerarquía tienen baja confianza;
- falta un parent obligatorio;
- el estado es `Por confirmar`;
- existe contradicción entre campos;
- falta un campo normativo obligatorio para el Space.

La propuesta se aprueba primero y la creación se confirma después. Cualquier modificación posterior invalida la aprobación anterior.

## 12. Estados de la propuesta

`UPLOADED → NORMALIZED → NEEDS_INPUT/DRAFT → VALIDATED → APPROVED → EXECUTING → COMPLETED`

Estados alternos: `PARTIAL_SUCCESS`, `FAILED` y `CANCELLED`.

Sólo `APPROVED` puede pasar a `EXECUTING`. La versión, el hash de origen y la identidad de aprobación deben coincidir.

## 13. Arquitectura AWS objetivo

### 13.1 Componentes

- **Frontend:** React y TypeScript; hospedaje estático administrado o S3/CloudFront según evaluación de costo y operación.
- **API:** Python y FastAPI en un runtime administrado apropiado; evitar servidores permanentes durante el piloto si no son necesarios.
- **Archivos:** S3 con cifrado, bloqueo de acceso público, versionado y ciclo de vida.
- **Estado:** DynamoDB On-Demand para propuestas, versiones, locks e idempotencia.
- **Procesamiento:** SQS y DLQ si la carga requiere desacoplamiento.
- **Orquestación:** Step Functions Standard sólo si el flujo durable de aprobación aporta valor frente a una máquina de estados en la API.
- **Agente:** Strands Agents; AgentCore sujeto a PoC de integración, costo y operación.
- **Secretos:** Secrets Manager para claves estáticas y referencias de configuración sensible.
- **Observabilidad:** CloudWatch Logs, Metrics, Alarms y trazas autorizadas.

### 13.2 Principio de selección

No se adopta un servicio por estar disponible. Cada componente debe justificar capacidad, volumen esperado, costo, seguridad, soporte y alternativa más simple. El MVP iniciará con mínimos razonables y escalado por medición.

## 14. Model Routing y Model Cascading

La cascada propuesta es:

1. **Sin modelo:** validación de formato, estados, fechas, catálogos y reglas seguras.
2. **Gemma/Ollama:** normalización o clasificación de bajo riesgo si la infraestructura y calidad son suficientes.
3. **Gemini/GCP:** sólo para casos habilitados por política y cuando Gemma no alcance el umbral.
4. **Humano:** ambigüedad, contradicción, baja confianza o impacto alto.

El router considera tipo de tarea, sensibilidad, complejidad, confianza, latencia, disponibilidad y presupuesto. El modelo devuelve JSON estructurado; la aplicación valida esquema, catálogos y reglas después de cada llamada.

Gemini permanece deshabilitado para información empresarial hasta confirmar contractualmente el proyecto GCP, región, retención, uso de datos y controles de acceso.

## 15. Strands Agents y AgentCore

Su uso se evaluará mediante una PoC, no como condición previa del producto. La PoC debe demostrar:

- ejecución estructurada del flujo;
- uso de MCP con lista de herramientas permitidas;
- trazabilidad con correlación por propuesta;
- compatibilidad con el router Gemma/Gemini;
- costo y operación aceptables;
- ausencia de acoplamiento innecesario.

Las reglas normativas, la aprobación, la idempotencia y el executor Jira seguirán siendo componentes deterministas aunque se use un framework de agentes.

## 16. Jira Cloud, MCP y OAuth

### 16.1 OAuth por usuario

La aplicación no recibe la contraseña Jira. El usuario pulsa `Conectar con Jira`, Atlassian muestra su propia pantalla de autorización y devuelve a la aplicación un código temporal. El backend lo intercambia por tokens y utiliza el token del usuario para las operaciones permitidas.

Esto conserva identidad y permisos individuales. Los tokens dinámicos deben cifrarse, tener expiración, rotación o revocación y no aparecer en logs. Secrets Manager es apropiado para el secreto del cliente OAuth; los tokens por usuario deben almacenarse cifrados en un repositorio diseñado para datos dinámicos, con acceso mínimo y TTL.

### 16.2 MCP

Las herramientas se separan por capacidad:

- Lectura: proyectos/Spaces, campos, Work Types, usuarios, sprints y metadatos de creación.
- Escritura: creación controlada de work items y consulta de resultado.

El modelo no construye ni ejecuta llamadas libres. El executor recibe una propuesta aprobada, vuelve a validar campos e idempotencia y llama herramientas permitidas.

### 16.3 Jira Cloud Free

Antes de codificar el mapeo definitivo se hará una prueba de capacidades en AT para obtener metadatos reales por Work Type. No se asumirá que todos los campos, automatizaciones o funciones premium están disponibles. El diseño debe funcionar con los límites de la edición Free y los 10 usuarios acordados.

## 17. Seguridad, observabilidad y costo

### 17.1 Controles mínimos

- Cifrado en tránsito y reposo.
- IAM de mínimo privilegio.
- S3 sin acceso público.
- Hash del archivo fuente y análisis de tipo/tamaño.
- Sanitización de logs y prompts.
- Validación de salida estructurada.
- Separación entre propuesta y executor.
- Aprobación vinculada a versión.
- Idempotencia por elemento.
- Kill switch para escritura Jira y proveedores externos.

### 17.2 Trazabilidad

Cada operación usa `correlation_id`, `proposal_id`, `version`, `row_id`, usuario, acción, resultado, latencia, ruta de modelo y consumo estimado. No se registran tokens, documentos completos ni contenido sensible innecesario.

### 17.3 Guardas de costo

- Presupuestos y alarmas por ambiente.
- Límites de filas, tamaño y llamadas por archivo.
- Reutilización de resultados deterministas y caché segura.
- Timeouts y concurrencia acotada.
- Retención explícita de logs y archivos.
- Gemini sólo cuando reglas y Gemma no sean suficientes.

## 18. Pruebas en Jira

AT se usa con cautela porque ya es productivo. La secuencia será:

1. Lectura de metadatos sin cambios.
2. Dry run con payload validado.
3. Canary de un solo Task identificable y reversible por proceso Jira permitido.
4. Verificación de título, descripción, assignee, Space y campos.
5. Segundo intento con la misma clave de idempotencia para confirmar que no duplica.
6. Aumento gradual de lote sólo después de evidencia satisfactoria.

## 19. Plan por fases

### Fase 0 - Contrato simple y validación con usuarios

- Entregar plantilla v1, ejemplo migrado y guía.
- Ejecutar piloto con 3 a 5 usuarios.
- Medir tiempo, dudas y correcciones.
- Congelar contrato v1 sólo después del piloto.

### Fase 1 - Fundación de aplicación

- Repositorio, CI/CD, ambientes y gestión de configuración.
- API de carga y validación.
- S3, DynamoDB, autenticación de aplicación y trazabilidad mínima.

### Fase 2 - Ingesta determinista

- Parser seguro de Excel.
- Normalización y errores por fila.
- Contrato JSON y versionado.
- Sin LLM y sin escritura Jira.

### Fase 3 - Lectura Jira y resolución

- OAuth por usuario.
- MCP de sólo lectura.
- Catálogos por Space, Work Type, campos, sprints y usuarios.
- Prueba de capacidades de Jira Free.

### Fase 4 - Generación y router

- Reglas de título, descripción y exclusión.
- Gemma para transformaciones autorizadas.
- Gemini sólo si gobierno lo permite.
- Evaluación con conjunto dorado del Excel migrado.

### Fase 5 - Revisión y aprobación

- Interfaz por excepciones.
- Edición, motivo, historial y versionado.
- Aprobación vinculada a versión y hash.

### Fase 6 - Executor y canario AT

- MCP de escritura aislado.
- Revalidación, idempotencia y manejo parcial.
- Canary de una actividad y expansión gradual.

### Fase 7 - UAT y endurecimiento

- Pruebas funcionales, seguridad, costo, recuperación y auditoría.
- Runbooks, alarmas y soporte.
- Decisión de paso a ASIT y MTTI.

## 20. Criterios de aceptación del MVP

### Simplicidad

- Sólo Actividad y Responsable son obligatorios por fila.
- Space se captura una sola vez por plan.
- No se solicita ningún ID técnico Jira en Excel.
- El piloto demuestra ahorro de tiempo frente a captura manual.
- La meta inicial es que al menos 80 % de filas no requiera pregunta individual; se ajustará con evidencia.

### Calidad

- El archivo se valida con errores accionables por fila.
- La descripción no introduce hechos sin evidencia.
- Las exclusiones y dudas muestran un motivo.
- Los campos Jira se validan contra metadatos reales.

### Control

- No hay escritura antes de aprobación y confirmación.
- Cambiar la propuesta invalida su aprobación previa.
- Reintentar no crea duplicados.
- Toda creación conserva correlación y resultado.

### Operación

- Secretos y tokens no aparecen en logs.
- Alarmas y presupuestos están activos.
- El flujo se recupera de fallos parciales.
- Existe un kill switch probado para escritura.

## 21. Preguntas pendientes

### Antes de congelar la plantilla

1. ¿Los usuarios comprenden `Grupo_o_Modulo` o conviene llamarlo `Frente_de_trabajo`?
2. ¿Qué formato estable identifica al Responsable: nombre, correo corporativo o catálogo desplegable?
3. ¿El 80 % sin preguntas por fila es alcanzable con planes reales?

### Antes de la arquitectura definitiva

4. ¿Qué servicio corporativo autenticará la aplicación?
5. ¿AgentCore y Step Functions justifican su costo frente a una primera implementación más simple?
6. ¿Dónde se ejecutará Ollama/Gemma y qué capacidad tendrá?
7. ¿GCP está autorizado para los datos empresariales del piloto?

### Antes de escribir en Jira

8. ¿Cuál es el sitio Atlassian, `cloudId`, scopes OAuth y URL de callback aprobada?
9. ¿Qué campos y opciones reales exige cada Work Type en AT, ASIT y MTTI?
10. ¿Qué MCP server se usará y qué operaciones soporta?
11. ¿Qué convención identificará inequívocamente los canarios en AT?

## 22. Próximo punto de control

El siguiente paso no es agregar más arquitectura. Es ejecutar el piloto de la plantilla v1 con usuarios reales, medir si reduce trabajo y ajustar nombres, ayudas y reglas. En paralelo puede diseñarse el parser, pero el contrato de entrada no debe congelarse hasta revisar la evidencia del piloto.

## 23. Objetivo verificable propuesto

Construir y validar un MVP que, usando la plantilla Excel v1, genere una propuesta versionada de Jira en la que:

- se procesen planes de 10 a 40 actividades;
- sólo Actividad y Responsable sean obligatorios por fila;
- el usuario resuelva explícitamente todas las dudas;
- ninguna actividad se cree antes de aprobación y confirmación;
- un canario aprobado se cree una sola vez en AT;
- existan trazas suficientes para reconstruir el resultado sin exponer secretos.

El objetivo se considerará cumplido cuando el piloto de usuarios, las pruebas del contrato, la prueba de capacidades Jira y el canario controlado produzcan evidencia documentada y satisfactoria.

## 24. Referencias internas

- `normativa_operativa_seguimiento_jira_v1.pdf`.
- `guia_operativa_registro_jira_drive.pdf`.
- `Plan de trabajo Reclasificación.xlsx`.
- `plantilla_plan_trabajo_jira_v1.xlsx`.
- `docs/schemas/jira_proposal_v1.schema.json`.
- `docs/diseno_revision_propuesta_v1.md`.
- `docs/checklist_piloto_plantilla_v1.md`.

## 25. Historial

| Versión | Cambio principal |
|---|---|
| 0.1 | Definición inicial de aplicación y flujo Jira |
| 0.2 | Ajustes de Jira Cloud Free, Spaces, normativa e Iniciativa |
| 0.3 | AWS, AgentCore, Strands, Secrets Manager, CloudWatch y model routing |
| 0.4 | Plantilla mínima, valores por plan, descripción generada y revisión por excepciones |
