@echo off
setlocal
cd /d "%~dp0"
if errorlevel 1 exit /b 1
call run-gongmudam.bat %*
set "result=%errorlevel%"
endlocal & exit /b %result%
