# 🏡 Monitor de Alquileres de Montevideo

Sistema automatizado de monitoreo y auditoría inteligente de alquileres en Montevideo (Malvín, Punta Gorda y Carrasco) con criterios estrictos (precio $\le$ $40.000 UYU, garaje, espacio exterior y $\ge$ 1 dormitorio).

---

## 📌 Arquitectura y Flujo Completo

```
1. Extractor Python (Termux/PC)
   └─ Rastrear publicaciones de hoy en Mercado Libre
   
2. Auditor Inteligente (Gemini 3.6 Flash)
   └─ Evalúa lotes de 5 publicaciones con criterios estrictos
   
3. Creador de Documento (Google Apps Script 1)
   └─ Crea el Google Doc nativo en la carpeta "Paulina" de Google Drive
   
4. Notificador de Telegram (Google Apps Script 2)
   └─ Lee el Google Doc y envía el resumen a tu grupo de Telegram
```

---

## 📂 Estructura del Repositorio

- `scraper.py`: Código principal en Python que extrae publicaciones de MercadoLibre, las envía a Gemini y hace el POST al Webhook de Drive.
- `requirements.txt`: Librerías Python necesarias (100% compatibles con Android y Windows).
- `ejecutar_monitor.bat`: Lanzador de 1-clic para Windows.
- `google_apps_scripts/`:
  - `01_crear_reporte_drive.js`: Código del Google Apps Script para desplegar como Aplicación Web.
  - `02_notificar_telegram.js`: Código del Google Apps Script para notificaciones programadas en Telegram.

---

## ⚙️ Variables de Entorno (`.env`)

En la raíz del proyecto (o en Termux) se crea el archivo `.env`:

```env
GEMINI_API_KEY=AIzaSy...tu_clave_de_google_ai_studio...
APPS_SCRIPT_URL=https://script.google.com/macros/s/...tu_url.../exec
```

---

## 🚀 Cómo ponerlo en marcha desde cero en cualquier dispositivo (Android / Termux)

### 1. Clonar e instalar:
```bash
pkg update -y && pkg install -y git python cronie nano
git clone https://github.com/fringon/alquileres-mdv-monitor.git
cd alquileres-mdv-monitor
pip install -r requirements.txt
```

### 2. Configurar variables:
```bash
cat << 'EOF' > .env
GEMINI_API_KEY=tu_clave_de_gemini
APPS_SCRIPT_URL=https://script.google.com/macros/s/.../exec
EOF
```

### 3. Probar ejecución:
```bash
python scraper.py
```

### 4. Automatizar todos los días a las 21:50:
```bash
termux-wake-lock
(crontab -l 2>/dev/null; echo "50 21 * * * cd $HOME/alquileres-mdv-monitor && python scraper.py >> $HOME/monitor.log 2>&1") | crontab -
crond
```
