@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" goto setup_needed
".venv\Scripts\python.exe" tools\restore_submission.py
if errorlevel 1 goto failed
echo Registered-data guidance works without an AI model. A connected model is optional; enable the Local AI assistance checkbox when asking a question.
".venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8781 %*
if errorlevel 1 goto failed
exit /b 0
:setup_needed
echo Install the submission package first by running install-submission.bat.
exit /b 1
:failed
echo Submission startup failed. Check the installation and application logs.
exit /b 1
