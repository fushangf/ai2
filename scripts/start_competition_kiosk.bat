@echo off
setlocal
cd /d "%~dp0\.."
set COMPETITION_KIOSK_MODE=true
set COMPETITION_DEMO_LOCALHOST_ONLY=true
if "%DATABASE_URL%"=="" set DATABASE_URL=sqlite:///./data/competition.db

start "AI Voice Draw Server" cmd /c "python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000"
timeout /t 3 /nobreak >nul

set "BROWSER=%ProgramFiles%\Google\Chrome\Application\chrome.exe"
if not exist "%BROWSER%" set "BROWSER=%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"
if not exist "%BROWSER%" set "BROWSER=%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"

if exist "%BROWSER%" (
  start "" "%BROWSER%" --kiosk --autoplay-policy=no-user-gesture-required --use-fake-ui-for-media-stream http://127.0.0.1:8000/workspace
) else (
  start "" http://127.0.0.1:8000/workspace
  echo 未找到 Chrome/Edge，已使用系统默认浏览器打开。
)
endlocal
