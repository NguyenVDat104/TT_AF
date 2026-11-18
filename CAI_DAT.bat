@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion
cd /d "%~dp0"

echo ============================================================
echo   CAI DAT CONG CU XUONG VIDEO TIKTOK AFFILIATE (BAN 1.3)
echo ============================================================
echo.

set "WINGET_LINKS=%LOCALAPPDATA%\Microsoft\WinGet\Links"
if exist "%WINGET_LINKS%" set "PATH=%PATH%;%WINGET_LINKS%"

echo [1/4] Kiem tra Python 3...
set "PY_CMD="
where py >nul 2>nul
if %ERRORLEVEL% EQU 0 (
    py -3 --version >nul 2>nul
    if !ERRORLEVEL! EQU 0 set "PY_CMD=py -3"
)
if "!PY_CMD!"=="" (
    where python >nul 2>nul
    if !ERRORLEVEL! EQU 0 (
        python --version >nul 2>nul
        if !ERRORLEVEL! EQU 0 set "PY_CMD=python"
    )
)

if "!PY_CMD!"=="" (
    echo Chua tim thay Python. Dang cai dat Python 3.12 qua winget...
    winget install -e --id Python.Python.3.12 --scope user --accept-source-agreements --accept-package-agreements
    set "PY_FALLBACK=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
    if exist "!PY_FALLBACK!" (
        set "PY_CMD="!PY_FALLBACK!""
    ) else (
        echo [LOI] Khong tim thay Python sau khi cai. Hay dong cua so nay va chay lai CAI_DAT.bat.
        pause
        exit /b 1
    )
)
echo   -> Da tim thay Python: !PY_CMD!

echo.
echo [2/4] Kiem tra FFmpeg...
where ffmpeg >nul 2>nul
if %ERRORLEVEL% NEQ 0 (
    echo Chua tim thay FFmpeg. Dang cai dat Gyan.FFmpeg qua winget...
    winget install -e --id Gyan.FFmpeg --accept-source-agreements --accept-package-agreements
    if exist "%WINGET_LINKS%" set "PATH=%PATH%;%WINGET_LINKS%"
    for /d %%D in ("%LOCALAPPDATA%\Microsoft\WinGet\Packages\Gyan.FFmpeg*") do (
        for /d %%B in ("%%D\ffmpeg-*") do (
            if exist "%%B\bin\ffmpeg.exe" set "PATH=!PATH!;%%B\bin"
        )
    )
)
where ffmpeg >nul 2>nul
if %ERRORLEVEL% EQU 0 (
    echo   -> Da san sang FFmpeg.
) else (
    echo   -> [CANH BAO] FFmpeg vua cai xong. MO_CONG_CU.bat se tu dong tim duong dan FFmpeg.
)

echo.
echo [3/4] Khoi tao moi truong ao (.venv)...
if not exist ".venv\Scripts\python.exe" (
    !PY_CMD! -m venv .venv
)
if not exist ".venv\Scripts\python.exe" (
    echo [LOI] Khong the tao moi truong ao .venv!
    pause
    exit /b 1
)

echo.
echo [4/4] Cai dat cac thu vien Python (FastAPI, Pillow, Edge-TTS...)...
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install --upgrade -r requirements.txt

if not exist "san_pham" mkdir "san_pham"
if not exist "san_sang_dang" mkdir "san_sang_dang"
if not exist "_tam" mkdir "_tam"
if not exist "app\assets" mkdir "app\assets"

echo.
echo ============================================================
echo   CAI DAT HOAN TAT!
echo   Ban co the nhap dup vao MO_CONG_CU.bat de bat dau su dung.
echo ============================================================
pause
