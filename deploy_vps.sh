#!/usr/bin/env bash
# DOGE 币本位 OI 提醒 — 境外免费 VPS (Ubuntu) 一键部署
# 适用: Oracle Cloud Always Free / 任意非美区 Ubuntu 22.04+ 机器
# 用法(注意先下载再执行, 不要 curl | bash, 否则交互输入读不到):
#   curl -fsSL -o ~/deploy_vps.sh https://raw.githubusercontent.com/beijisi522/doge-oi/main/deploy_vps.sh
#   bash ~/deploy_vps.sh
set -euo pipefail

REPO="https://github.com/beijisi522/doge-oi.git"
DIR="$HOME/doge-oi"
ENVF="$HOME/.doge-oi.env"
SVC="/etc/systemd/system/doge-oi.service"
PY="$(command -v python3)"

echo "== 0/4 检查本机 IP 能否访问币安币本位接口 =="
"$PY" - <<'PYPROBE'
import urllib.request, sys
u = "https://dapi.binance.com/dapi/v1/ticker/price?symbol=DOGEUSD_PERP"
try:
    r = urllib.request.urlopen(u, timeout=10)
    print("  ✅ HTTP", r.status, "— 这台机器可用, 继续")
except Exception as e:
    print("  ❌", e)
    print("  -> 该区域 IP 被币安封锁(451 即地域限制), 请换非美区域重开实例")
    sys.exit(1)
PYPROBE

echo "== 1/4 安装依赖 / 拉取代码 =="
sudo apt-get update -qq
sudo apt-get install -y -qq git python3
if [ -d "$DIR/.git" ]; then
  git -C "$DIR" pull -q
else
  git clone -q "$REPO" "$DIR"
fi

echo "== 2/4 配置 Telegram (与 GitHub Secrets 里同两个值) =="
if [ ! -f "$ENVF" ]; then
  read -r -p "  Bot Token: " T < /dev/tty
  read -r -p "  Chat ID:   " C < /dev/tty
  printf 'DOGE_TG_TOKEN=%s\nDOGE_TG_CHAT_ID=%s\nTZ=Asia/Shanghai\n' "$T" "$C" > "$ENVF"
  chmod 600 "$ENVF"
else
  echo "  已有 $ENVF, 跳过"
fi

echo "== 3/4 建立 systemd 常驻服务 =="
sudo tee "$SVC" > /dev/null <<EOF
[Unit]
Description=DOGE 币本位 OI 提醒
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$(id -un)
WorkingDirectory=$DIR
EnvironmentFile=$ENVF
ExecStart=$PY -u $DIR/doge_oi_alert_v2.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF
sudo systemctl daemon-reload
sudo systemctl enable --now doge-oi.service > /dev/null

echo "== 4/4 运行状态 =="
sudo systemctl is-active doge-oi.service
echo
echo "实时日志: sudo journalctl -u doge-oi.service -f"
echo "--------------------------------------------"
sudo journalctl -u doge-oi.service -n 12 --no-pager
