import os
import json
import re
import time
import urllib.parse
from datetime import datetime
from typing import List, Optional
import requests
from bs4 import BeautifulSoup
from google.oauth2 import service_account
from googleapiclient.discovery import build
from io import BytesIO
from googleapiclient.http import MediaIoBaseUpload

# ================= Cargar variables locales =================
if os.path.exists(".env"):
    try:
        with open(".env", "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    k, v = line.split("=", 1)
                    k = k.strip()
                    v = v.strip()
                    # Quitar comillas exteriores si las tiene
                    if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
                        v = v[1:-1]
                    os.environ[k] = v
    except Exception as e:
        print(f"Aviso cargando .env: {e}")

# ================= Configuración =================
DRIVE_FOLDER_ID = "1Hvr7ARrIa9UL72jJqnhutkt3d1x8r9nT"

URLS_BUSQUEDA = [
    # Malvín (Publicados hoy hasta 40.000 UYU)
    ("Malvín Aptos Hoy", "https://listado.mercadolibre.com.uy/inmuebles/apartamentos/alquiler/montevideo/malvin/_PriceRange_0UYU-40000UYU_PublishedToday_YES_NoIndex_True"),
    ("Malvín Casas Hoy", "https://listado.mercadolibre.com.uy/inmuebles/casas/alquiler/montevideo/malvin/_PriceRange_0UYU-40000UYU_PublishedToday_YES_NoIndex_True"),
    # Punta Gorda (Publicados hoy hasta 40.000 UYU)
    ("Punta Gorda Aptos Hoy", "https://listado.mercadolibre.com.uy/inmuebles/apartamentos/alquiler/montevideo/punta-gorda/_PriceRange_0UYU-40000UYU_PublishedToday_YES_NoIndex_True"),
    ("Punta Gorda Casas Hoy", "https://listado.mercadolibre.com.uy/inmuebles/casas/alquiler/montevideo/punta-gorda/_PriceRange_0UYU-40000UYU_PublishedToday_YES_NoIndex_True"),
    # Carrasco (Publicados hoy hasta 40.000 UYU)
    ("Carrasco Aptos Hoy", "https://listado.mercadolibre.com.uy/inmuebles/apartamentos/alquiler/montevideo/carrasco/_PriceRange_0UYU-40000UYU_PublishedToday_YES_NoIndex_True"),
    ("Carrasco Casas Hoy", "https://listado.mercadolibre.com.uy/inmuebles/casas/alquiler/montevideo/carrasco/_PriceRange_0UYU-40000UYU_PublishedToday_YES_NoIndex_True"),
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "es-UY,es;q=0.9",
}

def descargar_html(url: str, timeout: int = 15) -> str:
    """Descarga directa y rápida con cabeceras de indexación."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=timeout)
        if resp.status_code == 200:
            return resp.text
    except Exception as e:
        print(f"Error descargando {url[:50]}...: {e}")
    return ""

# ================= 1. Extractor Determinista =================
def extraer_publicaciones_del_dia():
    publicaciones_candidatas = []
    total_evaluadas = 0
    urls_vistas = set()

    for etiqueta, url_cat in URLS_BUSQUEDA:
        try:
            html = descargar_html(url_cat, timeout=15)
            if not html:
                continue

            soup = BeautifulSoup(html, "html.parser")
            enlaces = soup.find_all("a", href=re.compile(r"/MLU-\d+"))
            
            candidatas_categoria = 0
            for a_tag in enlaces:
                raw_url = a_tag["href"].split("#")[0].split("?")[0]
                if raw_url in urls_vistas:
                    continue
                urls_vistas.add(raw_url)
                total_evaluadas += 1
                publicaciones_candidatas.append(raw_url)
                candidatas_categoria += 1

            print(f"[{etiqueta}] Encontradas hoy: {candidatas_categoria}")

        except Exception as e:
            print(f"Error escaneando {etiqueta}: {e}")

    return publicaciones_candidatas, total_evaluadas

def obtener_detalle_publicacion(url: str) -> str:
    try:
        html = descargar_html(url, timeout=15)
        if not html:
            return ""
        soup = BeautifulSoup(html, "html.parser")
        
        titulo = soup.select_one("h1.ui-pdp-title, h1")
        precio = soup.select_one("div.ui-pdp-price__second-line, span.andes-money-amount__fraction, .ui-pdp-price")
        caracteristicas = soup.select("div.ui-pdp-attributes, table.andes-table, div.ui-pdp-specs__table, .ui-pdp-features")
        descripcion = soup.select_one("div.ui-pdp-description__content, p.ui-pdp-description__content, .ui-pdp-description")

        texto_completo = f"URL: {url}\n"
        if titulo: texto_completo += f"Título: {titulo.get_text(strip=True)}\n"
        if precio: texto_completo += f"Precio: {precio.get_text(strip=True)}\n"
        for c in caracteristicas:
            texto_completo += f"Ficha técnica: {c.get_text(' | ', strip=True)}\n"
        if descripcion:
            texto_completo += f"Descripción: {descripcion.get_text(' ', strip=True)}\n"

        return texto_completo
    except Exception:
        return ""

# ================= 2. Evaluador Gemini (REST API con Reintentos) =================
def evaluar_con_gemini(textos_avisos: List[str]) -> List[dict]:
    if not textos_avisos:
        return []

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("ERROR: No se encontró GEMINI_API_KEY en las variables de entorno.")
        return []

    gemini_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.6-flash:generateContent?key={api_key}"
    cumplen = []
    
    # Procesar en lotes de 5 avisos para máxima precisión
    batch_size = 5
    for i in range(0, len(textos_avisos), batch_size):
        batch = textos_avisos[i : i + batch_size]
        print(f"Evaluando lote de {len(batch)} propiedades con Gemini...")
        prompt = f"""
        Eres un auditor inmobiliario estricto para Montevideo (Malvín, Punta Gorda, Carrasco).
        Evalúa las siguientes publicaciones de alquiler con estos requisitos ESTRICTOS:
        - Alquiler mensual residencial.
        - Costo total (Precio base + Gastos Comunes + Cochera) <= $40.000 UYU mensuales.
        - Mínimo 1 dormitorio (priorizar 2 dormitorios).
        - Mínimo 50 m² (si no se especifica pero describe casa/apto amplio, indícalo en observaciones).
        - Espacio exterior OBLIGATORIO: terraza, patio, balcón amplio o jardín.
        - Cochera / Garaje OBLIGATORIO (incluido o dentro del tope de $40.000 UYU).

        Devuelve ÚNICAMENTE un array JSON válido con la evaluación de cada aviso.
        Formato de cada objeto en el array JSON:
        {{
            "titulo": "Título de la publicación",
            "url": "URL exacta del aviso",
            "barrio": "Malvín, Punta Gorda o Carrasco",
            "precio_base_uyu": 35000,
            "gastos_comunes_uyu": 3000,
            "costo_total_estimado": 38000,
            "dormitorios": 2,
            "metros_cuadrados": 55,
            "tiene_espacio_exterior": true,
            "detalle_espacio_exterior": "Terraza al frente",
            "tiene_cochera": true,
            "detalle_cochera": "Cochera incluida",
            "cumple_estricto": true,
            "justificacion_calificacion": "Cumple todos los requisitos",
            "prioridad_score": 85
        }}

        Avisos para analizar:
        {json.dumps(batch, ensure_ascii=False)}
        """

        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "response_mime_type": "application/json"
            }
        }

        # Intentar hasta 3 veces con retroceso si hay alta demanda (503/429)
        for intento in range(3):
            try:
                resp = requests.post(gemini_url, json=payload, timeout=40)
                if resp.status_code == 200:
                    data = resp.json()
                    texto_json = data["candidates"][0]["content"]["parts"][0]["text"]
                    items = json.loads(texto_json)
                    for item in items:
                        if item.get("cumple_estricto"):
                            cumplen.append(item)
                    break
                elif resp.status_code in [503, 429]:
                    print(f"Gemini temporalmente ocupado (intento {intento+1}/3), reintentando en 3s...")
                    time.sleep(3)
                else:
                    print(f"Error en llamada a Gemini API ({resp.status_code}): {resp.text}")
                    break
            except Exception as e:
                print(f"Error evaluando lote con Gemini (intento {intento+1}/3): {e}")
                time.sleep(2)

    cumplen.sort(key=lambda x: x.get("prioridad_score", 0), reverse=True)
    return cumplen

# ================= 3. Exportador a Google Drive =================
def subir_reporte_drive(total_evaluadas: int, propiedades: List[dict]):
    if not propiedades:
        print("No se encontraron propiedades que cumplan todos los requisitos hoy. No se crea archivo.")
        return

    sa_info = None
    if os.path.exists("credentials.json"):
        try:
            with open("credentials.json", "r", encoding="utf-8") as f:
                sa_info = json.load(f)
        except Exception as e:
            print(f"Aviso leyendo credentials.json: {e}")

    if not sa_info:
        sa_raw = os.environ.get("GCP_SA_KEY", "").strip()
        if not sa_raw:
            print("ERROR: No se encontró GCP_SA_KEY ni archivo credentials.json.")
            return
        
        if (sa_raw.startswith("'") and sa_raw.endswith("'")) or (sa_raw.startswith('"') and sa_raw.endswith('"')):
            sa_raw = sa_raw[1:-1]

        try:
            sa_info = json.loads(sa_raw)
        except Exception as e:
            print(f"ERROR: No se pudo decodificar el JSON de GCP_SA_KEY: {e}")
            return

    creds = service_account.Credentials.from_service_account_info(
        sa_info, scopes=[
            "https://www.googleapis.com/auth/drive",
            "https://www.googleapis.com/auth/documents"
        ]
    )
    drive_service = build("drive", "v3", credentials=creds)

    fecha_hoy = datetime.now().strftime("%d/%m/%Y")
    nombre_archivo = f"Reporte Alquileres - {fecha_hoy}"

    # Construir texto limpio del reporte
    texto_reporte = f"Reporte Diario de Alquileres - {fecha_hoy}\n"
    texto_reporte += f"* Total de publicaciones evaluadas hoy: {total_evaluadas} publicaciones\n"
    texto_reporte += f"* Propiedades calificadas: {len(propiedades)}\n"
    texto_reporte += "=" * 50 + "\n\n"

    for idx, prop in enumerate(propiedades, 1):
        gc = prop.get('gastos_comunes_uyu')
        gc_str = f"${gc:,.0f} UYU" if gc else "No especificados / $0"
        m2 = prop.get('metros_cuadrados')
        m2_str = f"{m2} m²" if m2 else "N/A"

        texto_reporte += f"{idx}. {prop.get('titulo', 'Sin título')}\n"
        texto_reporte += f"• Link: {prop.get('url', '')}\n"
        texto_reporte += f"• Ubicación: {prop.get('barrio', '')}\n"
        texto_reporte += f"• Precio base: ${prop.get('precio_base_uyu', 0):,.0f} UYU\n"
        texto_reporte += f"• Gastos comunes: {gc_str}\n"
        texto_reporte += f"• Costo total estimado: ${prop.get('costo_total_estimado', 0):,.0f} UYU\n"
        texto_reporte += f"• Características: {prop.get('dormitorios', 1)} dorm | {m2_str} | Exterior: {prop.get('detalle_espacio_exterior', '')} | Cochera: {prop.get('detalle_cochera', '')}\n"
        texto_reporte += f"• Justificación: {prop.get('justificacion_calificacion', '')}\n\n"

    # Creación nativa con Google Docs API (evita el límite de cuota de almacenamiento de Service Accounts)
    try:
        docs_service = build("docs", "v1", credentials=creds)
        doc = docs_service.documents().create(body={"title": nombre_archivo}).execute()
        doc_id = doc.get("documentId")

        # Mover el archivo a la carpeta "Paulina"
        drive_service.files().update(
            fileId=doc_id,
            addParents=DRIVE_FOLDER_ID,
            fields="id, parents"
        ).execute()

        # Insertar el texto formateado
        docs_service.documents().batchUpdate(
            documentId=doc_id,
            body={"requests": [{"insertText": {"location": {"index": 1}, "text": texto_reporte}}]}
        ).execute()

        print(f"Reporte creado exitosamente en Google Drive: {nombre_archivo} (ID: {doc_id})")
        return
    except Exception as e:
        print(f"Aviso Google Docs API: {e}. Intentando método alternativo...")

    # Alternativa en caso de que Google Docs API no esté habilitada
    try:
        html_content = f"""
        <html><body>
            <h1>Reporte Diario de Alquileres - {fecha_hoy}</h1>
            <p><strong>Total evaluadas hoy:</strong> {total_evaluadas}</p>
            <p><strong>Propiedades calificadas:</strong> {len(propiedades)}</p>
            <pre>{texto_reporte}</pre>
        </body></html>
        """
        media = MediaIoBaseUpload(BytesIO(html_content.encode("utf-8")), mimetype="text/html", resumable=False)
        file_metadata = {
            "name": nombre_archivo,
            "mimeType": "application/vnd.google-apps.document",
            "parents": [DRIVE_FOLDER_ID],
        }
        archivo_creado = drive_service.files().create(
            body=file_metadata, media_body=media, fields="id, name", supportsAllDrives=True
        ).execute()
        print(f"Reporte creado exitosamente en Google Drive: {archivo_creado.get('name')} (ID: {archivo_creado.get('id')})")
    except Exception as e:
        print(f"ERROR subiendo archivo a Google Drive: {e}")

# ================= Ejecución Principal =================
if __name__ == "__main__":
    print("Iniciando rastreo de alquileres...")
    urls_hoy, total_evaluadas = extraer_publicaciones_del_dia()
    print(f"\n--- RESUMEN DE RASTREO ---")
    print(f"Total publicaciones evaluadas: {total_evaluadas} | Publicadas hoy: {len(urls_hoy)}")

    detalles = []
    print(f"Descargando fichas de {len(urls_hoy)} publicaciones...")
    for idx, u in enumerate(urls_hoy, 1):
        txt = obtener_detalle_publicacion(u)
        if txt:
            detalles.append(txt)

    propiedades_aprobadas = evaluar_con_gemini(detalles)
    print(f"\nPropiedades que cumplen todos los criterios: {len(propiedades_aprobadas)}")

    subir_reporte_drive(total_evaluadas, propiedades_aprobadas)
