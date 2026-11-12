#!/usr/bin/env bash
# DOGE 币本位 OI 提醒 启动器 (macOS / Linux / 安卓 Termux)
# 用法:  chmod +x start_doge_oi.sh  &&  ./start_doge_oi.sh
# 请与 doge_oi_alert_v2.py 放在同一目录
cd "$(dirname "$0")" || exit 1

echo "============================================"
echo "  DOGE 币本位 OI 提醒  启动器"
echo "============================================"
echo

PY="$(command -v python3 || command -v python)"
if [ -z "$PY" ]; then
  echo "[错误] 没找到 python3, 请先安装 Python 3"
  exit 1
fi

if [ -z "$DOGE_TG_TOKEN" ]; then
  read -r -p "粘贴 Bot Token: " DOGE_TG_TOKEN
  export DOGE_TG_TOKEN
fi
if [ -z "$DOGE_TG_CHAT_ID" ]; then
  read -r -p "粘贴 Chat ID:  " DOGE_TG_CHAT_ID
  export DOGE_TG_CHAT_ID
fi
echo

echo "[1/2] 正在自检配置和网络..."
"$PY" doge_oi_alert_v2.py --check
echo
echo "--------------------------------------------"
echo "  若上面 1/2/3 不是全 OK, 先按提示修好再继续"
echo "--------------------------------------------"
echo
MODE_LINE="$(grep -E '^MODE=' mode.conf 2>/dev/null | tail -n 1)"
echo "  当前模式: ${MODE_LINE:-MODE=unknown}"
case "$MODE_LINE" in
  *worker*) ;;
  *) echo "  注意: 非 worker 模式下本地进程只判定、不推送 Telegram;"
     echo "        如需本地收到提醒, 请把 mode.conf 改成 MODE=worker" ;;
esac
echo
echo "[2/2] 启动监控 (按 Ctrl+C 停止)..."
"$PY" doge_oi_alert_v2.py
