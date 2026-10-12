@echo off
chcp 65001 >nul
echo ============================================================
echo   微信数据分析工具 - 数据备份助手
echo ============================================================
echo.
echo 正在打开微信解密聊天数据目录 (output)...
echo.
echo 提示：换电脑时，只需将弹出的 output 文件夹复制到 U 盘即可！
echo.
set "DATA_DIR=%APPDATA%\wechat-data-analysis-hd\output"
if not exist "%DATA_DIR%" (
    mkdir "%DATA_DIR%" 2>nul
)
start "" explorer "%DATA_DIR%"
exit /b 0
