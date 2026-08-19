// ====================================================================
// SCRIPT 1: Crear Reporte en Google Drive (Aplicación Web)
// ====================================================================
// Función: Recibe el reporte enviado por Python (scraper.py) y crea el 
// Google Doc nativo dentro de la carpeta compartida "Paulina".
//
// Despliegue:
// 1. Implementar > Nueva implementación > Aplicación web.
// 2. Ejecutar como: "Yo (tu cuenta)".
// 3. Quién tiene acceso: "Cualquier usuario" (Anyone).
// 4. Copiar la URL terminada en /exec y guardarla en APPS_SCRIPT_URL de tu .env.
// ====================================================================

function doPost(e) {
  try {
    var data = JSON.parse(e.postData.contents);
    var folderId = "1Hvr7ARrIa9UL72jJqnhutkt3d1x8r9nT"; // Carpeta "Paulina"
    var folder = DriveApp.getFolderById(folderId);
    
    // 1. Crear el documento con la cuenta del usuario
    var doc = DocumentApp.create(data.nombre_archivo);
    var body = doc.getBody();
    body.setText(data.texto_reporte);
    
    // 2. Mover el archivo a la carpeta destino
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
