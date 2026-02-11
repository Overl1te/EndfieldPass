@echo off
setlocal

cd /d "%~dp0"

if not exist "manage.py" (
    echo [EndfieldPass] manage.py not found in project root.
    goto :error
)

set "VENV_DIR=.venv"
set "VENV_PY=%VENV_DIR%\Scripts\python.exe"

if not exist "%VENV_PY%" (
    echo [EndfieldPass] Virtual environment not found. Creating...
    where py >nul 2>&1
    if %errorlevel%==0 (
        py -3 -m venv "%VENV_DIR%"
    ) else (
        python -m venv "%VENV_DIR%"
    )
    if errorlevel 1 goto :error
)

set "PYTHON=%VENV_PY%"

echo [EndfieldPass] Installing dependencies...
%PYTHON% -m pip install -r requirements.txt
if errorlevel 1 goto :error

echo [EndfieldPass] Creating migrations...
%PYTHON% manage.py makemigrations
if errorlevel 1 goto :error

echo [EndfieldPass] Applying migrations...
%PYTHON% manage.py migrate
if errorlevel 1 goto :error

echo [EndfieldPass] Bootstrapping app data...
%PYTHON% manage.py bootstrap_app_data
if errorlevel 1 goto :error

echo [EndfieldPass] Ensuring superuser from .env...
%PYTHON% manage.py ensure_superuser
if errorlevel 1 goto :error

echo [EndfieldPass] Starting server at http://127.0.0.1:8000/
%PYTHON% manage.py runserver 127.0.0.1:8000
goto :eof

:error
echo [EndfieldPass] Failed to start.
pause
exit /b 1
