import os
import json
import re
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
    with open(".env", "r", encoding="utf-8") as f:
        for line in f:
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.strip().split("=", 1)
                os.environ[k.strip()] = v.strip()

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

# ================= 2. Evaluador Gemini (REST API Puro) =================
def evaluar_con_gemini(textos_avisos: List[str]) -> List[dict]:
    if not textos_avisos:
        return []

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("ERROR: No se encontró GEMINI_API_KEY en las variables de entorno.")
        return []

    gemini_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={api_key}"
    cumplen = []
    
    # Procesar en lotes de 10 avisos
    batch_size = 10
    for i in range(0, len(textos_avisos), batch_size):
        batch = textos_avisos[i : i + batch_size]
        print(f"Evaluando lote de {len(batch)} propiedades con Gemini 2.0...")
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

        try:
            resp = requests.post(gemini_url, json=payload, timeout=40)
            if resp.status_code == 200:
                data = resp.json()
                texto_json = data["candidates"][0]["content"]["parts"][0]["text"]
                items = json.loads(texto_json)
                for item in items:
                    if item.get("cumple_estricto"):
                        cumplen.append(item)
            else:
                print(f"Error en llamada a Gemini API ({resp.status_code}): {resp.text}")
        except Exception as e:
            print(f"Error evaluando lote con Gemini: {e}")

    cumplen.sort(key=lambda x: x.get("prioridad_score", 0), reverse=True)
    return cumplen

# ================= 3. Exportador a Google Drive =================
def subir_reporte_drive(total_evaluadas: int, propiedades: List[dict]):
    if not propiedades:
        print("No se encontraron propiedades que cumplan todos los requisitos hoy. No se crea archivo.")
        return

    sa_raw = os.environ.get("GCP_SA_KEY")
    if not sa_raw:
        print("ERROR: No se encontró GCP_SA_KEY en las variables de entorno.")
        return

    sa_info = json.loads(sa_raw)
    creds = service_account.Credentials.from_service_account_info(
        sa_info, scopes=["https://www.googleapis.com/auth/drive"]
    )
    drive_service = build("drive", "v3", credentials=creds)

    fecha_hoy = datetime.now().strftime("%d/%m/%Y")
    nombre_archivo = f"Reporte Alquileres - {fecha_hoy}"

    html_content = f"""
    <html>
    <head><style>body{{font-family: Arial, sans-serif; line-height: 1.6;}} h1{{color: #1a73e8;}} h2{{color: #202124; border-bottom: 1px solid #dadce0; padding-bottom: 4px;}}</style></head>
    <body>
        <h1>Reporte Diario de Alquileres - {fecha_hoy}</h1>
        <p><strong>* Total de publicaciones evaluadas hoy:</strong> {total_evaluadas} publicaciones</p>
        <p><strong>* Propiedades calificadas:</strong> {len(propiedades)}</p>
        <hr/>
    """

    for idx, prop in enumerate(propiedades, 1):
        gc = prop.get('gastos_comunes_uyu')
        gc_str = f"${gc:,.0f} UYU" if gc else "No especificados / $0"
        m2 = prop.get('metros_cuadrados')
        m2_str = f"{m2} m²" if m2 else "N/A"

        html_content += f"""
        <h2>{idx}. <a href="{prop.get('url', '#')}" target="_blank">{prop.get('titulo', 'Sin título')}</a></h2>
        <ul>
            <li><strong>Ubicación:</strong> {prop.get('barrio', '')}</li>
            <li><strong>Precio base:</strong> ${prop.get('precio_base_uyu', 0):,.0f} UYU</li>
            <li><strong>Gastos comunes:</strong> {gc_str}</li>
            <li><strong>Costo total estimado:</strong> ${prop.get('costo_total_estimado', 0):,.0f} UYU</li>
            <li><strong>Características:</strong> {prop.get('dormitorios', 1)} dorm | {m2_str} | Exterior: {prop.get('detalle_espacio_exterior', '')} | Cochera: {prop.get('detalle_cochera', '')}</li>
            <li><strong>Justificación:</strong> {prop.get('justificacion_calificacion', '')}</li>
        </ul>
        """

    html_content += "</body></html>"

    media = MediaIoBaseUpload(BytesIO(html_content.encode("utf-8")), mimetype="text/html", resumable=True)
    file_metadata = {
        "name": nombre_archivo,
        "mimeType": "application/vnd.google-apps.document",
        "parents": [DRIVE_FOLDER_ID],
    }

    archivo_creado = drive_service.files().create(
        body=file_metadata, media_body=media, fields="id, name"
    ).execute()
    print(f"Reporte creado exitosamente en Google Drive: {archivo_creado.get('name')} (ID: {archivo_creado.get('id')})")

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
