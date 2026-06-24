@echo off
setlocal EnableDelayedExpansion

set MAX_RETRIES=5
set RETRY_WAIT=10

echo ============================================================
echo  TestPilot AI - Setup
echo ============================================================
echo.

:: ---------------------------------------------------------------
:: Pull images with retry
:: ---------------------------------------------------------------
call :pull_with_retry "postgres:15"
if errorlevel 1 (
    echo [ERROR] Failed to pull postgres:15 after %MAX_RETRIES% attempts. Aborting.
    exit /b 1
)

call :pull_with_retry "localstack/localstack:latest"
if errorlevel 1 (
    echo [ERROR] Failed to pull localstack/localstack:latest after %MAX_RETRIES% attempts. Aborting.
    exit /b 1
)

:: ---------------------------------------------------------------
:: Start the stack
:: ---------------------------------------------------------------
echo.
echo [INFO] All images ready. Starting docker compose...
echo.

docker compose up --build
if errorlevel 1 (
    echo.
    echo [ERROR] docker compose up --build failed.
    exit /b 1
)

exit /b 0


:: ---------------------------------------------------------------
:: :pull_with_retry <image>
:: ---------------------------------------------------------------
:pull_with_retry
set IMAGE=%~1
set ATTEMPT=0

:retry_loop
set /a ATTEMPT+=1
echo [INFO] Pulling %IMAGE% (attempt !ATTEMPT!/%MAX_RETRIES%)...
docker pull %IMAGE%
if not errorlevel 1 (
    echo [OK] Pulled %IMAGE% successfully.
    exit /b 0
)
if !ATTEMPT! lss %MAX_RETRIES% (
    echo [WARN] Pull failed. Retrying in %RETRY_WAIT% seconds...
    timeout /t %RETRY_WAIT% /nobreak >nul
    goto retry_loop
)
exit /b 1
