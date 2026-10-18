@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist logs mkdir logs
set PYTHONIOENCODING=utf-8
"C:\Users\a5013\AppData\Local\Programs\Python\Python313\python.exe" daily_run.py >> logs\task.log 2>&1
