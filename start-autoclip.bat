@echo off
setlocal EnableExtensions EnableDelayedExpansion
title AutoClip - Local Launcher

rem Run from the repository root no matter where this file was launched from.
cd /d "%~dp0"

set "APP_URL=http://localhost:8000"
set "OLLAMA_URL=http://127.0.0.1:11434"
set "OLLAMA_HOST=127.0.0.1:11434"
set "VENV_PYTHON=%~dp0.venv\Scripts\python.exe"
set "FRONTEND_BUILD=%~dp0backend\autoclip\static\index.html"
set "OLLAMA_EXE="

echo.
echo  ===============================================
echo   AutoClip local launcher
echo  ===============================================
echo   App:    %APP_URL%
echo   Ollama: %OLLAMA_URL%
echo.

rem curl.exe is used for the local readiness checks. It ships with current
rem Windows 10 and Windows 11 installations.
where curl.exe >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Windows curl.exe was not found in PATH.
    echo         AutoClip needs it for the launcher readiness checks.
    pause
    exit /b 1
)
for /f "delims=" %%I in ('where ollama.exe 2^>nul') do if not defined OLLAMA_EXE set "OLLAMA_EXE=%%I"
if not defined OLLAMA_EXE if exist "%USERPROFILE%\.local\bin\ollama.exe" set "OLLAMA_EXE=%USERPROFILE%\.local\bin\ollama.exe"
if not defined OLLAMA_EXE if exist "%LOCALAPPDATA%\Programs\Ollama\ollama.exe" set "OLLAMA_EXE=%LOCALAPPDATA%\Programs\Ollama\ollama.exe"

rem Start Ollama only when it is not already answering on loopback.
curl.exe -fsS --max-time 2 "%OLLAMA_URL%/api/tags" >nul 2>&1
if errorlevel 1 goto :start_ollama
echo [OK] Ollama is already running.
goto :check_autoclip

:start_ollama
if not defined OLLAMA_EXE (
    echo [WARN] Ollama was not found. AutoClip will still start.
    echo        If you use Ollama for clip selection, install it from https://ollama.com
    goto :check_autoclip
)
echo [INFO] Starting Ollama on loopback...
start "AutoClip Ollama" /min "%OLLAMA_EXE%" serve

set "OLLAMA_READY="
for /l %%I in (1,1,30) do (
    curl.exe -fsS --max-time 2 "%OLLAMA_URL%/api/tags" >nul 2>&1
    if not errorlevel 1 (
        set "OLLAMA_READY=1"
        goto :ollama_ready
    )
    ping -n 2 127.0.0.1 >nul 2>&1
)
if not defined OLLAMA_READY (
    echo [WARN] Ollama did not become ready within 30 seconds.
    echo        AutoClip will still start; check the AutoClip Ollama window if needed.
    goto :check_autoclip
)
echo [OK] Ollama is ready.

:ollama_ready
:check_autoclip
if not exist "%VENV_PYTHON%" (
    echo [ERROR] The local Python environment was not found.
    echo         Expected: "%VENV_PYTHON%"
    echo         Create it with: uv venv --python 3.11
    echo         Then install with: uv pip install -e ".[dev]"
    pause
    exit /b 1
)
if not exist "%FRONTEND_BUILD%" (
    echo [ERROR] The frontend build is missing.
    echo         Run this from the repository root:
    echo           cd frontend ^&^& npm ci ^&^& npm run build ^&^& cd ..
    pause
    exit /b 1
)
rem If AutoClip is already healthy, only open it in the browser.
curl.exe -fsS --max-time 2 "%APP_URL%/api/health" >nul 2>&1
if not errorlevel 1 (
    echo [OK] AutoClip is already running.
    echo [INFO] Opening %APP_URL%
    start "" "%APP_URL%"
    exit /b 0
)
echo [INFO] Starting AutoClip...
echo [INFO] The browser will open automatically when the server is ready.
echo [INFO] Press Ctrl+C in this window to stop AutoClip.
echo.
"%VENV_PYTHON%" -m autoclip.cli serve --host 127.0.0.1 --port 8000 --open
set "EXIT_CODE=%ERRORLEVEL%"

if not "%EXIT_CODE%"=="0" (
    echo.
    echo [ERROR] AutoClip exited with code %EXIT_CODE%.
    echo         Review the error above and fix the reported dependency or port issue.
    pause
)
exit /b %EXIT_CODE%
