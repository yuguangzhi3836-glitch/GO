@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-local-wsl-backend.ps1" %*
exit /b %ERRORLEVEL%
