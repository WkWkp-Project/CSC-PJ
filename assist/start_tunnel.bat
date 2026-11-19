@echo off
where cloudflared >nul 2>nul
if errorlevel 1 (
  echo cloudflared is not installed. Install it with this command in PowerShell:
  echo     winget install --id Cloudflare.cloudflared
  echo Then close ALL windows and open start_tunnel.bat again.
  pause
  exit /b 1
)
echo Starting tunnel. Copy the https://....trycloudflare.com address it prints.
echo   Facebook Callback URL = that address + /webhook/meta
echo   LINE Webhook URL      = that address + /webhook/line
echo Keep this window open. The address changes every time you start it.
cloudflared tunnel --url http://127.0.0.1:8080
pause
