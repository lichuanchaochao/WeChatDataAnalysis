@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ============================================================
echo   微信数据分析工具 - Windows 双击秒级极速启动
echo   模式：100%% 纯本地离线 ^| 自动打开界面
echo ============================================================
echo.

REM 1. 优先检查独立安装包或桌面版
set "APP_EXE=%LOCALAPPDATA%\Programs\WeChatDataAnalysis-HD\WeChatDataAnalysis-HD.exe"
set "ALT_EXE=desktop\dist\win-unpacked\WeChatDataAnalysis-HD.exe"

if exist "%APP_EXE%" (
    echo 检测到已安装独立桌面版，正在打开...
    start "" "%APP_EXE%"
    exit /b 0
)

if exist "%ALT_EXE%" (
    echo 检测到本地打包版，正在打开...
    start "" "%ALT_EXE%"
    exit /b 0
)

REM 2. 检查 Python / uv 环境以启动免安装纯净服务
echo 正在启动本地解密服务与高仿微信前端界面...

set "PYTHON_CMD="
if exist ".venv\Scripts\python.exe" (
    set "PYTHON_CMD=.venv\Scripts\python.exe"
) else (
    where uv >nul 2>nul
    if %errorlevel% equ 0 (
        set "PYTHON_CMD=uv run python"
    ) else (
        where python >nul 2>nul
        if %errorlevel% equ 0 (
            set "PYTHON_CMD=python"
        )
    )
)

if "%PYTHON_CMD%"=="" (
    echo [错误] 未检测到 Python 或 uv 环境，请先安装 Python 3.10+。
    pause
    exit /b 1
)

%PYTHON_CMD% main.py
