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

echo [1/4] Checking Python dependencies ...
python -c "import flask, pandas, sklearn, joblib" >nul 2>nul
if errorlevel 1 (
    echo Dependencies missing, installing ...
    python -m pip install --disable-pip-version-check -r requirements.txt
    if errorlevel 1 (
        echo Default PyPI failed, trying Tsinghua mirror ...
        python -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
        if errorlevel 1 (
            echo [ERROR] Dependency installation failed.
            echo Please check your network and run this file again.
            pause
            exit /b 1
        )
    )
) else (
    echo Dependencies already installed.
)

if not exist "data\load_data.csv" (
    echo [2/4] Generating sample data ...
    python data\generate_data.py
) else (
    echo [2/4] Data file already exists.
)

if not exist "data\grid.db" (
    echo [3/4] Initializing database ...
    python scripts\init_db.py
) else (
    echo [3/4] Database already exists.
)

echo [4/4] Training model and detecting anomalies ...
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
