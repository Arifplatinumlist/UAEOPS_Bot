#!/bin/bash
echo "Checking setup..."
python3 check_setup.py || { echo "Fix the issues above, then run this script again."; exit 1; }
echo ""
echo "Starting UAEOPS Bot..."
echo "Keep this terminal open. Closing it will stop the bot."
echo ""
python3 app.py
