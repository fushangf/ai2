@echo off
setlocal
cd /d "%~dp0\.."
echo [AI Voice Draw] Starting Docker services...
docker compose up --build
endlocal
