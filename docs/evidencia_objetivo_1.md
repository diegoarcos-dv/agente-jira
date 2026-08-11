# Evidencia de cumplimiento - Objetivo 1

Fecha de verificación: 2026-07-16.

## Resultado

La aplicación local implementa el flujo Plantilla Excel v1.1 → validación → normalización → catálogo ficticio → propuesta versionada → revisión y corrección. No existe conexión ni escritura hacia AWS, GCP, modelos externos, Atlassian o Jira.

## Matriz de criterios

| Criterio | Evidencia |
|---|---|
| React y FastAPI ejecutables | `frontend/dist/index.html`, endpoint `/api/health` y prueba HTTP integrada con respuesta 200 |
| Login de desarrollo reemplazable | `backend/app/auth.py`: contrato `AuthProvider` e implementación `LocalAuthProvider`; pantalla React de acceso |
| Plantilla v1.1 validada | `backend/app/parser.py`; caso válido `examples/plan_timeline_referencia_v1_1_valido.xlsx` |
| Rechazo de versión, hoja y encabezados | Pruebas `INVALID_TEMPLATE_VERSION`, `MISSING_SHEET` e `INVALID_HEADER` |
| Sólo Actividad y Responsable obligatorios | Parser y pruebas de filas válidas con campos opcionales vacíos |
| Agrupación normalizada | `frente_trabajo_origen` se conserva en `source`, descripción y comparación visual |
| Catálogo ficticio | `backend/app/catalog.py`; endpoint `/api/assignees`; selección explícita durante revisión |
| JSON conforme al esquema v1.1 | `examples/propuesta_timeline_referencia_v1_1.json`, validado por `ProposalSchemaValidator` |
| Título, descripción, Work Type, responsable, fecha, decisión y origen | Servicio `ProposalService` y JSON de evidencia |
| Vistas Listas, Revisión y Excluidas | Componente `ProposalReview` y prueba React de navegación entre las tres vistas |
| Origen frente a propuesta | Tabla principal y panel lateral; prueba React verifica ambos textos |
| Corrección versionada | SQLite conserva versiones; prueba de servicio y prueba HTTP crean versión 2 sin modificar `source` ni su hash |
| Timeline como caso de prueba | Excel válido derivado de actividades de la hoja Transcripción y Análisis |
| Pruebas automatizadas | 17 pruebas Python y 2 pruebas React |
| Sin conexiones externas | Búsqueda estática del código, endpoint `external_connections: false` y ausencia de clientes externos |

## Cadena final ejecutada

```text
17 pruebas backend: aprobadas
2 pruebas frontend: aprobadas
Compilación TypeScript y Vite: aprobada
```

Comando reproducible:

```powershell
scripts\test.cmd
```

## Demostración HTTP integrada

Resultado final:

```text
health.status: ok
health.external_connections: false
frontend: HTTP 200
descarga de plantilla: HTTP 200
caso timeline: 5 actividades
decisiones iniciales: 3 Incluir, 1 Revisar, 1 Excluir
corrección: versión 1 → versión 2
responsable corregido: local-account-wilfrido
hash del origen conservado: true
archivo inválido: HTTP 422 / INVALID_HEADER
```

## Artefactos de demostración

- `examples/plan_timeline_referencia_v1_1_valido.xlsx`
- `examples/plan_v1_1_invalido_encabezado.xlsx`
- `examples/propuesta_timeline_referencia_v1_1.json`

## Límites conservados

- No se desplegó AWS.
- No se utilizó Cognito real.
- No se invocaron AgentCore, Strands, Gemma o Gemini.
- No se configuró Rovo MCP ni OAuth Atlassian.
- No se leyó ni escribió Jira.
- No se implementó un importador universal de documentos.

