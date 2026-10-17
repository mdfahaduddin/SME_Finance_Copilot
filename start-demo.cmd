@echo off
rem One-command local demo of SME Finance Copilot (Windows). Needs Docker Desktop running.
rem Usage: start-demo.cmd      (optional: set DEMO_PORT=8090 first to use another port)
setlocal
cd /d "%~dp0"
if "%DEMO_PORT%"=="" set "DEMO_PORT=8080"

docker info >nul 2>&1
if errorlevel 1 (
  echo Docker is not running. Start Docker Desktop, wait for "Engine running", then try again.
  goto fail
)

echo Building and starting SME Finance Copilot. The first run takes a few minutes...
docker compose -f docker-compose.demo.yml up --build -d
if errorlevel 1 goto fail

echo Waiting for the app to answer...
for /l %%i in (1,1,90) do (
  curl -s -f -o nul "http://localhost:%DEMO_PORT%/api/ready" && goto ready
  ping -n 3 127.0.0.1 >nul
)
echo The app did not answer in time. Check the logs: docker compose -f docker-compose.demo.yml logs
goto fail

:ready
echo.
echo   ============================================================
echo     SME Finance Copilot is ready:  http://localhost:%DEMO_PORT%
echo     Sign in with a demo account: Owner, Accountant or Viewer
echo   ============================================================
echo     Logs:  docker compose -f docker-compose.demo.yml logs -f
echo     Stop:  docker compose -f docker-compose.demo.yml down
echo.
start "" "http://localhost:%DEMO_PORT%"
endlocal
exit /b 0

:fail
rem Keep the window open when the script was started by double-click.
echo %cmdcmdline% | find /i "/c" >nul && pause
endlocal
exit /b 1
