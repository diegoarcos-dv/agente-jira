# Plan técnico - Agente de generación controlada de work items en Jira

| Dato | Valor |
|---|---|
| Versión | 0.8 |
| Fecha | 17 de julio de 2026 |
| Estado | Objetivo 1.2 implementado y verificado |
| Plantilla de entrada | Excel v1.1 congelada |
| Ejecución actual | Local, sin conexiones externas |

## 1. Relación con la versión 0.7

La versión 0.8 conserva la Plantilla Excel v1.1, las reglas deterministas, el versionado local y los ajustes de experiencia del [Objetivo 1.1](plan_tecnico_agente_jira_v0.7.md). Esta revisión resuelve tres necesidades encontradas durante la aceptación:

1. distinguir propuestas que provienen de archivos con nombres iguales;
2. recuperar de forma segura una actividad excluida por error;
3. disponer de un cierre explícito cuando ya no quedan actividades por revisar.

## 2. Nombre operativo independiente de la fuente

Cada propuesta tiene un `display_name` editable, independiente del nombre y del SHA-256 del archivo de origen.

- El nombre operativo se usa en el historial y en el encabezado.
- `source_file.name` y `source_file.sha256` no cambian al renombrar.
- La actualización registra fecha y usuario en `proposal_lifecycle`.
- El nombre tiene entre 1 y 120 caracteres.
- Renombrar no crea una versión de contenido, porque no altera la propuesta ni su fuente.

Esta separación permite identificar planes repetidos sin perder trazabilidad documental.

## 3. Recuperación auditada de actividades excluidas

Una actividad puede reactivarse únicamente cuando fue excluida porque el archivo fuente la marcó como `Completada` o `Rechazada`.

```text
Excluida
   ↓ motivo obligatorio
Reactivar actividad
   ↓ nueva versión y auditoría
Requiere revisión
   ↓ revisión y confirmación explícita
Lista
```

La reactivación:

- exige un motivo de al menos cinco caracteres;
- conserva el estado y todos los datos originales de la fila;
- registra `source_state_override`, motivo, fecha y usuario;
- crea una versión nueva;
- fuerza `REVISAR` mediante `REACTIVATION_REVIEW_REQUIRED`;
- nunca envía la actividad directamente a `Listas`;
- requiere confirmar que la reactivación fue revisada antes de incluirla.

## 4. Ciclo de aprobación final

Cuando no existen actividades en `REVISAR`, la propuesta adquiere estado técnico `VALIDATED` y la interfaz muestra `Lista para aprobación`.

Antes de aprobar se presenta un resumen con conteos, fuente, hash y una confirmación explícita. La aprobación:

- crea una versión nueva;
- cambia el estado a `APPROVED`;
- registra `approved_at` y `approved_by`;
- bloquea edición, reactivación y una segunda aprobación;
- habilita la descarga JSON de la versión aprobada;
- no ejecuta ninguna operación en Jira.

La reapertura sólo está permitida desde `APPROVED`. Genera otra versión editable, conserva la versión aprobada en el historial y vuelve a `VALIDATED` o `NEEDS_INPUT`, según los pendientes existentes.

## 5. API incorporada

| Operación | Propósito |
|---|---|
| `PATCH /api/proposals/{id}/metadata` | Cambiar el nombre operativo |
| `POST /api/proposals/{id}/items/{row}/reactivate` | Recuperar una exclusión con motivo auditado |
| `POST /api/proposals/{id}/approve` | Aprobar y bloquear una versión final |
| `GET /api/proposals/{id}/approved-export` | Descargar el JSON de la versión aprobada |
| `POST /api/proposals/{id}/reopen` | Crear una versión editable desde una aprobada |

Las transiciones inválidas responden con HTTP `409 Conflict` y un mensaje de negocio.

## 6. Persistencia y trazabilidad

`proposal_versions` conserva cada versión completa. `proposal_lifecycle` mantiene datos administrativos que no modifican el contenido:

- archivado y restauración;
- nombre operativo;
- fecha y usuario del último cambio de nombre.

La aprobación y la reapertura sí generan versiones porque cambian el estado controlado del documento. El JSON exportado contiene el nombre operativo y la propuesta aprobada completa.

## 7. Seguridad y límites vigentes

- No hay clientes ni conexiones con Jira, Atlassian, AWS, GCP, Gemini o Rovo MCP.
- No hay escritura de work items.
- No hay secretos productivos.
- El catálogo de responsables continúa siendo ficticio.
- La persistencia y autenticación son locales para desarrollo.
- El endpoint `/api/health` mantiene `external_connections: false`.

La ejecución Jira sigue reservada para el Objetivo 4. La base AWS, identidad y observabilidad corresponden a una etapa posterior y requieren una planeación específica.

## 8. Verificación del Objetivo 1.2

Estado: **cumplido y verificado**.

- 22 pruebas de backend aprobadas.
- 7 pruebas de frontend aprobadas.
- TypeScript y compilación Vite de producción aprobados.
- Flujo interactivo completo validado desde renombrado hasta reapertura.
- Descarga JSON comprobada en API e interfaz.
- Bloqueo de edición aprobada cubierto por pruebas.
- Reapertura comprobada sin perder la versión aprobada.
- Interfaz comprobada sin errores de consola ni desbordamiento horizontal.

La evidencia reproducible se documenta en [evidencia_objetivo_1_2.md](evidencia_objetivo_1_2.md).

## 9. Siguiente paso

El siguiente paso es la validación de aceptación del Objetivo 1.2 mediante la [guía de validación](guia_validacion_objetivo_1_2.md). Después de aceptarlo, corresponde revisar y activar un objetivo de arquitectura AWS no productiva; no se habilitará Jira como consecuencia automática de esta aprobación.

## 10. Ajuste posterior de la barra lateral

Durante la validación de aceptación se detectó que los metadatos de nombres largos podían invadir el espacio reservado para `Archivar`. Se corrigió la distribución para que:

- el área de apertura y la acción administrativa sean columnas independientes;
- nombre y archivo fuente se recorten con puntos suspensivos;
- el texto completo continúe disponible como ayuda contextual;
- `Archivar` o `Restaurar` conserve un ancho mínimo y no se comprima;
- el modo de barra contraída mantenga su disposición propia.

La prueba de regresión usa deliberadamente un nombre operativo y un archivo fuente extensos.

## 11. Gestión futura de usuarios y responsables

Se distinguen dos catálogos que no deben mezclarse:

1. **Usuarios de la aplicación:** ingresan al sistema, tienen rol y serán administrados mediante Cognito en el Objetivo 2.
2. **Responsables Jira:** pueden recibir work items y deben existir en Atlassian con un `accountId` asignable al Space. Su resolución real corresponde al Objetivo 3, mediante Rovo MCP de sólo lectura.

La aplicación no debe “crear” localmente un responsable como si eso lo convirtiera en usuario Jira. Para un nombre no encontrado, el flujo futuro permitirá solicitar alta o registrar un alias/mapeo; sólo Jira o su administración corporativa puede dar de alta la identidad Atlassian y sus permisos.

No se implementará un CRUD local definitivo que después deba reemplazarse. El panel administrativo se construirá sobre Cognito y el catálogo real cuando existan la identidad AWS y la lectura Jira.
