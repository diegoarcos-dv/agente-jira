# Ajuste de datos finales y valores generales v0.14

## Resultado

La propuesta ahora separa de forma explicita dos capas:

- **Origen inmutable:** conserva exactamente el responsable y los datos leidos del Excel.
- **Propuesta final:** contiene los valores corregidos por el usuario y verificados contra Jira.

El responsable de la propuesta final es la fuente usada por la interfaz, la prevalidacion y los payloads candidatos. El valor original solo se muestra como evidencia de trazabilidad.

## Edicion de valores generales

La accion `Editar valores` esta disponible durante la revision, despues de la aprobacion y durante la validacion tecnica. Guardar produce una version nueva y aplica a todas las actividades:

- Space
- Iniciativa
- Linea de trabajo
- Sprint
- Tipo de seguimiento
- Semaforo

No se modifica el archivo Excel ni una version historica. Si la propuesta estaba aprobada, la nueva version queda editable, se retira su aprobacion y el usuario debe repetir la aprobacion y la prevalidacion con Jira.

## Catalogos procedentes de Jira

Los metadatos leidos mediante Rovo MCP incluyen, cuando Jira los publica, las opciones permitidas de los campos de negocio. La aplicacion une y elimina duplicados entre los Work Types del Space elegido y presenta las opciones con nombres legibles.

No se mantienen catalogos paralelos en codigo. La fecha `verified_at` de la conexion identifica la vigencia de la fotografia utilizada y `Actualizar diagnostico` renueva los metadatos.

### Caso sin catalogo

Jira no siempre publica `allowedValues` para todos los campos. Sprint es un caso frecuente porque puede depender de tableros y de Jira Software Agile, no solo de la metadata de creacion de una actividad. En ese caso:

1. La interfaz avisa que Jira no publico un catalogo.
2. Se permite captura manual para no bloquear el MVP.
3. La prevalidacion usa el metadato vigente disponible antes de avanzar.
4. Si se requiere un catalogo completo de Sprint en una evolucion, se agrega una lectura especializada autorizada sin cambiar el contrato de la propuesta.

## Control contra desactualizacion

Cuando Jira entrega una lista de opciones y el valor guardado ya no pertenece a ella, la prevalidacion genera `FIELD_VALUE_NOT_ALLOWED` y bloquea esa actividad. El usuario debe editar los valores generales y seleccionar una opcion vigente.

## Seguridad y escritura

Este ajuste usa exclusivamente metadatos Jira de lectura. `jira_write_enabled` permanece en `false`; no crea ni modifica actividades.
