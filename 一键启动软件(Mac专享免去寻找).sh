#!/bin/bash
# 微信数据分析工具 - Mac 快速启动脚本
APP_PATH="/Applications/WeChatDataAnalysis-HD.app"
ALT_APP_PATH="/Applications/WeChatDataAnalysis.app"
DIR="$(cd "$(dirname "$0")" && pwd)"

echo "============================================================"
echo "  微信数据分析工具 - Mac 快速启动"
echo "============================================================"
echo ""

if [ -d "$APP_PATH" ]; then
    echo "正在启动 WeChatDataAnalysis-HD..."
    open "$APP_PATH"
elif [ -d "$ALT_APP_PATH" ]; then
    echo "正在启动 WeChatDataAnalysis..."
    open "$ALT_APP_PATH"
else
    DMG_FILE=$(find "$DIR" -maxdepth 2 -name "*.dmg" | head -n 1)
    if [ -n "$DMG_FILE" ]; then
        echo "检测到安装包，正在为您挂载并打开: $(basename "$DMG_FILE")"
        open "$DMG_FILE"
    else
        echo "未检测到安装包，正在启动本地服务..."
        cd "$DIR/desktop" && npm run dev
    fi
fi
