@echo off
setlocal
cd /d "%~dp0"
if not exist "service\.venv\Scripts\python.exe" (
  echo Run install-service.bat first.
  exit /b 1
)
"service\.venv\Scripts\python.exe" tools\prepare_public_runtime.py
if errorlevel 1 exit /b 1
set "GONGMUDAM_SERVICE_ROOT=%~dp0.local-runtime\service"
set "GONGMUDAM_PUBLIC=1"
"service\.venv\Scripts\python.exe" -m uvicorn integration.application:create_app --factory --host 127.0.0.1 --port 8892 %*
set "result=%errorlevel%"
endlocal & exit /b %result%
