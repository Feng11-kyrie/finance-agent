#!/bin/bash
# 本地定时报告运行脚本
# 用法: ./run_local.sh morning  或  ./run_local.sh afternoon
#
# 电脑开机 + cc-connect 运行时 → 微信 Bot 推送
# 电脑关机 / cc-connect 未运行时 → Server酱 兜底

set -e

cd "$(dirname "$0")"

# 加载环境变量
export $(grep -v '^#' .env | grep -v '^$' | xargs)

# 启动 cc-connect（如果没在跑）
if ! pgrep -f "cc-connect" > /dev/null 2>&1; then
    echo "启动 cc-connect..."
    nohup cc-connect > /tmp/cc-connect.log 2>&1 &
    sleep 3
fi

# 运行报告
python report_generator.py "$1"
