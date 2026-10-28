@echo off
rem Double-click to start wowsyukarinano. Close this window to quit.
title wowsyukarinano
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo [wowsyukarinano] .venv not found. Set it up once:
    echo     python -m venv .venv
    echo     .venv\Scripts\python -m pip install -r requirements.txt
    pause
    exit /b 1
)
".venv\Scripts\python.exe" -u -m wowsyukarinano.app
if errorlevel 1 (
    echo.
    echo [wowsyukarinano] exited with an error, see the messages above.
    pause
)
