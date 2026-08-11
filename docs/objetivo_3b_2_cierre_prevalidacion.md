# Objetivo 3B.2 — cierre práctico de la prevalidación Jira

## Objetivo verificable

Una persona puede conservar su autorización Atlassian, aprobar una propuesta y ejecutar la prevalidación final en un solo paso, entender el resultado sin decidir entre acciones ambiguas y descargar una evidencia auditable, con garantía de cero escrituras en Jira.

## Cambios implementados

### 1. Autorización Atlassian recuperable

- Los tokens y los datos del cliente OAuth se guardan por usuario en un archivo cifrado con Windows DPAPI.
- El archivo no contiene secretos en texto claro y sólo puede descifrarse bajo el usuario de Windows que lo creó.
- Al reiniciar el backend, la primera consulta de estado intenta recuperar la autorización y reconstruir el diagnóstico MCP.
- `Salir` cierra únicamente la sesión de la aplicación.
- `Desconectar Atlassian` elimina explícitamente la autorización cifrada.
- Para el futuro despliegue Linux/AWS se requiere sustituir el proveedor DPAPI por Secrets Manager/KMS; no se permite degradar silenciosamente a texto claro.

### 2. Aprobación y Dry run en una acción

El botón final ahora se llama **Aprobar y ejecutar prevalidación final**. La API comprueba primero que Atlassian esté conectado; sólo entonces crea la versión aprobada y genera su Dry run. Si no existe conexión, la propuesta permanece editable.

### 3. Estados finales claros

- **Prevalidación completada:** no existen bloqueos ni advertencias.
- **Prevalidación completada con advertencias técnicas:** la cuenta Jira fue identificada, pero el MCP público de Rovo no ofrece una prueba de asignabilidad por Space y Work Type.
- **Prevalidación requiere correcciones:** existe al menos un error real que el usuario debe resolver.

La advertencia `ASSIGNEE_ASSIGNABILITY_UNVERIFIED` no bloquea el Objetivo 3B porque éste no escribe en Jira. Antes de habilitar el Objetivo 4 sí será obligatorio incorporar una comprobación estricta de asignabilidad y tratar su ausencia como bloqueo.

### 4. Acciones contextuales

- Resultado correcto: **Descargar evidencia JSON**, **Repetir prevalidación** y **Reabrir para editar**.
- Resultado bloqueado: **Reabrir y resolver bloqueos** como acción principal, más evidencia y repetición como acciones secundarias.
- Un Dry run de una versión anterior se etiqueta como **resultado histórico** y nunca determina el estado de la versión vigente.
- Ya no se presenta `Actualizar Dry run` como siguiente paso ambiguo.

La evidencia combina la versión aprobada y el registro completo de prevalidación, incluye `mode: DRY_RUN_NO_WRITE` y mantiene `write_performed: false`.

## Validación manual recomendada

1. Inicia la aplicación y conecta Atlassian una vez.
2. Pulsa **Salir**, vuelve a iniciar sesión y confirma que el estado continúa conectado.
3. Reinicia `scripts\start.cmd`, vuelve a entrar y espera a que el diagnóstico se recupere automáticamente.
4. Abre una propuesta sin actividades por revisar.
5. Pulsa **Revisar y aprobar propuesta final**.
6. Confirma y pulsa **Aprobar y ejecutar prevalidación final**.
7. Verifica que aparezca un único resultado final y que todas las actividades queden listas, listas con advertencia o realmente bloqueadas.
8. Descarga la evidencia y comprueba `write_performed: false`.
9. Usa **Desconectar** sólo para comprobar que la autorización guardada se elimina y que se requiere OAuth nuevamente.

## Evidencia automatizada

- Backend: 42 pruebas aprobadas.
- Frontend: 8 pruebas aprobadas.
- Compilación TypeScript/Vite aprobada.
- Prueba DPAPI real: cifrado, recuperación y ausencia del token en texto claro aprobadas.
- Prueba de API: aprobación + Dry run en una sola llamada y evidencia sin escritura aprobadas.

## Límite pendiente antes de escritura

El Objetivo 3B.2 cierra el flujo de prevalidación sin escritura. No autoriza crear, editar ni transicionar actividades Jira. El siguiente objetivo funcional debe diseñar el control estricto de asignabilidad, la confirmación explícita del lote y la ejecución canario antes de cualquier escritura productiva.
