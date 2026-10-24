@echo off
setlocal
cd /d "%~dp0desktop"
if errorlevel 1 exit /b 1
py -3.12 server.py %*
set "result=%errorlevel%"
endlocal & exit /b %result%
