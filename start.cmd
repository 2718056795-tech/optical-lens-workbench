@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Environment not ready. Give DEPLOY_FOR_AI.md to your AI.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -I -B "launch_workbench.py"
if errorlevel 1 (
  echo Launch blocked. Read launch_check.json or run deploy.ps1 to verify deployment.
  pause
  exit /b 1
)
