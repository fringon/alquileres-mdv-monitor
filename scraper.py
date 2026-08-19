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

# ================= Configuración =================
DRIVE_FOLDER_ID = "1Hvr7ARrIa9UL72jJqnhutkt3d1x8r9nT"

URLS_BUSQUEDA = [
    # Malvín (Casas y Aptos hasta 40.000 UYU)
    "https://inmuebles.mercadolibre.com.uy/apartamentos/alquiler/montevideo/malvin/_PriceRange_0UYU-40000UYU",
    "https://inmuebles.mercadolibre.com.uy/casas/alquiler/montevideo/malvin/_PriceRange_0UYU-40000UYU",
    # Punta Gorda
    "https://inmuebles.mercadolibre.com.uy/apartamentos/alquiler/montevideo/punta-gorda/_PriceRange_0UYU-40000UYU",
    "https://inmuebles.mercadolibre.com.uy/casas/alquiler/montevideo/punta-gorda/_PriceRange_0UYU-40000UYU",
    # Carrasco
    "https://inmuebles.mercadolibre.com.uy/apartamentos/alquiler/montevideo/carrasco/_PriceRange_0UYU-40000UYU",
    "https://inmuebles.mercadolibre.com.uy/casas/alquiler/montevideo/carrasco/_PriceRange_0UYU-40000UYU",
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
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
                continue

            soup = BeautifulSoup(resp.text, "html.parser")
            items = soup.select("li.ui-search-layout__item, div.ui-search-result__wrapper")

            for item in items:
                total_evaluadas += 1
                link_tag = item.select_one("a.ui-search-link, a.poly-component__title")
                if not link_tag or not link_tag.get("href"):
                    continue

                raw_url = link_tag["href"].split("#")[0].split("?")[0]
                if not re.search(r"/MLU-\d+", raw_url) or raw_url in urls_vistas:
                    continue

                # Validar etiqueta temporal estricta en el listado
                item_text = item.get_text(" ", strip=True).lower()
                es_de_hoy = "publicado hoy" in item_text or "hace " in item_text and ("hora" in item_text or "minuto" in item_text)

                if es_de_hoy:
                    urls_vistas.add(raw_url)
                    publicaciones_candidatas.append(raw_url)

        except Exception as e:
            print(f"Error escaneando categoría {url_cat}: {e}")

    return publicaciones_candidatas, total_evaluadas

def obtener_detalle_publicacion(url: str) -> str:
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        if resp.status_code != 200:
            return ""
        soup = BeautifulSoup(resp.text, "html.parser")
        
        # Extraer bloques relevantes de texto
        titulo = soup.select_one("h1.ui-pdp-title")
        precio = soup.select_one("div.ui-pdp-price__second-line, span.andes-money-amount__fraction")
        caracteristicas = soup.select("div.ui-pdp-attributes, table.andes-table")
        descripcion = soup.select_one("div.ui-pdp-description__content, p.ui-pdp-description__content")

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
    Avisos para analizar:
    {json.dumps(textos_avisos, ensure_ascii=False)}
    """

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
        config={
            "response_mime_type": "application/json",
            "response_schema": list[EvaluacionAlquiler],
        },
    )

    resultados: List[EvaluacionAlquiler] = json.loads(response.text)
    # Filtrar solo las que cumplen estrictamente y ordenar por prioridad
    cumplen = [r for r in resultados if r.cumple_estricto]
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

    # Construir contenido HTML enriquecido
    html_content = f"""
    <html>
    <head><style>body{{font-family: Arial, sans-serif; line-height: 1.6;}} h1{{color: #1a73e8;}} h2{{color: #202124; border-bottom: 1px solid #dadce0; padding-bottom: 4px;}} .badge{{background: #e8f0fe; color: #1a73e8; padding: 2px 8px; border-radius: 4px;}}</style></head>
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

    from io import BytesIO
    from googleapiclient.http import MediaIoBaseUpload

    media = MediaIoBaseUpload(BytesIO(html_content.encode("utf-8")), mimetype="text/html", resumable=True)
    file_metadata = {
        "name": nombre_archivo,
        "mimeType": "application/vnd.google-apps.document",  # Convierte directo a Google Doc nativo
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
    print(f"Total publicaciones evaluadas: {total_evaluadas} | Publicadas hoy: {len(urls_hoy)}")

    detalles = []
    for u in urls_hoy:
        txt = obtener_detalle_publicacion(u)
        if txt:
            detalles.append(txt)

    propiedades_aprobadas = evaluar_con_gemini(detalles)
    print(f"Propiedades que cumplen todos los criterios: {len(propiedades_aprobadas)}")

    subir_reporte_drive(total_evaluadas, propiedades_aprobadas)
