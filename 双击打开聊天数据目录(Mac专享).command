#!/bin/bash
# ============================================================
#  微信数据分析工具 - Mac 双击打开数据目录 (.command)
# ============================================================
DIR="$(cd "$(dirname "$0")" && pwd)"
DATA_DIR="$HOME/Library/Application Support/wechat-data-analysis-hd/output"
ALT_DATA_DIR="$DIR/output"

echo "============================================================"
echo "  微信数据分析工具 - Mac 数据备份助手"
echo "============================================================"
echo ""
echo "正在定位聊天数据输出目录 (output)..."
echo "提示：换电脑或备份时，只需将该 output 目录复制即可！"
echo ""

if [ -d "$DATA_DIR" ]; then
    open "$DATA_DIR"
elif [ -d "$ALT_DATA_DIR" ]; then
    open "$ALT_DATA_DIR"
else
    mkdir -p "$ALT_DATA_DIR"
    open "$ALT_DATA_DIR"
fi
