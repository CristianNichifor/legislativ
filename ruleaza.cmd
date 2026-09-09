@echo off
setlocal
cd /d "%~dp0"
if defined LEGISLATIV_PYTHON goto custom
py -3 -c "import sys; sys.exit(sys.version_info < (3, 12))" >nul 2>&1
if not errorlevel 1 (
  set "PYTHON_CMD=py -3"
  goto run
)
python -c "import sys; sys.exit(sys.version_info < (3, 12))" >nul 2>&1
if errorlevel 1 goto missing
set "PYTHON_CMD=python"
goto run
:custom
"%LEGISLATIV_PYTHON%" -c "import sys; sys.exit(sys.version_info < (3, 12))" >nul 2>&1
if errorlevel 1 goto missing
set PYTHON_CMD="%LEGISLATIV_PYTHON%"
:run
if exist legislativ.pyz (
  %PYTHON_CMD% -B legislativ.pyz %*
) else (
  %PYTHON_CMD% -B -m scripts.launcher %*
)
set "RESULT=%ERRORLEVEL%"
if not "%RESULT%"=="0" pause
exit /b %RESULT%
:missing
echo Instaleaza Python 3.12+ de la python.org. Python nu este inclus.
pause
exit /b 1
