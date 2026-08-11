# Guía de validación manual — Objetivo 4D

La primera prueba real recomendada contiene exactamente **un Bug y una Story**. Task ya fue validado mediante AT-507, AT-508, AT-509 y AT-510.

## Preparación

1. Detén el servidor actual con `Ctrl+C`.
2. Ejecuta:

   ```powershell
   scripts\start-objective-4d.cmd
   ```

3. Abre una propuesta aprobada con Dry run vigente y cero bloqueos.
4. Confirma que existan al menos una actividad Bug y una Story listas.

## Prueba

1. Selecciona únicamente el Bug y la Story.
2. Pulsa **Preparar lote de 2 actividades**.
3. Revisa que cada fila muestre su Work Type correcto, responsable y Sprint.
4. Confirma que los títulos técnicos comiencen con `AgenteTest_Bug_` y `AgenteTest_Story_` en el detalle.
5. Escribe `CREAR 2 ACTIVIDADES EN AT`.
6. Pulsa **Confirmar lote real**.
7. Pulsa **Crear 2 actividades reales en AT** una sola vez.

## Resultado esperado

- dos actividades creadas y verificadas;
- una clave Jira para el Bug y otra para la Story;
- cuatro llamadas MCP;
- cero reintentos;
- lectura posterior con `issue_key`, título, Space, Work Type, responsable y Sprint aprobados.

Abre ambas claves en Jira y confirma visualmente que una sea Bug y la otra Story.

Si el lote se detiene, no lo repitas automáticamente. Descarga la evidencia y aplica el procedimiento de conciliación de 4C.1.

Después de la prueba vuelve al modo seguro mediante:

```powershell
scripts\start.cmd
```
