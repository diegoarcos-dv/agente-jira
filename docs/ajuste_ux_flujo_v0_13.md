# Ajuste de experiencia y flujo — v0.13

## Propósito

Reducir la saturación de la pantalla principal y presentar el proceso con términos orientados al usuario, sin exponer nombres de objetivos internos ni detalles técnicos como parte del recorrido cotidiano.

## Cambios aplicados

### Navegación

- `Nueva propuesta` y `Configuración Jira` viven en la barra lateral.
- La configuración abre una vista independiente con conexión, desconexión y diagnóstico.
- La carga del Excel sólo se muestra cuando no hay una propuesta abierta.
- El historial permanece intacto al iniciar una nueva propuesta.
- En pantallas pequeñas existen accesos equivalentes en la barra superior.

### Orientación del usuario

La propuesta muestra tres pasos:

1. Revisar actividades.
2. Validar con Jira.
3. Probar el envío.

El paso actual queda destacado visualmente. La prueba segura se abre como la siguiente acción cuando la propuesta está aprobada y la validación no tiene bloqueos.

### Secciones plegables

- Resultado de la validación con Jira.
- Actividades de la propuesta.
- Prueba segura antes del envío.
- Detalles técnicos y huella.

Los detalles técnicos permanecen disponibles, pero no compiten con la información necesaria para decidir.

### Lenguaje

En la interfaz se retiraron los términos `Objetivo`, `canario`, `payload` y `Dry run` de las acciones principales. Se sustituyeron por expresiones como `prueba segura`, `actividad de prueba`, `detalles técnicos` y `validación con Jira`.

### Vista previa

- El usuario ve título, destino, responsable, vigencia y campos adicionales.
- Los `customfield_*` se traducen con los nombres recibidos de los metadatos Jira.
- Si un ID no tiene nombre disponible, aparece como dato técnico secundario.
- El JSON completo y la huella SHA-256 siguen disponibles dentro de una sección plegada.

### Responsables

El catálogo de demostración dejó de mostrarse en el editor. Las opciones visibles provienen de una búsqueda real en Jira mediante Rovo MCP. La búsqueda por nombre o correo es intencional: evita descargar o exponer un directorio completo y permite elegir una identidad verificable.

### Cierre del flujo

Después de completar la prueba segura aparece `Generar nueva propuesta`. La acción limpia la selección y regresa a la carga del Excel; no elimina, archiva ni modifica propuestas previas.

## Seguridad conservada

- Jira continúa en modo de sólo lectura.
- La prueba utiliza el simulador local.
- No se habilitó `createJiraIssue`.
- La reorganización no modifica la política `PLANNING_ONLY` ni el kill switch.
