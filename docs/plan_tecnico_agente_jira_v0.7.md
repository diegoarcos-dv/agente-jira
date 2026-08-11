# Plan técnico - Agente de generación controlada de work items en Jira

| Dato | Valor |
|---|---|
| Versión | 0.7 |
| Fecha | 16 de julio de 2026 |
| Estado | Objetivo 1.1 implementado y verificado |
| Plantilla de entrada | Excel v1.1 congelada |
| Ejecución actual | Local, sin conexiones externas |

## 1. Relación con la versión 0.6

La versión 0.7 conserva la arquitectura objetivo, normativa, Plantilla Excel v1.1 y ruta AWS definidas en la [versión 0.6](plan_tecnico_agente_jira_v0.6.md). Esta revisión consolida los ajustes derivados de la primera validación de aceptación realizada por el usuario sobre la aplicación local.

Los cambios de esta versión se concentran en cuatro problemas observados:

1. Corregir un responsable no retiraba automáticamente la actividad de `Revisar`.
2. La aplicación mostraba sólo el primer conflicto y no todos los pendientes.
3. El historial de propuestas no podía contraerse, buscarse ni depurarse visualmente.
4. El login local no explicaba el tratamiento futuro de una contraseña olvidada.

## 2. Principio de decisión derivada

`Incluir`, `Revisar` y `Excluir` dejan de tratarse como un dato técnico que el usuario debe manipular durante una corrección. Son el resultado de volver a evaluar la actividad.

```text
Corrección del usuario
        ↓
Guardar y volver a validar
        ↓
Evaluar todos los pendientes
        ├── quedan pendientes → Revisar
        ├── no quedan pendientes → Incluir
        └── origen completado/rechazado → Excluir
```

Cada guardado conserva el mismo `proposal_id`, incrementa `version` y mantiene sin cambios la fuente y su hash.

## 3. Pendientes accionables

La validación contiene `pending_requirements`, una lista de objetos con:

| Campo | Propósito |
|---|---|
| `code` | Identificador estable de la regla |
| `field` | Campo o confirmación que resuelve el pendiente |
| `message` | Instrucción comprensible para el usuario |

Reglas implementadas:

| Código | Condición | Resolución |
|---|---|---|
| `ASSIGNEE_UNRESOLVED` | Responsable ambiguo, inexistente o inactivo | Seleccionar una persona activa del catálogo |
| `SOURCE_STATE_UNCONFIRMED` | Estado de origen `Por confirmar` | Confirmar que la actividad sigue vigente |
| `WORK_TYPE_UNCONFIRMED` | Confianza de clasificación menor a 0.8 | Confirmar el Work Type |
| `SUBTASK_PARENT_MISSING` | Subtask sin parent | Cambiar Work Type o definir una actividad padre en una evolución posterior |

La aplicación reúne todos los pendientes en una sola evaluación. Resolver sólo uno conserva la actividad en `Revisar` y muestra los restantes.

## 4. Flujo de corrección v0.7

1. El usuario abre una actividad en `Requieren revisión`.
2. La interfaz muestra origen, propuesta y todos los pendientes.
3. Cada pendiente cambia visualmente a resuelto conforme se completa su dato.
4. El botón permanece deshabilitado mientras falte un requisito conocido.
5. El usuario selecciona `Guardar y volver a validar`.
6. El backend recalcula la decisión y crea una versión nueva.
7. Si no quedan pendientes, la interfaz abre `Listas` y muestra una confirmación explícita.

Ejemplo de confirmación:

```text
Versión 2 guardada. Se resolvieron todos los pendientes y la actividad pasó a Listas.
```

## 5. Historial de propuestas

### 5.1 Navegación

- Barra lateral alineada con el borde izquierdo.
- Alternancia expandida/compacta desde el encabezado.
- Atajo `Ctrl+B`.
- Preferencia conservada en `localStorage`.
- Sin desbordamiento horizontal en el viewport de escritorio validado.

### 5.2 Búsqueda y filtros

La búsqueda local considera nombre de archivo, Space e identificador de propuesta. Los filtros disponibles son:

- Activas.
- Con pendientes.
- Sin pendientes.
- Archivadas.

### 5.3 Archivado reversible

El MVP no elimina físicamente propuestas. `Archivar` retira la propuesta de la vista principal y `Restaurar` la recupera. El estado se guarda en `proposal_lifecycle`, separado de `proposal_versions`, por lo que archivar no altera el archivo fuente ni fabrica una versión de contenido.

La eliminación definitiva se reserva para una fase con roles, política de retención y auditoría productiva.

## 6. Login y recuperación de contraseña

El proveedor local incorpora mostrar/ocultar contraseña y explica que la recuperación se habilitará con Cognito. No se implementó una recuperación ficticia o insegura.

La recuperación real pertenece al Objetivo 2A e incluirá el mecanismo institucional configurado en Amazon Cognito.

## 7. Cambios de API y persistencia

| Operación | Uso |
|---|---|
| `PATCH /api/proposals/{id}/items/{row}` | Corrige y vuelve a validar la actividad |
| `POST /api/proposals/{id}/archive` | Archiva de forma reversible |
| `POST /api/proposals/{id}/restore` | Restaura una propuesta archivada |
| `GET /api/proposals` | Devuelve resumen, conteos y estado de archivado |

El backend hidrata propuestas creadas antes de la versión 0.7 para calcular sus pendientes cuando se abren, sin modificar silenciosamente las versiones almacenadas.

## 8. Seguridad y límites

- No hay clientes AWS, GCP o Atlassian.
- No existe escritura Jira.
- No se introdujeron secretos productivos.
- El catálogo de responsables continúa siendo ficticio.
- El token local se conserva sólo en memoria del backend.
- Las propuestas y versiones se almacenan localmente en SQLite.
- El endpoint de salud continúa reportando `external_connections: false`.

## 9. Verificación del Objetivo 1.1

Estado: **cumplido y verificado**.

Resultados:

- 20 pruebas de backend aprobadas.
- 5 pruebas de frontend aprobadas.
- Compilación TypeScript y Vite aprobada.
- Flujo interactivo validado con dos pendientes simultáneos.
- Transición comprobada de 3 listas/1 revisión a 4 listas/0 revisiones.
- Versión incrementada de 1 a 2.
- Barra expandida y compacta inspeccionadas visualmente.
- Desbordamiento horizontal detectado durante la inspección y corregido.

La evidencia reproducible se encuentra en [evidencia_objetivo_1_1.md](evidencia_objetivo_1_1.md).

## 10. Siguiente etapa

Después de una segunda validación de aceptación por parte del usuario, la siguiente conversación de planeación corresponde al Objetivo 2A:

> Desplegar una base no productiva en AWS con identidad, almacenamiento y observabilidad, manteniendo deshabilitados los modelos externos y cualquier acceso a Jira.

Antes de activarlo se confirmarán cuenta y región AWS, acceso mediante rol o SSO, límites iniciales de costo y restricciones de red.
