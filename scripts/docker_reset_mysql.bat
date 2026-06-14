@echo off
setlocal
cd /d "%~dp0\.."
echo.
echo ============================================================
echo This will remove ONLY the Docker named MySQL volume used by
echo the current project and rebuild the database from .env.
echo The legacy folder data\mysql will NOT be deleted.
echo ============================================================
choice /C YN /M "Continue"
if errorlevel 2 exit /b 0

docker compose down -v --remove-orphans
if errorlevel 1 exit /b 1

docker compose up --build
endlocal
