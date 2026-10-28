@echo off
rem Builds local\dist\wowsyukarinano\wowsyukarinano.exe. PyInstaller replaces that whole folder, so the
rem config.json and data\ inside it are moved aside and put back.
cd /d "%~dp0"
set KEEP=local\build\keep
if exist %KEEP% rmdir /s /q %KEEP%
mkdir %KEEP%
if exist local\dist\wowsyukarinano\config.json move local\dist\wowsyukarinano\config.json %KEEP%\ >nul
if exist local\dist\wowsyukarinano\data move local\dist\wowsyukarinano\data %KEEP%\data >nul
.venv\Scripts\python -m PyInstaller --noconfirm --distpath local\dist --workpath local\build wowsyukarinano.spec || goto :fail
call :restore
rem PyInstaller's work folder holds a wowsyukarinano.exe that cannot run on its own: remove it
if exist local\build\wowsyukarinano rmdir /s /q local\build\wowsyukarinano
echo.
echo Built: local\dist\wowsyukarinano\wowsyukarinano.exe
pause
exit /b 0
:fail
echo BUILD FAILED
call :restore
pause
exit /b 1
:restore
if not exist local\dist\wowsyukarinano mkdir local\dist\wowsyukarinano
if exist %KEEP%\config.json (move /y %KEEP%\config.json local\dist\wowsyukarinano\ >nul) else (copy /y config.json local\dist\wowsyukarinano\ >nul)
if exist %KEEP%\data (if not exist local\dist\wowsyukarinano\data move %KEEP%\data local\dist\wowsyukarinano\data >nul)
if not exist local\dist\wowsyukarinano\data mkdir local\dist\wowsyukarinano\data
exit /b 0
