# Plantilla Excel Jira v1.2

Incluye captura guiada con catálogo desplegable para `Tipo_de_seguimiento` y es compatible con el parser v1.1/v1.2. La copia congelada y su `manifest.json` sirven como referencia reproducible.

La descarga operativa es `GET /api/template/v1.2`: el backend regenera la hoja `CATÁLOGOS` con el catálogo verificado de Jira para `AT / Task / customfield_10147`. Si Jira no está disponible, la respuesta queda marcada como `unavailable` y no inventa opciones.
