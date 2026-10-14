# Minutes Semantic Intelligence v1

`MINUTES_LLM_MODEL` selecciona el modelo local para la comprensión semántica;
el valor predeterminado es `qwen3.5:4b`. El prompt versionado es
`minutes_semantic_v1`.

El flujo conserva el parser de secciones/listas explícitas y suma candidatos de
lenguaje natural cuando no hay una lista estructurada. La respuesta del modelo
debe cumplir un esquema JSON estricto, contener evidencia literal y no puede
aportar IDs Jira. Si Ollama no responde, el extractor de reglas sigue creando
el preview seguro; ninguna de estas fases crea incidencias Jira.

Las fechas numéricas se interpretan con la convención México `DD/MM/YYYY`:
`09/10/2026` equivale a `2026-10-09`. Fechas relativas (`mañana`, `viernes`,
`fin de mes`) se calculan desde la fecha real del análisis. Los responsables se
resuelven después con la lógica Jira existente; colaboradores se conservan sólo
en contexto local y no se convierten en asignados ni campos personalizados.
