@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  py -3.12 -m venv .venv
  if errorlevel 1 goto failed
)
".venv\Scripts\python.exe" -m pip install --no-index --find-links wheels -r requirements-travel.lock.txt
if errorlevel 1 goto failed
".venv\Scripts\python.exe" -m pip check
if errorlevel 1 goto failed
".venv\Scripts\python.exe" tools\restore_submission.py
if errorlevel 1 goto failed
exit /b 0
:failed
echo Submission setup failed. Check that Python 3.12 x64 and the bundled wheels are available.
exit /b 1
