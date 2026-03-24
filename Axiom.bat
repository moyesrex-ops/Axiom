@echo off
title AXIOM
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
set "AXIOM_DIR=%~dp0"
cd /d "%AXIOM_DIR%"

echo [AXIOM] Booting up...
python main.py %*
