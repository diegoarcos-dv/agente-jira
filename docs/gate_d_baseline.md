# GATE D — Baseline reproducible (antes de optimizar)

Fecha del baseline: 2026-09-08. El benchmark es local y sintético: no llama a
Jira, no contiene credenciales y usa una latencia determinista de 5 ms por
lectura para comparar cambios de código.

Comando:

```powershell
$env:PYTHONPATH='backend'
.\.venv\Scripts\python.exe backend\scripts\benchmark_gate_d.py
```

| Actividades | Duración total (ms) | Llamadas Jira/MCP | Cache hits | Cache misses | Concurrencia máxima |
|---:|---:|---:|---:|---:|---:|
| 1 | 19.9 | 2 | 1 | 2 | 1 |
| 3 | 36.6 | 3 | 4 | 3 | 1 |
| 10 | 54.5 | 3 | 18 | 3 | 1 |
| 25 | 68.3 | 3 | 48 | 3 | 1 |

Interpretación:

- La reutilización request-scoped ya evitaba duplicar el catálogo de
  responsables y Sprint: en este escenario hay dos responsables únicos y un
  Sprint por Space, por eso las llamadas reales se estabilizan en tres desde
  tres actividades.
- El cuello de botella medido era el acceso secuencial: la concurrencia máxima
  era 1 aunque las lecturas son independientes.
- Este archivo conserva el punto de comparación **antes** del prefetch
  concurrente de lecturas. Los tiempos de Jira real pueden diferir; el panel de
  diagnóstico y los logs estructurados de la aplicación muestran las métricas
  de cada request real.

## Comparación después de GATE D

Con el mismo comando y la misma latencia sintética, el prefetch de lecturas
independientes quedó limitado por defecto a 4 tareas concurrentes (sin superar
8 aunque se cambie la variable de entorno):

| Actividades | Antes (ms) | Después (ms) | Llamadas Jira/MCP antes/después | Concurrencia después |
|---:|---:|---:|---:|---:|
| 1 | 19.9 | 8.6 | 2 / 2 | 2 |
| 3 | 36.6 | 17.0 | 3 / 3 | 3 |
| 10 | 54.5 | 22.4 | 3 / 3 | 3 |
| 25 | 68.3 | 36.1 | 3 / 3 | 3 |

La mejora proviene de solapar únicamente lecturas independientes; no se
paralelizan escrituras, autenticación, preflight ni idempotencia. El resultado
de cada actividad conserva su propia validación y error, y el cache permanece
aislado al request.

### Política de caché e invalidación

- Responsables: sólo cache request-scoped; no se conserva entre usuarios,
  OAuth ni propuestas.
- Sprint: el manager mantiene un cache de lectura de 5 minutos por sesión
  OAuth y Space para consultas no forzadas; el Dry run fuerza una lectura
  vigente para evitar escribir con un catálogo incompleto. `disconnect` elimina
  la sesión y su cache.
- Snapshot, Work Type, campos obligatorios y autorización de escritura no se
  cachean globalmente. Un fallo o una sesión incompleta obliga a reconsultar y
  bloquea de forma segura; nunca se reutiliza una decisión de escritura vieja.
