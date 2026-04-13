@echo off
REM =============================================================================
REM HoneyBadge E2E Test Runner - Local Development (Windows)
REM =============================================================================
REM This script runs E2E tests locally on Windows with the same setup as GitHub Actions.
REM
REM Usage:
REM   run-e2e-tests.bat                    Run all tests
REM   run-e2e-tests.bat --filter auth       Run only auth tests
REM   run-e2e-tests.bat --setup-only        Only start infra
REM   run-e2e-tests.bat --teardown-only     Only stop infra
REM =============================================================================

setlocal enabledelayedexpansion

set "SCRIPT_DIR=%~dp0.."
set "COMPOSE_FILE=%SCRIPT_DIR%\deploy\docker\docker-compose.yaml"
set "ENV_FILE=%SCRIPT_DIR%\deploy\docker\.env"

set "FILTER="
set "SETUP_ONLY="
set "TEARDOWN_ONLY="
set "SKIP_SETUP="

REM Parse arguments
:parse_args
if "%~1"=="" goto done_parsing
if "%~1"=="--filter" (
    set "FILTER=%~2"
    shift
    shift
    goto parse_args
)
if "%~1"=="--setup-only" (
    set "SETUP_ONLY=1"
    shift
    goto parse_args
)
if "%~1"=="--teardown-only" (
    set "TEARDOWN_ONLY=1"
    shift
    goto parse_args
)
if "%~1"=="--skip-setup" (
    set "SKIP_SETUP=1"
    shift
    goto parse_args
)
if "%~1"=="--help" goto show_help
if "%~1"=="-h" goto show_help
shift
goto parse_args

:done_parsing

echo.
echo ==============================================
echo   HoneyBadge E2E Test Runner
echo ==============================================
echo.

REM Handle teardown-only mode
if defined TEARDOWN_ONLY (
    echo [INFO] Tearing down infrastructure...
    cd /d "%SCRIPT_DIR%"
    docker compose -f "%COMPOSE_FILE%" --env-file "%ENV_FILE%" down
    echo [SUCCESS] Infrastructure stopped
    exit /b 0
)

REM Setup infrastructure unless skipped
if not defined SKIP_SETUP (
    echo [INFO] Setting up HoneyBadge infrastructure...
    cd /d "%SCRIPT_DIR%"

    REM Check Docker
    docker info >nul 2>&1
    if errorlevel 1 (
        echo [ERROR] Docker is not running. Please start Docker Desktop.
        exit /b 1
    )

    REM Start core services
    echo [INFO] Starting core services...
    docker compose -f "%COMPOSE_FILE%" --env-file "%ENV_FILE%" up -d

    REM Start observability
    echo [INFO] Starting observability stack...
    docker compose -f "%COMPOSE_FILE%" --env-file "%ENV_FILE%" --profile observability up -d

    REM Wait for services
    echo [INFO] Waiting for services to be healthy...

    :wait_server
    curl -sf "http://localhost:8090/api/health" >nul 2>&1
    if errorlevel 1 (
        echo Waiting for honeybadge-server... (Ctrl+C to abort)
        timeout /t 2 /nobreak >nul
        goto wait_server
    )
    echo [SUCCESS] honeybadge-server is ready

    :wait_auth
    curl -sf "http://localhost:8091/health" >nul 2>&1
    if errorlevel 1 (
        echo Waiting for honeybadge-auth...
        timeout /t 2 /nobreak >nul
        goto wait_auth
    )
    echo [SUCCESS] honeybadge-auth is ready

    REM Initialize NebulaGraph
    echo [INFO] Initializing NebulaGraph schema...
    bash "%SCRIPT_DIR%\deploy\docker\init-nebula.sh"

    REM Initialize HiClaw workers
    echo [INFO] Initializing HiClaw workers...
    bash "%SCRIPT_DIR%\deploy\hiclaw\init-workers.sh"

    REM Restart workers
    echo [INFO] Restarting workers...
    docker compose -f "%COMPOSE_FILE%" --env-file "%ENV_FILE%" restart hiclaw-graph-worker hiclaw-analytics-worker

    echo [INFO] Waiting for workers to connect...
    timeout /t 30 /nobreak >nul

    echo [SUCCESS] Infrastructure is ready!
)

REM Handle setup-only mode
if defined SETUP_ONLY (
    echo.
    echo [INFO] Setup complete. Run without --setup-only to run tests.
    exit /b 0
)

echo.
echo Ready to run tests. Press Ctrl+C to abort.
timeout /t 2 /nobreak >nul

REM Run tests
cd /d "%SCRIPT_DIR%"

set "PYTEST_CMD=pytest tests/e2e/ -v --tb=short --timeout=120"

REM Add test filter if specified
if defined FILTER (
    echo [INFO] Running tests with filter: %FILTER%

    if "%FILTER%"=="auth" set "PYTEST_CMD=%PYTEST_CMD% tests/e2e/test_01_auth.py"
    if "%FILTER%"=="chat" set "PYTEST_CMD=%PYTEST_CMD% tests/e2e/test_02_chat.py"
    if "%FILTER%"=="session" set "PYTEST_CMD=%PYTEST_CMD% tests/e2e/test_03_session.py"
    if "%FILTER%"=="isolation" set "PYTEST_CMD=%PYTEST_CMD% tests/e2e/test_04_isolation.py"
    if "%FILTER%"=="permission" set "PYTEST_CMD=%PYTEST_CMD% tests/e2e/test_05_permissions.py"
    if "%FILTER%"=="antihal" set "PYTEST_CMD=%PYTEST_CMD% tests/e2e/test_06_antihal.py"
    if "%FILTER%"=="mcp" set "PYTEST_CMD=%PYTEST_CMD% tests/e2e/test_07_mcp.py"
    if "%FILTER%"=="infra" set "PYTEST_CMD=%PYTEST_CMD% tests/e2e/test_08_infra.py"
    if "%FILTER%"=="observability" set "PYTEST_CMD=%PYTEST_CMD% tests/e2e/test_09_observability.py"
)

echo.
echo [INFO] Executing: %PYTEST_CMD%
echo.

%PYTEST_CMD%
set "TEST_RESULT=%ERRORLEVEL%"

if %TEST_RESULT% equ 0 (
    echo.
    echo ==============================================
    echo   All E2E Tests Passed!
    echo ==============================================
    exit /b 0
) else (
    echo.
    echo ==============================================
    echo   E2E Tests Failed!
    echo ==============================================
    echo.
    echo [INFO] Gathering debug information...
    echo === Recent Container Logs ===
    docker compose -f "%COMPOSE_FILE%" logs --tail=50
    exit /b %TEST_RESULT%
)

:show_help
echo Usage: %~nx0 [options]
echo.
echo Options:
echo   --filter ^<tests^>   Run specific test groups (auth,chat,session,isolation,permission,antihal,mcp,infra,observability)
echo   --setup-only        Only start infrastructure
echo   --teardown-only     Only stop infrastructure
echo   --skip-setup        Skip infrastructure setup
echo   --help, -h          Show this help message
