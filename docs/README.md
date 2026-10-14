# Documentación del proyecto Agente Jira

## Contratos actuales

- Plantilla operativa: [`../releases/plantilla_excel_v1_2/plantilla_plan_trabajo_jira_v1_2.xlsx`](../releases/plantilla_excel_v1_2/plantilla_plan_trabajo_jira_v1_2.xlsx).
- Endpoint de plantilla dinámica: `GET /api/template/v1.2`.
- La v1.2 conserva compatibilidad de lectura con v1.1 y publica el catálogo Jira vigente cuando está disponible.
- Esquema de propuesta: [`schemas/jira_proposal_v1_1.schema.json`](schemas/jira_proposal_v1_1.schema.json).
- Política segura por defecto: [`../config/jira_execution_policy_v1.json`](../config/jira_execution_policy_v1.json).

## Evidencia de Gates

- [GATE A — Arranque robusto](gate_a_arranque_robusto.md)
- [GATE B — Conectividad](gate_b_conectividad.md)
- [GATE C — Write Lock](gate_c_write_lock.md)
- [GATE D — Baseline y validación Jira](gate_d_baseline.md)
- [GATE E — Voz bajo demanda](gate_e_validation.md)
- [GATE F — Release readiness](gate_f_release_readiness.md)

Los documentos `objetivo_*`, `plan_tecnico_*`, `evidencia_*` y `guia_validacion_*` anteriores se conservan como historial y evidencia de compatibilidad. No deben interpretarse como una descripción más reciente que los documentos `gate_*` ni que el README raíz.

## Guías operativas

- [Objetivo 4B — escritura controlada](objetivo_4b_escritura_controlada.md)
- [Objetivo 4B.2 — resolución de Sprint](objetivo_4b_2_resolucion_sprint.md)
- [Objetivo 4C.1 — lote de Tasks](objetivo_4c_1_lote_tasks_at.md)
- [Objetivo 4D — Bug y Story](objetivo_4d_bug_story.md)
- [Objetivo 4E — jerarquías](objetivo_4e_jerarquias.md)
- [Despliegue Linux con voz](DESPLIEGUE_LINUX_VOZ.md)

Para instalación, configuración, diagnóstico y troubleshooting, la fuente operativa es el [README raíz](../README.md).
