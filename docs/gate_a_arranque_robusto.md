# GATE A — Arranque robusto y diagnóstico local

## Alcance

Este Gate sólo valida el entorno local antes de arrancar la aplicación. No modifica OAuth,
Jira, dry-run, creación de issues, propuestas, plantillas ni la lógica de voz.

## Auditoría baseline

- `setup.ps1` sólo comprobaba si existía `.venv\Scripts\python.exe`; un ejecutable roto se
  reutilizaba y la instalación fallaba con un mensaje poco accionable.
- No se validaban Python 3.12+, Node.js, pnpm ni las importaciones backend antes de iniciar.
- `dev.ps1` podía lanzar el frontend aunque el backend no pudiera arrancar.
- Los modos de ejecución comprobaban 8000 mediante una llamada HTTP, pero no comprobaban
  5173 ni distinguían una instancia propia de otro proceso.
- No existía un diagnóstico read-only ni una comprobación de dependencias frontend completas.

## Uso

```powershell
.\scripts\doctor.ps1
.\scripts\setup.cmd
.\scripts\dev.cmd
```

`doctor.ps1` no modifica archivos, no reconstruye `.venv`, no instala paquetes y no contacta
Jira. Devuelve `0` si el sistema está listo y `1` si existe un bloqueo.

Si `.venv` existe pero no funciona, el doctor informa que está dañado. La reconstrucción sólo
se ofrece desde `setup.ps1`, con confirmación explícita y conservando el entorno anterior con
un sufijo `.broken-YYYYMMDD-HHmmss`.

## Cambios

- `scripts/preflight.ps1`: comprobaciones compartidas de Python, versiones, puertos y salud local.
- `scripts/doctor.ps1`: diagnóstico humano y código de salida estable.
- `scripts/setup.ps1`: selección explícita de Python compatible, validación real del entorno,
  instalación y verificación de dependencias backend/frontend.
- `scripts/dev.ps1`, `scripts/start.ps1` y `scripts/start-objective-4{b,c1,d,e}.ps1`:
  precheck antes de levantar procesos.

## Validación realizada

- Python 3.12.14 y todas las importaciones backend: OK.
- Backend: `158 passed`.
- Parseo sintáctico de todos los scripts PowerShell: OK.
- Doctor con entorno sano y puertos omitidos: exit `0`.
- Doctor con 8000 ocupado por Agente Jira: exit `1`, sin matar el proceso.
- Se detectó además un `node_modules` frontend incompleto (`vitest` ausente); el doctor y
  setup ahora lo reportan explícitamente.

## Riesgos pendientes

- La reparación de dependencias frontend necesita acceso al registro npm si el store local no
  contiene todos los paquetes.
- En Windows sin Node.js en `PATH`, el diagnóstico requiere instalarlo o configurarlo; no se
  usa un fallback silencioso.
- La identificación del PID puede no estar disponible si Windows deniega `Get-NetTCPConnection`.
