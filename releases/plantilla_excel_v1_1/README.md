# Plantilla Excel v1.1 congelada

Esta carpeta contiene la versión canónica y congelada del contrato de entrada Excel para el Objetivo 1 del Agente Jira.

## Artefactos

- `plantilla_plan_trabajo_jira_v1_1.xlsx`: archivo canónico.
- `manifest.json`: estructura, reglas y huella de integridad.

## Regla de integridad

La huella SHA-256 del archivo canónico es:

```text
9a4b913d55a27afdbee04efbc011ed134b394190eeaf968e94b2150b010f4204
```

La huella identifica la plantilla vacía canónica. Los archivos llenados por los usuarios tendrán una huella diferente y se validarán mediante versión, hoja, encabezados, tipos y reglas.

## Política de cambio

- La v1.1 no debe sobrescribirse con cambios incompatibles.
- Cualquier columna nueva, cambio de encabezado, obligatoriedad, semántica o validación incompatible requiere una versión posterior, comenzando por v1.2.
- Las reglas completas se encuentran en `manifest.json` y en `docs/plan_tecnico_agente_jira_v0.6.md`.

## Alcance

La plantilla oficial captura intención de trabajo. No contiene identificadores técnicos de Jira, columnas del Gantt ni configuraciones repetidas por actividad.

El timeline `TIMELINE IA 150726 V.2.xlsx` es una referencia y un caso de prueba; no sustituye este contrato.
