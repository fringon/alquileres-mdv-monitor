import os
import json
import re
from datetime import datetime
from typing import List, Optional
import requests
from bs4 import BeautifulSoup
from pydantic import BaseModel, Field
from google import genai
from google.oauth2 import service_account
from googleapiclient.discovery import build
from io import BytesIO
from googleapiclient.http import MediaIoBaseUpload

# ================= Configuración =================
DRIVE_FOLDER_ID = "1Hvr7ARrIa9UL72jJqnhutkt3d1x8r9nT"

URLS_BUSQUEDA = [
    # Malvín
    "https://listado.mercadolibre.com.uy/inmuebles/apartamentos/alquiler/montevideo/malvin/_PriceRange_0UYU-40000UYU_PublishedToday_YES",
    "https://listado.mercadolibre.com.uy/inmuebles/apartamentos/alquiler/montevideo/malvin/_PriceRange_0UYU-40000UYU",
    "https://listado.mercadolibre.com.uy/inmuebles/casas/alquiler/montevideo/malvin/_PriceRange_0UYU-40000UYU_PublishedToday_YES",
    "https://listado.mercadolibre.com.uy/inmuebles/casas/alquiler/montevideo/malvin/_PriceRange_0UYU-40000UYU",
    # Punta Gorda
    "https://listado.mercadolibre.com.uy/inmuebles/apartamentos/alquiler/montevideo/punta-gorda/_PriceRange_0UYU-40000UYU_PublishedToday_YES",
    "https://listado.mercadolibre.com.uy/inmuebles/apartamentos/alquiler/montevideo/punta-gorda/_PriceRange_0UYU-40000UYU",
    "https://listado.mercadolibre.com.uy/inmuebles/casas/alquiler/montevideo/punta-gorda/_PriceRange_0UYU-40000UYU",
    # Carrasco
    "https://listado.mercadolibre.com.uy/inmuebles/apartamentos/alquiler/montevideo/carrasco/_PriceRange_0UYU-40000UYU_PublishedToday_YES",
    "https://listado.mercadolibre.com.uy/inmuebles/apartamentos/alquiler/montevideo/carrasco/_PriceRange_0UYU-40000UYU",
    "https://listado.mercadolibre.com.uy/inmuebles/casas/alquiler/montevideo/carrasco/_PriceRange_0UYU-40000UYU",
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "es-UY,es;q=0.9",
}

# ================= Schema para Gemini =================
class EvaluacionAlquiler(BaseModel):
    titulo: str = Field(description="Título claro de la publicación")
    url: str = Field(description="URL exacta del aviso")
    barrio: str = Field(description="Barrio: Malvín, Punta Gorda o Carrasco")
    precio_base_uyu: float = Field(description="Precio base publicado en pesos uruguayos")
    gastos_comunes_uyu: Optional[float] = Field(description="Gastos comunes aproximados en pesos uruguayos (0 si no aplica o incluidos, None si no se indica)")
    costo_total_estimado: float = Field(description="Suma estimada de alquiler + gastos comunes")
    dormitorios: int = Field(description="Cantidad de dormitorios")
    metros_cuadrados: Optional[float] = Field(description="Metraje total o construido en m2")
    tiene_espacio_exterior: bool = Field(description="True si tiene patio, terraza, balcón amplio o jardín")
    detalle_espacio_exterior: str = Field(description="Detalle del espacio exterior encontrado")
    tiene_cochera: bool = Field(description="True si tiene garaje o cochera incluida/disponible")
    detalle_cochera: str = Field(description="Detalle de cochera/garaje")
    cumple_estricto: bool = Field(description="True SOLO si costo_total <= 40000, m2 >= 50 (o razonable si no aclara), tiene espacio exterior, cochera y >= 1 dorm")
    justificacion_calificacion: str = Field(description="Explicación detallada de por qué cumple o qué puntos no aclara")
    prioridad_score: int = Field(description="Puntuación 1-100: mayor puntaje a 2 dorm, garaje incluido, terraza amplia y mejor precio")

# ================= 1. Extractor Determinista =================
def extraer_publicaciones_del_dia():
    publicaciones_candidatas = []
    total_evaluadas = 0
    urls_vistas = set()

    for url_cat in URLS_BUSQUEDA:
        try:
            resp = requests.get(url_cat, headers=HEADERS, timeout=15)
            if resp.status_code != 200:
                print(f"[HTTP {resp.status_code}] Saltando categoría: {url_cat}")
                continue

            soup = BeautifulSoup(resp.text, "html.parser")
            enlaces = soup.find_all("a", href=re.compile(r"/MLU-\d+"))
            es_url_hoy = "_PublishedToday_YES" in url_cat

            candidatas_categoria = 0
            for a_tag in enlaces:
                raw_url = a_tag["href"].split("#")[0].split("?")[0]
                if raw_url in urls_vistas:
                    continue
                urls_vistas.add(raw_url)
                total_evaluadas += 1

                # Evaluar etiqueta de fecha en la tarjeta
                padre = a_tag.find_parent(["li", "div", "article"])
                texto_tarjeta = padre.get_text(" ", strip=True).lower() if padre else ""

                es_de_hoy = es_url_hoy or (
                    "publicado hoy" in texto_tarjeta 
                    or "hoy" in texto_tarjeta 
                    or ("hace " in texto_tarjeta and ("hora" in texto_tarjeta or "minuto" in texto_tarjeta))
                )

                if es_de_hoy and raw_url not in publicaciones_candidatas:
                    publicaciones_candidatas.append(raw_url)
                    candidatas_categoria += 1

            nombre_cat = url_cat.split("inmuebles/")[-1].split("/_")[0]
            print(f"Categoría: {nombre_cat} | Enlaces encontrados: {len(enlaces)} | De hoy: {candidatas_categoria}")

        except Exception as e:
            print(f"Error escaneando categoría {url_cat}: {e}")

    return publicaciones_candidatas, total_evaluadas

def obtener_detalle_publicacion(url: str) -> str:
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        if resp.status_code != 200:
            return ""
        soup = BeautifulSoup(resp.text, "html.parser")
        
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

# ================= 2. Evaluador Gemini =================
def evaluar_con_gemini(textos_avisos: List[str]) -> List[EvaluacionAlquiler]:
    if not textos_avisos:
        return []

    client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))
    cumplen = []
    
    # Procesar en lotes de 15 avisos
    batch_size = 15
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

        Analiza cada aviso y genera la evaluación estructurada.
        Avisos:
        {json.dumps(batch, ensure_ascii=False)}
        """

        try:
            response = client.models.generate_content(
                model="gemini-2.0-flash",
                contents=prompt,
                config={
                    "response_mime_type": "application/json",
                    "response_schema": list[EvaluacionAlquiler],
                },
            )
            data = json.loads(response.text)
            for item in data:
                ev = EvaluacionAlquiler(**item) if isinstance(item, dict) else item
                if ev.cumple_estricto:
                    cumplen.append(ev)
        except Exception as e:
            print(f"Error evaluando lote con Gemini: {e}")

    cumplen.sort(key=lambda x: x.prioridad_score, reverse=True)
    return cumplen

# ================= 3. Exportador a Google Drive =================
def subir_reporte_drive(total_evaluadas: int, propiedades: List[EvaluacionAlquiler]):
    if not propiedades:
        print("No se encontraron propiedades que cumplan todos los requisitos hoy. No se crea archivo.")
        return

    sa_info = json.loads(os.environ.get("GCP_SA_KEY"))
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
        html_content += f"""
        <h2>{idx}. <a href="{prop.url}" target="_blank">{prop.titulo}</a></h2>
        <ul>
            <li><strong>Ubicación:</strong> {prop.barrio}</li>
            <li><strong>Precio base:</strong> ${prop.precio_base_uyu:,.0f} UYU</li>
            <li><strong>Gastos comunes:</strong> {'$' + f'{prop.gastos_comunes_uyu:,.0f} UYU' if prop.gastos_comunes_uyu else 'No especificados / $0'}</li>
            <li><strong>Costo total estimado:</strong> ${prop.costo_total_estimado:,.0f} UYU</li>
            <li><strong>Características:</strong> {prop.dormitorios} dorm | {prop.metros_cuadrados or 'N/A'} m² | Exterior: {prop.detalle_espacio_exterior} | Cochera: {prop.detalle_cochera}</li>
            <li><strong>Justificación:</strong> {prop.justificacion_calificacion}</li>
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
    for u in urls_hoy:
        txt = obtener_detalle_publicacion(u)
        if txt:
            detalles.append(txt)

    propiedades_aprobadas = evaluar_con_gemini(detalles)
    print(f"Propiedades que cumplen todos los criterios: {len(propiedades_aprobadas)}")

    subir_reporte_drive(total_evaluadas, propiedades_aprobadas)
