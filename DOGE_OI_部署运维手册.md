# DOGE OI 提醒系统 · 部署运维手册

> 最后更新：2026-11-13 10:55（GMT+8）
> 用途：换电脑时照这份文档就能把整套提醒恢复起来；也可直接在资料库里编辑补充。
> 代码本体在 GitHub 仓库，本手册只记录「配置、决策、机器相关部署件」。

---

## 0. 一分钟现状

| 项 | 当前值 |
|---|---|
| 做什么 | DOGE **币本位永续** 5 分钟 OI / 资金费率 / 多空账户比信号，A 级强信号推手机 + 电脑 |
| 代码仓库 | `https://github.com/beijisi522/doge-oi`，分支 `main`，公开仓库 |
| 工作流 | 「狗狗币持仓监控」，`.github/workflows/doge-oi.yml` |
| 运行模式 | `mode.conf` 里 `MODE=actions`（Worker 侧静默，两边互斥不会重复推） |
| 判定周期 | `*/5 * * * *`（UTC），脚本内 `PERIOD = "5m"` |
| 推送门槛 | `PUSH_MIN_LEVEL = "A"`，只有 A 级强信号才推，同一信号靠状态文件去重 |
| 手机接收端 | **Telegram**，与 `@beijisibot` 的私聊（显示名 wayne） |
| 电脑接收端 | ① Telegram Desktop 登录同一账号（多端同步，零配置）；② **macOS 系统通知弹窗**（`desktop_notify.sh`，需本机触发器） |
| 数据源 | 币安 `DOGEUSD_PERP` 官方口径优先；遇 451 / 超时自动降级 OKX `DOGE-USD-SWAP`（同为币本位），报告会标注 |
| 状态文件 | `.doge_oi_state.json`，信号变化时才提交回仓库（需 Workflow permissions = Read and write） |

**平时安静是正常的**：只有 A 级才推，C 弱信号只在 runner 日志里。手动点 Run workflow 才会额外发一条「✅ DOGE OI 提醒配置成功」测试消息。

**截至 2026-11-13 10:55 的实际状态**：GitHub 原生 `schedule` 已经开始触发（共 2 次，北京时间 05:54 和 10:20，间隔约 4.5 小时），说明不是配置错，但频率远低于 5 分钟。今早 10:20 那次成功出判定（OKX 降级，价 0.06581 / +0.17% / OI -0.45% / 震荡整理 / **A 强 0 个**），因此**没有推送**——没信号，不是坏了。本机 launchd 仍**未注册**，5 分钟稳定触发 + 桌面弹窗要等装好它才有。

---

## 1. 三条通知链路别搞混

| 提醒 | 触发 | 接收端 |
|---|---|---|
| **DOGE OI 信号（本系统）** | GitHub Actions · 每 5 分钟（本机触发器兜底） | **Telegram 手机 + 电脑 App**；装了 `desktop_notify.sh` 再加 macOS 弹窗 |
| 加密货币与美元宏观决策参考 | WorkBuddy 自动化 · 每日 07:30 | WorkBuddy 对话里 |
| 费率反转监控（`funding-reversal-monitor`） | GitHub Actions · 每日 3 次 | iPhone 的 Bark 通知 |

WorkBuddy 只是改代码、查日志的操作台，**不接收本系统的推送**。日志里「推送到手机 + 电脑 Telegram」原本指 Telegram 多端同步（一个渠道、多个端）；2026-11-13 起另外新增了真正的 macOS 系统通知。

**电脑端两种方式的区别**

- **Telegram Desktop**：本机 `/Applications/Telegram.app` 已安装。用与手机相同的手机号登录，机器人 `@beijisibot` 的对话会自动同步，手机收到什么电脑就收到什么。**不需要改任何代码**。
- **macOS 系统通知**：`desktop_notify.sh` 在检测到「确实往 Telegram 推了 A 级信号」后，用 `osascript` 在屏幕右上角弹一条带声音（Glass）的通知，不开 Telegram 也能看见。只有 A 级才弹，不会刷屏。它依赖本机触发器每 5 分钟跑一次。

---

## 2. 数据链路

```
本机 launchd（每 300 秒）
    ├─ POST workflow_dispatch（self_check=no）
    │    └─ GitHub Actions 美国 runner
    │         ├─ 币安 dapi / DOGEUSD_PERP ── 200 ──► 用币安
    │         └─ 451 / 超时 ──► 自动降级 OKX / DOGE-USD-SWAP
    │              └─ 判定 → A 级且信号有变化 → Telegram Bot API
    │                                          ├─► 手机 Telegram
    │                                          └─► 电脑 Telegram Desktop
    └─ desktop_notify.sh 读取「上一次已完成 run」的日志
         └─ 发现 >>> 推送到手机 → osascript 弹 macOS 通知
```

**为什么需要本机触发器**：GitHub 对**新建仓库的高频 schedule** 会降权。本仓库最初 `event=schedule` 为 0 次，约 12 小时后才开始触发，且实测两次间隔 4.5 小时。因此改成由本机定时打 `workflow_dispatch` API（本机 `api.github.com` 实测 200、手动触发 100% 成功），GitHub 原生 `*/5` 保留作兜底。两边同时触发也不会重复推送：`concurrency` + 状态文件去重。

**为什么桌面通知要读日志而不是本机自己判定**：本机实测 `www.okx.com`、`dapi.binance.com`、`api.telegram.org` 全部 curl 000（连不上），只有 `api.github.com` 通。所以本机不重复拉行情，只从已完成的 Actions 日志里读结果，按 run id 去重（记录文件 `~/.doge_oi_desktop_last_run`）。

**为什么用 OKX 降级而不是换标的**：Gate.io 没有 DOGE 币本位合约（只有 U 本位），换过去会把标的口径改掉；OKX 的 `DOGE-USD-SWAP` 是币本位永续，价格 / 5m K 线 / OI / 资金费率端点齐全且不受 451 影响。以后若把 Worker 搬去非美机房，代码一行不用改会自动切回币安。

---

## 3. 换电脑部署清单

1. **拿到代码**：`git clone https://github.com/beijisi522/doge-oi.git`（或下载资料库里的完整代码包 `doge-oi-full-*.zip`）。`trigger_actions.sh` 与 `desktop_notify.sh` 必须放在**同一目录**（前者按自身目录找后者）。
2. **确认仓库侧设置**（以 owner 身份在网页操作，协作者无 admin）：
   - Settings → Secrets and variables → Actions → 两个 Repository secrets：`DOGE_TG_TOKEN`、`DOGE_TG_CHAT_ID`（名字一字不差）。值不要写进任何文件或聊天记录。
   - Settings → Actions → General → Workflow permissions 勾 **Read and write permissions** 并 Save。
   - Telegram 里给机器人发一次 `/start`，否则机器人无法主动发消息（表现为 HTTP 400）。
3. **装 Telegram Desktop**（可选但推荐）并用同一手机号登录，确认 `@beijisibot` 对话里有历史测试消息 = 电脑端已同步。
4. **装 gh CLI 并登录**，账号需要对 `beijisi522/doge-oi` 有写权限；记下 gh 可执行文件位置与凭证目录。
5. **改 `trigger_actions.sh` 和 `desktop_notify.sh` 里的机器相关值**（见第 4 节），`chmod +x` 两个脚本。
6. **改 plist 模板里脚本的绝对路径**，放到 `~/Library/LaunchAgents/`，然后注册：
   ```bash
   launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.wayne.doge-oi-trigger.plist
   ```
   报 `Bootstrap failed` 时改用 `launchctl load -w ~/Library/LaunchAgents/com.wayne.doge-oi-trigger.plist`。
   ⚠️ 这一步必须在**用户自己打开「终端」App** 里粘，Agent 会话的后台域注册会报 `Input/output error`。
7. **验证**：
   ```bash
   bash desktop_notify.sh --test        # 立刻弹一条 macOS 通知，验证弹窗通道
   launchctl list | grep doge-oi        # 定时触发器已注册
   tail ~/Library/Logs/doge-oi-trigger.log     # 每 5 分钟一行 OK HTTP 204
   tail ~/Library/Logs/doge-oi-desktop.log     # INIT / SKIP / NOTIFY
   ```
   GitHub Actions 页应出现新的 workflow_dispatch 运行，日志里有 `价格 x.xxxxx | ±x.xx% | OI变动 ±x.xx%`。「手动触发时验证链路」这一步应为 `skipped`（不会每 5 分钟刷测试消息）。

**换电脑必须改的 5 个地方**

| 位置 | 说明 |
|---|---|
| `trigger_actions.sh` → `GH` | 新机器上 `gh` 的实际路径 |
| `trigger_actions.sh` → `CFG` | 新机器上 gh 凭证目录（`GH_CONFIG_DIR`），token 由 `gh auth token` 动态取，**不要硬编码** |
| `desktop_notify.sh` → `GH` / `CFG` / `REPO` | 同上两份路径 + 目标仓库（换仓库时改） |
| `com.wayne.doge-oi-trigger.plist` → `ProgramArguments` | 脚本的**绝对路径**（launchd 不展开 `~`） |
| 登录账号 | 必须是仓库协作者或 owner，能打 `workflow_dispatch` |

Linux / 其他常驻机器不适合这套 launchd 方案，改跑 `deploy_vps.sh`（systemd 常驻 60 秒轮询），并把 `mode.conf` 切成 `MODE=worker`，Actions 侧会自动静默。此时桌面通知不适用（本机没有 macOS 通知中心）。

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

# self_check=no 是关键: 否则每次触发都会往 Telegram 发一条测试消息
CODE=$(curl -s -o /tmp/doge_dispatch_body -w '%{http_code}' --max-time 20 \
  -X POST \
  -H "Authorization: Bearer $TOKEN" \
  -H "Accept: application/vnd.github+json" \
  -H "X-GitHub-Api-Version: 2022-11-28" \
  -H "Content-Type: application/json" \
  -d '{"ref":"main","inputs":{"self_check":"no"}}' "$API")

[ "$CODE" = "204" ] && log "OK    HTTP 204  已触发判定 (self_check=no, 不发测试消息)" \
                   || log "WARN  HTTP $CODE  $(head -c 160 /tmp/doge_dispatch_body | tr -d '\n')"

# 顺带检查上一次已完成的判定: 真推了 A 级信号就在 Mac 弹系统通知
SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NOTIFY="$SELF_DIR/desktop_notify.sh"
if [ -f "$NOTIFY" ]; then
  /bin/bash "$NOTIFY" >> "$LOG" 2>&1 || log "WARN  桌面通知检查失败(不影响判定)"
fi
```

### `desktop_notify.sh`（macOS 弹窗）

- 由 `trigger_actions.sh` 每 5 分钟调用；完整源码在仓库，此处只记行为。
- 取最近 10 次 run，筛 `status=completed` 且 id 大于 `~/.doge_oi_desktop_last_run` 的，逐个拉日志。
- 日志含 `>>> 推送到手机` → 提取 `价格 / 【当前状态】 / 【信号】 / 数据源`，弹 macOS 通知（标题「🔔 DOGE OI 强信号（已推 Telegram）」，声音 Glass）；含 `>>> 强信号解除` 则弹解除通知。
- 首次运行只写基线、**不回溯历史信号**，避免把几天前的信号全弹一遍。
- `bash desktop_notify.sh --test` 可随时弹一条测试通知验证通道。
- 依赖：`/usr/bin/osascript`、`/usr/bin/python3`、`gh`；日志 `~/Library/Logs/doge-oi-desktop.log`。
- 若系统通知没弹出：系统设置 → 通知 → 允许「Script Editor / osascript / 终端」的通知；合盖睡眠期间 launchd 不跑。

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
        <string>/绝对路径/改成你的/trigger_actions.sh</string>
    </array>
    <key>StartInterval</key>
    <integer>300</integer>
    <key>RunAtLoad</key>
    <true/>
    <key>ProcessType</key>
    <string>Background</string>
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
| `PUSH_MIN_LEVEL` | `A` | 改 `B` 会把中信号也推手机（也会推电脑弹窗） |
| `PRICE_MOVE` / `OI_MOVE` / `OI_SURGE` | 0.3% / 1% / 3% | 信号阈值，按手感调 |
| `LSR_HIGH` / `LSR_LOW` | 1.8 / 0.6 | 极端多空账户比 |
| `FUND_HOT` | 0.05% | 费率过热 |
| `DOGE_TG_TOKEN` / `DOGE_TG_CHAT_ID` | 空 | Telegram Bot Token / 私聊 chat id |
| `DOGE_STATE_DIR` | 脚本目录 | 状态文件目录，容器里指到持久卷 |
| `DOGE_DISABLE_FALLBACK` | 未设 | 设 `1` 则禁用 OKX 降级，只用币安 |

`mode.conf` 用一行 `MODE=actions|worker` 控制哪一侧真正推 Telegram，另一侧照常判定打印但静默 —— 这是双部署不重复推的关键，切换后 Actions 立即生效、Worker 需 Redeploy。

---

## 6. 故障排查

| 现象 | 原因 / 处理 |
|---|---|
| 日志 `[ERR] ... HTTP 451` 但没有后续判定 | 两个数据源都失败才会跳过；单看币安 451 是正常的，后面应紧跟 `[FALLBACK] 切换 OKX` |
| Telegram HTTP 400 | 多半是没给机器人发过 `/start`；其次检查 chat_id 是否带空格、token 是否抄错 |
| 每 5 分钟收到一条「配置成功」 | `self_check` 开关没生效，检查 workflow 里 `--check` step 的 `if` 条件与 dispatch body |
| Actions 显示 success 却什么都没发 | 脚本对网络失败只打印不报错，**绿色不等于链路通**，要看日志里的 `[2] ✅ 测试消息已发出` 和真实行情行 |
| `schedule` 次数远少于预期 | 已知平台降权行为，不是配置错；用本机触发器，别等它 |
| `状态提交失败 / job 报红` | Workflow permissions 没勾 Read and write |
| 手机长期没消息 | 先手动 Run workflow 收一条测试消息；再确认是否真的有 A 级信号（C/B 级不推） |
| **电脑 Telegram 没消息** | 打开 Telegram Desktop 用同一手机号登录；`@beijisibot` 对话应自动同步历史消息 |
| **macOS 不弹通知** | 先 `bash desktop_notify.sh --test`；不弹查系统设置→通知权限；能弹但信号没弹，看 `~/Library/Logs/doge-oi-desktop.log` 是否 `SKIP`（说明那次没有 A 级推送） |
| `launchctl bootstrap` 报 `Input/output error` | Agent 会话不在 GUI 登录域；必须在用户自己打开的「终端」App 里执行 |
| Mac 合盖后没有判定 | launchd 在睡眠时不跑；GitHub schedule 兜底，或改用常驻 Worker |

一键手动触发（会发测试消息，仅用于验链路）：
```bash
curl -X POST \
  -H "Authorization: Bearer $(gh auth token)" \
  -H "Accept: application/vnd.github+json" \
  -d '{"ref":"main","inputs":{"self_check":"yes"}}' \
  https://api.github.com/repos/beijisi522/doge-oi/actions/workflows/doge-oi.yml/dispatches
```

---

## 7. 已知限制与遗留项

- GitHub 的 `*/5` 是 best-effort，即使激活也可能延迟数分钟 / 高峰跳过，**不是 60 秒实时**；做日内短线更理想的是 Worker。
- **Mac 睡眠 / 关机期间不触发**，桌面通知同理。
- 桌面通知最多比手机晚一个 5 分钟周期（本机先 dispatch、再检查上一次已完成的 run）。
- OKX 降级源下「多空账户比」维度暂时禁用：OKX 按币种统计（约 4.9），币安按单合约（约 1~3），硬套 1.8 阈值会永远误判极端多头；报告标注「不参与判定」。以后可按历史分位数做动态阈值补回。
- 换交易所后 OI 绝对值、费率口径不同，阈值手感建议观察几天再微调。
- Oracle Cloud / Railway / Render 等常驻方案已评估过并放弃：要么要月费，要么注册风控卡住，且 451 已由 OKX 降级解决，不再需要非美机房。`deploy_vps.sh` 保留，随时可升级实时 Worker。
- 状态文件目前提交回公开仓库（内容只是信号指纹，无密钥）。

---

## 8. 相关位置

- 代码仓库：https://github.com/beijisi522/doge-oi
- Actions 运行记录：https://github.com/beijisi522/doge-oi/actions
- 资料库本手册（在线可编辑）：https://www.workbuddy.cn/space/d/CAjt1zW1JtXDtzgQUbePoU
- 资料库完整代码包：https://www.workbuddy.cn/space/d/PUzePqWyNhZZOdzqdVJfN6
- 资料库《行情数据源清单_币安_DOGE》：https://www.workbuddy.cn/space/d/W9Ogqf8KIghs0b7e0UdJNf
- 资料库旧项目包 `doge-oi-mac`：早期版本，不含之后的修复；以带日期的最新包为准
