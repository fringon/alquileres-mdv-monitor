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
        time.sleep(1.5)  # Pausa de cortesía para evitar rate limiting de MercadoLibre
        try:
            html = descargar_html(url_cat, timeout=15)
            if not html or len(html) < 30000:
                print(f"[{etiqueta}] Aviso: Respuesta vacía o reducida ({len(html)} bytes).")
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

# ================= 2. Evaluador Gemini (Con Fallback de Modelos) =================
def evaluar_con_gemini(textos_avisos: List[str]) -> List[dict]:
    if not textos_avisos:
        return []

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("ERROR: No se encontró GEMINI_API_KEY en las variables de entorno.")
        return []

    # Modelos activos y 100% disponibles para tu clave
    modelos_disponibles = ["gemini-3.5-flash", "gemini-3.5-flash-lite"]
    cumplen = []
    
    # Procesar en lotes de 5 avisos
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

        evaluado_con_exito = False
        for modelo in modelos_disponibles:
            if evaluado_con_exito:
                break
            
            gemini_url = f"https://generativelanguage.googleapis.com/v1beta/models/{modelo}:generateContent?key={api_key}"
            
            for intento in range(2):
                try:
                    resp = requests.post(gemini_url, json=payload, timeout=35)
                    if resp.status_code == 200:
                        data = resp.json()
                        texto_json = data["candidates"][0]["content"]["parts"][0]["text"]
                        items = json.loads(texto_json)
                        for item in items:
                            if item.get("cumple_estricto"):
                                cumplen.append(item)
                        evaluado_con_exito = True
                        break
                    elif resp.status_code in [503, 429]:
                        print(f"Modelo {modelo} saturado temporalmente, reintentando...")
                        time.sleep(3)
                    else:
                        # Si da otro error (ej 404), pasar al siguiente modelo
                        break
                except Exception as e:
                    time.sleep(2)

        if not evaluado_con_exito:
            print("Aviso: No se pudo evaluar este lote tras probar los modelos de respaldo.")

    cumplen.sort(key=lambda x: x.get("prioridad_score", 0), reverse=True)
    return cumplen

# ================= 3. Exportador a Google Drive =================
def subir_reporte_drive(total_evaluadas: int, propiedades: List[dict]):
    if not propiedades:
        print("No se encontraron propiedades que cumplan todos los requisitos hoy. No se crea archivo.")
        return

    fecha_hoy = datetime.now().strftime("%d/%m/%Y")
    nombre_archivo = f"Reporte Alquileres - {fecha_hoy}"

    # Construir texto limpio y estructurado del reporte
    texto_reporte = f"Reporte Diario de Alquileres - {fecha_hoy}\n"
    texto_reporte += f"* Total de publicaciones evaluadas hoy: {total_evaluadas} publicaciones\n"
    texto_reporte += f"* Propiedades calificadas: {len(propiedades)}\n"
    texto_reporte += "=" * 50 + "\n\n"

    for idx, prop in enumerate(propiedades, 1):
        gc = prop.get('gastos_comunes_uyu')
        gc_str = f"${gc:,.0f} UYU" if gc else "No especificados / $0"
        m2 = prop.get('metros_cuadrados')
        m2_str = f"{m2} m²" if m2 else "N/A"

        titulo_limpio = prop.get('titulo', 'Propiedad en alquiler').replace('[', '').replace(']', '')
        texto_reporte += f"{idx}. [{titulo_limpio}]({prop.get('url', '')})\n"
        texto_reporte += f"• Ubicación: {prop.get('barrio', '')}\n"
        texto_reporte += f"• Precio base: ${prop.get('precio_base_uyu', 0):,.0f} UYU\n"
        texto_reporte += f"• Gastos comunes: {gc_str}\n"
        texto_reporte += f"• Costo total estimado: ${prop.get('costo_total_estimado', 0):,.0f} UYU\n"
        texto_reporte += f"• Características: {prop.get('dormitorios', 1)} dorm | {m2_str} | Exterior: {prop.get('detalle_espacio_exterior', '')} | Cochera: {prop.get('detalle_cochera', '')}\n"
        texto_reporte += f"• Justificación: {prop.get('justificacion_calificacion', '')}\n\n"

    # 1. Enviar vía Google Apps Script (creación con la cuenta del usuario, 0 problemas de cuota)
    apps_script_url = os.environ.get("APPS_SCRIPT_URL", "").strip()
    if apps_script_url:
        try:
            payload = {
                "nombre_archivo": nombre_archivo,
                "total_evaluadas": total_evaluadas,
                "propiedades": propiedades,
                "texto_reporte": texto_reporte
            }
            resp = requests.post(apps_script_url, json=payload, timeout=30)
            if resp.status_code == 200:
                data = resp.json() if resp.text.startswith("{") else {}
                print(f"Reporte creado exitosamente en Google Drive: {nombre_archivo}")
                if data.get("url"):
                    print(f"URL del documento: {data.get('url')}")
                return
            else:
                print(f"Aviso Apps Script ({resp.status_code}): {resp.text}")
        except Exception as e:
            print(f"Aviso enviando a Apps Script: {e}")

    # 2. Respaldo local
    print("Guardando copia local del reporte en 'reporte_hoy.txt'...")
    with open("reporte_hoy.txt", "w", encoding="utf-8") as f:
        f.write(texto_reporte)

# ================= Ejecución Principal =================
if __name__ == "__main__":
    print("Iniciando rastreo de alquileres...")
    urls_hoy, total_evaluadas = extraer_publicaciones_del_dia()
    print(f"\n--- RESUMEN DE RASTREO ---")
    print(f"Total publicaciones evaluadas: {total_evaluadas} | Publicadas hoy: {len(urls_hoy)}")

    detalles = []
    print(f"Descargando fichas de {len(urls_hoy)} publicaciones...")
    for idx, u in enumerate(urls_hoy, 1):
        time.sleep(0.8)
        txt = obtener_detalle_publicacion(u)
        if txt:
            detalles.append(txt)

    propiedades_aprobadas = evaluar_con_gemini(detalles)
    print(f"\nPropiedades que cumplen todos los criterios: {len(propiedades_aprobadas)}")

    subir_reporte_drive(total_evaluadas, propiedades_aprobadas)
