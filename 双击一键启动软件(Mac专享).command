#!/bin/bash
# ============================================================
#  微信数据分析工具 - Mac 双击一键秒级启动脚本 (.command)
# ============================================================
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

echo "============================================================"
echo "  微信数据分析工具 - 正在为您极速启动..."
echo "  模式：100% 纯本地离线 | 自动打开界面"
echo "============================================================"
echo ""

# 1. 优先检查是否存在桌面独立客户端
APP_PATH="/Applications/WeChatDataAnalysis-HD.app"
ALT_APP_PATH="/Applications/WeChatDataAnalysis.app"
LOCAL_APP="$DIR/desktop/dist/mac-arm64/WeChatDataAnalysis-HD.app"

if [ -d "$APP_PATH" ]; then
    echo "检测到已安装独立桌面版，正在打开..."
    open "$APP_PATH"
    exit 0
elif [ -d "$ALT_APP_PATH" ]; then
    echo "检测到已安装独立桌面版，正在打开..."
    open "$ALT_APP_PATH"
    exit 0
elif [ -d "$LOCAL_APP" ]; then
    echo "检测到本地打包版，正在打开..."
    open "$LOCAL_APP"
    exit 0
fi

# 2. 启动本地免安装纯净服务
echo "正在启动本地解密服务与高仿微信前端界面..."

PYTHON_BIN=""
if [ -x "$DIR/.venv/bin/python" ]; then
    PYTHON_BIN="$DIR/.venv/bin/python"
elif command -v uv >/dev/null 2>&1; then
    PYTHON_BIN="uv run python"
elif command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN="python3"
else
    echo "[错误] 未检测到 Python 或 uv，请先安装 Python 3 环境。"
    read -n 1 -s -r -p "按任意键退出..."
    exit 1
fi

$PYTHON_BIN main.py
