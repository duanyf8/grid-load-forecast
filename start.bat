@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

echo ============================================================
echo   Grid Load Forecast - One-click Start
echo ============================================================
echo.

where python >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Python not found.
    echo Install Python 3.10+ and check "Add Python to PATH".
    echo Download: https://www.python.org/downloads/
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo [1/5] Creating virtual environment .venv ...
    python -m venv .venv
    if errorlevel 1 (
        echo [ERROR] Failed to create virtual environment.
        pause
        exit /b 1
    )
) else (
    echo [1/5] Virtual environment already exists.
)

call ".venv\Scripts\activate.bat"

echo [2/5] Installing dependencies ...
python -m pip install --disable-pip-version-check -r requirements.txt
if errorlevel 1 (
    echo [ERROR] Dependency installation failed.
    echo Try the Tsinghua mirror:
    echo python -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
    pause
    exit /b 1
)

if not exist "data\load_data.csv" (
    echo [3/5] Generating sample data ...
    python data\generate_data.py
) else (
    echo [3/5] Data file already exists.
)

if not exist "data\grid.db" (
    echo [4/5] Initializing database ...
    python scripts\init_db.py
) else (
    echo [4/5] Database already exists.
)

echo [5/5] Training model and detecting anomalies ...
python ml\train.py
if errorlevel 1 (
    echo [ERROR] Model training failed.
    pause
    exit /b 1
)
python ml\anomaly.py
if errorlevel 1 (
    echo [ERROR] Anomaly detection failed.
    pause
    exit /b 1
)

echo.
echo ============================================================
echo   Ready. Open in your browser:
echo   http://127.0.0.1:5000
echo   Press Ctrl+C to stop the server.
echo ============================================================
echo.
python app.py

pause
