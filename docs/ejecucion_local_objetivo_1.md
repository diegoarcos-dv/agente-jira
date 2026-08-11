# Ejecución local - Objetivos 1 y 1.1

## Alcance

Esta versión ejecuta el flujo local:

1. Login de desarrollo.
2. Carga de la Plantilla Excel v1.1.
3. Validación de versión, hoja, encabezados y campos obligatorios.
4. Normalización de actividades y fechas.
5. Resolución contra un catálogo ficticio.
6. Clasificación determinista de Work Type.
7. Decisión Incluir, Revisar o Excluir.
8. Revisión del origen frente a la propuesta.
9. Corrección con creación de una versión nueva.
10. Revalidación automática de todos los pendientes.
11. Transición automática de `Revisar` a `Listas`.
12. Búsqueda, filtros, archivado y restauración de propuestas.

No se realizan conexiones a AWS, GCP, Gemini, Atlassian ni Jira.

## Preparación

Desde PowerShell, en la raíz del proyecto:

```powershell
scripts\setup.cmd
```

Este comando crea `.venv`, instala las dependencias Python y prepara el frontend.

## Desarrollo

```powershell
scripts\dev.cmd
```

- Frontend: `http://localhost:5173`
- API y documentación OpenAPI: `http://localhost:8000/docs`

Credenciales locales:

```text
Usuario: admin@agentejira.local
Contraseña: AgenteJira2026!
```

Pueden modificarse con:

```powershell
$env:AGENTE_JIRA_LOCAL_USER="usuario@ejemplo.local"
$env:AGENTE_JIRA_LOCAL_PASSWORD="contraseña-local"
```

## Ejecución integrada

Para compilar React y servir frontend y API desde FastAPI:

```powershell
scripts\start.cmd
```

Abre `http://localhost:8000`.

Si ya existe una instancia saludable en el puerto 8000, el comando informará que la aplicación está ejecutándose en lugar de mostrar el error técnico de puerto ocupado.

## Pruebas

```powershell
scripts\test.cmd
```

Las pruebas cubren:

- archivo v1.1 aceptado;
- encabezado incompatible;
- actividad obligatoria faltante;
- filas reservadas vacías;
- reglas de Work Type;
- responsables resueltos y no encontrados;
- decisiones Incluir, Revisar y Excluir;
- conformidad con el esquema JSON v1.1;
- versionado sin modificar el origen;
- login, carga, consulta y edición mediante API;
- render básico del acceso React;
- compilación TypeScript;
- revalidación parcial y completa de múltiples pendientes;
- transición automática a `INCLUIR`;
- archivado y restauración sin perder versiones;
- búsqueda y filtros de la barra lateral;
- barra lateral colapsable y mensajes de confirmación.

## Persistencia

Las propuestas se guardan en `backend/data/agente_jira.db`. Cada modificación crea un registro con el mismo `proposal_id` y un número de versión superior. El contenido del archivo fuente no se modifica ni se almacena.

## Seguridad local

- El token de sesión existe solamente en memoria.
- Las credenciales de demostración no son productivas.
- No hay SDKs ni clientes de AWS, GCP o Atlassian.
- El endpoint `/api/health` expone `external_connections: false`.
- No existe endpoint de ejecución o escritura Jira.
