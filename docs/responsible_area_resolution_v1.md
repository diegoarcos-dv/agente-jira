# Responsible → Area Resolution v1

La fuente de verdad para `responsable → área` es la tabla local persistente
`responsible_area_map` de la base de datos de Agente Jira:

| Columna | Uso |
| --- | --- |
| `account_id` | Identidad Jira verificada mediante consulta de sólo lectura. |
| `area_id` / `area_display_name` | Identidad y etiqueta local del área. |
| `active`, `source`, `updated_at` | Mantenimiento y trazabilidad del catálogo. |

No existe en el MCP/Jira usado por la aplicación una relación fiable de persona
a área. Los Spaces/proyectos, componentes, roles e historial de incidencias no
se tratan como esa relación.

Después de resolver un `account_id` Jira, el resultado por fila es:

- 0 mapeos: no se asigna área (`UNRESOLVED`). La selección manual permanece
  disponible y el campo conserva su obligatoriedad actual.
- 1 mapeo: se asigna automáticamente (`SINGLE_MAPPING`).
- 2+ mapeos: se muestran sólo esas opciones; no se elige una sin evidencia.
  Una mención literal de área en la minuta permite `TEXT_CONFIRMED` únicamente
  si coincide con el catálogo del responsable.

Una selección humana compatible se conserva como `USER_SELECTED`. Al cambiar
el responsable, se recalcula el conjunto: un área incompatible se limpia y la
fila vuelve a revisión. Las áreas se cachean por `account_id` durante la vida
del proceso. Ninguna operación escribe usuarios, Teams, grupos, componentes,
proyectos ni issues de Jira.

El catálogo se mantiene localmente mediante las rutas administrativas
`GET`/`PUT /api/admin/responsible-area-map/{account_id}`. El `PUT` recibe una
lista de `{ "area_id", "label" }`, actualiza sólo SQLite e invalida la caché de
esa cuenta. Los identificadores no se muestran en la vista previa normal.
