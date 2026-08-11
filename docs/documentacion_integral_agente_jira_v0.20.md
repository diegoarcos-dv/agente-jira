# Agente Jira — documentación integral del proyecto

| Dato | Valor |
|---|---|
| Versión documental | 0.20 |
| Versión de la aplicación | 0.20.0 |
| Fecha de corte | 28 de julio de 2026 |
| Estado | MVP local funcional con escritura controlada en Jira Cloud |
| Sitio Jira | `https://dpti.atlassian.net` |
| Entrada oficial actual | Plantilla Excel v1.1 |
| Integración Jira | OAuth por usuario y Atlassian Rovo MCP |

## 1. Propósito del documento

Este documento reúne el contexto funcional, técnico y operativo acumulado del Agente Jira. Sustituye como referencia consolidada a la documentación técnica v1.1, cuyo corte correspondía a una versión anterior de la aplicación.

Se distingue expresamente entre:

- funcionalidad implementada;
- funcionalidad verificada mediante pruebas automatizadas;
- funcionalidad validada por el usuario contra Jira real;
- arquitectura objetivo o trabajo futuro.

Los documentos de cada objetivo se conservan como evidencia histórica y detalle especializado.

## 2. Resumen ejecutivo

El Agente Jira es una aplicación web independiente que transforma un plan de trabajo capturado en una plantilla Excel simplificada en una propuesta estructurada de actividades Jira.

La aplicación:

1. valida la plantilla;
2. genera títulos, descripciones y Work Types mediante reglas deterministas;
3. resuelve responsables contra cuentas reales de Jira;
4. permite revisar y corregir la propuesta sin alterar el archivo fuente;
5. versiona y conserva cada cambio;
6. prevalida campos y relaciones contra Jira sin escribir;
7. solicita aprobación y confirmación explícitas;
8. crea actividades de forma controlada mediante Rovo MCP;
9. vuelve a leer cada actividad creada para comprobar el resultado;
10. genera evidencia auditable e impide reintentos automáticos inciertos.

La versión 0.20.0 admite en el Space AT:

- Task;
- Bug;
- Story;
- Epic;
- Subtask;
- relaciones `Epic → Task/Bug/Story`;
- relaciones `Task/Bug/Story → Subtask`;
- lotes sucesivos de hasta cinco actividades por confirmación.

La aplicación no es un simple importador masivo. Su valor principal es reducir la carga de captura, generar contenido útil, detectar ambigüedades, ofrecer una revisión humana y colocar barreras técnicas antes de modificar Jira.

## 3. Decisiones de producto vigentes

### 3.1 Aplicación independiente

El producto se desarrolla como una aplicación independiente porque no todos los usuarios disponen de Codex. La base tecnológica actual es:

- backend en Python y FastAPI;
- frontend en React y TypeScript;
- almacenamiento local SQLite durante el MVP;
- integración con Jira Cloud mediante Atlassian Rovo MCP.

Una skill o plugin de Codex puede explorarse posteriormente como canal adicional, pero no es el producto principal.

### 3.2 Jira Cloud Free

El sitio usa Jira Cloud en modalidad gratuita. Existe un grupo definido de hasta diez usuarios Jira. Los Spaces vigentes para el piloto son:

| Space | Tipo | Estado en el proyecto |
|---|---|---|
| AT | Team-managed software | Lectura y escritura controlada |
| ASIT | Company-managed software | Lectura y prevalidación; escritura no autorizada |
| MTTI | Company-managed software | Lectura y prevalidación; escritura no autorizada |

Normalmente un plan completo corresponde a un solo Space. La aplicación captura el Space como valor general y lo propaga a sus actividades.

Aunque la interfaz de Jira use el término “proyecto” en algunas APIs, este documento utiliza “Space” de acuerdo con la terminología acordada.

### 3.3 Normativa

La normativa operativa general prevalece sobre la guía del piloto cuando exista una diferencia.

- Se usa el campo **Iniciativa**.
- El campo Jira **Proyecto** se considera deprecado y no debe usarse para nuevas cargas.
- `Frente_de_trabajo_o_Proyecto` es un dato descriptivo de agrupación proveniente de la plantilla; no representa el campo Jira deprecado.

### 3.4 Primera fase basada en Excel

La primera fase sólo admite la Plantilla Excel v1.1. La lectura libre de PDF, Word, Markdown, TXT, minutas u otros documentos se difiere a fases posteriores.

La plantilla fue simplificada para evitar que capturarla tenga la misma complejidad que registrar directamente cada actividad en Jira. El usuario aporta información breve y la aplicación construye la descripción propuesta.

### 3.5 Inteligencia artificial

La transformación actual no requiere un LLM: las reglas son deterministas, explicables y de menor costo.

La arquitectura futura contempla un enrutamiento o cascada:

1. reglas y validaciones sin modelo;
2. Gemma para transformaciones autorizadas de bajo riesgo;
3. Gemini cuando la complejidad o calidad lo justifiquen;
4. revisión humana ante ambigüedad o baja confianza.

DeepSeek y GLM quedan fuera de las fases actuales. GCP/Gemini está autorizado conceptualmente para el piloto, pero la integración todavía no está implementada.

## 4. Alcance funcional actual

### 4.1 Incluido

- inicio de sesión local con un rol administrador;
- carga y validación de Plantilla Excel v1.1;
- generación determinista de una propuesta;
- clasificación en Task, Bug, Story, Epic o Subtask;
- generación automática de título y descripción;
- resolución y corrección de responsable mediante Jira real;
- edición atómica de los datos de cada actividad;
- edición de valores generales del plan;
- inclusión, revisión, exclusión y reactivación de actividades;
- versiones inmutables y reapertura controlada;
- historial, búsqueda, archivado y restauración de propuestas;
- aprobación final;
- conexión OAuth por usuario a Atlassian Rovo MCP;
- consulta de Spaces, Work Types, campos, opciones, responsables y Sprints;
- prevalidación contra Jira sin escritura;
- simulación local con evidencia y cero llamadas de escritura;
- creación real y verificación posterior en AT;
- lotes de hasta cinco actividades;
- lotes sucesivos para planes mayores;
- Epic, Subtask y relaciones padre-hijo;
- idempotencia, auditoría, evidencias JSON y ausencia de reintentos automáticos.

### 4.2 Diferido

- PDF, Word, Markdown, TXT y otros formatos de entrada;
- uso efectivo de Gemma o Gemini;
- escritura en ASIT o MTTI;
- despliegue productivo en AWS;
- autenticación productiva mediante Cognito o identidad corporativa;
- gestión administrativa de usuarios;
- recuperación de contraseña;
- múltiples roles;
- edición, transición, comentario o registro de trabajo en actividades existentes;
- ejecución desatendida;
- despliegue de AgentCore y Strands Agents.

### 4.3 Fuera del flujo de escritura actual

La aplicación sólo crea actividades nuevas. No invoca herramientas para:

- editar una actividad existente;
- agregar comentarios;
- registrar worklogs;
- cambiar estados;
- eliminar actividades;
- reintentar automáticamente una creación incierta.

## 5. Arquitectura implementada

```text
Usuario
  |
  v
React + TypeScript
  |
  v
FastAPI
  |-- Parser y reglas deterministas
  |-- Servicio de propuestas y versiones
  |-- Prevalidación y políticas de ejecución
  |-- Gateway de escritura controlada
  |
  |-- SQLite: propuestas, versiones, Dry runs e intenciones
  |-- Windows DPAPI: autorización OAuth cifrada
  |
  v
Atlassian Rovo MCP
  |
  v
Jira Cloud
```

### 5.1 Componentes del repositorio

| Ruta | Responsabilidad |
|---|---|
| `backend/` | API, autenticación, parser, reglas, persistencia, MCP y ejecución Jira |
| `frontend/` | Interfaz web React/TypeScript |
| `config/` | Políticas explícitas para cada modo de ejecución |
| `releases/plantilla_excel_v1_1/` | Plantilla Excel congelada |
| `examples/` | Archivos válidos, inválidos y de prueba |
| `docs/` | Planes, guías, evidencias y documentación |
| `scripts/` | Preparación, desarrollo, pruebas y arranques controlados |

### 5.2 Persistencia local

SQLite almacena:

- versiones completas de propuestas;
- ciclo de vida y estado de archivado;
- resultados de prevalidación;
- intenciones y resultados de simulación o escritura;
- huellas e identificadores de idempotencia.

El archivo fuente se conserva como referencia inmutable. Las correcciones afectan la propuesta derivada, no el Excel original.

### 5.3 Autenticación local

El MVP tiene un proveedor local de autenticación:

- un único usuario administrador;
- sesión Bearer mantenida en memoria;
- usuario y contraseña configurables por variables de entorno;
- sin autorregistro;
- sin recuperación de contraseña;
- sin CRUD de usuarios.

Las credenciales de demostración no deben reutilizarse en un ambiente compartido. La identidad de la aplicación y la autorización Jira son mecanismos independientes.

## 6. Contrato de la Plantilla Excel v1.1

La plantilla está congelada para evitar cambios silenciosos durante el piloto.

| Propiedad | Valor |
|---|---|
| Hoja principal | `PLAN_DE_TRABAJO` |
| Fila de encabezados | 5 |
| Rango previsto de actividades | Filas 6 a 55 |
| SHA-256 de la plantilla congelada | `9a4b913d55a27afdbee04efbc011ed134b394190eeaf968e94b2150b010f4204` |

### 6.1 Columnas

| Columna | Campo | Obligatorio | Uso |
|---|---|---:|---|
| A | Actividad | Sí | Base del título, descripción y Work Type |
| B | Responsable | Sí | Nombre de captura que se resuelve contra Jira |
| C | Frente_de_trabajo_o_Proyecto | No | Agrupación funcional |
| D | Contexto_o_Resultado | No | Contexto para la descripción |
| E | Fecha_Objetivo | No | Due date cuando aplica |
| F | Estado_Actual | No | Regla inicial de inclusión o exclusión |
| G | Comentarios | No | Información adicional para la descripción |

Estados admitidos:

- Pendiente;
- En curso;
- En pausa;
- Completada;
- Rechazada;
- Por confirmar.

La versión también incluye hojas de ayuda y ejemplo migrado.

### 6.2 Valores generales del plan

Los valores generales son:

- Space;
- Iniciativa;
- Línea de trabajo;
- Sprint;
- Tipo de seguimiento;
- Semáforo.

Pueden editarse durante el flujo. Un cambio crea una versión nueva, reabre una propuesta aprobada si fuera necesario y obliga a repetir aprobación y prevalidación.

Las opciones se consultan en los metadatos de Jira cuando están disponibles. Si Jira no publica un catálogo, la interfaz informa la limitación y permite captura manual, que vuelve a comprobarse en la prevalidación.

### 6.3 Relaciones jerárquicas

La Plantilla v1.1 no agrega columnas de jerarquía. El usuario elige el padre desde el editor de la propuesta. Esta decisión mantiene simple el archivo y permite validar la relación con el contexto real de Jira.

El archivo de prueba más amplio para jerarquías es:

`examples/plan_pruebas_objetivo_4e_jerarquias_v1_1.xlsx`

## 7. Transformación de una fila

### 7.1 Título

El título se normaliza y limita a 140 caracteres.

Al escribir en Jira, la política agrega un prefijo de prueba:

- `AgenteTest_Task_`;
- `AgenteTest_Bug_`;
- `AgenteTest_Story_`;
- `AgenteTest_Epic_`;
- `AgenteTest_Subtask_`.

Este prefijo sustituyó al término interno “canario” en la experiencia del usuario.

### 7.2 Descripción

La descripción se construye con:

- actividad;
- contexto o resultado;
- frente de trabajo;
- comentarios;
- fecha objetivo;
- referencia de la fila fuente.

El usuario revisa y puede editar el resultado antes de aprobarlo.

### 7.3 Clasificación de Work Type

La clasificación vigente es determinista y usa principalmente Actividad y Contexto. La prioridad de reglas es:

1. términos de Bug;
2. términos de Subtask;
3. términos de Epic;
4. términos de Story;
5. Task como valor predeterminado.

Una confianza baja lleva la actividad a revisión. Epic se propone con una confianza conservadora y normalmente requiere confirmación humana.

### 7.4 Decisión inicial

- `Completada` o `Rechazada` se excluye de forma predeterminada.
- Un responsable sin resolver requiere revisión.
- `Por confirmar` requiere confirmación del usuario.
- Una Subtask sin padre requiere revisión.
- Una clasificación de baja confianza requiere revisión.
- Cuando no existen pendientes, la actividad pasa a lista.

Una actividad excluida puede recuperarse. La reactivación exige un motivo y la devuelve primero a revisión.

## 8. Revisión, versionado y aprobación

### 8.1 Estados funcionales

La propuesta distingue:

- actividades que requieren revisión;
- actividades listas;
- actividades excluidas;
- bloqueos o advertencias provenientes de Jira.

Los bloqueos Jira pertenecen al resultado técnico de una versión y no sustituyen la decisión funcional del usuario.

### 8.2 Versiones

Cada guardado significativo crea una nueva versión inmutable. Esto permite:

- conservar el origen;
- comparar la evolución;
- auditar quién aprobó;
- reabrir sin borrar la aprobación histórica;
- asociar cada Dry run y ejecución a una versión exacta.

Una versión aprobada queda bloqueada para edición. Reabrir crea otra versión editable.

### 8.3 Editor atómico

En “Origen y propuesta”, el usuario puede modificar:

- título;
- descripción;
- Work Type;
- decisión;
- nota de revisión;
- responsable Jira;
- padre, cuando aplica.

Seleccionar un responsable no guarda ni cierra la ventana. El valor queda pendiente junto con los demás cambios. Sólo `Guardar y volver a validar` crea una versión nueva con el conjunto completo de cambios.

El nombre original del Excel se conserva como dato de origen; el responsable seleccionado y verificado en Jira es el valor final de la propuesta.

### 8.4 Historial

La barra lateral permite:

- buscar propuestas;
- filtrar activas o archivadas;
- cambiar el nombre operativo;
- archivar;
- restaurar;
- contraer la barra con el control visual o `Ctrl+B`.

El archivado es reversible. No elimina versiones ni evidencias.

### 8.5 Flujo visual

La interfaz organiza el trabajo en tres pasos:

1. **Revisar actividades**.
2. **Validar con Jira**.
3. **Probar y enviar**.

Las secciones secundarias son plegables. La conexión Jira vive en la barra lateral, los detalles técnicos permanecen ocultos de forma predeterminada y `Generar nueva propuesta` limpia el área de trabajo sin borrar el historial.

## 9. Integración Atlassian Rovo MCP

### 9.1 OAuth por usuario

Cada usuario autoriza la aplicación en Atlassian con su propia sesión. La aplicación:

1. inicia el flujo OAuth;
2. redirige al consentimiento de Atlassian;
3. recibe el callback local;
4. obtiene la autorización MCP;
5. trabaja con los mismos permisos que el usuario tiene en Jira.

La aplicación no solicita ni almacena la contraseña Jira.

En Windows, la autorización se cifra mediante DPAPI y se asocia al usuario local. Se escribe de forma atómica. Cerrar sesión en la aplicación no desconecta Jira; `Desconectar` elimina explícitamente la autorización. En plataformas sin DPAPI se usa memoria únicamente y no se guarda el token en texto plano.

### 9.2 Herramientas de lectura permitidas

La aplicación usa una lista positiva de herramientas:

- información del usuario Atlassian;
- recursos Atlassian accesibles;
- proyectos o Spaces Jira visibles;
- Work Types y metadatos de campos;
- opciones de campos;
- búsqueda y comprobación de cuentas;
- búsqueda de usuarios asignables;
- búsqueda JQL;
- lectura de una actividad Jira.

La disponibilidad del contrato de creación se inspecciona sin invocarlo durante los modos de sólo lectura.

### 9.3 Escritura permitida

La única herramienta de escritura autorizada es `createJiraIssue`.

Antes de transportarla, el gateway:

- comprueba la política activa;
- valida el payload contra el esquema anunciado por Rovo;
- registra la intención;
- impide herramientas fuera de la lista positiva.

Después de la creación invoca `getJiraIssue` para verificar el resultado.

### 9.4 Responsable

La búsqueda:

- acepta nombre o correo;
- exige al menos dos caracteres;
- elimina duplicados;
- descarta cuentas inactivas;
- prioriza coincidencia exacta;
- muestra un mensaje claro cuando no hay resultados.

La prevalidación puede emitir una advertencia cuando Rovo identifica una cuenta, pero no entrega evidencia suficiente de asignabilidad estricta para el Space y Work Type. La creación real todavía incluye el `accountId` en forma atómica; Jira tiene la decisión final y puede rechazarlo.

## 10. Resolución de Sprint

El usuario trabaja con nombres, no con IDs técnicos.

La aplicación consulta mediante JQL:

- Sprints activos;
- Sprints futuros.

Reglas:

1. Si se indicó un nombre, debe resolverse de forma exacta a un Sprint activo o futuro.
2. Si no se indicó nombre y existe exactamente un Sprint activo, se selecciona automáticamente.
3. Si existen varios activos, se bloquea hasta que el usuario elija.
4. Si no existe uno activo y no se eligió uno futuro, la actividad puede quedar sin Sprint con advertencia, si el Work Type lo permite.
5. Un Sprint desconocido, cerrado o ambiguo bloquea la escritura.

El catálogo se conserva cinco minutos para la interfaz, pero se fuerza una consulta nueva durante la prevalidación y justo antes de la primera creación real. La evidencia guarda nombre, ID, estado, tablero, origen y método de resolución.

Una limitación conocida de Jira es que un Sprint vacío puede no aparecer en ciertas búsquedas JQL. En ese caso la aplicación falla de forma segura en vez de adivinar un ID.

## 11. Prevalidación contra Jira

El Dry run consulta el estado real de Jira y no realiza escrituras.

Por actividad puede producir:

- `READY`;
- `READY_WITH_WARNINGS`;
- `BLOCKED`;
- `SKIPPED`.

Comprueba, según corresponda:

- Space visible;
- Work Type existente;
- campos obligatorios;
- opciones válidas;
- responsable activo y resoluble;
- Sprint;
- relación padre-hijo;
- política de ejecución.

La evidencia contiene:

- identificador DRY;
- propuesta y versión;
- huella de entrada;
- usuario;
- resultado por fila;
- claves de idempotencia;
- advertencias y bloqueos.

Repetir sin cambios recupera el resultado equivalente. Un Dry run histórico no habilita una versión nueva.

Una prevalidación con advertencias técnicas puede continuar si no hay bloqueos. La asignabilidad vuelve a comprobarse durante la creación real.

## 12. Simulación segura

La simulación:

- prepara el payload candidato;
- presenta campos con nombres comprensibles;
- conserva los IDs técnicos en un detalle opcional;
- solicita confirmación;
- recorre un gateway exclusivamente local;
- registra huellas y evidencia;
- realiza cero llamadas MCP;
- garantiza `write_performed=false`;
- garantiza `jira_issue_created=false`.

Su finalidad es probar el flujo y la evidencia, no demostrar que Jira aceptará el payload.

## 13. Políticas de ejecución

El inicio normal usa una política segura sin escritura. Los modos reales requieren un comando separado y una política explícita.

| Modo | Work Types | Space | Máximo | Escritura |
|---|---|---|---:|---|
| Seguro | Task de prueba local | AT | 1 | No |
| Objetivo 4B | Task | AT | 1 | Sí |
| Objetivo 4C.1 | Task | AT | 5 | Sí |
| Objetivo 4D | Task, Bug, Story | AT | 5 | Sí |
| Objetivo 4E | Task, Bug, Story, Epic, Subtask | AT | 5 | Sí |

Controles comunes de los modos reales:

- versión vigente y aprobada;
- Dry run vigente;
- cero bloqueos;
- cuenta activa y exacta;
- responsable en la creación atómica;
- segunda confirmación;
- confirmación con caducidad de diez minutos;
- lectura posterior obligatoria;
- máximo de 90 segundos;
- cero reintentos automáticos;
- sólo ambiente local;
- sólo Space AT.

Las frases de confirmación son deliberadamente explícitas:

- `CREAR 1 TASK EN AT`;
- `CREAR N TASKS EN AT`;
- `CREAR N ACTIVIDADES EN AT`.

## 14. Escritura controlada y verificación

### 14.1 Secuencia por actividad

1. Registrar intención e idempotencia.
2. Revalidar Sprint cuando aplica.
3. Resolver la clave real del padre cuando aplica.
4. Invocar `createJiraIssue`.
5. Recibir la clave Jira.
6. Invocar `getJiraIssue`.
7. Comparar campos críticos.
8. Registrar evidencia.
9. Continuar o detener el lote.

La lectura posterior comprueba:

- clave;
- summary;
- Space;
- Work Type;
- responsable;
- Sprint, cuando aplica;
- `parent.key`, cuando aplica.

### 14.2 Resultados

Una ejecución distingue:

- creada y verificada;
- creada con verificación incompleta;
- rechazada por Jira;
- resultado incierto;
- no intentada porque una actividad anterior detuvo el lote.

Un HTTP 4xx explícito de Jira es `REJECTED`. Una interrupción después de iniciar la creación, sin respuesta concluyente, es `UNKNOWN`.

Ante `UNKNOWN` no hay reintento automático porque podría duplicar una actividad. El operador debe conciliar manualmente el resultado en Jira.

### 14.3 Lotes sucesivos

Cada confirmación permite hasta cinco actividades. Si el plan contiene más:

- las verificadas no vuelven a ofrecerse;
- las ya intentadas no se reenvían;
- las `NOT_ATTEMPTED` permanecen disponibles;
- el progreso se calcula desde SQLite sin llamadas MCP adicionales.

### 14.4 Idempotencia

La aplicación usa huellas por propuesta, versión, selección y fila.

- La intención se persiste antes del transporte.
- Una ejecución terminal idéntica se devuelve desde la evidencia.
- Un lote idéntico no vuelve a invocar Jira.
- No se ofrecen actividades solapadas que ya fueron intentadas.

No existe rollback automático: borrar o revertir actividades reales está fuera del alcance del agente.

## 15. Epic, Subtask y relaciones padre-hijo

### 15.1 Jerarquías admitidas

| Padre | Hijos permitidos |
|---|---|
| Epic | Task, Bug, Story |
| Task | Subtask |
| Bug | Subtask |
| Story | Subtask |

Reglas adicionales:

- Epic no puede tener padre.
- Subtask debe tener padre.
- Subtask no puede ser padre.
- No se permite autorreferencia.
- No se permiten ciclos.
- El padre debe existir en la propuesta, estar incluido y ser compatible.

### 15.2 Orden de creación

El lote se ordena topológicamente para crear al padre antes que al hijo, aunque el usuario los seleccione en otro orden.

La relación se guarda inicialmente como referencia simbólica de fila, por ejemplo `ROW-0006`. Cuando el padre termina como `CREATED_VERIFIED`, su clave Jira —por ejemplo `AT-511`— sustituye esa referencia antes de crear al hijo.

El payload de Jira usa:

```json
{
  "parent": {
    "key": "AT-511"
  }
}
```

Después, `getJiraIssue` debe devolver la misma clave en `fields.parent.key`. Una discrepancia detiene el lote y deja las actividades restantes sin intentar.

### 15.3 Padres creados en lotes anteriores

Un hijo puede enviarse sin el padre en el mismo lote sólo si ese padre:

- pertenece a la misma versión aprobada;
- fue creado mediante el modo 4E;
- terminó como `CREATED_VERIFIED`;
- tiene su clave Jira conservada en la evidencia local.

La aplicación no busca padres por título ni adivina claves.

## 16. Trazabilidad y evidencia

La evidencia descargable permite reconstruir:

- archivo y versión de propuesta;
- usuario local;
- usuario Atlassian;
- política activa;
- payload confirmado;
- huellas SHA-256;
- instante de preparación y confirmación;
- llamadas MCP realizadas;
- ausencia de reintentos;
- clave creada;
- lectura posterior;
- relación padre-hijo;
- estado final por actividad;
- motivo de detención.

Los errores se sanitizan antes de mostrarse. Tokens, contraseñas y secretos no deben aparecer en logs, evidencias, prompts o repositorio.

## 17. Evolución por objetivos

| Objetivo | Resultado principal | Estado |
|---|---|---|
| 1 | Parser, reglas, propuesta local y Plantilla v1.1 | Implementado |
| 1.1 | Corrección guiada, barra lateral e historial | Implementado |
| 1.2 | Nombre editable, recuperación de excluidas y aprobación | Implementado |
| 3A | OAuth y lectura real mediante Rovo MCP | Implementado y validado |
| 3B | Prevalidación real sin escritura | Implementado |
| 3B.1 | Flujo práctico para corregir bloqueos | Implementado |
| 3B.2 | Cierre claro de prevalidación y advertencias | Implementado |
| 4A | Simulación segura y evidencia local | Implementado |
| 4B | Creación real de una Task en AT | Implementado y validado |
| 4B.2 | Resolución automática y revalidación de Sprint | Implementado y validado |
| 4C.1 | Lote de hasta cinco Tasks | Implementado y validado |
| 4C.2 | Lotes sucesivos y continuidad | Implementado y validado |
| 4D | Task, Bug y Story | Implementado y validado por el usuario |
| 4E | Epic, Subtask y jerarquías | Implementado; validación real integral pendiente |

No se implementó un Objetivo 4A.1 separado: sus mejoras de claridad se incorporaron al flujo final para evitar trabajo desechable.

## 18. Validaciones realizadas

### 18.1 Pruebas automatizadas al corte

El 28 de julio de 2026 se verificó:

- backend: 96 pruebas aprobadas;
- frontend: 13 pruebas aprobadas;
- compilación TypeScript y Vite de producción: exitosa.

El script integral requiere que Node.js y pnpm estén disponibles en `PATH`. En el entorno de validación fue necesario usar el runtime Node incluido en el workspace para ejecutar la parte frontend.

### 18.2 Validaciones reales reportadas

Se confirmó en Jira:

- conexión OAuth/Rovo;
- lectura de los Spaces AT, ASIT y MTTI;
- consulta de Work Types;
- búsqueda de responsables reales;
- creación y verificación de `AT-507`, incluyendo responsable y Sprint;
- creación y verificación de Tasks `AT-508`, `AT-509` y `AT-510`;
- escritura de Task, Bug y Story;
- continuidad mediante lotes sucesivos;
- guardado atómico de responsable y demás correcciones.

Para `AT-507` se reportaron dos llamadas MCP y cero reintentos. Para `AT-508` a `AT-510` se reportaron seis llamadas MCP y cero reintentos.

El modo 4E tiene pruebas automatizadas y un Excel específico, pero todavía debe completarse una prueba real representativa que incluya Epic, actividades estándar, Subtasks y relaciones en uno o más lotes.

## 19. Operación local

### 19.1 Requisitos

- Python 3.12 o superior;
- Node.js 20 o superior;
- pnpm;
- navegador con acceso a Atlassian;
- salida a Internet hacia Jira y Rovo MCP.

### 19.2 Preparación y desarrollo

```powershell
scripts\setup.cmd
scripts\dev.cmd
```

La interfaz de desarrollo usa normalmente `http://localhost:5173` y FastAPI `http://localhost:8000`.

### 19.3 Inicio normal seguro

```powershell
scripts\start.cmd
```

El inicio normal conserva la escritura deshabilitada.

### 19.4 Modos de escritura

```powershell
scripts\start-objective-4b.cmd
scripts\start-objective-4c1.cmd
scripts\start-objective-4d.cmd
scripts\start-objective-4e.cmd
```

Arrancar un modo no crea actividades. La escritura sólo ocurre después de cargar, revisar, prevalidar, aprobar, seleccionar, confirmar la frase exacta y pulsar la acción final.

Debe detenerse previamente cualquier servidor que esté ocupando el puerto 8000.

### 19.5 Pruebas

```powershell
scripts\test.cmd
```

### 19.6 Variables relevantes

| Variable | Finalidad |
|---|---|
| `AGENTE_JIRA_LOCAL_USER` | Usuario local |
| `AGENTE_JIRA_LOCAL_PASSWORD` | Contraseña local |
| `AGENTE_JIRA_EXECUTION_POLICY` | Archivo de política activo |

La configuración predeterminada usa:

- base SQLite en `backend/data/agente_jira.db`;
- OAuth local en `backend/data/atlassian_oauth`;
- Rovo MCP en `https://mcp.atlassian.com/v1/mcp/authv2`;
- callback OAuth local en el puerto 8000.

## 20. Resumen de API

La API se agrupa en:

| Grupo | Capacidades |
|---|---|
| Salud | health y readiness |
| Autenticación | login y sesión |
| Atlassian | estado, conectar, callback, desconectar, diagnóstico |
| Catálogos Jira | responsables, Sprints, Spaces, Work Types y campos |
| Plantilla | descarga de v1.1 |
| Propuestas | crear, listar, consultar, renombrar, archivar y restaurar |
| Actividades | editar, reactivar y resolver responsable |
| Valores generales | consultar y actualizar |
| Aprobación | aprobar, aprobar con Dry run, reabrir y exportar |
| Dry run | ejecutar, consultar último resultado y descargar evidencia |
| Simulación | preparar, confirmar, simular, cancelar y evidenciar |
| Escritura individual | preparar, confirmar, ejecutar y evidenciar |
| Lotes | preparar, consultar progreso, confirmar, ejecutar y evidenciar |

El contrato detallado también puede inspeccionarse en la documentación OpenAPI de FastAPI durante la ejecución local.

## 21. Limitaciones y riesgos conocidos

- Sólo AT está autorizado para escritura.
- Máximo cinco actividades por confirmación.
- El entorno es local y tiene un único rol.
- SQLite y DPAPI no son la solución productiva para Linux/AWS.
- La publicación de metadatos varía entre proyectos Team-managed y Company-managed.
- Rovo puede no demostrar asignabilidad estricta aun cuando Jira acepte la cuenta.
- Jira puede omitir Sprints vacíos en búsquedas.
- Una respuesta incierta requiere conciliación manual.
- No hay rollback ni eliminación Jira.
- Los prefijos `AgenteTest_` siguen siendo obligatorios mientras se use un Space productivo para pruebas.
- El costo y la calidad de un LLM todavía no se justifican para la entrada Excel estructurada.
- La validación real integral de jerarquías 4E está pendiente.

## 22. Arquitectura AWS objetivo, no implementada

La cuenta AWS prevista:

- usa la región `us-east-1`;
- es compartida;
- pertenece a AWS Organizations como cuenta miembro;
- tiene habilitadas todas las características de Organizations;
- dispone de IAM Identity Center en `us-east-1`;
- requiere que el administrador institucional complete las asignaciones y Permission Sets;
- recibirá alertas operativas en `callejaj@telmex.com`.

Estos aspectos de administración no bloquean el desarrollo local del agente y deben resolverse como parte del despliegue, con el responsable de la cuenta.

Arquitectura objetivo:

```text
React/TypeScript
       |
Amazon Cognito
       |
FastAPI
  |-- S3: archivos y evidencias
  |-- DynamoDB on-demand: propuestas, versiones e idempotencia
  |-- CloudWatch: logs, métricas y alarmas
  |-- Secrets Manager + KMS: secretos y autorización
  |-- AgentCore + Strands: sólo donde aporten valor
  |-- Endpoint Gemma o Vertex AI/Gemini: bajo enrutamiento
  `-- Atlassian Rovo MCP: Jira Cloud
```

Principios:

- servicios administrados sólo cuando reduzcan operación real;
- configuración de bajo consumo;
- etiquetas de propietario, ambiente, aplicación y centro de costos;
- alertas tempranas;
- mínimo privilegio;
- secretos fuera de código;
- sin Step Functions al inicio, salvo que aparezcan flujos largos o distribuidos que lo justifiquen.

El objetivo económico preliminar del MVP es mantener el consumo incremental bajo, aproximadamente menor a 50 USD mensuales. Debe medirse por etiquetas porque la cuenta es compartida y su costo total no representa el costo del Agente Jira.

## 23. Ruta recomendada inmediata

El siguiente incremento con mayor valor es cerrar la validación real del Objetivo 4E:

1. iniciar con `scripts\start-objective-4e.cmd`;
2. cargar `examples/plan_pruebas_objetivo_4e_jerarquias_v1_1.xlsx`;
3. resolver responsables, Work Types y padres;
4. ejecutar la prevalidación;
5. comenzar con un lote pequeño que incluya un Epic y un hijo;
6. verificar claves y relación en Jira;
7. enviar un segundo lote con Subtasks cuyo padre ya esté verificado;
8. descargar y conservar la evidencia.

Después de esa aceptación conviene:

1. congelar el alcance funcional del MVP local;
2. corregir únicamente defectos de aceptación;
3. preparar infraestructura AWS no productiva;
4. sustituir autenticación, persistencia y secretos locales;
5. desplegar sin habilitar escrituras inicialmente;
6. repetir las pruebas de lectura, Dry run y escritura controlada.

## 24. Documentos y artefactos principales

- [README del proyecto](../README.md)
- [Objetivo 4E — jerarquías](objetivo_4e_jerarquias.md)
- [Guía de validación 4E](guia_validacion_objetivo_4e.md)
- [Objetivo 4D — Bug y Story](objetivo_4d_bug_story.md)
- [Objetivo 4C.2 — lotes sucesivos](objetivo_4c_2_continuidad_lotes.md)
- [Objetivo 4C.1 — lote de Tasks](objetivo_4c_1_lote_tasks_at.md)
- [Objetivo 4B.2 — Sprint](objetivo_4b_2_resolucion_sprint.md)
- [Objetivo 4B — escritura controlada](objetivo_4b_escritura_controlada.md)
- [Objetivo 3B.2 — cierre de prevalidación](objetivo_3b_2_cierre_prevalidacion.md)
- [Ajuste de experiencia v0.13](ajuste_ux_flujo_v0_13.md)
- [Ajuste de datos finales v0.14](ajuste_datos_finales_v0_14.md)
- [Corrección del editor v0.18](correccion_editor_responsable_v0_18.md)
- [Esquema JSON v1.1](schemas/jira_proposal_v1_1.schema.json)
- [Política segura](../config/jira_execution_policy_v1.json)
- [Política 4E](../config/jira_execution_policy_4e.json)
- [Plantilla congelada](../releases/plantilla_excel_v1_1/)
- [Plan de pruebas de jerarquías](../examples/plan_pruebas_objetivo_4e_jerarquias_v1_1.xlsx)

## 25. Glosario

| Término | Significado |
|---|---|
| Propuesta | Versión revisable derivada del Excel antes de crear en Jira |
| Space | Contenedor Jira equivalente al proyecto técnico en las APIs |
| Work Type | Tipo de actividad: Task, Bug, Story, Epic o Subtask |
| Dry run | Prevalidación contra Jira sin escritura |
| Simulación | Recorrido totalmente local del envío |
| Readback | Lectura posterior de la actividad recién creada |
| Idempotencia | Control que evita repetir una misma operación |
| Referencia simbólica | Identificador local `ROW-nnnn` antes de conocer la clave Jira |
| Evidencia | JSON auditable con huellas, decisiones, llamadas y resultados |
| Resultado incierto | Creación cuyo resultado no pudo confirmarse de manera segura |
| Lote sucesivo | Nueva confirmación que continúa con actividades todavía no intentadas |

---

**Conclusión:** el MVP local ya cubre el ciclo completo desde Excel hasta creación controlada y verificada de actividades Jira. La principal prueba funcional pendiente es la aceptación real de las jerarquías del Objetivo 4E; el despliegue AWS y el uso de modelos son evoluciones posteriores, no dependencias del funcionamiento actual.
