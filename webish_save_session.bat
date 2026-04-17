@echo off
cd /d "%~dp0SBACO\webish"
echo.
echo === webish: First-run session save ===
echo A Chrome window will open. Log in to ChatGPT.
echo Session auto-saves when chat UI appears. No Enter needed.
echo.
python browser_query.py --save-session
echo.
pause
