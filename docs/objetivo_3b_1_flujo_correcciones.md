# Objetivo 3B.1 - Flujo práctico de correcciones Jira

Fecha: 17 de julio de 2026  
Estado: implementado y verificado localmente.

## Propósito

Evitar que el usuario apruebe una propuesta antes de atender los bloqueos que realmente puede corregir y separar esos casos de las limitaciones técnicas que no requieren editar una actividad.

## Flujo implementado

1. Una propuesta reabierta recupera el último Dry run como evidencia histórica.
2. Los bloqueos se clasifican en:
   - `Por corregir`: requieren una acción concreta del usuario;
   - `Validación técnica`: dependen de una capacidad de integración y no solicitan cambios innecesarios;
   - `Corregidas`: la modificación fue guardada y se comprobará en la prevalidación final.
3. `Resolver siguiente bloqueo` abre directamente la primera actividad accionable.
4. La actividad explica el problema y la acción requerida en lenguaje operativo.
5. Para responsables Jira, `Guardar y continuar` crea una versión nueva y avanza a la siguiente corrección.
6. La aprobación permanece oculta y también es rechazada por el backend mientras existan correcciones de usuario pendientes.
7. Cuando las correcciones de usuario llegan a cero, se habilita `Revisar y aprobar correcciones`.
8. El Dry run anterior queda colapsado bajo `Ver detalle técnico del último Dry run`.

## Clasificación inicial del caso real

- tres actividades `ASSIGNEE_NOT_FOUND`: acción del usuario;
- dos actividades `ASSIGNEE_ASSIGNABILITY_UNVERIFIED`: validación técnica;
- escrituras Jira: cero.

La validación técnica no se presenta como una corrección manual porque cambiar datos sin evidencia de asignabilidad no resolvería la limitación de Rovo MCP.

## Controles

- la clasificación se calcula en el backend;
- la interfaz consume la misma clasificación;
- la API de aprobación aplica la misma regla de bloqueo;
- los resultados del Dry run conservan versión, auditoría e idempotencia;
- `write_performed=false` permanece obligatorio.

## Verificación

- backend: 40 pruebas aprobadas;
- frontend: 8 pruebas aprobadas;
- TypeScript y build de producción: aprobados;
- caso local: propuesta v7, 3 correcciones de usuario y 2 validaciones técnicas.
