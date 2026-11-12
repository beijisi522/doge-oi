#!/bin/bash
# DOGE OI 监控 — 本机触发器（macOS launchd 每 5 分钟调用一次）
#
# 背景: GitHub 对新建仓库的高频 schedule(*/5) 会延迟数小时甚至整天丢弃,
#       实测本仓库 schedule 触发 0 次, 而 workflow_dispatch 100% 成功。
#       本机 api.github.com 可达, 因此由本机定时打 dispatch API 兜底。
# 依赖: ~/bin/gh（已登录, 对 beijisi522/doge-oi 有协作者写权限）
# 日志: ~/Library/Logs/doge-oi-trigger.log
# 卸载: launchctl bootout gui/$(id -u)/com.wayne.doge-oi-trigger
set -u

GH="$HOME/bin/gh"
CFG="$HOME/WorkBuddy/github/funding-reversal-monitor/.gh-config"
API="https://api.github.com/repos/beijisi522/doge-oi/actions/workflows/doge-oi.yml/dispatches"
LOG="$HOME/Library/Logs/doge-oi-trigger.log"
mkdir -p "$(dirname "$LOG")"

log() { printf '%s  %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >> "$LOG"; }

# 简单轮转, 避免日志无限增长
if [ -f "$LOG" ] && [ "$(wc -l < "$LOG" | tr -d ' ')" -gt 4000 ]; then
  tail -n 2000 "$LOG" > "$LOG.tmp" && mv "$LOG.tmp" "$LOG"
fi

export GH_CONFIG_DIR="$CFG"
if [ ! -x "$GH" ]; then log "ERROR gh 不存在: $GH"; exit 1; fi
TOKEN=$("$GH" auth token 2>/dev/null) || TOKEN=""
if [ -z "$TOKEN" ]; then log "ERROR 取 GitHub token 失败"; exit 1; fi

# self_check=no 是关键: 否则每次触发都会往 Telegram 发一条「配置成功」测试消息。
CODE=$(curl -s -o /tmp/doge_dispatch_body -w '%{http_code}' --max-time 20 \
  -X POST \
  -H "Authorization: Bearer $TOKEN" \
  -H "Accept: application/vnd.github+json" \
  -H "X-GitHub-Api-Version: 2022-11-28" \
  -H "Content-Type: application/json" \
  -d '{"ref":"main","inputs":{"self_check":"no"}}' \
  "$API")

if [ "$CODE" = "204" ]; then
  log "OK    HTTP 204  已触发判定 (self_check=no, 不发测试消息)"
else
  log "WARN  HTTP $CODE  $(head -c 160 /tmp/doge_dispatch_body 2>/dev/null | tr -d '\n')"
fi
