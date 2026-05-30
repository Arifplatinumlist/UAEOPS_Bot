@echo off
echo Checking setup...
python check_setup.py
if %errorlevel% neq 0 (
    echo.
    echo Fix the issues above, then run this file again.
    pause
    exit /b 1
)
echo.
echo Starting UAEOPS Bot...
echo Keep this window open. Closing it will stop the bot.
echo.
python app.py
pause
