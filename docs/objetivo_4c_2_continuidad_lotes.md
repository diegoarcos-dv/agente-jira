# Objetivo 4C.2: continuidad segura entre lotes

Versión de la aplicación: 0.18.0  
Estado: implementado y verificado con dobles locales; no requirió escrituras adicionales en Jira.

## Propósito

Permitir que un plan con más de cinco Tasks avance mediante lotes sucesivos, sin aumentar el límite ni relajar las garantías de 4C.1.

## Reglas

- Cada lote conserva el máximo de cinco Tasks `AT / Task`.
- Cada lote requiere su propia vista previa y frase de confirmación dinámica.
- Cada Task mantiene creación y lectura posterior; no se elimina la verificación para ahorrar créditos.
- El avance entre lotes se calcula exclusivamente con SQLite y la evidencia ya persistida: cero llamadas MCP adicionales.
- Una Task `CREATED_VERIFIED`, `CREATED_UNVERIFIED`, `REJECTED`, `UNKNOWN`, `PENDING` o `SUBMITTED` no vuelve a ofrecerse en la misma versión.
- Una Task `NOT_ATTEMPTED` continúa disponible porque nunca se invocó su creación.
- Un lote idéntico se recupera por idempotencia; un lote solapado se rechaza.

## Experiencia de usuario

Después del resultado consolidado, si quedan actividades disponibles aparece **Preparar siguiente lote**. La pantalla muestra:

- cantidad total verificada;
- cantidad todavía pendiente;
- número de lotes registrados;
- las siguientes cinco Tasks seleccionadas de forma predeterminada.

Cuando ya no quedan Tasks disponibles, la acción cambia a **Generar nueva propuesta**.

## Consumo

4C.2 no agrega consultas a Rovo para calcular el avance. Una ejecución real mantiene dos llamadas MCP por Task: una creación y una lectura. Reducir ese número impediría demostrar que Jira guardó los campos esperados y no se considera una optimización segura.

## Fuera de alcance

- más de cinco Tasks dentro de una confirmación;
- ejecución paralela;
- otros Work Types;
- ASIT o MTTI;
- reintentos o rollback automáticos.
