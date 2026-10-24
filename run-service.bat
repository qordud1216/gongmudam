@echo off
setlocal
cd /d "%~dp0service"
if errorlevel 1 exit /b 1
call start-submission.bat %*
set "result=%errorlevel%"
endlocal & exit /b %result%
