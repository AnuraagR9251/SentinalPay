@echo off
title Senetinal Pay
echo ========================================================
echo         Starting Senetinal Pay Development Server...
echo ========================================================
echo.
cd /d "%~dp0"
start http://localhost:5173
npm run dev
pause
