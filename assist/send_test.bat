@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONUTF8=1
set PYTHONPATH=.
if not exist local.env (
  echo local.env not found.
  pause
  exit /b 1
)
for /f "usebackq eol=# tokens=1,* delims==" %%A in ("local.env") do set "%%A=%%B"
if "%~1"=="" (
  echo Usage: send_test.bat "your test message"
  pause
  exit /b 1
)
py -m phase8.tools.simulate %*
pause
