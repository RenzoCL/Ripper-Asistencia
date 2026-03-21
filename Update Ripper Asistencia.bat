@echo off
set /p msg="Introduce el mensaje del commit: "
if "%msg%"=="" set msg="Actualizacion automatica %date% %time%"

echo.
echo 🕒 Iniciando actualizacion en GitHub...

git add .
git commit -m "%msg%"

:: Forzamos que la rama sea main antes de subir
git branch -M main
git push origin main

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo ❌ ERROR: No se pudo subir. 
) else (
    echo.
    echo ✅ ¡Subida exitosa! Revisa Render ahora.
)
pause