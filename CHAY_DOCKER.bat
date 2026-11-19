@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion
cd /d "%~dp0"

echo ============================================================
echo   KHOI DONG XUONG VIDEO TIKTOK BANG DOCKER (LOCAL)
echo ============================================================

REM Kiem tra Docker da chay chua
docker info >nul 2>nul
if %ERRORLEVEL% NEQ 0 (
    echo [THONG BAO] Docker chua chay. Dang khoi dong Docker Desktop...
    if exist "C:\Program Files\Docker\Docker\Docker Desktop.exe" (
        start "" "C:\Program Files\Docker\Docker\Docker Desktop.exe"
    )
    echo Dang doi Docker Engine san sang...
    :wait_docker
    timeout /t 5 /nobreak >nul
    docker info >nul 2>nul
    if %ERRORLEVEL% NEQ 0 (
        echo   ...van dang cho Docker khoi dong...
        goto wait_docker
    )
    echo [OK] Docker Engine da san sang!
)

echo.
echo [1/3] Dang build Docker Image (xuong-video-tiktok:latest)...
docker compose build

echo.
echo [2/3] Dang khoi chay Container...
docker compose up -d

echo.
echo [3/3] Dang mo trinh duyet http://localhost:8765 ...
timeout /t 3 /nobreak >nul
start "" "http://localhost:8765"

echo.
echo ============================================================
echo   XUONG VIDEO DANG CHAY TAI: http://localhost:8765
echo   Tai khoan: admin  ^|  Mat khau: admin
echo   Toan bo video render se luu vao thu muc san_pham va san_sang_dang!
echo.
echo   DANG THEO DOI NHAT KY TRUC TIEP (LIVE LOGS):
echo   (Nhan Ctrl+C neu muon dung xem log, container van chay ngam)
echo ============================================================
docker compose logs -f xuong-video-tiktok
