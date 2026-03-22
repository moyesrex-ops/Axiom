@echo off
title AXIOM
set "AXIOM_DIR=%~dp0"
cd /d "%AXIOM_DIR%"

echo [AXIOM] Booting up...
python main.py
