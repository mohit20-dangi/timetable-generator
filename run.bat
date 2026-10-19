@echo off
cd /d %~dp0
start "Backend" cmd /k call backend\run.bat
start "Frontend" cmd /k call frontend\run.bat
