@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\install_desktop_shortcut.ps1" %*
set "result=%errorlevel%"
endlocal & exit /b %result%
