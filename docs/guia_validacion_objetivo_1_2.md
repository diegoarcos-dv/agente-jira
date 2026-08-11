# Guía de validación del Objetivo 1.2

## 1. Iniciar la aplicación

Detén con `Ctrl+C` cualquier instancia anterior y, desde la raíz del proyecto, ejecuta:

```powershell
scripts\start.cmd
```

Abre `http://localhost:8000` e inicia sesión:

```text
Usuario: admin@agentejira.local
Contraseña: AgenteJira2026!
```

## 2. Crear una propuesta de prueba

Carga `examples\plan_timeline_referencia_v1_1_valido.xlsx`, selecciona Space `AT` y genera la propuesta.

Resultado inicial esperado:

- 3 listas;
- 1 requiere revisión;
- 1 excluida.

## 3. Cambiar el nombre operativo

1. Selecciona `Editar nombre`.
2. Escribe un nombre reconocible, por ejemplo `Validación AT - julio`.
3. Guarda el cambio.
4. Comprueba el nuevo nombre en el encabezado y el historial.
5. Confirma que `Archivo fuente inmutable` siga mostrando el nombre original del Excel.

El cambio de nombre no debe incrementar la versión.

## 4. Recuperar una actividad excluida

1. Abre la pestaña `Excluidas`.
2. Selecciona una actividad completada.
3. Escribe un motivo real de recuperación.
4. Selecciona `Reactivar y revisar`.

Resultado esperado:

- se crea una versión nueva;
- la actividad se mueve a `Requieren revisión`;
- la fuente continúa indicando su estado original;
- se muestra el motivo y la auditoría de reactivación.

Abre esa actividad, confirma que revisaste la reactivación y selecciona `Guardar y volver a validar`. Debe pasar a `Listas` si no quedan otros pendientes en ella.

## 5. Resolver los demás pendientes

En la actividad de anonimización:

1. selecciona un responsable activo;
2. confirma su vigencia si se solicita;
3. guarda y vuelve a validar.

Cuando el contador `Requieren revisión` llegue a cero debe aparecer el panel `Lista para aprobación`.

## 6. Aprobar y descargar

1. Selecciona `Revisar y aprobar propuesta final`.
2. Revisa conteos, fuente y SHA-256.
3. Confirma que entiendes que todavía no se escribirá en Jira.
4. Selecciona `Aprobar y bloquear versión`.
5. Comprueba el sello `Propuesta aprobada` y la ausencia de edición.
6. Selecciona `Descargar JSON aprobado` y abre el archivo.

El JSON debe contener el nombre operativo y una propuesta con estado `APPROVED`.

## 7. Validar bloqueo y reapertura

Selecciona `Reabrir para editar`.

Resultado esperado:

- se crea otra versión;
- vuelve el panel `Lista para aprobación`;
- la versión aprobada anterior permanece almacenada;
- la nueva versión puede editarse y aprobarse de nuevo.

## 8. Validar una restricción

Como control adicional, intenta aprobar una propuesta que aún tenga actividades en `Requieren revisión`. La aplicación debe impedirlo con un mensaje y no crear una versión aprobada.

## 9. Reportar observaciones

Indica pantalla, acción, resultado observado, resultado esperado y captura cuando ayude. Esta prueba es totalmente local: no realiza conexiones ni escrituras en Jira, AWS o GCP.
