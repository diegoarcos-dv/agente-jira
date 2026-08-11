# Guía de validación del Objetivo 1.1

## 1. Reiniciar la aplicación actualizada

Si todavía tienes abierta una instancia anterior, detén su terminal con `Ctrl+C`. Después ejecuta desde la raíz:

```powershell
scripts\start.cmd
```

Abre `http://localhost:8000`.

Credenciales locales:

```text
Usuario: admin@agentejira.local
Contraseña: AgenteJira2026!
```

## 2. Generar el caso de prueba

Carga:

```text
examples\plan_timeline_referencia_v1_1_valido.xlsx
```

Selecciona Space `AT` y genera la propuesta.

Resultado inicial esperado:

- 3 listas.
- 1 requiere revisión.
- 1 excluida.

## 3. Validar el nuevo flujo de pendientes

1. Abre `Requieren revisión`.
2. Selecciona la actividad `Definir estrategia de anonimización de datos sensibles`.
3. Comprueba que aparezcan dos pendientes.
4. Selecciona un responsable del catálogo.
5. Confirma que la actividad sigue vigente.
6. Verifica que ambos pendientes aparezcan resueltos.
7. Selecciona `Guardar y volver a validar`.

Resultado esperado:

- la propuesta cambia a versión 2;
- la actividad aparece en `Listas`;
- los conteos cambian a 4 listas y 0 por revisar;
- aparece un mensaje confirmando la transición;
- no existe un selector manual de decisión.

## 4. Validar la barra lateral

1. Selecciona el botón superior `Alternar barra lateral`.
2. Comprueba que el historial quede compacto.
3. Vuelve a expandirlo.
4. Prueba también `Ctrl+B`.
5. Escribe parte del nombre del archivo en `Buscar propuesta`.
6. Prueba los filtros disponibles.

## 5. Validar archivado y restauración

1. Selecciona la acción `Archivar` de una propuesta de prueba.
2. Confirma la operación.
3. Comprueba que desaparezca de `Activas`.
4. Selecciona el filtro `Archivadas`.
5. Restaura la propuesta.
6. Comprueba que vuelva a `Activas` con sus versiones intactas.

## 6. Validar login

- Comprueba `Mostrar contraseña` y `Ocultar contraseña`.
- Verifica que la pantalla informe que la recuperación real se habilitará con Cognito.
- No se espera todavía un envío de correo o código de recuperación.

## 7. Reportar observaciones

Para cada hallazgo indica:

- pantalla o actividad;
- acción realizada;
- resultado observado;
- resultado que esperabas;
- captura de pantalla, si ayuda a explicarlo.

Esta validación no realiza conexiones ni escrituras en Jira.
