@echo off
setlocal
title Slayers 2 - Pesca (instalacao)
cd /d "%~dp0"
where py >nul 2>nul || (echo Python nao encontrado. Instale em https://www.python.org/downloads/ e marque "Add python.exe to PATH". & pause & exit /b 1)
if not exist ".venv\Scripts\python.exe" py -3 -m venv .venv || (echo Nao consegui criar o ambiente .venv & pause & exit /b 1)
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r requirements.txt || (echo Falha ao instalar pacotes. & pause & exit /b 1)
echo.
echo Pronto! Agora abra o Iniciar.bat
pause
