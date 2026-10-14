# Plantilla Excel v1.1 congelada

Esta carpeta contiene la versión canónica y congelada del contrato de entrada Excel para el Objetivo 1 del Agente Jira.

## Artefactos

- `plantilla_plan_trabajo_jira_v1_1.xlsx`: archivo canónico.
- `manifest.json`: estructura, reglas y huella de integridad.

## Regla de integridad

La huella SHA-256 del archivo canónico es:

```text
b7acbbfa54a412688d73ebcc2eb9e87447c35bb1dc247cf8e11c47efb5e69dda
```

La huella identifica la plantilla vacía canónica. Los archivos llenados por los usuarios tendrán una huella diferente y se validarán mediante versión, hoja, encabezados, tipos y reglas.

Corrección compatible del 17 de agosto de 2026: las definiciones internas de las tablas se alinearon con el encabezado `Frente_de_trabajo_o_Proyecto` para evitar que Microsoft Excel solicite reparar el libro. El contrato, los datos, las validaciones y el formato de la versión 1.1 no cambiaron.

## Política de cambio

- La v1.1 no debe sobrescribirse con cambios incompatibles.
- Cualquier columna nueva, cambio de encabezado, obligatoriedad, semántica o validación incompatible requiere una versión posterior, comenzando por v1.2.
- Las reglas completas se encuentran en `manifest.json` y en `docs/plan_tecnico_agente_jira_v0.6.md`.

## Alcance

La plantilla oficial captura intención de trabajo. No contiene identificadores técnicos de Jira, columnas del Gantt ni configuraciones repetidas por actividad.

El timeline `TIMELINE IA 150726 V.2.xlsx` es una referencia y un caso de prueba; no sustituye este contrato.
