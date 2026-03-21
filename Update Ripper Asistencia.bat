@echo off
set /p msg="Introduce el mensaje del commit: "
if "%msg%"=="" set msg="Actualizacion automatica %date% %time%"

echo.
echo 🕒 Iniciando actualizacion en GitHub...

:: Intentamos agregar los archivos
git add .
if %ERRORLEVEL% NEQ 0 goto error

:: Intentamos hacer el commit
git commit -m "%msg%"
if %ERRORLEVEL% NEQ 0 goto error

:: Intentamos subir al repositorio de RenzoCL
git push origin master
if %ERRORLEVEL% NEQ 0 goto error

echo.
echo ✅ ¡Subida exitosa a https://github.com/RenzoCL/Ripper-Asistencia!
echo Render deberia empezar el deploy en unos segundos.
goto end

:error
echo.
echo ❌ ERROR CRITICO: No se pudo completar la operacion.
echo Asegurate de estar en la carpeta del proyecto y tener internet.

:end
pause