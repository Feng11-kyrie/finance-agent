#!/bin/bash
# 本地定时报告运行脚本
# 用法: ./run_local.sh morning  或  ./run_local.sh afternoon

set -e
cd "$(dirname "$0")"

# cron 的 PATH 很短，补上 npm 全局 bin（cc-connect 安装在这里）
export PATH="$HOME/.npm-global/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"

# 加载环境变量
set -a
source .env
set +a

# 从文件加载 GCP 服务账号
export GCP_SERVICE_ACCOUNT=$(cat .gcp-sa.json)

# 启动 cc-connect（如果没在跑）
if ! pgrep -f "cc-connect" > /dev/null 2>&1; then
    echo "[$(date)] 启动 cc-connect..."
    nohup cc-connect > /tmp/cc-connect.log 2>&1 &
    sleep 3
fi

# 运行报告
python3 report_generator.py "$1"
