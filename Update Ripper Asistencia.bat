@echo off
set /p msg="Introduce el mensaje del commit: "
if "%msg%"=="" set msg="Actualizacion automatica %date% %time%"

echo.
echo 🕒 Sincronizando con GitHub (Pull)...
:: Traemos lo que haya en la nube y lo mezclamos con lo local
git pull origin main --rebase

echo.
echo 🚀 Subiendo tus cambios (Push)...
git add .
git commit -m "%msg%"
git push origin main

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo ❌ ERROR: Algo salio mal. Si hay conflictos, avisame.
) else (
    echo.
    echo ✅ ¡EXITO TOTAL! Revisa Render en 2 minutos.
)
pause