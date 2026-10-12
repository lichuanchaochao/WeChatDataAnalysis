@echo off
chcp 65001 >nul
echo ============================================================
echo   微信数据分析工具 - 快速启动
echo ============================================================
echo.
set "APP_EXE=D:\自己开发WeChatDataAnalysis-main\WeChatDataAnalysis-HD\WeChatDataAnalysis-HD.exe"
set "INSTALLER=WeChatDataAnalysis-2.6.0-HD2-Setup.exe"

if exist "%APP_EXE%" (
    echo 正在启动 WeChatDataAnalysis-HD...
    start "" "%APP_EXE%"
) else (
    echo 检测到尚未安装软件，正在为您启动安装包: %INSTALLER%
    start "" "%INSTALLER%"
)
exit /b 0
