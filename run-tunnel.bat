@echo off
setlocal
cd /d "%~dp0"
if not exist "node_modules\wrangler\bin\wrangler.js" (
  echo Run npm ci first, then sign in to the correct Cloudflare account.
  exit /b 1
)
call npm.cmd run tunnel
set "result=%errorlevel%"
endlocal & exit /b %result%
