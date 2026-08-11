# Evidencia verificable - Objetivo 1.1

Fecha de verificación: 16 de julio de 2026.

## Objetivo

Refinar y verificar la aplicación local para que las actividades corregidas se revaliden automáticamente, muestren todos sus pendientes, transicionen de `Revisar` a `Incluir` cuando queden resueltas y para que el historial incorpore barra colapsable, búsqueda, filtros, archivado y restauración.

## Evidencia automatizada

Comando reproducible desde la raíz del proyecto:

```powershell
scripts\test.cmd
```

Resultado final registrado:

```text
20 passed
Test Files 1 passed
Tests 5 passed
TypeScript build passed
Vite production build passed
Verificación completa.
```

Cobertura relevante:

- reunión de múltiples pendientes en una actividad;
- permanencia en `REVISAR` después de una corrección parcial;
- transición automática a `INCLUIR` al resolver el último pendiente;
- incremento de versión sin mutar la fuente;
- archivado, listado y restauración mediante API;
- ausencia de selector manual de decisión en el panel de corrección;
- botón deshabilitado mientras quedan requisitos;
- búsqueda, filtros y acciones del historial;
- compilación de producción.

## Demostración HTTP y visual

Caso utilizado:

- archivo `examples/plan_timeline_referencia_v1_1_valido.xlsx`;
- Space `AT`;
- actividad de la fila 9;
- responsable de origen `Wilfrido / José`;
- estado de origen `Por confirmar`.

Estado inicial:

```text
Versión: 1
Listas: 3
Requieren revisión: 1
Excluidas: 1
Pendientes de la fila 9: 2
```

Pendientes mostrados simultáneamente:

1. Seleccionar un responsable disponible en el catálogo.
2. Confirmar que la actividad sigue vigente.

Acciones realizadas:

1. Selección de `Wilfrido Hernández`.
2. Confirmación de vigencia.
3. Selección de `Guardar y volver a validar`.

Resultado observado:

```text
Versión: 2
Listas: 4
Requieren revisión: 0
Excluidas: 1
Responsable: Wilfrido Hernández
Decisión derivada: INCLUIR
```

Mensaje mostrado:

```text
Versión 2 guardada. Se resolvieron todos los pendientes y la actividad pasó a Listas.
```

## Inspección visual

Se verificó:

- alineación estable del historial;
- controles de búsqueda y filtros visibles;
- barra expandida de 288 px aproximadamente;
- barra compacta de 77 px aproximadamente;
- conservación del ancho del viewport sin desplazamiento horizontal;
- responsable seleccionado reflejado antes de guardar;
- checklist de pendientes resueltos;
- pestaña `Listas` seleccionada después de la transición.

Durante la inspección se detectó que el input invisible del selector de archivos provocaba desbordamiento horizontal. Se corrigió acotándolo al contenedor de carga y se volvió a comprobar que `scrollWidth` fuera igual al ancho del viewport.

## Archivado y restauración

La API y las pruebas automatizadas comprobaron:

1. Archivar una propuesta devuelve `archived: true`.
2. La propuesta permanece en el listado con estado archivado.
3. Restaurarla devuelve `archived: false`.
4. Las versiones almacenadas no se eliminan.

## Inicio con puerto ocupado

Con una instancia saludable en el puerto 8000, `scripts\start.cmd` termina correctamente y muestra:

```text
La aplicación ya está ejecutándose en http://localhost:8000
```

Esto sustituye el error técnico `WinError 10048` para ese escenario.

## Confirmación de aislamiento

- `/api/health` reporta `external_connections: false`.
- La búsqueda estática no encontró clientes AWS, GCP o Atlassian.
- La única coincidencia con `secret` corresponde al módulo estándar `secrets` utilizado para generar tokens locales.
- No existe endpoint de escritura Jira.

## Resultado

El Objetivo 1.1 cumple sus criterios técnicos, funcionales y visuales. Queda listo para una validación de aceptación breve por parte del usuario.
