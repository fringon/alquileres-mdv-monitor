@echo off
cd /d "%~dp0"
title Monitor Diario de Alquileres Montevideo
echo ========================================================
echo   MONITOR DE ALQUILERES (Malvin, Punta Gorda, Carrasco)
echo ========================================================
echo.
python scraper.py
echo.
echo ========================================================
echo   Proceso finalizado.
echo ========================================================
timeout /t 10
