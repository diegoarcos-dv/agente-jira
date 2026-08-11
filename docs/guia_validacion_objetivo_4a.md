# Guía de validación — Objetivo 4A

Esta validación es segura: todo el recorrido termina en una simulación local y no escribe en Jira.

## Preparación

1. Cierra cualquier instancia anterior de la aplicación.
2. Desde la raíz del proyecto ejecuta:

   ```powershell
   scripts\start.cmd
   ```

3. Abre `http://localhost:8000`.
4. Inicia sesión con tu usuario local.
5. Confirma que la cabecera indique que Jira está en sólo lectura.
6. Conecta Atlassian si la autorización no se restauró automáticamente.

## Condiciones de entrada

Usa una propuesta que cumpla todo lo siguiente:

- está aprobada;
- su Dry run corresponde a la versión actual;
- el Dry run tiene cero actividades bloqueadas;
- contiene al menos una actividad del Space `AT` y Work Type `Task`.

Si no se cumplen estas condiciones, el panel 4A no se habilita. Corrige o prevalida la propuesta antes de continuar.

## Recorrido esperado

1. En la propuesta aprobada localiza **Objetivo 4A — Simulación segura**.
2. Selecciona una actividad elegible.
3. Pulsa **Preparar simulación**.
4. Verifica la vista previa:
   - Space `AT`;
   - tipo `Task`;
   - título con prefijo `AgenteTest_Task_`;
   - responsable esperado;
   - aviso de que el payload todavía es candidato;
   - sello `0 escrituras Jira`.
5. Marca la confirmación de que revisaste la vista previa.
6. Pulsa **Confirmar vista previa**.
7. Pulsa **Ejecutar simulación segura**.
8. Verifica el resultado **Lista para evaluar el Objetivo 4B**.
9. Descarga la evidencia JSON.

## Evidencia que debes revisar

El archivo descargado debe contener:

```json
{
  "objective": "4A",
  "mode": "SIMULATION_ONLY",
  "real_mcp_calls": 0,
  "write_performed": false,
  "jira_issue_created": false
}
```

También debe incluir el historial de estados y el hash confirmado, pero nunca tokens OAuth, cookies, contraseñas ni cabeceras de autorización.

## Casos negativos recomendados

- Deja vencer la confirmación: debe pasar a `EXPIRED` y exigir preparar otra simulación.
- Modifica la propuesta o genera otro Dry run: la intención anterior debe invalidarse.
- Intenta utilizar Bug, Story, Epic, Subtask o un Space distinto de AT: la preparación debe rechazarse.
- Cancela una intención preparada: no debe poder simularse sin volver a preparar.

## Criterio de aprobación manual

El Objetivo 4A queda validado por el usuario cuando:

- completa el recorrido sin errores;
- la evidencia reporta cero llamadas MCP y cero escrituras;
- no aparece ninguna actividad nueva en Jira;
- el flujo y la vista previa son comprensibles.

Sólo después de esta validación conviene preparar el Objetivo 4B para una única Task real y controlada.
