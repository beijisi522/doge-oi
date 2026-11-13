#!/bin/bash
# DOGE OI 监控 — macOS 桌面通知转发器
#
# 作用: 每次 GitHub Actions 判定完成后, 若真的往 Telegram 推了 A 级信号,
#       就在 Mac 屏幕右上角弹一条系统通知 + 声音(Glass)。不开 Telegram 也能看到。
# 原理: 本机连不上 OKX / 币安 / Telegram(curl 000), 但 api.github.com 可达,
#       因此从「已完成的 Actions run 日志」里读判定结果, 不重复做行情判定。
# 去重: $HOME/.doge_oi_desktop_last_run 记录已检查过的 run id。
# 调用: 由 trigger_actions.sh 每 5 分钟调一次; 也可手动 `bash desktop_notify.sh --test`
# 日志: ~/Library/Logs/doge-oi-desktop.log
set -u
export LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8

GH="$HOME/bin/gh"
CFG="$HOME/WorkBuddy/github/funding-reversal-monitor/.gh-config"
REPO="beijisi522/doge-oi"
LOG="$HOME/Library/Logs/doge-oi-desktop.log"
STAMP="$HOME/.doge_oi_desktop_last_run"
TMP="$(mktemp -t doge-oi-log)"
trap 'rm -f "$TMP"' EXIT
export GH_CONFIG_DIR="$CFG"
mkdir -p "$(dirname "$LOG")"

log() { printf '%s  %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >> "$LOG"; }

notify() {
  /usr/bin/osascript \
    -e 'on run argv' \
    -e 'display notification (item 3 of argv) with title (item 1 of argv) subtitle (item 2 of argv) sound name "Glass"' \
    -e 'end run' "$1" "$2" "$3" >/dev/null 2>&1
}

# 手动验证通道是否正常(不需要有信号)
if [ "${1:-}" = "--test" ]; then
  notify "DOGE OI 桌面通知已就绪" "测试消息" "以后 A 级强信号会在这里弹窗；手机 Telegram 同时收到。"
  log "TEST  已弹测试通知"
  echo "已弹测试通知，请看屏幕右上角（没弹出请检查 系统设置→通知→Script Editor / osascript 是否允许）"
  exit 0
fi

[ -x "$GH" ] || { log "ERROR gh 不存在: $GH"; exit 1; }

# 取最近 10 次运行: "id status conclusion"（GitHub 按时间倒序返回）
LIST=$("$GH" api "repos/$REPO/actions/runs?per_page=10" \
        --jq '.workflow_runs[] | "\(.id) \(.status) \(.conclusion)"' 2>>"$LOG") \
      || { log "ERROR 拉取 run 列表失败"; exit 1; }
[ -n "$LIST" ] || exit 0

COMPLETED=$(printf '%s\n' "$LIST" | awk '$2=="completed"{print $1}' | sort -n)
[ -n "$COMPLETED" ] || exit 0
MAXID=$(printf '%s\n' "$COMPLETED" | tail -1)

# 首次运行: 只设基线, 不回溯历史信号(否则会把几天前的信号全弹一遍)
if [ ! -f "$STAMP" ]; then
  printf '%s' "$MAXID" > "$STAMP"
  log "INIT  基线 run=${MAXID} (历史信号不回溯)"
  exit 0
fi
LAST=$(cat "$STAMP" 2>/dev/null || echo 0)
case "$LAST" in ''|*[!0-9]*) LAST=0 ;; esac

for id in $COMPLETED; do
  [ "$id" -gt "$LAST" ] || continue
  "$GH" run view "$id" --repo "$REPO" --log > "$TMP" 2>/dev/null || continue

  # 日志解析 + 弹通知交给 Python(UTF-8 稳, 避免 shell 中文编码问题)
  RESULT=$(/usr/bin/python3 - "$TMP" <<'PY'
import sys, re, subprocess
raw = open(sys.argv[1], encoding="utf-8", errors="replace").read().splitlines()
lines = []
for l in raw:
    body = l.split("\t")[-1].strip()
    body = re.sub(r"^\d{4}-\d\d-\d\dT[\d:.]+Z\s*", "", body)
    lines.append(body)
joined = "\n".join(lines)

sent = (">>> 推送到手机" in joined)
clear = (">>> 强信号解除" in joined)
if not (sent or clear):
    print("NONE")
    sys.exit(0)

if clear and not sent:
    title, sub, msg = "✅ DOGE OI 强信号解除", "市场恢复平静", "已同步推送到手机 Telegram"
else:
    def pick(kw):
        for b in lines:
            if kw in b:
                return b.strip()
        return ""
    price = pick("价格 ")
    state = pick("【当前状态】").replace("【当前状态】", "").strip()
    sig   = pick("【信号】").replace("【信号】", "").strip()
    src   = pick("数据源:").replace("数据源:", "").strip()
    title = "🔔 DOGE OI 强信号（已推 Telegram）"
    sub   = (state or "A 级信号")[:60]
    msg   = " | ".join(x for x in [price, sig, ("源 " + src) if src else ""] if x)[:200]

subprocess.run([
    "/usr/bin/osascript",
    "-e", "on run argv",
    "-e", 'display notification (item 3 of argv) with title (item 1 of argv) subtitle (item 2 of argv) sound name "Glass"',
    "-e", "end run", title, sub, msg,
], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
print("NOTIFIED|" + sub + "|" + msg[:120])
PY
)
  case "$RESULT" in
    NOTIFIED*) log "NOTIFY run=$id  ${RESULT#NOTIFIED|}" ;;
    *)         log "SKIP   run=$id  无 A 级推送" ;;
  esac
  printf '%s' "$id" > "$STAMP"
done

# 日志轮转, 避免无限增长
if [ -f "$LOG" ] && [ "$(wc -l < "$LOG" | tr -d ' ')" -gt 4000 ]; then
  tail -n 2000 "$LOG" > "$LOG.tmp" && mv "$LOG.tmp" "$LOG"
fi
