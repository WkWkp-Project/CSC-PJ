@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONUTF8=1
set PYTHONPATH=.
if not exist local.env (
  echo local.env not found. Copy local.env.example to local.env and fill it in.
  pause
  exit /b 1
)
for /f "usebackq eol=# tokens=1,* delims==" %%A in ("local.env") do set "%%A=%%B"
echo Starting WakuFlow Assist. Keep this window open. Close it to stop.
py -m phase8.webhook_server
pause
