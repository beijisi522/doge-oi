#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DOGE 币本位永续 (DOGEUSD_PERP) — OI 日内短线提醒脚本  v2（信号分级版）
======================================================================
v2 相比 v1 新增:
  * 信号分级 A / B / C
      A 强信号 -> 推 Telegram(手机 + 电脑), 值得据此找入场
      B 中信号 -> 默认仅终端, 是"别做什么"的风控提示
      C 弱信号 -> 仅终端, 边缘/噪音
  * 多信号共振: 同时出现 >=2 个 A 级 -> 加急标注 🚨
  * --once: 拉一次实时数据, 输出「当前情况判定」后退出
  * --demo: 用离线快照演示判定逻辑(不联网), 先看效果用
  * --check: 自检 token/chat_id 是否配对、网络是否通
  * token/chat_id 支持环境变量, 不用改文件
  * 状态持久化: 定时跑 --once 也不会重复推送

用法:
  python3 doge_oi_alert_v2.py --check     # 【第一步】先自检配置
  python3 doge_oi_alert_v2.py            # 常驻轮询 + 分级提醒
  python3 doge_oi_alert_v2.py --once     # 单次判定当前盘面(实时)
  python3 doge_oi_alert_v2.py --demo     # 离线演示, 无需网络

配置方式二选一(推荐 A, 不用打开/修改脚本):
  A. 环境变量(命令行临时设置)
     export DOGE_TG_TOKEN="123456:ABC-DEF..."
     export DOGE_TG_CHAT_ID="123456789"
     python3 doge_oi_alert_v2.py --check
  B. 直接改下面「用户配置区」的两行, 把值填进引号里

提醒通道: Telegram 机器人(手机 App + 电脑桌面端同步弹窗)
运行依赖: 纯 Python 标准库, 无需 pip install
注意: 运行脚本的机器必须能同时访问 api.telegram.org 与 dapi.binance.com
"""

import urllib.request
import urllib.parse
import urllib.error
import json
import os
import time
import sys
import html

# 容器/云主机常为 UTC, 允许用 TZ 环境变量切成北京时间(如 TZ=Asia/Shanghai)
if os.environ.get("TZ"):
    try:
        time.tzset()
    except AttributeError:
        pass  # Windows 无 tzset, 忽略即可

# ====================== 用户配置区 ======================
# 优先读环境变量; 没设就用这里的空值(可直接把值填进引号)
TELEGRAM_TOKEN    = os.environ.get("DOGE_TG_TOKEN") or ""
TELEGRAM_CHAT_ID  = os.environ.get("DOGE_TG_CHAT_ID") or ""
SYMBOL            = "DOGEUSD_PERP"  # 币本位永续符号
PAIR              = "DOGEUSD"       # OI 历史接口用的 pair
POLL_INTERVAL     = 60              # 轮询间隔(秒), 建议 30~120
PERIOD            = "5m"            # 统计周期

# ---- 分级推送设置 ----
PUSH_MIN_LEVEL    = "A"             # 推送门槛: "A"=只推强信号(推荐)
                                    #            "B"=中信号也推手机
MIN_A_RESONANCE   = 2               # 几个 A 级同时出现算「共振」

# ---- 信号阈值(按手感调) ----
PRICE_MOVE  = 0.003    # 价格变动阈值 0.3%
OI_MOVE     = 0.01     # OI 变动阈值 1%
OI_SURGE    = 0.03     # OI 暴增阈值 3%
FLAT_BAND   = 0.002    # 横盘带 ±0.2%
LSR_HIGH    = 1.8      # 多空人数比 极端多头
LSR_LOW     = 0.6      # 多空人数比 极端空头
FUND_HOT    = 0.0005   # 费率过热阈值(0.05%)
# ========================================================

BASE = "https://dapi.binance.com/dapi/v1"
TG_API = "https://api.telegram.org/bot"
# 币安 dapi 对美国 IP 返回 451(GitHub Actions 托管 runner 即属此类)。
# 降级源 OKX 的 DOGE-USD-SWAP 同为「币本位永续」, 信号逻辑不变;
# 币安可用时永远优先用币安, 仅 451/超时才降级, 报告会标注当前数据源。
OKX_BASE = "https://www.okx.com/api/v5"
OKX_INST = "DOGE-USD-SWAP"
SRC_BINANCE = "币安 DOGEUSD_PERP"
SRC_OKX = "OKX DOGE-USD-SWAP (降级源)"
LEVEL_ORDER = {"A": 3, "B": 2, "C": 1}
LEVEL_TAG = {"A": "[A]强", "B": "[B]中", "C": "[C]弱"}
# 状态文件: 记住上次推送过什么, 这样定时跑 --once 或脚本重启都不会重复推送
# 云端 Worker 可用 DOGE_STATE_DIR 指到持久化卷, 容器重启也不会重复推一条;
# GitHub Actions 不设此变量 -> 写在仓库根目录, 供 workflow 提交回仓库
STATE_FILE = os.path.join(os.environ.get("DOGE_STATE_DIR") or
                          os.path.dirname(os.path.abspath(__file__)),
                          ".doge_oi_state.json")
# 模式开关: 一个文件同时控制 GitHub Actions 与云端 Worker, 保证只有一套负责推送
MODE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mode.conf")


def read_mode():
    """读 mode.conf; 文件缺失时按运行环境推断, 避免两边全部静默"""
    try:
        with open(MODE_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("MODE="):
                    v = line.split("=", 1)[1].strip().lower()
                    if v in ("actions", "worker"):
                        return v
    except Exception:
        print("[WARN] 未找到 mode.conf, 按运行环境自动推断", flush=True)
    return "actions" if in_github_actions() else "worker"


def in_github_actions():
    return os.environ.get("GITHUB_ACTIONS", "").lower() == "true"


def push_allowed(mode=None):
    """两套互斥: actions 模式只放行 Actions 侧; worker 模式只放行容器/本地侧"""
    m = mode or read_mode()
    return in_github_actions() if m == "actions" else not in_github_actions()


def load_state():
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(state):
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False)
    except Exception as e:
        print(f"[WARN] 状态文件写入失败(不影响本次运行): {e}", flush=True)


def check_setup():
    """自检: token 有效性 / chat_id 能否收消息 / 两个 API 是否连通"""
    print("=" * 56, flush=True)
    print("  DOGE OI 脚本 配置自检", flush=True)
    print("=" * 56, flush=True)
    proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    print(f"[0] 代理设置: {proxy if proxy else '未检测到(直连)'}", flush=True)

    # 1. token 是否有效
    if not TELEGRAM_TOKEN:
        print("[1] ❌ TELEGRAM_TOKEN 为空 -> 用环境变量 DOGE_TG_TOKEN 设置, 或填进脚本", flush=True)
    else:
        masked = TELEGRAM_TOKEN[:6] + "..." + TELEGRAM_TOKEN[-4:]
        try:
            r = get_json(f"{TG_API}{TELEGRAM_TOKEN}/getMe")
            print(f"[1] ✅ Token 有效 ({masked}), 机器人: @{r['result']['username']}", flush=True)
        except Exception as e:
            print(f"[1] ❌ Token 校验失败: {e}", flush=True)
            print("     -> 要么是 token 抄错, 要么这台机器连不上 api.telegram.org", flush=True)

    # 2. chat_id 能否收到测试消息
    if not TELEGRAM_CHAT_ID:
        print("[2] ❌ TELEGRAM_CHAT_ID 为空 -> 用环境变量 DOGE_TG_CHAT_ID 设置", flush=True)
    elif not TELEGRAM_TOKEN:
        print("[2] ⏭️  跳过(缺 token)", flush=True)
    else:
        try:
            url = f"{TG_API}{TELEGRAM_TOKEN}/sendMessage"
            data = urllib.parse.urlencode({
                "chat_id": TELEGRAM_CHAT_ID,
                "text": "✅ DOGE OI 提醒配置成功！手机和电脑 Telegram 都会收到这条。"
            }).encode()
            with urllib.request.urlopen(url, data=data, timeout=15) as resp:
                j = json.loads(resp.read().decode("utf-8"))
            if j.get("ok"):
                print(f"[2] ✅ 测试消息已发出 (chat_id={TELEGRAM_CHAT_ID}) 去 Telegram 看一眼", flush=True)
            else:
                print(f"[2] ❌ 发送被拒: {j}", flush=True)
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:300]
            print(f"[2] ❌ 发送失败: HTTP {e.code} {e.reason}", flush=True)
            print(f"     Telegram 返回: {detail}", flush=True)
            print("     -> 常见原因: chat_id 填错 / 还没给机器人发过 /start / 填成了用户名", flush=True)
        except Exception as e:
            print(f"[2] ❌ 发送失败: {e}", flush=True)
            print("     -> 常见原因: chat_id 填错, 或你还没给机器人发过 /start", flush=True)

    # 3. 行情数据源连通性。币安对部分地区(含 GitHub Actions 的美国 IP)返回 451,
    #    逐个探测便于一眼看出这台机器上哪些源能用。
    print("[3] 行情数据源连通性:", flush=True)
    probes = [
        ("币安币本位 dAPI", f"{BASE}/ticker/price?symbol={SYMBOL}"),
        ("币安现货镜像", "https://data-api.binance.vision/api/v3/ticker/price?symbol=DOGEUSDT"),
        ("Gate.io 永续", "https://api.gateio.ws/api/v4/futures/usdt/contracts/DOGE_USDT"),
        ("OKX 币本位(降级源)", f"{OKX_BASE}/market/ticker?instId={OKX_INST}"),
    ]
    for name, url in probes:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=8) as r:
                body = r.read(120).decode("utf-8", "replace")
            print(f"    ✅ {name}: {body[:80]}", flush=True)
        except urllib.error.HTTPError as e:
            print(f"    ❌ {name}: HTTP {e.code} {e.reason}", flush=True)
        except Exception as e:
            print(f"    ❌ {name}: {e}", flush=True)

    print("-" * 56, flush=True)
    print("自检完成。1/2 全 ✅, 且第 3 项中「币安币本位 dAPI」或「OKX 币本位」任一可用即可判定。", flush=True)
    print("=" * 56, flush=True)


# ---------------------------------------------------------------
# 离线演示快照: 2026-11-12 上午 多源汇总(日线级别), 非实时 5m
# 来源: CoinGlass / Kairotrade / CoinPulseHQ / TradingView / 币安官网
# 仅用于演示判定逻辑, 实盘请跑 --once 拉实时数据
# ---------------------------------------------------------------
DEMO_SNAPSHOT = {
    "price": 0.06759,
    "prev_open": 0.06847,      # 24h 前, 使 price_chg = -1.29%
    "oi_now": 900.49,          # 全市场 OI, 百万美元
    "oi_prev": 917.56,         # 使 oi_chg = -1.86%
    "fund_now": -0.000001,     # -0.0001% (CoinGlass, 空头付多头)
    "fund_prev": 0.000029,     # +0.0029% (前值, Binance)
    "long_short": None,        # 该快照未取到多空人数比
    "ts": int(time.time() * 1000),
    "extra": [
        "24h 爆仓 $4.00M, 其中多单占 90% ($3.61M)",
        "恐慌贪婪指数 29 (恐惧)",
        "OI 处于近 3 周 1% 分位 (明显低于常态)",
        "价格位于年内区间下 1/3, 距年内低点约 1%",
        "24h 成交额处年度 100% 分位 (异常活跃)",
        "BTC 相关性 0.77, 跟随大盘",
        "日线均线技术面: Strong sell / RSI 34",
    ],
    "_note": "日线级快照(2026-11-12 上午), 演示用; 实时 5m 判定请跑 --once",
}


def get_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode("utf-8"))


def _fetch_snapshot_binance():
    """币安官方口径(优先)。必需字段失败才整体放弃; 多空人数比可缺失"""
    def must(label, fn):
        try:
            return fn()
        except Exception as e:
            print(f"[ERR] {label} 拉取失败: {e}", flush=True)
            raise

    try:
        price = must("价格", lambda: float(
            get_json(f"{BASE}/ticker/price?symbol={SYMBOL}")["price"]))
        kl = must("K线", lambda: get_json(
            f"{BASE}/klines?symbol={SYMBOL}&interval={PERIOD}&limit=2"))
        if not kl:
            raise ValueError("K线返回空")
        prev_open = float(kl[0][1])

        oih = must("OI历史", lambda: get_json(
            f"{BASE}/openInterestHist?pair={PAIR}&contractType=PERPETUAL"
            f"&period={PERIOD}&limit=2"))
        if not oih:
            raise ValueError("OI 历史返回空")
        oi_now = float(oih[-1]["sumOpenInterest"])
        # 开盘/数据缺失时可能只有 1 条, 按"无变化"处理, 避免 IndexError
        oi_prev = float(oih[-2]["sumOpenInterest"]) if len(oih) > 1 else oi_now
        if len(oih) < 2:
            print("[WARN] OI 历史不足 2 条, 本帧 OI 变动按 0 处理", flush=True)

        fr = must("资金费率", lambda: get_json(
            f"{BASE}/fundingRate?symbol={SYMBOL}&limit=2"))
        if not fr:
            raise ValueError("资金费率返回空")
        fund_now = float(fr[-1]["fundingRate"])
        fund_prev = float(fr[-2]["fundingRate"]) if len(fr) > 1 else fund_now
    except Exception as e:
        print(f"[ERR] 必需数据不完整({e}), 本帧跳过判定", flush=True)
        return None

    # 多空人数比是增强项, 币安对部分合约不提供; 缺了不影响主判定
    long_short = None
    try:
        lsr = get_json(f"{BASE}/globalLongShortAccountRatio?"
                       f"symbol={SYMBOL}&period={PERIOD}&limit=1")
        if lsr:
            long_short = float(lsr[-1]["longShortRatio"])
        else:
            print("[WARN] 多空人数比无数据, 本帧忽略该指标", flush=True)
    except Exception as e:
        print(f"[WARN] 多空人数比拉取失败, 本帧忽略该指标: {e}", flush=True)

    return {"price": price, "prev_open": prev_open,
            "oi_now": oi_now, "oi_prev": oi_prev,
            "fund_now": fund_now, "fund_prev": fund_prev,
            "long_short": long_short, "ts": int(time.time() * 1000),
            "extra": [], "_note": ""}


def fetch_snapshot_okx():
    """降级源: OKX 币本位永续 DOGE-USD-SWAP。仅在币安不可用时调用。"""
    def okx(path):
        j = get_json(f"{OKX_BASE}/{path}")
        if j.get("code") != "0" or not j.get("data"):
            raise ValueError(f"OKX 返回异常: {str(j)[:140]}")
        return j["data"]

    try:
        price = float(okx(f"market/ticker?instId={OKX_INST}")[0]["last"])
        kl = okx(f"market/candles?instId={OKX_INST}&bar={PERIOD}&limit=2")
        # OKX K线倒序: [0]=当前根, [1]=上一根; 与币安分支取「上一根开盘」保持一致
        if not kl:
            raise ValueError("K线返回空")
        prev_open = float(kl[1][1]) if len(kl) > 1 else float(kl[0][1])
        # data 倒序: [ts, oi, vol]; 默认 5m 间隔
        oi = okx("rubik/stat/contracts/open-interest-volume?ccy=DOGE")
        if not oi:
            raise ValueError("OI 历史返回空")
        oi_now = float(oi[0][1])
        oi_prev = float(oi[1][1]) if len(oi) > 1 else oi_now
        fr = okx(f"public/funding-rate-history?instId={OKX_INST}&limit=2")
        if not fr:
            raise ValueError("资金费率返回空")
        fund_now = float(fr[0]["fundingRate"])
        fund_prev = float(fr[1]["fundingRate"]) if len(fr) > 1 else fund_now
    except Exception as e:
        print(f"[ERR] OKX 降级源必需数据失败({e}), 本帧跳过判定", flush=True)
        return None

    return {"price": price, "prev_open": prev_open,
            "oi_now": oi_now, "oi_prev": oi_prev,
            "fund_now": fund_now, "fund_prev": fund_prev,
            # OKX 的多空账户比是「币种」维度(实测约 4.9), 与币安「单合约」维度(约 1~3)
            # 口径不同, 直接套 LSR_HIGH/LOW 会永远误判极端多头, 故本维度不参与判定
            "long_short": None, "ts": int(time.time() * 1000),
            "extra": [], "_source": SRC_OKX,
            "_note": "降级源 OKX; 多空账户比口径不同, 本帧不参与判定"}


def fetch_snapshot():
    """币安官方口径优先; 451/网络失败时自动降级到 OKX 币本位永续。

    设 DOGE_DISABLE_FALLBACK=1 可禁用降级(只用币安)。
    """
    snap = _fetch_snapshot_binance()
    if snap is not None:
        snap["_source"] = SRC_BINANCE
        return snap
    if os.environ.get("DOGE_DISABLE_FALLBACK", "").strip() == "1":
        return None
    print("[FALLBACK] 币安不可用, 切换 OKX 币本位 DOGE-USD-SWAP", flush=True)
    return fetch_snapshot_okx()


def gen_signals(d):
    """生成带级别的信号: [(level, title, detail), ...]"""
    price_chg = (d["price"] - d["prev_open"]) / d["prev_open"]
    oi_chg = (d["oi_now"] - d["oi_prev"]) / d["oi_prev"]
    fund_chg = d["fund_now"] - d["fund_prev"]
    lsr = d.get("long_short")
    p, o = f"{price_chg*100:+.2f}%", f"{oi_chg*100:+.2f}%"
    sigs = []

    # --- A 级: OI 增加类(新资金进场, 趋势有持续性) + 极端反向信号 ---
    if price_chg > PRICE_MOVE and oi_chg > OI_MOVE and d["fund_now"] > 0 and fund_chg > 0:
        sigs.append(("A", "⚠️ 多头过热",
                     f"价{p} OI{o} 费率{d['fund_now']*100:+.4f}%↑ 三因子共振, 不追多/等 OI 拐点做空"))
    if price_chg < -PRICE_MOVE and oi_chg > OI_MOVE:
        sigs.append(("A", "🐻 空头砸盘",
                     f"价{p} OI{o} 新空真进场, 反弹做空胜率高(趋势可持续)"))
    if abs(price_chg) < FLAT_BAND and oi_chg > OI_SURGE:
        sigs.append(("A", "🔥 变盘前兆",
                     f"价{p}(横盘) OI{o} 大资金堆积, 盯突破且须 OI 同步放大才跟"))
    if lsr is not None and lsr > LSR_HIGH:
        sigs.append(("A", "📊 人数比极端多",
                     f"多空比 {lsr:.2f} > {LSR_HIGH} 散户一边倒, 反向做空胜率高(DOGE 很灵)"))
    if lsr is not None and lsr < LSR_LOW:
        sigs.append(("A", "📊 人数比极端空",
                     f"多空比 {lsr:.2f} < {LSR_LOW} 恐慌出清, 留意做多反弹"))

    # --- B 级: OI 减少类(平仓/回补, 是"别做什么"的风控提示) ---
    if price_chg > PRICE_MOVE and oi_chg < -OI_MOVE:
        sigs.append(("B", "↩️ 回补反弹",
                     f"价{p} OI{o} 空头回补式虚涨, 易回落, 不追多/多单落袋"))
    if price_chg < -PRICE_MOVE and oi_chg < -OI_MOVE:
        sigs.append(("B", "💧 多头割肉",
                     f"价{p} OI{o} 多头在平仓非新空, 勿追空, 等 OI 企稳"))

    # --- C 级: 边缘/噪音 ---
    if d["fund_now"] > FUND_HOT:
        sigs.append(("C", "💵 费率偏高",
                     f"费率 {d['fund_now']*100:+.4f}% > 阈值, 多头拥挤度上升"))
    if abs(oi_chg) < 0.002 and abs(price_chg) < FLAT_BAND:
        sigs.append(("C", "😴 垃圾时间",
                     f"价{p} OI{o} 资金离场/无方向, 减少操作"))

    return sigs, price_chg, oi_chg


def judge_market(d, price_chg, oi_chg):
    """输出「当前是啥情况」: (状态名, 解读, 操作倾向)"""
    p, o = f"{price_chg*100:+.2f}%", f"{oi_chg*100:+.2f}%"
    fund = d["fund_now"]
    lsr = d.get("long_short")

    if price_chg > PRICE_MOVE and oi_chg > OI_MOVE:
        state = "多头增仓推动"
        read = f"价{p} + OI{o}, 是新多进场而非空头回补, 涨势有资金支撑、可持续。"
        bias = f"回踩跟多为主; 但费率{fund*100:+.4f}%若同步走高, 转「多头过热」则改等拐点做空。"
    elif price_chg > PRICE_MOVE and oi_chg < -OI_MOVE:
        state = "空头回补反弹(虚涨)"
        read = f"价{p} 但 OI{o}, 上涨来自空头平仓而非新多, 买盘不实。"
        bias = "不追多, 多单逢高落袋; 上方阻力若 OI 不增, 可轻仓试空。"
    elif price_chg < -PRICE_MOVE and oi_chg > OI_MOVE:
        state = "空头增仓砸盘"
        read = f"价{p} + OI{o}, 新空真金白银进场, 跌势有持续性。"
        bias = "反弹做空为主, 止损放 OI 开始回落处; 别急着抄底。"
    elif price_chg < -PRICE_MOVE and oi_chg < -OI_MOVE:
        state = "多头减仓 / Long Unwinding"
        read = (f"价{p} + OI{o}, 杀跌来自**多头平仓/被强平**, 不是新空进场 —— "
                "属于「旧钱撤退」而非「新钱做空」, 抛压会随平仓完成而衰减。")
        bias = ("⚠️ 不追空(最容易追在坑里)。等 OI 止跌企稳 + 价格不再创新低, "
                "再轻仓做超跌反弹, 严格止损; 只按「反弹」不按「反转」对待。")
    elif abs(price_chg) < FLAT_BAND and oi_chg > OI_SURGE:
        state = "OI 堆积 / 变盘前兆"
        read = f"价{p}(横盘) 但 OI{o} 暴增, 多空在悄悄建仓博弈。"
        bias = "别猜方向, 等突破; 突破那一刻 OI 同步放大才跟, 否则当假突破。"
    elif abs(price_chg) < FLAT_BAND and oi_chg < -OI_SURGE:
        state = "资金离场 / 垃圾时间"
        read = f"价{p} 且 OI{o}, 资金在撤, 波动会被压缩。"
        bias = "减少操作, 等 OI 重新回升再进场。"
    else:
        state = "震荡整理 / 方向不明"
        read = f"价{p} OI{o}, 变动都未达阈值, 无明确主导方。"
        bias = "观望, 或只在关键位做小仓位高抛低吸。"

    extra = []
    if lsr is not None:
        extra.append(f"多空人数比 {lsr:.2f}"
                     + (" (极端多头, 反向偏空)" if lsr > LSR_HIGH else
                        " (极端空头, 反向偏多)" if lsr < LSR_LOW else " (中性)"))
    if fund < 0:
        extra.append(f"资金费率 {fund*100:+.4f}% 为负(空头付多头), 多头拥挤度已释放")
    elif fund > FUND_HOT:
        extra.append(f"资金费率 {fund*100:+.4f}% 偏高, 多头偏拥挤")
    for line in d.get("extra", []):
        extra.append(line)
    if extra:
        read += "\n  补充: " + "; ".join(extra)

    return state, read, bias


def render_report(d, sigs, price_chg, oi_chg, resonance):
    """渲染一份完整判定报告(纯文本, 终端/Telegram 通用)"""
    state, read, bias = judge_market(d, price_chg, oi_chg)
    lsr = d.get("long_short")
    lines = []
    lines.append("=" * 56)
    lines.append(f"  DOGE 币本位 OI 盘面判定   {fmt_time(d['ts'])}")
    if d.get("_source"):
        lines.append(f"  数据源: {d['_source']}")
    if d.get("_note"):
        lines.append(f"  ⚠️ {d['_note']}")
    lines.append("=" * 56)
    lines.append(f"价格 {d['price']:.5f}  |  周期变动 {price_chg*100:+.2f}%  |  OI变动 {oi_chg*100:+.2f}%")
    lines.append(f"资金费率 {d['fund_now']*100:+.4f}%  |  多空人数比 "
                 + (f"{lsr:.2f}" if lsr is not None else "缺数据"))
    lines.append("")
    lines.append(f"【当前状态】{state}")
    lines.append(f"  解读: {read}")
    lines.append(f"  操作: {bias}")
    lines.append("")
    a = [s for s in sigs if s[0] == "A"]
    b = [s for s in sigs if s[0] == "B"]
    c = [s for s in sigs if s[0] == "C"]
    lines.append(f"【信号】A强 {len(a)} / B中 {len(b)} / C弱 {len(c)}"
                 + ("   🚨 多信号共振(加急)" if resonance else ""))
    if not sigs:
        lines.append("  (无信号, 市场平静)")
    for lv, title, detail in sigs:
        lines.append(f"  {LEVEL_TAG[lv]} {title}: {detail}")
    lines.append("")
    mode = read_mode()
    side = "GitHub Actions" if in_github_actions() else "Worker/本地"
    owner = "是(本进程负责推)" if push_allowed(mode) else "否(另一套负责, 本次只判定)"
    lines.append(f"  运行模式: {mode} | 当前进程: {side} | 负责推送: {owner}")
    lines.append(f"  推送规则: 仅 {PUSH_MIN_LEVEL} 级及以上推送到手机; "
                 "其余只留电脑终端")
    lines.append("=" * 56)
    return "\n".join(lines)


def esc(s):
    """Telegram HTML 模式转义: 信号文案含 < > 等符号, 不转义会拒收整条消息"""
    return html.escape(str(s), quote=False)


def send_telegram(text, force=False):
    """force=True 用于 --check 的测试消息, 不受模式开关限制"""
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return
    if not force and not push_allowed():
        print(f"[静默] 当前为 {read_mode()} 模式, 本进程不负责推送(另一套在负责)", flush=True)
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    # 消息里的 <b> 是静态标签; 所有动态内容必须经 esc() 转义, 否则 Telegram
    # 会返回 "can't parse entities" 并拒收整条消息
    data = urllib.parse.urlencode({"chat_id": TELEGRAM_CHAT_ID,
                                    "text": text,
                                    "parse_mode": "HTML"}).encode()
    try:
        with urllib.request.urlopen(url, data=data, timeout=15) as resp:
            j = json.loads(resp.read().decode("utf-8"))
        if not j.get("ok"):
            print(f"[ERR] Telegram 拒收: {j}", flush=True)
    except Exception as e:
        print(f"[ERR] 发Telegram失败: {e}", flush=True)


def need_push(sigs, resonance):
    """是否达到推送门槛"""
    if resonance:
        return True
    return any(LEVEL_ORDER[s[0]] >= LEVEL_ORDER[PUSH_MIN_LEVEL] for s in sigs)


def fmt_time(ts):
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts / 1000))


def once(d, demo=False):
    """单次判定: 打印报告, 达标且信号有变化才推送(状态存文件, 防重复)"""
    sigs, price_chg, oi_chg = gen_signals(d)
    resonance = sum(1 for s in sigs if s[0] == "A") >= MIN_A_RESONANCE
    report = render_report(d, sigs, price_chg, oi_chg, resonance)
    print(report, flush=True)
    if demo:
        return sigs

    # 模式互斥: 不由本进程负责时只判定打印, 不推送也不改状态
    # (不改状态很关键, 否则切回本模式时会因为"上次已推过"而漏掉一条信号)
    if not push_allowed():
        print(f"[静默] 当前 MODE={read_mode()}, 本进程不负责推送, 本次仅判定"
              " (由另一套部署负责)。若要让本进程负责, 请改 mode.conf 的 MODE 行", flush=True)
        return sigs

    push_sigs = [s for s in sigs
                 if LEVEL_ORDER[s[0]] >= LEVEL_ORDER[PUSH_MIN_LEVEL]]
    push_key = "|".join(s[1] for s in push_sigs)
    st = load_state()
    prev = st.get("push_key", "")

    if not (TELEGRAM_TOKEN and TELEGRAM_CHAT_ID):
        print("[提示] 未配置 Telegram, 本次不推送(只打印)", flush=True)
        return sigs

    if push_key and push_key != prev:
        msg = "🔔 <b>DOGE OI 信号" + (" (🚨共振加急)" if resonance else "") + "</b>\n"
        msg += "\n".join(f"{esc(LEVEL_TAG[lv])} {esc(t)}\n   {esc(dt)}"
                         for lv, t, dt in push_sigs)
        msg += f"\n\n当前状态: {esc(judge_market(d, price_chg, oi_chg)[0])}"
        if d.get("_source"):
            msg += f"\n数据源: {esc(d['_source'])}"
        print(">>> 推送到手机 + 电脑 Telegram", flush=True)
        send_telegram(msg)
        st["push_key"] = push_key
        save_state(st)
    elif not push_key and prev:
        print(">>> 强信号解除", flush=True)
        send_telegram("✅ DOGE 强信号解除, 市场恢复平静")
        st["push_key"] = ""
        save_state(st)
    else:
        print(">>> 信号无变化, 不重复推送", flush=True)
    return sigs


def hourly():
    """每小时盘面汇总: 不受 A 级门槛限制, 固定推一条(手机 Telegram + 电脑弹窗)。

    同一个 UTC 小时只推一次, 靠状态文件里的 last_hour 去重 —— 这样
    GitHub 每小时 cron 与本机触发器的兜底不会重复推两条。
    """
    print("[每小时盘面汇总模式] 本次不受 A 级门槛限制\n", flush=True)
    d = fetch_snapshot()
    if not d:
        print("[ERR] 行情拉取失败, 本次不出汇总", flush=True)
        return

    sigs, price_chg, oi_chg = gen_signals(d)
    resonance = sum(1 for s in sigs if s[0] == "A") >= MIN_A_RESONANCE
    state, read, bias = judge_market(d, price_chg, oi_chg)
    # 打印完整报告, 桌面通知脚本会从日志里提取 价格/状态/信号 三行
    print(render_report(d, sigs, price_chg, oi_chg, resonance), flush=True)

    hour_key = time.strftime("%Y-%m-%d %H", time.gmtime()) + " UTC"
    st = load_state()
    if st.get("last_hour") == hour_key:
        print(f">>> 本小时({hour_key})已汇总过, 跳过(去重)", flush=True)
        return
    if not push_allowed():
        print("[静默] 当前 MODE 下本进程不负责推送, 汇总仅打印", flush=True)
        return
    if not (TELEGRAM_TOKEN and TELEGRAM_CHAT_ID):
        print("[提示] 未配置 Telegram, 汇总仅打印", flush=True)
        return

    lsr = d.get("long_short")
    a = sum(1 for s in sigs if s[0] == "A")
    b = sum(1 for s in sigs if s[0] == "B")
    c = sum(1 for s in sigs if s[0] == "C")
    lines = [
        "📊 <b>DOGE 每小时盘面汇总</b>",
        esc(f"{fmt_time(d['ts'])}  |  {hour_key}"),
        "",
        esc(f"价格 {d['price']:.5f}   周期 {price_chg*100:+.2f}%   OI {oi_chg*100:+.2f}%"),
        esc("资金费率 %+.4f%%   多空账户比 %s" % (
            d["fund_now"] * 100, f"{lsr:.2f}" if lsr is not None else "缺数据")),
        "",
        esc(f"状态: {state}"),
        esc(f"信号: A强 {a} / B中 {b} / C弱 {c}" + ("   🚨共振" if resonance else "")),
    ]
    for lv, title, detail in sigs[:4]:
        lines.append(esc(f"   {LEVEL_TAG[lv]} {title}: {detail}"))
    lines += ["", esc(f"操作: {bias}")]
    if d.get("_source"):
        lines.append(esc(f"数据源: {d['_source']}"))
    if d.get("_note"):
        lines.append(esc(f"注: {d['_note']}"))
    msg = "\n".join(lines)

    print(">>> 每小时盘面汇总已推送 (Telegram 手机+电脑 / macOS 弹窗)", flush=True)
    send_telegram(msg)
    # 保留原有 push_key, 否则会把「上次推过什么信号」清掉导致重复推 A 级
    st["last_hour"] = hour_key
    save_state(st)


def main():
    args = sys.argv[1:]
    if "--check" in args:
        check_setup()
        return
    if "--demo" in args:
        print("[离线演示模式, 不联网]\n", flush=True)
        once(DEMO_SNAPSHOT, demo=True)
        return
    if "--once" in args:
        print("[单次实时判定模式]\n", flush=True)
        d = fetch_snapshot()
        if d:
            once(d)
        return
    if "--hourly" in args:
        hourly()
        return

    print("=== DOGE 币本位 OI 提醒脚本 v2 (信号分级版) 启动 ===", flush=True)
    print(f"标的 {SYMBOL} | 轮询 {POLL_INTERVAL}s | 周期 {PERIOD} | 推送门槛 {PUSH_MIN_LEVEL} 级", flush=True)
    _m = read_mode()
    print(f"运行模式: {_m} | 本进程负责推送: {'是' if push_allowed(_m) else '否(静默监控, 由另一套负责)'}",
          flush=True)
    if not push_allowed(_m):
        print("⚠️ 本进程只判定、不推送 Telegram (由另一套部署负责);"
              " 需切换负责人请改 mode.conf 的 MODE 行", flush=True)
    if TELEGRAM_TOKEN and TELEGRAM_CHAT_ID:
        print("Telegram: 已配置 (手机 + 电脑同步提醒)", flush=True)
    else:
        print("Telegram: 未配置, 仅电脑终端打印 (先跑 --check 自检)", flush=True)

    # 从状态文件恢复, 脚本重启后不会把上次已推过的信号再推一遍
    last_push_key = load_state().get("push_key", "")
    while True:
        d = fetch_snapshot()
        if d:
            sigs, price_chg, oi_chg = gen_signals(d)
            resonance = sum(1 for s in sigs if s[0] == "A") >= MIN_A_RESONANCE
            print(f"[{fmt_time(d['ts'])}] 价{d['price']:.5f} "
                  f"{price_chg*100:+.2f}% | OI {oi_chg*100:+.2f}% | "
                  f"费率{d['fund_now']*100:+.4f}% | "
                  f"A{sum(1 for s in sigs if s[0]=='A')} "
                  f"B{sum(1 for s in sigs if s[0]=='B')} "
                  f"C{sum(1 for s in sigs if s[0]=='C')}", flush=True)
            for lv, title, detail in sigs:
                action = "→推手机" if LEVEL_ORDER[lv] >= LEVEL_ORDER[PUSH_MIN_LEVEL] else "→仅终端"
                print(f"   {LEVEL_TAG[lv]} {title} {action}: {detail}", flush=True)

            # 静默侧照常监控打印, 但不推送也不写状态(不退出, 避免容器被判定崩溃反复重启)
            if not push_allowed():
                time.sleep(POLL_INTERVAL)
                continue

            push_key = "|".join(s[1] for s in sigs
                                if LEVEL_ORDER[s[0]] >= LEVEL_ORDER[PUSH_MIN_LEVEL])
            if need_push(sigs, resonance) and push_key and push_key != last_push_key:
                msg = "🔔 <b>DOGE OI 信号" + (" (🚨共振加急)" if resonance else "") + "</b>\n"
                for lv, t, dt in sigs:
                    if LEVEL_ORDER[lv] >= LEVEL_ORDER[PUSH_MIN_LEVEL]:
                        msg += f"{esc(LEVEL_TAG[lv])} {esc(t)}\n   {esc(dt)}\n"
                msg += f"\n当前状态: {esc(judge_market(d, price_chg, oi_chg)[0])}"
                print(">>> 推送到手机+电脑", flush=True)
                send_telegram(msg)
                last_push_key = push_key
                save_state({"push_key": push_key})
            elif not push_key and last_push_key:
                print(">>> 强信号解除(恢复平静)", flush=True)
                send_telegram("✅ DOGE 强信号解除, 市场恢复平静")
                last_push_key = ""
                save_state({"push_key": ""})
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n已停止。", flush=True)
        sys.exit(0)
