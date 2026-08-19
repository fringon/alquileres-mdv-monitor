// ====================================================================
// SCRIPT 1: Crear Reporte en Google Drive (Formato Enriquecido)
// ====================================================================
// Función: Recibe las propiedades de Python y crea un Google Doc con
// formato visual profesional (Títulos, Viñetas, Enlaces clicables y Negritas).
// ====================================================================

function doPost(e) {
  try {
    var data = JSON.parse(e.postData.contents);
    var folderId = "1Hvr7ARrIa9UL72jJqnhutkt3d1x8r9nT"; // Carpeta "Paulina"
    var folder = DriveApp.getFolderById(folderId);
    
    // 1. Crear el documento
    var doc = DocumentApp.create(data.nombre_archivo);
    var body = doc.getBody();
    body.clear();
    
    // Título Principal
    var title = body.appendParagraph(data.nombre_archivo);
    title.setHeading(DocumentApp.ParagraphHeading.HEADING1);
    
    // Resumen
    var p1 = body.appendParagraph("* Total de publicaciones evaluadas hoy: " + (data.total_evaluadas || 0) + " publicaciones");
    p1.setBold(true);
    var p2 = body.appendParagraph("* Propiedades calificadas: " + (data.propiedades ? data.propiedades.length : 0));
    p2.setBold(true);
    body.appendHorizontalRule();
    
    // Listado de Propiedades con formato profesional
    if (data.propiedades && data.propiedades.length > 0) {
      data.propiedades.forEach(function(prop, idx) {
        // Título del aviso como Heading 2 y enlace directo
        var titulo = (idx + 1) + ". " + (prop.titulo || "Propiedad en alquiler");
        var heading = body.appendParagraph(titulo);
        heading.setHeading(DocumentApp.ParagraphHeading.HEADING2);
        if (prop.url) {
          heading.setLinkUrl(prop.url);
        }
        
        // Viñetas con detalles
        var gcStr = prop.gastos_comunes_uyu ? "$" + Number(prop.gastos_comunes_uyu).toLocaleString('es-UY') + " UYU" : "No especificados / $0";
        var m2Str = prop.metros_cuadrados ? prop.metros_cuadrados + " m²" : "N/A";
        var totalStr = "$" + Number(prop.costo_total_estimado || 0).toLocaleString('es-UY') + " UYU";
        var baseStr = "$" + Number(prop.precio_base_uyu || 0).toLocaleString('es-UY') + " UYU";
        
        body.appendListItem("Ubicación: " + (prop.barrio || "")).setGlyphType(DocumentApp.GlyphType.BULLET);
        body.appendListItem("Precio base: " + baseStr).setGlyphType(DocumentApp.GlyphType.BULLET);
        body.appendListItem("Gastos comunes: " + gcStr).setGlyphType(DocumentApp.GlyphType.BULLET);
        body.appendListItem("Costo total estimado: " + totalStr).setGlyphType(DocumentApp.GlyphType.BULLET);
        body.appendListItem("Características: " + (prop.dormitorios || 1) + " dorm | " + m2Str + " | Exterior: " + (prop.detalle_espacio_exterior || "No") + " | Cochera: " + (prop.detalle_cochera || "No")).setGlyphType(DocumentApp.GlyphType.BULLET);
        body.appendListItem("Justificación: " + (prop.justificacion_calificacion || "")).setGlyphType(DocumentApp.GlyphType.BULLET);
        
        var linkItem = body.appendListItem("Ver en Mercado Libre: " + (prop.url || ""));
        linkItem.setGlyphType(DocumentApp.GlyphType.BULLET);
        if (prop.url) {
          linkItem.setLinkUrl(prop.url);
        }
        
        body.appendParagraph(""); // Separador
      });
    } else {
      body.appendParagraph("No se encontraron propiedades que cumplan todos los requisitos hoy.");
    }
    
    // Mover el archivo a la carpeta "Paulina"
    var file = DriveApp.getFileById(doc.getId());
    folder.addFile(file);
    DriveApp.getRootFolder().removeFile(file);
    
    return ContentService.createTextOutput(JSON.stringify({
      status: "success",
      id: doc.getId(),
      url: doc.getUrl()
    })).setMimeType(ContentService.MimeType.JSON);
    
  } catch (err) {
    return ContentService.createTextOutput(JSON.stringify({
      status: "error",
      message: err.toString()
    })).setMimeType(ContentService.MimeType.JSON);
  }
}
