# Evidencia verificable - Objetivo 1.2

Fecha de verificación: 17 de julio de 2026.

## Objetivo

Implementar y verificar la identificación, recuperación y aprobación final de propuestas: nombre editable independiente de la fuente, reactivación auditada de actividades excluidas, estado `Lista para aprobación`, aprobación bloqueada, descarga JSON y reapertura controlada.

## Evidencia automatizada

Comando reproducible desde la raíz:

```powershell
scripts\test.cmd
```

Resultado esperado y verificado:

```text
22 passed
Test Files 1 passed
Tests 7 passed
TypeScript build passed
Vite production build passed
Verificación completa.
```

La cobertura incluye:

- renombrado y conservación del archivo fuente;
- validación del nombre operativo;
- reactivación sólo para exclusiones recuperables;
- motivo obligatorio y auditoría de la reactivación;
- retorno obligatorio a `REVISAR` antes de `INCLUIR`;
- aprobación impedida mientras existan pendientes;
- bloqueo de una versión aprobada;
- descarga permitida sólo en `APPROVED`;
- reapertura versionada y conservación de la versión aprobada;
- controles de interfaz para renombrar, reactivar, aprobar y descargar.

## Recorrido interactivo

Se utilizó una copia del plan de referencia con cinco actividades.

| Acción | Versión resultante | Estado observado |
|---|---:|---|
| Creación y cambio de nombre a `Validación Objetivo 1.2` | 1 | Nombre operativo distinto de `obj12_browser_test.xlsx` |
| Reactivar la fila 6 con motivo | 2 | `Requiere revisión` |
| Confirmar la revisión de la reactivación | 3 | Actividad en `Listas` |
| Resolver responsable de la fila 9 | 4 | `Lista para aprobación` |
| Aprobar y bloquear | 5 | `Propuesta aprobada` |
| Reabrir para editar | 6 | `Lista para aprobación`; aprobación v5 conservada |

Durante la aprobación se verificó que la interfaz mostrara conteos, fuente, SHA-256 y el aviso de que Jira no se ejecuta en este objetivo.

## Bloqueo y exportación

En la versión 5 aprobada se observaron:

- sello `Propuesta aprobada`;
- usuario y fecha de aprobación;
- texto `Versión final bloqueada`;
- acción `Descargar JSON aprobado`;
- acción `Reabrir para editar`;
- ausencia de controles de edición del contenido.

La API comprobó además el encabezado de descarga y el contenido con `display_name` y la propuesta completa.

## Verificación visual

Viewport validado: 1280 × 720.

- `scrollWidth`: 1265, menor que `innerWidth`: 1280.
- No se detectaron errores de consola.
- El encabezado mostró el nombre operativo y, por separado, `Archivo fuente inmutable`.
- Tras reabrir, la interfaz mostró versión 6 y el botón `Revisar y aprobar propuesta final`.

## Confirmación de aislamiento

- `/api/health` reporta `external_connections: false`.
- La búsqueda estática no encuentra clientes Jira, AWS o GCP en el código ejecutable.
- No existe una operación de creación o modificación de work items Jira.
- La palabra Jira que aparece en textos y contratos describe el destino futuro, no una conexión activa.

## Resultado

El Objetivo 1.2 cumple los criterios funcionales, de versionado, trazabilidad, bloqueo y aislamiento. Está listo para validación de aceptación del usuario.

## Corrección visual posterior

El 17 de julio de 2026 se corrigió la colisión entre metadatos extensos y la acción `Archivar` del historial.

Evidencia:

- prueba de componente con nombre operativo y archivo fuente extensos;
- truncamiento independiente con puntos suspensivos;
- columna de acción con ancho mínimo y texto no divisible;
- 7 pruebas frontend aprobadas;
- compilación TypeScript y Vite de producción aprobada.

La inspección automatizada en navegador quedó pendiente de repetición porque la instalación local del complemento de navegador no contiene su módulo de control. La estructura causante del defecto sí quedó corregida y cubierta por la prueba de regresión y el build.
