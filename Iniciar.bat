@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (echo Rode o Instalar.bat primeiro. & pause & exit /b 1)
start "" ".venv\Scripts\pythonw.exe" "src\app.py"
