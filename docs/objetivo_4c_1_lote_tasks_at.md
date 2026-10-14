# Objetivo 4C.1: lote controlado de Tasks en AT

Versión de la aplicación: 0.18.0  
Estado: implementado y validado contra Jira real el 20 de julio de 2026.

Evidencia funcional reportada por el usuario:

- `AT-508` — Habilitar accesos a la nube AWS;
- `AT-509` — Definir estrategia de anonimización de datos sensibles;
- `AT-510` — Construir dashboard de resultados de Monitor Wifi;
- tres Tasks creadas y verificadas;
- seis llamadas MCP;
- cero reintentos.

## Resultado

El Objetivo 4C.1 amplía el flujo 4B de una sola Task a un lote pequeño de **una a cinco Tasks**, exclusivamente en el Space **AT**. No habilita otros Work Types, Spaces, comentarios, transiciones, edición ni eliminación.

Cada actividad conserva su clave idempotente, se crea individualmente y se consulta inmediatamente después para verificar clave Jira, título, Space, Work Type, responsable y Sprint cuando corresponda.

## Flujo implementado

1. La propuesta debe estar aprobada y tener un Dry run vigente con cero bloqueos.
2. El usuario selecciona entre una y cinco Tasks elegibles.
3. La aplicación prepara el lote sin escribir y muestra el orden, responsable y Sprint.
4. El usuario confirma con la frase dinámica que muestra la aplicación para el lote actual.
5. Antes de la primera creación se actualiza el catálogo de Sprints y se valida cada ID.
6. Las Tasks se crean secuencialmente mediante `createJiraIssue`.
7. Después de cada creación se llama `getJiraIssue` y se comparan los campos núcleo.
8. Si todo coincide, continúa la siguiente actividad; si existe una anomalía, el lote se detiene.
9. El resultado consolidado y la evidencia JSON quedan disponibles en la interfaz.

## Política de detención

| Resultado de una actividad | Estado del lote | Actividades posteriores |
|---|---|---|
| Creada y verificada | Continúa | Se procesan en orden |
| Jira rechazó la creación | `STOPPED_REJECTED` | `NOT_ATTEMPTED` |
| Resultado incierto por interrupción | `STOPPED_UNKNOWN` | `NOT_ATTEMPTED` |
| Creada pero lectura incompleta | `STOPPED_UNVERIFIED` | `NOT_ATTEMPTED` |

No existe rollback automático. Una actividad ya creada permanece en Jira y debe conservarse como evidencia o corregirse mediante el proceso operativo autorizado. No hay reintentos automáticos.

Si la aplicación encuentra un lote persistido como `BATCH_RUNNING`, no lo reanuda: exige conciliación manual en Jira para evitar duplicados.

## Controles técnicos

- política independiente: `config/jira_execution_policy_4c1.json`;
- límite técnico y de esquema: máximo cinco actividades;
- lista positiva: `AT` y `Task`;
- única herramienta de escritura: `createJiraIssue`;
- lectura posterior obligatoria: `getJiraIssue`;
- confirmación con vigencia de diez minutos;
- revalidación de Sprint sin caché antes de cualquier escritura;
- persistencia del estado antes y después de cada llamada;
- evidencia con hashes, claves idempotentes, estados, errores, claves Jira y llamadas MCP.

## Alcance pendiente

- validar manualmente un primer lote pequeño en Jira real;
- autorización explícita antes de ampliar el límite;
- Bugs, Stories, Epics y Subtasks;
- ASIT y MTTI;
- despliegue AWS, autenticación corporativa y observabilidad CloudWatch.

La siguiente expansión debe decidirse con evidencia del primer lote real.
