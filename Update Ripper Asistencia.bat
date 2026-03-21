@echo off
set /p msg="Introduce el mensaje del commit: "
if "%msg%"=="" set msg="Actualizacion automatica %date% %time%"

echo.
echo 📦 1. Guardando tus cambios locales...
git add .
git commit -m "%msg%"

echo.
echo 🔄 2. Sincronizando con la nube (Pull)...
:: Traemos los cambios de GitHub y los ponemos "debajo" de los tuyos
git pull origin main --rebase

echo.
echo 🚀 3. Subiendo todo a GitHub (Push)...
git push origin main

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo ❌ Algo fallo. Si ves un mensaje de "CONFLICT", avisame.
) else (
    echo.
    echo ✅ ¡EXITO! Proyecto actualizado. Render empezara el deploy.
)
pause