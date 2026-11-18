@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion
cd /d "%~dp0"

set "PYTHONUTF8=1"
set "WINGET_LINKS=%LOCALAPPDATA%\Microsoft\WinGet\Links"
if exist "%WINGET_LINKS%" set "PATH=%PATH%;%WINGET_LINKS%"

for /d %%D in ("%LOCALAPPDATA%\Microsoft\WinGet\Packages\Gyan.FFmpeg*") do (
    for /d %%B in ("%%D\ffmpeg-*") do (
        if exist "%%B\bin\ffmpeg.exe" set "PATH=!PATH!;%%B\bin"
    )
)

set "PY_EXE=.venv\Scripts\python.exe"
if not exist "%PY_EXE%" (
    echo [THONG BAO] Moi truong .venv chua duoc cai dat. Dang chay CAI_DAT.bat...
    call CAI_DAT.bat
)

netstat -ano | findstr /R /C:":8765 .*LISTENING" >nul 2>nul
if %ERRORLEVEL% EQU 0 (
    echo May chu da dang chay tai http://127.0.0.1:8765 - Dang mo trinh duyet...
    start "" "http://127.0.0.1:8765"
    exit /b 0
)

echo ============================================================
echo   DANG KHOI DONG XUONG VIDEO TIKTOK (http://127.0.0.1:8765)
echo   Giu cua so nay mo trong khi lam video. Nhan Ctrl+C de tat.
echo ============================================================
start "" cmd /c "timeout /t 2 /nobreak >nul & start "" http://127.0.0.1:8765"
"%PY_EXE%" -m uvicorn app.main:app --host 127.0.0.1 --port 8765
pause
