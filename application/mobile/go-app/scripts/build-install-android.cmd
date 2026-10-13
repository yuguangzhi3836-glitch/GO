@echo off
setlocal
set "SCRIPT=%~dp0build-install-android.ps1"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT%" %*
exit /b %ERRORLEVEL%
