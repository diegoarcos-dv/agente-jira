# Login unificado con Atlassian

## Flujo

La pantalla normal sólo ofrece **Continuar con Atlassian**. El navegador se
dirige al proveedor OAuth de Atlassian; Agente Jira nunca recibe, valida ni
almacena la contraseña de Atlassian.

El callback reutiliza:

`http://localhost:8000/api/integrations/atlassian/callback`

Cada inicio registra un `state` aleatorio, almacenado como SHA-256, de un solo
uso y con vigencia de diez minutos. El callback valida además el estado que
mantiene el proveedor MCP antes de crear una sesión local.

## Identidad y autorización

`app_users` mantiene el rol interno (`ADMIN` o `USER`) y el estado local
(`PENDING`, `ACTIVE` o `DISABLED`). La primera autenticación busca un usuario
preautorizado por correo y guarda su `atlassian_account_id`. Los siguientes
inicios se resuelven exclusivamente por `atlassian_account_id`.

Por defecto, una cuenta autenticada que no exista en `app_users`, o que esté
deshabilitada, recibe `NO_ALLOWED_LOCAL_USER`. Los administradores pueden
preautorizar usuarios mediante `POST /api/auth/admin/users` con `email`,
`display_name` y `role`.

En esta instalación, `AGENTE_JIRA_ALLOW_ALL_CORPORATE_USERS=true` registra
como `USER` a toda identidad que complete OAuth y valide el sitio Jira
corporativo configurado. No concede roles dentro de Atlassian ni reactiva una
cuenta local deshabilitada: Jira sigue aplicando sus permisos reales.

El administrador heredado queda `PENDING` durante la migración. Se activa si
una autorización OAuth nueva demuestra el mismo `account_id` de la credencial
Atlassian local ya almacenada. Si esa credencial DPAPI quedó ilegible por un
cambio del perfil Windows, existe una única recuperación de migración: requiere
la credencial cifrada local y que el OAuth nuevo ya haya validado el sitio Jira
corporativo. El evento `LEGACY_ADMIN_BOOTSTRAP` queda auditado y el mecanismo
deja de aplicar al vincular el primer `account_id`.

## Sesiones y credenciales

- `app_sessions` conserva únicamente hashes SHA-256 de tokens de sesión.
- La cookie `agente_jira_session` es `HttpOnly`, `SameSite=Lax` y usa `Secure`
  cuando el callback se configura con HTTPS.
- `atlassian_credentials` guarda metadatos de propiedad, expiración, scopes y
  sitio; no contiene tokens.
- Los tokens y refresh tokens viven en un archivo por usuario, identificado por
  un hash del usuario y cifrado con DPAPI de Windows.
- El refresh usa un candado asíncrono por usuario. El almacenamiento del SDK
  persiste de forma atómica el token nuevo que Atlassian entrega durante la
  rotación.
- `POST /api/auth/logout` invalida sólo la sesión local actual.
- `POST /api/auth/atlassian/unlink` elimina únicamente las credenciales locales
  del usuario actual; salir no obliga un consentimiento OAuth nuevo.

## Configuración Atlassian

En Atlassian Developer Console, la integración debe mantener exactamente el
callback anterior y los scopes de identidad que el MCP ya solicita:

- `read:me`
- `read:account`
- `email` cuando esté disponible para el tenant
- `offline_access`
- los scopes Jira de lectura ya utilizados por el agente

No se debe pegar `client_secret` en la aplicación, documentos ni chat. Si la
consola requiere un cambio, guardar el callback y scopes anteriores sin ampliar
permisos de escritura por este flujo de login.

## Recuperación local de desarrollo

El endpoint heredado de recuperación no tiene UI y está deshabilitado por
defecto. Sólo un operador local puede activarlo temporalmente con:

`AGENTE_JIRA_EMERGENCY_LOCAL_AUTH_ENABLED=true`

También requiere `AGENTE_JIRA_LOCAL_PASSWORD`. No usar esta opción como login
normal ni habilitarla en producción.

## Seguridad Jira

La autenticación federada no modifica las políticas de Jira. El bloqueo global,
las confirmaciones explícitas, el dry-run, la idempotencia y las restricciones
de escritura siguen siendo controles independientes. Esta migración no crea ni
actualiza issues.

La política de arranque `jira_execution_policy_4e.json` permite crear hasta
cinco elementos de los tipos soportados en AT. Cada usuario corporativo puede
abrir una ventana de escritura temporal; antes de cualquier creación se exige
una propuesta vigente, dry-run sin bloqueos, responsable confirmado, segunda
confirmación y lectura posterior. No habilita edición, transición, comentarios
ni worklogs.
