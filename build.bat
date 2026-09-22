@echo off
setlocal EnableExtensions EnableDelayedExpansion

rem ============================================================
rem  SensorHost one-click build wrapper (Windows)
rem
rem  Delegates to tools\package_host.ps1 which handles:
rem    - venv creation and reuse under build\host-package\.venv
rem    - dependency reconciliation (requirements-build.txt + [dev])
rem    - pytest gate with offscreen Qt
rem    - PyInstaller build via STM32SensorHost.spec
rem    - packaged smoke test + SHA-256 manifest under dist\host\
rem
rem  Usage:
rem    build.bat                              default build
rem    build.bat --skip-tests                 skip the pytest gate
rem    build.bat --clean                      recreate the build venv
rem    build.bat --python C:\path\python.exe  explicit interpreter
rem    build.bat --no-pause                   do not pause at exit (CI)
rem    build.bat --help
rem
rem  Requires: Python 3.11 or newer, PowerShell 5.1 or newer.
rem  Output  : dist\host\VibrationSensorHost-<version>-win64.exe (+ .json)
rem
rem  Exit codes: 0 success, 1 build/ps1 failure, 2 usage error.
rem ============================================================

set "REPO_ROOT=%~dp0"
if "!REPO_ROOT:~-1!"=="\" set "REPO_ROOT=!REPO_ROOT:~0,-1!"
set "PS_SCRIPT=!REPO_ROOT!\tools\package_host.ps1"
set "PS_ARGS="
set "NO_PAUSE="
set "EXIT_CODE=0"

rem Pre-scan the whole command line so --no-pause works at any position,
rem including after --help which short-circuits the parse loop below.
set "ALL_ARGS=%*"
echo(!ALL_ARGS! | find /I "--no-pause" >nul && set "NO_PAUSE=1"

if not exist "!PS_SCRIPT!" (
    echo [ERROR] Cannot find !PS_SCRIPT!
    echo         Please run build.bat from a complete SensorHost checkout.
    set "EXIT_CODE=1"
    goto end
)

rem ------------------------------------------------------------
rem  Argument parsing uses goto labels instead of parenthesized
rem  blocks so that %1 re-expands correctly after each shift.
rem ------------------------------------------------------------
:parse
if "%~1"=="" goto run
set "ARG=%~1"
if /I "!ARG!"=="--skip-tests" goto opt_skip_tests
if /I "!ARG!"=="--clean"      goto opt_clean
if /I "!ARG!"=="--python"     goto opt_python
if /I "!ARG!"=="--no-pause"   goto opt_no_pause
if /I "!ARG!"=="-h"           goto opt_help
if /I "!ARG!"=="--help"       goto opt_help
echo [ERROR] Unknown option: !ARG!
set "EXIT_CODE=2"
goto opt_help

:opt_skip_tests
set PS_ARGS=!PS_ARGS! -SkipTests
shift
goto parse

:opt_clean
set PS_ARGS=!PS_ARGS! -CleanEnvironment
shift
goto parse

:opt_python
shift
if "%~1"=="" goto err_python_missing
set "PY_ARG=%~1"
if "!PY_ARG:~0,1!"=="-" goto err_python_missing
set PS_ARGS=!PS_ARGS! -Python "!PY_ARG!"
shift
goto parse

:err_python_missing
echo [ERROR] --python requires an executable path ^(not another flag or nothing^).
set "EXIT_CODE=2"
goto end

:opt_no_pause
set "NO_PAUSE=1"
shift
goto parse

:opt_help
echo.
echo SensorHost build wrapper ^(Windows^)
echo.
echo Usage: build.bat [options]
echo.
echo Options:
echo   --skip-tests            Skip the pytest gate before packaging.
echo   --clean                 Recreate build\host-package\.venv from scratch.
echo   --python ^<path^>         Use an explicit Python 3.11+ interpreter.
echo   --no-pause              Do not pause at exit ^(for CI or scripted use^).
echo   -h, --help              Show this help and exit.
echo.
echo Output: dist\host\VibrationSensorHost-^<version^>-win64.exe ^(plus .json manifest^)
echo.
echo The wrapper delegates to tools\package_host.ps1 which creates an isolated
echo venv, installs pinned dependencies, runs tests, invokes PyInstaller and
echo smoke-tests the packaged EXE. The first build downloads PyInstaller and
echo PyQt6 wheels; later builds reuse the cached environment.
if "!EXIT_CODE!"=="0" set "EXIT_CODE=0"
goto end

:run
echo.
echo [INFO] Repository root : !REPO_ROOT!
echo [INFO] Packaging script: !PS_SCRIPT!
if defined PS_ARGS echo [INFO] Extra arguments : !PS_ARGS!
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "!PS_SCRIPT!" !PS_ARGS!
set "EXIT_CODE=!ERRORLEVEL!"

echo.
if "!EXIT_CODE!"=="0" (
    echo [OK] Build succeeded. Artifact under dist\host\
) else (
    echo [ERROR] Build failed with exit code !EXIT_CODE!.
)

:end
rem Pause by default so Explorer double-click keeps the window open.
rem Pass --no-pause to skip when driven by another script or CI.
if not defined NO_PAUSE pause
rem NOTE: use %EXIT_CODE% (immediate expansion) so the value is baked into
rem the command line before endlocal wipes it. !EXIT_CODE! would evaluate
rem after endlocal and always yield 0.
endlocal & exit /b %EXIT_CODE%
