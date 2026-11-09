@echo off
echo Starting tunnel. Copy the https://....trycloudflare.com address it prints.
echo LINE Webhook URL = that address + /webhook/line
cloudflared tunnel --url http://localhost:8080
pause
