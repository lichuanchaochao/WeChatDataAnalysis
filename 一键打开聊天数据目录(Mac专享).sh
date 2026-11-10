#!/bin/bash
# 微信数据分析工具 - Mac 数据备份助手
DIR="$(cd "$(dirname "$0")" && pwd)"
DATA_DIR="$HOME/Library/Application Support/wechat-data-analysis-hd/output"
ALT_DATA_DIR="$DIR/output"

echo "============================================================"
echo "  微信数据分析工具 - Mac 数据备份助手"
echo "============================================================"
echo ""
echo "正在定位解密聊天数据目录 (output)..."
echo "提示：换电脑时，只需将该 output 目录复制到 U 盘或另一台电脑即可！"
echo ""

if [ -d "$DATA_DIR" ]; then
    open "$DATA_DIR"
elif [ -d "$ALT_DATA_DIR" ]; then
    open "$ALT_DATA_DIR"
else
    mkdir -p "$DATA_DIR"
    open "$DATA_DIR"
fi
