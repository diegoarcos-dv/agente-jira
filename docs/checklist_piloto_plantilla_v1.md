# Checklist del piloto de la plantilla simplificada v1

## Objetivo

Validar que la plantilla reduce trabajo real frente a capturar directamente en Jira, sin perder la información mínima necesaria para producir una propuesta confiable.

## Preparación

- [ ] Seleccionar entre 3 y 5 participantes que normalmente preparen o registren planes.
- [ ] Usar planes reales o copias anonimizadas de entre 10 y 40 actividades.
- [ ] Incluir al menos un plan de AT; si es posible, uno de ASIT y uno de MTTI sin ejecutar escritura.
- [ ] Entregar únicamente el archivo y una instrucción breve; no explicar cada columna de forma verbal.
- [ ] Registrar experiencia previa del participante con Jira.
- [ ] Medir por separado preparación de Excel, revisión de propuesta y correcciones.

## Prueba de captura

- [ ] El participante identifica sin ayuda los dos campos obligatorios.
- [ ] Captura una actividad por fila.
- [ ] Usa Grupo_o_Modulo sólo cuando aporta organización.
- [ ] Añade contexto, fecha, estado o comentarios sólo si existen.
- [ ] No busca ni captura IDs técnicos de Jira.
- [ ] No repite Space, sprint o iniciativa en cada fila.
- [ ] Indica qué campo le genera duda y por qué.

## Prueba de propuesta

- [ ] El Space se selecciona una sola vez.
- [ ] Los valores generales se aplican al plan completo.
- [ ] La aplicación genera título y descripción comprensibles.
- [ ] Las filas completadas o rechazadas aparecen excluidas.
- [ ] Los responsables ambiguos aparecen en revisión.
- [ ] La clasificación Epic/Story/Task/Bug/Subtask resulta razonable.
- [ ] El usuario puede comparar origen y propuesta.
- [ ] El usuario entiende por qué cada fila está incluida, excluida o en revisión.
- [ ] No se ofrece escritura en Jira antes de aprobar.

## Datos a registrar

| Métrica | Registro |
|---|---|
| Número de actividades | |
| Minutos de captura en plantilla | |
| Minutos estimados o medidos en Jira | |
| Filas listas sin intervención | |
| Filas con revisión | |
| Filas excluidas correctamente | |
| Títulos corregidos | |
| Descripciones corregidas | |
| Work Types corregidos | |
| Responsables no resueltos | |
| Campos que el usuario pidió agregar | |
| Campos que el usuario consideró innecesarios | |

## Preguntas de cierre

1. ¿Qué parte fue más rápida que trabajar directamente en Jira?
2. ¿Qué información tuviste que buscar fuera del plan?
3. ¿Qué campo no supiste cómo llenar?
4. ¿Qué corrección repetiste varias veces en la propuesta?
5. ¿Confiarías en aprobar la propuesta si se resolvieran las dudas mostradas?
6. ¿Qué haría que prefirieras Jira directamente?

## Criterios para aceptar la plantilla v1

- [ ] La mayoría de los participantes completa el archivo sin acompañamiento continuo.
- [ ] El tiempo total de captura y revisión es menor que la alternativa manual.
- [ ] Actividad y Responsable son suficientes como mínimos para iniciar la propuesta.
- [ ] Al menos 80 % de las filas no requiere pregunta individual, o se identifica una regla concreta para acercarse a esa meta.
- [ ] No se detecta una columna adicional que deba ser obligatoria para todos los planes.
- [ ] Las dudas restantes pueden resolverse en la aplicación.

## Regla de decisión

No agregar una columna obligatoria por un caso aislado. Primero evaluar, en este orden: valor general del plan, inferencia con evidencia, catálogo de configuración, pregunta por excepción y, sólo si aplica a casi todos los planes, nueva columna.
