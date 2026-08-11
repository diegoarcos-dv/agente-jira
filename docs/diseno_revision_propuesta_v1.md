# Diseño funcional de la revisión de propuesta v1

## Propósito

La pantalla debe permitir que una persona confirme una propuesta completa sin revisar mecánicamente cada campo de Jira. La aplicación muestra primero las excepciones y conserva siempre la comparación entre el dato de origen y lo que se propone crear.

Principio rector: **revisar decisiones, no recapturar información**.

## Flujo de pantallas

1. Cargar la plantilla `.xlsx`.
2. Seleccionar una vez el Space del plan: AT, ASIT o MTTI.
3. Completar, si aplican, los valores generales: Iniciativa, línea de trabajo, sprint, tipo de seguimiento y semáforo.
4. Procesar y generar la propuesta.
5. Resolver primero las filas con dudas.
6. Revisar el resumen y aprobar la versión.
7. Confirmar en un segundo paso la escritura en Jira.

## Wireframe de la pantalla principal

```text
┌──────────────────────────────────────────────────────────────────────────┐
│ Propuesta P-2026-004  ·  Space AT  ·  versión 3                         │
│ 42 incluidas     4 requieren revisión     11 excluidas                  │
├──────────────────────────────────────────────────────────────────────────┤
│ Valores generales: Iniciativa [Reclasificación]  Sprint [—]  [Editar]  │
├──────────────────────────────────────────────────────────────────────────┤
│ [Requieren revisión 4] [Listas 42] [Excluidas 11] [Todas]  Buscar [...] │
├──────────────────────────────────────────────────────────────────────────┤
│ □ Origen        Propuesta         Tipo     Responsable   Estado   Acción │
│ ! Reglas        Reglas            Task     2 personas    Revisar  Abrir  │
│   Integración…  Integrar con GIS  Story    Wilfrido      Lista    Abrir  │
│ ○ Link menú     Crear link…       Task     Giselle       Excluir  Abrir  │
├──────────────────────────────────────────────────────────────────────────┤
│ 4 dudas pendientes                      [Guardar] [Revisar aprobación]   │
└──────────────────────────────────────────────────────────────────────────┘
```

## Panel de detalle

Al abrir una fila se muestran dos columnas:

| Origen | Propuesta editable |
|---|---|
| Actividad | Título |
| Responsable escrito | Usuario Jira resuelto |
| Grupo o módulo | Work Type y parent propuestos |
| Contexto o resultado | Descripción generada |
| Fecha objetivo | Due date |
| Estado y comentarios | Incluir, revisar o excluir y su motivo |

El usuario puede corregir la propuesta sin alterar el archivo original. Cada cambio incrementa la versión o queda registrado como borrador de la siguiente versión.

## Revisión por excepciones

Una fila queda en **Revisar** cuando ocurre al menos uno de estos casos:

- No se puede resolver un único responsable en Jira.
- El texto parece un agrupador y no está claro si debe ser Epic o sólo una etiqueta de agrupación.
- El Work Type tiene baja confianza.
- Falta un parent obligatorio para Subtask.
- La actividad está marcada como `Por confirmar`.
- Hay contradicción entre estado, fecha o comentario.
- Un campo normativo requerido por el Space no puede obtenerse de los valores generales.

Las filas `Completada` o `Rechazada` aparecen inicialmente en **Excluidas**. El usuario puede reactivarlas de manera explícita.

## Acciones masivas seguras

- Aplicar responsable resuelto a todas las coincidencias del mismo nombre.
- Cambiar Work Type para las filas seleccionadas.
- Asignar un grupo o parent a varias filas.
- Incluir o excluir filas seleccionadas.
- Aplicar valores generales del plan.

No se permite una acción masiva que escriba en Jira. La creación sólo ocurre después de aprobar la versión completa y confirmar la ejecución.

## Aprobación en dos pasos

1. **Aprobar propuesta:** congela contenido, versión y hash del archivo fuente.
2. **Crear en Jira:** muestra Space, número de elementos por tipo y advertencia de impacto. Requiere confirmación expresa.

Si la propuesta cambia después de aprobarse, pierde la aprobación y debe generarse una nueva versión.

## Criterios UX del MVP

- Dos campos obligatorios por fila: Actividad y Responsable.
- Máximo cinco valores generales opcionales por plan, además del Space obligatorio.
- Ningún `accountId`, project key, field ID o parent ID se captura en Excel.
- Las dudas se presentan juntas y antes que las filas listas.
- El usuario siempre puede ver el origen y el motivo de una inferencia.
- El modelo no inventa hechos; una ausencia relevante se convierte en pregunta o advertencia.
- La interfaz debe poder usarse con teclado y no depender sólo del color.

## Hipótesis medibles para el piloto

- Al menos 80 % de las filas debería llegar sin pregunta individual; es una hipótesis, no un compromiso previo a medir.
- El tiempo de preparación debe ser claramente menor que la captura manual equivalente en Jira.
- Ningún participante debería necesitar conocer IDs técnicos de Jira.
- Las correcciones más frecuentes deben alimentar reglas, catálogos o ayudas, no más columnas obligatorias.

## Fuera de esta versión

- Edición colaborativa simultánea.
- Roles separados de capturista, revisor y aprobador.
- Extracción directa desde PDF, Word, minuta, TXT o Markdown.
- Escritura automática sin revisión humana.
