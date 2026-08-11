# Evidencia del Objetivo 3A

Fecha: 17 de julio de 2026  
Estado: cumplido y verificado con Jira real.

## Evidencia reproducible

Desde la raíz del proyecto:

```powershell
scripts\setup.cmd
scripts\test.cmd
scripts\start.cmd
```

Resultado automatizado esperado:

- backend: `30 passed`;
- frontend: `8 passed`;
- build de producción: completado sin errores.

## Controles demostrados

| Control | Evidencia |
|---|---|
| OAuth por usuario | Estado OAuth asociado al usuario autenticado y protegido por `state` + PKCE |
| Tokens no persistidos | Almacenamiento implementado únicamente en memoria |
| Tokens no expuestos | Contrato de estado y prueba API sin campos de token |
| Escritura bloqueada | Las cinco herramientas oficiales de escritura Jira generan `WriteToolBlocked` antes de llamar al transporte |
| Spaces limitados | Normalización exclusiva de AT, ASIT y MTTI |
| Sitio correcto | Selección por hostname exacto `dpti.atlassian.net` |
| MCP vigente | Transporte Streamable HTTP al endpoint `authv2` |

## Prueba viva previa al consentimiento

El 17 de julio de 2026 se ejecutó el inicio OAuth contra el servidor real y se comprobó, sin autorizar una cuenta ni consultar datos Jira:

- fase devuelta: `AWAITING_USER_CONSENT`;
- host de autorización: `auth.atlassian.com`;
- protocolo de autorización: HTTPS;
- parámetro `state`: presente;
- intento cancelado y credenciales temporales eliminadas al finalizar la comprobación.

Una prueba posterior demostró que reescribir los scopes anunciados por Rovo produce `invalid_request` en Atlassian Identity porque deja de coincidir con el registro dinámico del cliente. Esa modificación fue retirada. El enlace OAuth se conserva íntegro y el usuario puede desmarcar **Search** y **Write** en el consentimiento; la aplicación mantiene adicionalmente su bloqueo técnico de escritura.

La autorización real posterior alcanzó correctamente la etapa `READ_VISIBLE_PROJECTS`. Atlassian rechazó el valor inicial `maxResults=100` porque el contrato vigente de `getVisibleJiraProjects` admite como máximo `50`. El cliente fue corregido para enviar `50` y se agregó una prueba de regresión que inspecciona el argumento antes del transporte.

## Evidencia interactiva completada

La prueba interactiva del 17 de julio de 2026 confirmó, sin registrar identificadores sensibles:

- fase `CONNECTED` y etapa `COMPLETE`;
- sitio exacto `https://dpti.atlassian.net` y `cloudId` presente;
- AT, ASIT y MTTI visibles, con cinco Work Types cada uno;
- metadatos de campos en catorce Work Types; la Subtarea de AT fue visible pero devolvió cero campos;
- búsqueda satisfactoria de un responsable asignable real;
- tokens únicamente en memoria;
- `jiraWriteEnabled=false` y bloqueo de herramientas de escritura activo.

La [guía de validación](guia_validacion_objetivo_3a.md) queda disponible para futuras regresiones. No capturar ni compartir códigos OAuth, access tokens, refresh tokens, cookies o secretos.
