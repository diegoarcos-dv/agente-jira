# Guía de validación · Objetivo 4E

## Preparación

1. Detén el servidor actual con `Ctrl+C`.
2. Ejecuta `scripts\start-objective-4e.cmd`.
3. Abre la aplicación, inicia sesión y conecta Atlassian.
4. Confirma que el diagnóstico indique `READY_FOR_CONTROLLED_HIERARCHY_BATCH` y muestre los cinco Work Types de AT.

## Prueba recomendada de menor costo

Usa una propuesta de cuatro actividades sin Sprint, para evitar consultas adicionales:

| Orden lógico | Work Type | Padre |
|---|---|---|
| 1 | Epic | Sin padre |
| 2 | Story | La Epic |
| 3 | Task | Sin padre |
| 4 | Subtask | La Task |

En “Origen y propuesta”, guarda cada relación con `Guardar y volver a validar`. Después aprueba y repite la prevalidación.

## Ejecución

1. Selecciona las cuatro actividades. La interfaz puede agregar automáticamente al padre cuando eliges al hijo.
2. Pulsa `Preparar lote`.
3. Verifica que cada padre aparezca antes que su hijo.
4. Escribe la frase exacta `CREAR 4 ACTIVIDADES EN AT`.
5. Confirma y pulsa la creación real.

Resultado esperado:

- cuatro actividades `CREATED VERIFIED`;
- ocho llamadas MCP: una creación y una lectura por actividad;
- cero reintentos;
- la Story muestra la clave de la Epic como padre verificado;
- la Subtask muestra la clave de la Task como padre verificado;
- Jira presenta ambas relaciones correctamente.

## Prueba de lotes sucesivos

Para reducir el riesgo, también puedes crear primero sólo la Epic. Cuando quede verificada, prepara un segundo lote únicamente con su Story. La vista previa debe mostrar la clave Jira del padre ya conocida.

## Detención segura

Si Jira rechaza `parent`, la lectura no devuelve la relación o la clave no coincide, no vuelvas a enviar el lote automáticamente. Descarga la evidencia y comparte el mensaje exacto; las actividades posteriores quedarán `NOT_ATTEMPTED`.
