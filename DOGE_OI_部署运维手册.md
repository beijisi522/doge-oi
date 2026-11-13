# DOGE OI 提醒系统 · 部署运维手册

> 最后更新：2026-11-13 15:25（GMT+8）
> 用途：换电脑时照这份文档就能把整套提醒恢复起来；也可直接在资料库里编辑补充。
> 代码本体在 GitHub 仓库，本手册只记录「配置、决策、机器相关部署件」。

---

## 0. 一分钟现状

| 项 | 当前值 |
|---|---|
| 做什么 | DOGE **币本位永续** 5 分钟 OI / 资金费率 / 多空账户比信号 |
| 代码仓库 | `https://github.com/beijisi522/doge-oi`，分支 `main`，公开仓库 |
| 工作流 | 「狗狗币持仓监控」，`.github/workflows/doge-oi.yml` |
| 运行模式 | `mode.conf` 里 `MODE=actions`（Worker 侧静默，两边互斥不会重复推） |
| 判定周期 | `*/5 * * * *`（UTC），脚本内 `PERIOD = "5m"` |
| 信号推送 | `PUSH_MIN_LEVEL = "A"`，只有 A 级强信号才推，同一信号靠状态文件去重 |
| **每小时汇总** | `cron: '7 * * * *'`（UTC 每小时第 7 分）固定推一条盘面，**不受 A 级门槛限制**；同一 UTC 小时靠状态文件 `last_hour` 去重 |
| 手机接收端 | **Telegram**，与 `@beijisibot` 的私聊（显示名 wayne） |
| 电脑接收端 | ① Telegram Desktop 登录同一账号（多端同步，且 macOS 会弹系统通知）；② `desktop_notify.sh` 额外弹 osascript 通知 |
| 数据源 | 币安 `DOGEUSD_PERP` 官方口径优先；遇 451 / 超时自动降级 OKX `DOGE-USD-SWAP`（同为币本位），报告会标注 |
| 状态文件 | `.doge_oi_state.json`，`push_key`（信号去重）+ `last_hour`（汇总去重）变化时才提交回仓库（需 Workflow permissions = Read and write） |

**平时安静是正常的**：信号只在 A 级推；但**每小时一定有一条盘面汇总**。手动点 Run workflow 才会额外发一条「✅ DOGE OI 提醒配置成功」测试消息。

**本机后台状态（2026-11-13 15:25）**：`launchctl` 服务已被卸载（`bootout` 成功，`bootstrap` 在 Agent 会话里始终报 `Input/output error`，提权也一样）。**不影响每小时汇总** —— GitHub 的 `7 * * * *` cron 独立负责。受影响的只有「5 分钟判定密度」和「osascript 弹窗」，需要你在自己的终端里执行第 3 节第 6 步。

---

## 1. 三条通知链路别搞混

| 提醒 | 触发 | 接收端 |
|---|---|---|
| **DOGE OI 信号（本系统）** | GitHub Actions · 每 5 分钟（本机触发器兜底） | A 级信号 → Telegram 手机 + 电脑 |
| **DOGE 每小时盘面汇总（本系统）** | GitHub cron `7 * * * *` + 本机整点兜底 | 每 UTC 小时一条 → Telegram 手机 + 电脑 + macOS 弹窗 |
| 加密货币与美元宏观决策参考 | WorkBuddy 自动化 · 每日 07:30 | WorkBuddy 对话里 |
| 费率反转监控（`funding-reversal-monitor`） | GitHub Actions · 每日 3 次 | iPhone 的 Bark 通知 |

WorkBuddy 只是改代码、查日志的操作台，**不接收本系统的推送**。

**电脑端三种「看到消息」的方式**

- **Telegram Desktop**：本机 `/Applications/Telegram.app` 已安装，用与手机相同的手机号登录，`@beijisibot` 对话自动同步。Telegram 收到消息时 macOS 通知中心本来就会弹一条 —— 换句话说**登录桌面版就等于有了电脑弹窗**，零配置。
- **osascript 系统通知**：`desktop_notify.sh` 额外弹一条带声音（Glass）的通知，标题区分「🔔 A 级强信号」/「📊 每小时盘面汇总」/「✅ 强信号解除」。即使没开 Telegram 也能看见，但需要本机触发器在跑。
- 日志里「推送到手机 + 电脑 Telegram」指 Telegram 多端同步（一个渠道、多个端）。

---

## 2. 数据链路

```
GitHub cron 7 * * * *  ──────────────► --hourly 每小时盘面汇总 ─┐
                                                                │
本机 launchd（每 300 秒）                                        │
    ├─ POST workflow_dispatch（self_check=no, hourly=yes 仅在每小时开头）
    │    └─ GitHub Actions 美国 runner                          │
    │         ├─ 币安 dapi / DOGEUSD_PERP ── 200 ──► 用币安      │
    │         └─ 451 / 超时 ──► 自动降级 OKX / DOGE-USD-SWAP     │
    │              ├─ --once 判定 → A 级且信号有变化 ───────────┤
    │              └─ --hourly 汇总（固定推，按 UTC 小时去重）──┤
    │                                                          ▼
    │                                              Telegram Bot API
    │                                                ├─ 手机 Telegram
    │                                                └─ 电脑 Telegram Desktop
    └─ desktop_notify.sh 读「上一次已完成 run」的日志
         └─ 发现 >>> 每小时盘面汇总 / >>> 推送到手机 → osascript 弹 macOS 通知
```

**为什么需要本机触发器**：GitHub 对**新建仓库的高频 schedule** 会降权。本仓库最初 `event=schedule` 为 0 次，约 12 小时后才开始触发，且实测两次间隔 4.5 小时。因此改成由本机定时打 `workflow_dispatch` API（本机 `api.github.com` 实测 200、手动触发 100% 成功），GitHub 原生 `*/5` 保留作兜底。两边同时触发也不会重复推：`concurrency` + 状态文件去重。

**每小时汇总为什么不依赖本机**：低频 cron（`7 * * * *`）在 GitHub 上比 `*/5` 可靠得多，即使 launchd 完全没装，Telegram 也会每小时收到一条。本机触发器在每小时开头（分钟 00–04）额外带 `hourly=yes`，只是加速兜底；脚本内按 UTC 小时去重，两边都触发也只推一条。

**为什么桌面通知要读日志而不是本机自己判定**：本机实测 `www.okx.com`、`dapi.binance.com`、`api.telegram.org` 全部 curl 000（连不上），只有 `api.github.com` 通。所以本机不重复拉行情，只从已完成的 Actions 日志里读结果，按 run id 去重（记录文件 `~/.doge_oi_desktop_last_run`）。

**为什么用 OKX 降级而不是换标的**：Gate.io 没有 DOGE 币本位合约（只有 U 本位）；OKX 的 `DOGE-USD-SWAP` 是币本位永续，端点齐全且不受 451 影响。以后若把 Worker 搬去非美机房，代码一行不用改会自动切回币安。

---

## 3. 换电脑部署清单

1. **拿到代码**：`git clone https://github.com/beijisi522/doge-oi.git`（或下载资料库里的完整代码包 `doge-oi-full-*.zip`）。
2. **确认仓库侧设置**（以 owner 身份在网页操作，协作者无 admin）：
   - Settings → Secrets and variables → Actions → 两个 Repository secrets：`DOGE_TG_TOKEN`、`DOGE_TG_CHAT_ID`（名字一字不差）。值不要写进任何文件或聊天记录。
   - Settings → Actions → General → Workflow permissions 勾 **Read and write permissions** 并 Save。
   - Telegram 里给机器人发一次 `/start`，否则机器人无法主动发消息（表现为 HTTP 400）。
3. **装 Telegram Desktop**（推荐）并用同一手机号登录，确认 `@beijisibot` 对话里有历史消息 = 电脑端已同步。
4. **装 gh CLI 并登录**，账号需要对 `beijisi522/doge-oi` 有写权限；记下 gh 可执行文件位置与凭证目录。
5. **⚠️ 把 `trigger_actions.sh` 和 `desktop_notify.sh` 复制到用户主目录自建目录**（两个必须同目录）：
   ```bash
   mkdir -p ~/.doge-oi
   cp ~/Downloads/doge-oi/{trigger_actions.sh,desktop_notify.sh} ~/.doge-oi/
   chmod +x ~/.doge-oi/*.sh
   ```
   **不要直接把 plist 指向 `~/Downloads`、`~/Desktop` 或 `~/Documents`** —— 这些是 macOS TCC 保护目录，launchd 后台进程读不到脚本，会立刻 `exit 126`，而且报错很隐晦（只说 Input/output error）。改完源码后记得重新 `cp` 同步副本。
6. **改 plist 模板里脚本的绝对路径**，放到 `~/Library/LaunchAgents/`，然后在**自己打开的「终端」App** 里注册：
   ```bash
   launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.wayne.doge-oi-trigger.plist
   ```
   - 若报 `Bootstrap failed: 5: Input/output error`：先 `launchctl bootout gui/$(id -u)/com.wayne.doge-oi-trigger` 卸掉旧配置，再 bootstrap（**重复 bootstrap 是 I/O error 最常见的原因**）。
   - 仍失败可试 `launchctl load -w ~/Library/LaunchAgents/com.wayne.doge-oi-trigger.plist`。
   - 再不行用 cron 兜底：`(crontab -l 2>/dev/null; echo "*/5 * * * * /bin/bash $HOME/.doge-oi/trigger_actions.sh") | crontab -`
   - Agent 会话（含提权）注册会报 I/O error，这是会话不在 GUI 登录域，必须在用户终端执行。
7. **验证**：
   ```bash
   bash ~/.doge-oi/desktop_notify.sh --test   # 立刻弹一条 macOS 通知
   launchctl list | grep doge-oi              # 定时触发器已注册
   tail ~/Library/Logs/doge-oi-trigger.log    # 每 5 分钟一行 OK HTTP 204 hourly=yes/no
   tail ~/Library/Logs/doge-oi-desktop.log    # INIT / SKIP / NOTIFY
   ```
   GitHub Actions 页手动 Run workflow 时把 `hourly` 选 `yes`，可立刻验证汇总链路（手机会收到「📊 DOGE 每小时盘面汇总」）。

**换电脑必须改的 5 个地方**

| 位置 | 说明 |
|---|---|
| `trigger_actions.sh` → `GH` | 新机器上 `gh` 的实际路径 |
| `trigger_actions.sh` → `CFG` | 新机器上 gh 凭证目录（`GH_CONFIG_DIR`），token 由 `gh auth token` 动态取，**不要硬编码** |
| `desktop_notify.sh` → `GH` / `CFG` / `REPO` | 同上两份路径 + 目标仓库（换仓库时改） |
| `com.wayne.doge-oi-trigger.plist` → `ProgramArguments` | 运行副本的**绝对路径**（launchd 不展开 `~`，且必须避开 TCC 目录） |
| 登录账号 | 必须是仓库协作者或 owner，能打 `workflow_dispatch` |

Linux / 其他常驻机器改跑 `deploy_vps.sh`（systemd 常驻 60 秒轮询），并把 `mode.conf` 切成 `MODE=worker`；此时桌面通知不适用，每小时汇总需另配（当前只在 Actions workflow 里）。

---

## 4. 本机触发器与桌面通知

### `trigger_actions.sh`（核心逻辑）

```bash
#!/bin/bash
set -u
GH="$HOME/bin/gh"                       # ← 换电脑改这里
CFG="$HOME/.gh-config"                  # ← 换电脑改这里（gh 凭证目录）
API="https://api.github.com/repos/beijisi522/doge-oi/actions/workflows/doge-oi.yml/dispatches"
LOG="$HOME/Library/Logs/doge-oi-trigger.log"
mkdir -p "$(dirname "$LOG")"
log() { printf '%s  %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >> "$LOG"; }

# 日志轮转（>4000 行保留后 2000 行）
if [ -f "$LOG" ] && [ "$(wc -l < "$LOG" | tr -d ' ')" -gt 4000 ]; then
  tail -n 2000 "$LOG" > "$LOG.tmp" && mv "$LOG.tmp" "$LOG"
fi

export GH_CONFIG_DIR="$CFG"
[ -x "$GH" ] || { log "ERROR gh 不存在: $GH"; exit 1; }
TOKEN=$("$GH" auth token 2>/dev/null) || TOKEN=""
[ -n "$TOKEN" ] || { log "ERROR 取 GitHub token 失败"; exit 1; }

# self_check=no 避免刷屏；每小时开头（分钟 00-04）顺带带 hourly=yes 出汇总
MIN=$(date +%M)
HOURLY="no"
if [ "$((10#$MIN))" -lt 5 ]; then HOURLY="yes"; fi
BODY=$(printf '{"ref":"main","inputs":{"self_check":"no","hourly":"%s"}}' "$HOURLY")

CODE=$(curl -s -o /tmp/doge_dispatch_body -w '%{http_code}' --max-time 20 \
  -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Accept: application/vnd.github+json" \
  -H "X-GitHub-Api-Version: 2022-11-28" \
  -H "Content-Type: application/json" \
  -d "$BODY" "$API")

[ "$CODE" = "204" ] && log "OK    HTTP 204  已触发判定 (self_check=no, hourly=$HOURLY)" \
                   || log "WARN  HTTP $CODE  $(head -c 160 /tmp/doge_dispatch_body | tr -d '\n')"

# 顺带检查上一次已完成的判定: 真推了信号/汇总就在 Mac 弹系统通知
SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NOTIFY="$SELF_DIR/desktop_notify.sh"
if [ -f "$NOTIFY" ]; then
  /bin/bash "$NOTIFY" >> "$LOG" 2>&1 || log "WARN  桌面通知检查失败(不影响判定)"
fi
```

### `desktop_notify.sh`（macOS 弹窗）

- 由 `trigger_actions.sh` 每 5 分钟调用；完整源码在仓库。
- 取最近 10 次 run，筛 `status=completed` 且 id 大于 `~/.doge_oi_desktop_last_run` 的，逐个拉日志。
- 识别三种标志：`>>> 每小时盘面汇总` → 📊 汇总通知；`>>> 推送到手机` → 🔔 A 级信号；`>>> 强信号解除` → ✅ 解除。提取 `价格 / 【当前状态】 / 【信号】 / 数据源` 作为内容，弹 macOS 通知（声音 Glass）。
- 首次运行只写基线、**不回溯历史**；`bash desktop_notify.sh --test` 可随时弹测试通知。
- 依赖：`/usr/bin/osascript`、`/usr/bin/python3`、`gh`；日志 `~/Library/Logs/doge-oi-desktop.log`。

### `com.wayne.doge-oi-trigger.plist`

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.wayne.doge-oi-trigger</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>/Users/你的用户名/.doge-oi/trigger_actions.sh</string>
    </array>
    <key>StartInterval</key>
    <integer>300</integer>
    <key>RunAtLoad</key>
    <true/>
    <key>StandardOutPath</key>
    <string>/Users/你的用户名/Library/Logs/doge-oi-trigger.out.log</string>
    <key>StandardErrorPath</key>
    <string>/Users/你的用户名/Library/Logs/doge-oi-trigger.err.log</string>
</dict>
</plist>
```

**卸载 / 停用**
```bash
launchctl bootout gui/$(id -u)/com.wayne.doge-oi-trigger
rm ~/Library/LaunchAgents/com.wayne.doge-oi-trigger.plist
```

---

## 5. 脚本关键配置（改代码时看这里）

| 常量 / 环境变量 | 默认 | 说明 |
|---|---|---|
| `SYMBOL` / `PAIR` | `DOGEUSD_PERP` / `DOGEUSD` | 币安币本位永续 |
| `OKX_INST` | `DOGE-USD-SWAP` | 降级源，同为币本位 |
| `PERIOD` | `5m` | 统计周期 |
| `POLL_INTERVAL` | `60` | Worker 模式轮询秒数 |
| `PUSH_MIN_LEVEL` | `A` | 改 `B` 会把中信号也推手机（也弹电脑通知）；**不影响每小时汇总** |
| `PRICE_MOVE` / `OI_MOVE` / `OI_SURGE` | 0.3% / 1% / 3% | 信号阈值，按手感调 |
| `LSR_HIGH` / `LSR_LOW` | 1.8 / 0.6 | 极端多空账户比 |
| `FUND_HOT` | 0.05% | 费率过热 |
| `DOGE_TG_TOKEN` / `DOGE_TG_CHAT_ID` | 空 | Telegram Bot Token / 私聊 chat id |
| `DOGE_STATE_DIR` | 脚本目录 | 状态文件目录，容器里指到持久卷 |
| `DOGE_DISABLE_FALLBACK` | 未设 | 设 `1` 则禁用 OKX 降级，只用币安 |

命令行：`--once` 单次判定（A 级才推）、`--hourly` 每小时汇总（固定推、按 UTC 小时去重）、`--check` 自检并推测试消息、`--demo` 离线演示、无参数 = Worker 常驻 60 秒轮询。

`mode.conf` 用一行 `MODE=actions|worker` 控制哪一侧真正推 Telegram，另一侧照常判定打印但静默 —— 双部署不重复推的关键。

---

## 6. 故障排查

| 现象 | 原因 / 处理 |
|---|---|
| 日志 `[ERR] ... HTTP 451` 但没有后续判定 | 两个数据源都失败才会跳过；单看币安 451 是正常的，后面应紧跟 `[FALLBACK] 切换 OKX` |
| Telegram HTTP 400 | 多半是没给机器人发过 `/start`；其次检查 chat_id 是否带空格、token 是否抄错 |
| 每 5 分钟收到一条「配置成功」 | `self_check` 开关没生效，检查 workflow 里 `--check` step 的 `if` 条件与 dispatch body |
| Actions 显示 success 却什么都没发 | 脚本对网络失败只打印不报错，**绿色不等于链路通**，要看日志里的真实行情行 |
| `schedule` 次数远少于预期 | 高频 cron 降权的已知行为；用本机触发器，别等它 |
| `状态提交失败 / job 报红` | Workflow permissions 没勾 Read and write |
| 手机长期没消息 | 先确认是否有 A 级信号；**每小时汇总应该一定有**，没有就查 `7 * * * *` cron 是否被跳过 |
| 一小时内收到两条汇总 | 正常情况下 `last_hour` 会去重；若发生，检查状态文件是否被两个并发 run 互相覆盖 |
| **电脑 Telegram 没消息** | 打开 Telegram Desktop 用同一手机号登录；`@beijisibot` 对话应自动同步历史消息 |
| **macOS 不弹 osascript 通知** | 先 `bash ~/.doge-oi/desktop_notify.sh --test`；不弹查系统设置→通知权限；能弹但没弹，看 `~/Library/Logs/doge-oi-desktop.log` 是否 `SKIP` |
| **`launchctl bootstrap` 报 `Input/output error`** | ① 服务已加载 → 先 `bootout` 再 `bootstrap`；② 脚本放在 `~/Downloads`/`Desktop`/`Documents` → TCC 拒绝，移到 `~/.doge-oi/`（表现为 `last exit code = 126`）；③ Agent 会话无 GUI 域写权限 → 在用户自己的终端执行 |
| `last exit code = 126` | 后台进程读不到脚本。九成是 TCC 目录问题，见上一条 |
| Mac 合盖后没有判定 | launchd 在睡眠时不跑；GitHub schedule 兜底，每小时汇总不受影响 |

手动触发汇总（会真推一条 Telegram）：
```bash
printf '%s' '{"ref":"main","inputs":{"self_check":"no","hourly":"yes"}}' | \
  gh api -X POST repos/beijisi522/doge-oi/actions/workflows/doge-oi.yml/dispatches --input -
```
注意 `gh api` 不能用 `-f self_check=no` 直接传 —— inputs 必须嵌在 `inputs` 对象里，否则返回 422 `"hourly", "self_check" are not permitted keys`。

---

## 7. 已知限制与遗留项

- GitHub 的 `*/5` 是 best-effort，即使激活也可能延迟数分钟 / 高峰跳过，**不是 60 秒实时**；做日内短线更理想的是 Worker。
- **Mac 睡眠 / 关机期间不触发**本机触发器与 osascript 弹窗；但 GitHub 侧的两个 cron 照跑，Telegram 汇总不受影响。
- osascript 通知最多比手机晚一个 5 分钟周期（本机先 dispatch、再检查上一次已完成的 run）。
- OKX 降级源下「多空账户比」维度暂时禁用：OKX 按币种统计（约 4.9），币安按单合约（约 1~3），硬套 1.8 阈值会永远误判极端多头；报告标注「不参与判定」。
- 换交易所后 OI 绝对值、费率口径不同，阈值手感建议观察几天再微调。
- Oracle Cloud / Railway / Render 等常驻方案已评估过并放弃：要么要月费，要么注册风控卡住，且 451 已由 OKX 降级解决。`deploy_vps.sh` 保留，随时可升级实时 Worker（届时汇总需迁移到 Worker 侧）。
- 状态文件提交回公开仓库（只有 `push_key` / `last_hour` 指纹，无密钥）。

---

## 8. 相关位置

- 代码仓库：https://github.com/beijisi522/doge-oi
- Actions 运行记录：https://github.com/beijisi522/doge-oi/actions
- 资料库手册（在线可编辑，以最新日期版为准）：见资料库根目录带日期的 `DOGE_OI_部署运维手册_*.md`
- 资料库完整代码包（以最新版 `doge-oi-full-*-v*.zip` 为准）
- 资料库《行情数据源清单_币安_DOGE》：https://www.workbuddy.cn/space/d/W9Ogqf8KIghs0b7e0UdJNf
