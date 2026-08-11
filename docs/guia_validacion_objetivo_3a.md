# Guía de validación del Objetivo 3A

Esta validación es de solo lectura y no crea ni modifica actividades Jira.

## Preparación

1. Ejecuta `scripts\start.cmd`.
2. Abre exactamente `http://localhost:8000`.
3. Inicia sesión en Agente Jira.

## Conectar Atlassian

1. En **Conexión Atlassian Rovo MCP**, selecciona **Conectar mi cuenta Atlassian**.
2. Inicia sesión en Atlassian con tu cuenta habitual si el navegador lo solicita.
3. Revisa el consentimiento y autoriza.
4. Espera el regreso automático a Agente Jira.

Si Atlassian indica que el dominio no está autorizado, valida en **Atlassian Administration → Rovo → Rovo MCP server → Domains** que **Allow Atlassian supported domains** siga habilitado. `localhost` está incluido oficialmente; no agregues un dominio nuevo salvo que esa política haya sido deshabilitada.

No compartas capturas que muestren códigos OAuth, tokens, cookies o datos de sesión.

## Comprobaciones

Confirma visualmente:

- estado **Conectado · solo lectura**;
- sitio `https://dpti.atlassian.net`;
- `cloudId` con un valor no vacío;
- usuario Atlassian correcto;
- tarjetas AT, ASIT y MTTI con estado visible;
- Work Types al desplegar cada Space;
- conteos de campos para los Work Types disponibles.

En **Prueba de responsables reales**:

1. selecciona AT;
2. escribe parte del nombre de una persona que pueda recibir actividades;
3. selecciona **Buscar**;
4. confirma que aparece nombre y `accountId` o correo.

## Desconexión

1. Selecciona **Desconectar**.
2. Confirma la operación.
3. Verifica el estado **Desconectado**.

Al desconectar se eliminan los tokens en memoria. Si aparece un error, copia únicamente el mensaje visible de la aplicación; no compartas parámetros completos de la URL de callback.
