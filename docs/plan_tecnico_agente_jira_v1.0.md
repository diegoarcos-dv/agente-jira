# Plan técnico - Agente de generación controlada de work items en Jira

| Dato | Valor |
|---|---|
| Versión | 1.0 |
| Fecha | 17 de julio de 2026 |
| Estado | Objetivo 3B implementado; aceptación con Jira real pendiente |
| Entrada | Plantilla Excel v1.1 congelada |
| Integración | Atlassian Rovo MCP mediante OAuth 2.1 |
| Modo Jira | Dry run de solo lectura; escritura deshabilitada |

## 1. Objetivo 3B activo y verificable

Prevalidar una versión aprobada de la propuesta contra los metadatos reales de Jira y producir un artefacto Dry run auditable e idempotente sin crear, modificar, transicionar ni eliminar work items.

La prevalidación comprueba:

- sitio y Space reales;
- Work Type y sus campos disponibles;
- campos obligatorios configurados en Jira;
- título, descripción y Tipo de seguimiento exigidos por la normativa;
- existencia de una cuenta Jira coincidente para el responsable;
- disponibilidad del campo Assignee;
- relación padre para subtareas;
- tratamiento explícito de metadatos incompletos;
- una clave idempotente estable por actividad.

## 2. Flujo implementado

```text
Propuesta APPROVED e inmutable
  -> snapshot Jira obtenido por Rovo MCP
  -> validación determinista por actividad
  -> resolución de identidad Jira del responsable
  -> mapeo lógico de campos
  -> huella de propuesta + clave por fila
  -> registro Dry run inmutable en SQLite
  -> vista Listas / Bloqueadas / Excluidas
```

El Dry run no contiene un ejecutor y no tiene acceso a herramientas de escritura.

## 3. Estados

| Estado | Significado |
|---|---|
| `READY` | La actividad superó la prevalidación disponible |
| `BLOCKED` | Existe al menos un problema que impide continuar |
| `SKIPPED` | La propuesta aprobada excluyó la actividad |

El Dry run completo queda `READY` únicamente si no existen actividades bloqueadas.

## 4. Controles de seguridad

- Sólo se acepta la última versión con estado `APPROVED`.
- La propuesta permanece bloqueada durante el análisis.
- Se reutiliza la lista positiva de herramientas MCP de lectura.
- No existe una ruta API de creación Jira en el Objetivo 3B.
- Cada respuesta declara `write_performed=false`.
- Las pruebas verifican que el gateway recibe únicamente búsquedas de responsables.
- Reiniciar o desconectar elimina los tokens Atlassian guardados en memoria.

## 5. Idempotencia y auditoría

La huella SHA-256 canónica incluye la propuesta aprobada y el manifiesto lógico. Cada fila obtiene una clave `AJI-...`. El Dry run obtiene una clave `DRY-...`.

Si se repite la operación con los mismos datos se recupera el registro original y la API devuelve `reused=true`; no se crea un segundo registro equivalente. Una nueva versión aprobada o un cambio efectivo del manifiesto genera una huella distinta.

Los registros se almacenan en `jira_dry_runs` con:

- identificador Dry run;
- propuesta y versión;
- fecha y usuario;
- estado;
- documento completo de prevalidación.

## 6. Responsable Jira

El servidor real observado expone `lookupJiraAccountId`, no `findAssignableUsers`. Por ello se aplican dos niveles:

- `JIRA_ASSIGNABLE_USER_MATCH`: asignabilidad confirmada cuando Rovo expone `findAssignableUsers`;
- `JIRA_ACCOUNT_MATCH`: cuenta exacta y activa encontrada, pero todavía sin evidencia suficiente de asignabilidad.

En el segundo caso el Dry run queda bloqueado con `ASSIGNEE_ASSIGNABILITY_UNVERIFIED`. Si el metadato del campo Assignee incluye `allowedValues`, la cuenta debe aparecer en esa lista para convertirse en `JIRA_ASSIGNABLE_USER_MATCH`; si aparece una lista y la cuenta no pertenece a ella se usa `ASSIGNEE_NOT_ASSIGNABLE`. Esta limitación no se oculta ni se presenta como una garantía inexistente.

## 7. Subtareas

Una subtarea requiere:

- metadatos de campos no vacíos;
- `parent_row_id`;
- que el padre esté incluido en la misma propuesta.

Durante el Objetivo 3A, AT devolvió el Work Type **Subtarea** pero cero campos. El Dry run lo bloquea con `WORK_TYPE_FIELDS_UNAVAILABLE`. ASIT y MTTI sí reportaron el campo obligatorio Parent. No se habilitará una excepción silenciosa.

## 8. API

| Operación | Propósito |
|---|---|
| `POST /api/proposals/{proposal_id}/dry-run` | Generar o reutilizar una prevalidación |
| `GET /api/proposals/{proposal_id}/dry-run/latest` | Recuperar el resultado de la versión actual |

No se incorporó ningún endpoint de escritura Jira.

## 9. Interfaz

Una propuesta aprobada ofrece **Prevalidar contra Jira**. El resultado muestra:

- estado general;
- conteos Listas, Bloqueadas y Excluidas;
- evidencia visible de cero escrituras;
- resultado y mensajes por fila;
- responsable Jira encontrado;
- clave idempotente;
- advertencias sobre las limitaciones de Rovo.

Al reabrir la propuesta, el editor de cada actividad permite buscar una cuenta Jira real y seleccionarla. El backend repite la consulta y acepta únicamente una cuenta activa incluida en la respuesta de Rovo; después crea una versión nueva que debe aprobarse nuevamente.

## 10. Verificación automatizada

- 37 pruebas de backend aprobadas;
- 8 pruebas de frontend aprobadas;
- TypeScript y build de producción aprobados;
- prueba de idempotencia del Dry run;
- prueba de bloqueo de Subtarea AT sin metadatos;
- prueba de rechazo de propuestas no aprobadas;
- prueba de API que demuestra `write_performed=false` y ausencia de llamadas de escritura.

## 11. Criterios de aceptación con Jira real

1. Autorizar nuevamente Atlassian después del reinicio local.
2. Abrir una propuesta `APPROVED`.
3. Seleccionar **Prevalidar contra Jira**.
4. Confirmar que aparece un identificador `DRY-...`.
5. Revisar Listas, Bloqueadas y Excluidas.
6. Confirmar que cada bloqueo tiene código y explicación accionable.
7. Repetir el Dry run y comprobar que se recupera el mismo identificador.
8. Confirmar visualmente **Cero escrituras Jira**.

## 12. Paso posterior

Una vez aceptado el Objetivo 3B se podrá diseñar el Objetivo 4A: creación controlada de un único Task de prueba en AT, con confirmación adicional, kill switch, lectura posterior e idempotencia demostrada.
