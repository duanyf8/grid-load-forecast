@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

echo ============================================================
echo   台区负荷预测与异常用电预警系统 - 一键启动
echo ============================================================
echo.

where python >nul 2>nul
if errorlevel 1 (
    echo [错误] 没有找到 python 命令。
    echo 请先安装 Python 3.10 及以上版本，安装时勾选 "Add Python to PATH"。
    echo 下载地址：https://www.python.org/downloads/
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo [1/5] 创建虚拟环境 .venv ...
    python -m venv .venv
    if errorlevel 1 (
        echo [错误] 虚拟环境创建失败。
        pause
        exit /b 1
    )
) else (
    echo [1/5] 虚拟环境已存在，跳过创建。
)

call ".venv\Scripts\activate.bat"

echo [2/5] 安装/检查依赖 ...
python -m pip install --disable-pip-version-check -r requirements.txt
if errorlevel 1 (
    echo [错误] 依赖安装失败，请检查网络后重试。
    pause
    exit /b 1
)

if not exist "data\load_data.csv" (
    echo [3/5] 生成模拟数据 ...
    python data\generate_data.py
) else (
    echo [3/5] 数据文件已存在，跳过生成。
)

if not exist "data\grid.db" (
    echo [4/5] 初始化数据库 ...
    python scripts\init_db.py
) else (
    echo [4/5] 数据库已存在，跳过初始化。
)

echo [5/5] 训练模型并检测异常 ...
python ml\train.py
if errorlevel 1 (
    echo [错误] 模型训练失败。
    pause
    exit /b 1
)
python ml\anomaly.py
if errorlevel 1 (
    echo [错误] 异常检测失败。
    pause
    exit /b 1
)

echo.
echo ============================================================
echo   启动成功，请在浏览器打开：
echo   http://127.0.0.1:5000
echo   按 Ctrl+C 停止服务
echo ============================================================
echo.
python app.py

pause
