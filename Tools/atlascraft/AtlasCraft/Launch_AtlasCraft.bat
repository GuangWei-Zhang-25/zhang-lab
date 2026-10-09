@echo off
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 (
  echo AtlasCraft requires Python 3.10 or newer from https://www.python.org/downloads/
  pause
  exit /b 1
)
py -3 -c "import sys; assert sys.version_info >= (3,10), 'AtlasCraft requires Python 3.10 or newer.'"
if errorlevel 1 (
  pause
  exit /b 1
)
if not exist .venv\Scripts\atlascraft.exe (
  py -3 -m venv .venv
  .venv\Scripts\python -m pip install .
  if errorlevel 1 (
    pause
    exit /b 1
  )
)
.venv\Scripts\atlascraft.exe serve
pause
