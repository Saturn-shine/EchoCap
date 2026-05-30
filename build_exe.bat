@echo off
REM ============================================================
REM EchoCap — build EXE + Windows installer
REM ============================================================
REM Prerequisites:
REM   pip install pyinstaller
REM   pip install -r requirements.txt
REM   Inno Setup 6 (installed via winget or jrsoftware.org)
REM ============================================================

cd /d "%~dp0"

REM Activate conda environment (so python/pip resolve correctly)
call "C:\Users\saturnshine\miniconda3\Scripts\activate.bat" test
if %errorlevel% neq 0 (
    echo WARNING: Could not activate conda environment 'test'.
    echo Trying with system python...
)

REM --- Locate Inno Setup ---
set "ISCC="
if exist "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" (
    set "ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
)
if exist "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" (
    set "ISCC=C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
)
if "%ISCC%"=="" (
    echo ERROR: Inno Setup 6 not found.
    echo Install with: winget install JRSoftware.InnoSetup
    echo Or download from: https://jrsoftware.org
    pause
    exit /b 1
)

REM ============================================================
REM [1/4] App icon
REM ============================================================
echo.
echo [1/4] App icon...

if not exist "app_icon.ico" (
    python -c "from PyQt6.QtWidgets import QApplication; import sys; app=QApplication(sys.argv); from app_icon import get_app_icon; get_app_icon()"
    if %errorlevel% neq 0 (
        echo ERROR: Failed to generate app icon.
        pause
        exit /b 1
    )
    echo   Generated.
) else (
    echo   Already exists.
)

REM ============================================================
REM [2/4] PyInstaller build
REM ============================================================
echo.
echo [2/4] Building EchoCap.exe with PyInstaller...
echo   (this may take several minutes)

pyinstaller --clean EchoCap.spec

if %errorlevel% neq 0 (
    echo.
    echo ERROR: PyInstaller build failed (code %errorlevel%).
    pause
    exit /b 1
)
echo   Done.

REM ============================================================
REM [3/4] Models
REM ============================================================
echo.
echo [3/4] Preparing models...

python prepare_models.py
if %errorlevel% neq 0 (
    echo WARNING: Model preparation failed (code %errorlevel%).
    echo Installer will be built without models.
)

REM ============================================================
REM [4/4] Inno Setup installer
REM ============================================================
echo.
echo [4/4] Building installer with Inno Setup...

"%ISCC%" installer.iss
if %errorlevel% neq 0 (
    echo.
    echo ERROR: Inno Setup build failed (code %errorlevel%).
    pause
    exit /b 1
)

REM ============================================================
echo.
echo ============================================================
echo BUILD COMPLETE
echo ============================================================
echo.
echo   dist\EchoCap.exe        - portable executable
echo   dist\EchoCap_Setup.exe  - Windows installer
echo ============================================================
pause
