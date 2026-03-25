@echo off
setlocal
echo [1] Forcefully killing old backend processes (Host)...
taskkill /F /IM uvicorn.exe /T 2>nul
taskkill /F /IM python.exe /T 2>nul

echo [2] Stopping Docker containers (if any)...
docker-compose down 2>nul

echo [3] Cleaning up database and migrations...
if exist db.sqlite3 del /F /Q db.sqlite3
if exist app\migrations\0001_initial.py del /F /Q app\migrations\0001_initial.py

echo [4] Installing Dependencies from requirements.txt...
python -m pip install -r requirements.txt
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Dependency installation failed! Please check your internet connection or python environment.
    pause
    exit /b %ERRORLEVEL%
)

echo [5] Initializing Django Database...
python manage.py makemigrations mirrai_app
python manage.py migrate

echo [6] Starting Django Server (MirrAI Backend) on Port 8001...
python manage.py runserver 8001
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Server failed to start.
    pause
)
