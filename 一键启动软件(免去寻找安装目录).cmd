@echo off
chcp 65001 >nul
cd /d "%~dp0"
call "双击一键启动软件(Windows专享).cmd"
exit /b %errorlevel%
