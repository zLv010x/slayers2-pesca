@echo off
setlocal
title Slayers 2 - Pesca (instalacao)
cd /d "%~dp0"
rem Procura o Python: primeiro o "py" (instalador do python.org), depois o "python".
set "PY="
where py >/dev/null 2>/dev/null && set "PY=py -3"
if not defined PY where python >/dev/null 2>/dev/null && set "PY=python"
if not defined PY (
    echo Python nao encontrado.
    echo Instale em https://www.python.org/downloads/ e marque "Add python.exe to PATH".
    pause
    exit /b 1
)
echo Usando: %PY%
if not exist ".venv\Scripts\python.exe" (
    %PY% -m venv .venv || (echo Nao consegui criar o ambiente .venv & pause & exit /b 1)
)
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r requirements.txt || (echo Falha ao instalar pacotes. Mande um print desta janela. & pause & exit /b 1)
echo.
echo Pronto! Agora abra o Iniciar.bat
pause
