// ====================================================================
// SCRIPT 2: Notificador de Telegram
// ====================================================================
// Función: Lee los nuevos reportes creados hoy en la carpeta "Paulina"
// de Google Drive y envía un mensaje formateado con los enlaces directos
// a tu grupo/chat de Telegram.
//
// Despliegue:
// 1. Configurar un Activador (reloj en el menú izquierdo de Apps Script).
// 2. Función: enviarNotificacionTelegram.
// 3. Basado en tiempo > Temporizador por día (ej. 22:00 a 23:00).
// ====================================================================

// ID de la carpeta compartida "Paulina" en Google Drive
const FOLDER_ID = '1Hvr7ARrIa9UL72jJqnhutkt3d1x8r9nT'; 

// Credenciales de Telegram
const TELEGRAM_TOKEN = '8937387415:AAHy0YNbMtlauTEJG2WCGVsj_nQwG2iyfK4';
const TELEGRAM_CHAT_ID = '-1004400883944'; // ID del grupo o chat

// Notificación diaria por Telegram con enlaces directos y conteo exacto
function enviarNotificacionTelegram() {
  const folder = DriveApp.getFolderById(FOLDER_ID);
  const files = folder.getFiles();
  const hoy = new Date();
  const hoyStr = Utilities.formatDate(hoy, "America/Montevideo", "yyyy-MM-dd");
  
  let archivoDeHoy = null;
  while (files.hasNext()) {
    const file = files.next();
    const nombre = file.getName();
    if (nombre.includes(hoyStr) || (nombre.startsWith("Reporte Alquileres") && (hoy.getTime() - file.getLastUpdated().getTime()) / (1000 * 60 * 60) < 4)) {
      archivoDeHoy = file;
      break;
    }
  }

  if (archivoDeHoy && TELEGRAM_TOKEN !== 'PEGA_AQUI_TU_TOKEN_DE_BOTFATHER') {
    const datosDoc = extraerDatosDeDoc(archivoDeHoy.getId());
    const publicaciones = datosDoc.publicaciones;
    const totalEvaluadas = datosDoc.totalEvaluadas;
    
    let listaPublicaciones = "";
    if (publicaciones.length > 0) {
      publicaciones.forEach((pub, index) => {
        const tituloLimpio = String(pub.titulo).replace(/[_*[\]()~`>#+=|{}.!]/g, ' ').trim();
        listaPublicaciones += `${index + 1}. 🔗 [${tituloLimpio}](${pub.url})\n\n`;
      });
    } else {
      listaPublicaciones = "• Revisa el documento completo en el enlace abajo.\n\n";
    }

    const mensaje = `🏠 *Alquileres Nuevos (${hoyStr})*\n\n` +
                    `📊 *Total de publicaciones evaluadas hoy:* ${totalEvaluadas}\n` +
                    `✅ *Opciones que cumplen los criterios:* ${publicaciones.length}\n\n` +
                    `📍 *Acceso directo a las publicaciones:*\n\n` +
                    listaPublicaciones +
                    `📄 *Análisis detallado, gastos y datos faltantes:*\n` +
                    `👉 [Abrir reporte completo en Google Drive](${archivoDeHoy.getUrl()})`;
    
    const url = `https://api.telegram.org/bot${TELEGRAM_TOKEN}/sendMessage`;
    const payload = {
      chat_id: TELEGRAM_CHAT_ID,
      text: mensaje,
      parse_mode: 'Markdown',
      disable_web_page_preview: true
    };
    
    const response = UrlFetchApp.fetch(url, {
      method: 'post',
      contentType: 'application/json',
      payload: JSON.stringify(payload),
      muteHttpExceptions: true
    });
    
    Logger.log("Mensaje enviado a Telegram: " + response.getContentText());
  } else {
    Logger.log("No hay reporte nuevo hoy o faltan datos de configuración.");
  }
}

// Función para extraer total evaluadas y enlaces verificados del documento
function extraerDatosDeDoc(docId) {
  const doc = DocumentApp.openById(docId);
  const body = doc.getBody();
  const fullText = body.getText();
  
  let totalEvaluadas = "0";
  const lineas = fullText.split("\n");
  for (let i = 0; i < lineas.length; i++) {
    const linea = lineas[i];
    if (linea.indexOf("Total de publicaciones evaluadas") !== -1) {
      const soloDigitos = linea.replace(/\D/g, "").trim();
      if (soloDigitos.length > 0) {
        totalEvaluadas = soloDigitos;
        break;
      }
    }
  }

  let items = [];
  
  // 1. Extraer formato Link: URL si existiera
  const linkRegex = /Link:\s*(https?:\/\/[^\s]+mercadolibre[^\s]*)/g;
  const titleRegex = /(\d+)\.\s*(.+)/g;
  
  const paragraphs = fullText.split("\n");
  let currentTitle = "";
  for (let i = 0; i < paragraphs.length; i++) {
    const p = paragraphs[i].trim();
    let mTitle = p.match(/^(\d+)\.\s*(.+)/);
    if (mTitle) {
      currentTitle = mTitle[2].trim();
    }
    let mLink = p.match(/Link:\s*(https?:\/\/[^\s]+mercadolibre[^\s]*)/i);
    if (mLink) {
      let url = mLink[1].trim();
      if (url && !items.some(it => it.url === url)) {
        items.push({ titulo: currentTitle || "Ver publicación en Mercado Libre", url: url });
      }
    }
  }

  // 2. Extraer formato Markdown [Título](URL) si existiera
  if (items.length === 0) {
    const mdRegex = /\[(.*?)\]\((https?:\/\/[^\)\s]+mercadolibre[^\)\s]*)\)/g;
    let m;
    while ((m = mdRegex.exec(fullText)) !== null) {
      const rawTitle = String(m[1] || "");
      const rawUrl = String(m[2] || "");
      const titulo = rawTitle.replace(/^(\d+[\.\)]\s*|#+\s*)/, '').trim();
      const url = rawUrl.trim();
      if (url && !items.some(it => it.url === url)) {
        items.push({ titulo: titulo || "Ver publicación en Mercado Libre", url: url });
      }
    }
  }

  return { totalEvaluadas: totalEvaluadas, publicaciones: items };
}
