"""AI 需求监控信号层:A 定价行为(新浪美股,日频)+ B 增长质量(SEC XBRL 机读 + 台账)。

数据源实测(2026-10-11,全部免费匿名):
- 新浪实时 hq.sinajs.cn/list=gb_xxx   → 现价 + 52 周高(需 Referer)
- 新浪历史 K  US_MinKService.getDailyK?symbol=xxx → 全量日 K(OHLCV)
- SEC XBRL companyconcept(需 UA 含联系方式)→ capex/OCF 权威季帧(frame 标记)
- B1/B3 为台账常量(高盛 9-23 口径),人工随研报更新——机器不造预测

输出:data/signal_state.json。纪律:机器只统计现象与状态灯,不输出退出概率;
状态灯按固定阈值(历史分位待数据累积后切换)。

A3 利好弹性衰减 v1 未启用:需人工事件表(事件日登记),事件表建好前该指标
在 state 中为 null,看板显示"待事件表"。
"""
from . import tz
import datetime as dt
import json
import pathlib
import re

import os as _os
import requests

ROOT = pathlib.Path(__file__).resolve().parent.parent
STATE = ROOT / "data" / "signal_state.json"

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36"}
SEC_UA = {"User-Agent": "ai-signal-tracker research " + _os.environ.get("SEC_CONTACT_EMAIL", "research") + ""}

# 篮子定义(新浪 gb_ 符号小写)
HARDWARE = ["wdc", "smh", "nvda", "mu", "amd"]          # A1 硬件贝塔篮
SOFTWARE = ["msft", "crm", "now", "adbe"]               # A2 软件腿
SEMI_REF = "smh"                                        # A2 半导体腿(SMH ETF)

# B 层台账常量(人工维护;来源=高盛 2026-09-23 研究,经媒体转引)
CAPEX_GROWTH = [94, 50, 17]        # 四大 CSP capex yoy:E2026/E2027/E2028
AI_EARNINGS_SHARE = 50             # AI 对标普 500 盈利增长贡献 %,高盛口径
B4_META = {"NVDA": 89.0, "AMD": 6.7, "AVGO": 16.7}  # 最新 DC 收入 $B(参考,真值读库)


def _sina_quotes(symbols) -> dict:
    """新浪实时:gb_xxx → {sym: {price, high52w}}"""
    r = requests.get("https://hq.sinajs.cn/list=" + ",".join(f"gb_{s}" for s in symbols),
                     headers={**UA, "Referer": "https://finance.sina.com.cn/"}, timeout=15)
    out = {}
    for line in r.content.decode("gbk", "replace").split(";"):
        m = re.match(r'\s*var hq_str_gb_(\w+)="(.*)"', line)
        if not m:
            continue
        f = m.group(2).split(",")
        if len(f) > 32:
            # 字段序:0名称 1现价 … 8 52周高 9 52周低
            out[m.group(1)] = {"price": float(f[1]), "high52w": float(f[8]),
                               "low52w": float(f[9])}
    return out


def _sina_daily(symbol) -> list:
    """新浪历史日 K → [(date, close)] 按日期升序"""
    url = ("https://stock.finance.sina.com.cn/usstock/api/jsonp_v2.php/"
           f"var%20t=/US_MinKService.getDailyK?symbol={symbol}")
    r = requests.get(url, headers={**UA, "Referer": "https://finance.sina.com.cn/"}, timeout=20)
    m = re.search(r"\((\[.*\])\)", r.text, re.S)
    if not m:
        return []
    data = json.loads(m.group(1))
    return sorted([(d["d"], float(d["c"])) for d in data])


def _a1_drawdown() -> dict:
    """硬件贝塔篮子:每只距 52 周高回撤,篮子取中位;阈值 ≥40 红 / ≥25 黄"""
    q = _sina_quotes(HARDWARE)
    rows = []
    for s in HARDWARE:
        if s not in q or not q[s]["high52w"]:
            continue
        dd = (q[s]["price"] / q[s]["high52w"] - 1) * 100
        rows.append({"sym": s.upper(), "price": q[s]["price"],
                     "high52w": q[s]["high52w"], "dd": round(dd, 1)})
    if not rows:
        return {"value": None, "status": "nodata", "rows": []}
    dds = sorted(r["dd"] for r in rows)
    med = dds[len(dds) // 2]
    worst = min(rows, key=lambda r: r["dd"])   # 中位会掩盖 WDC 式单只深回撤,
    worst_dd = worst["dd"]                      # 故状态取 中位与最差 双判定
    status = ("red" if (med <= -40 or worst_dd <= -45)
              else "amber" if (med <= -25 or worst_dd <= -30) else "ok")
    # 最差标的存 60 根日 K 供看板画「价格先杀」线(仅 worst 一只,控流量)
    wdc_daily = []
    if worst_dd <= -25:
        try:
            wdc_daily = [{"d": d, "c": c} for d, c in _sina_daily(worst["sym"])][-60:]
        except Exception:
            pass
    return {"value": round(med, 1), "status": status, "rows": rows, "worst": worst,
            "worst_daily": wdc_daily}


def _index(closes_by_sym: dict, symbols) -> list:
    """多标的等权指数(各自基期=100 再取均值;以最短序列对齐尾部)"""
    series = {s: [c for _, c in closes_by_sym[s]] for s in symbols if s in closes_by_sym}
    n = min(len(v) for v in series.values())
    tails = {s: v[-n:] for s, v in series.items()}
    out = []
    for i in range(n):
        vals = [tails[s][i] / tails[s][0] * 100 for s in symbols if s in series]
        out.append(sum(vals) / len(vals))
    return out


def _a2_ratio_quantile() -> dict:
    """软件/半导体比价:比值 120 日分位;≤20% 分位 = 黄"""
    daily = {s: _sina_daily(s) for s in SOFTWARE + [SEMI_REF]}
    sw = _index(daily, SOFTWARE)
    semi = _index(daily, [SEMI_REF])
    n = min(len(sw), len(semi), 250)
    if not n:
        return {"value": None, "status": "nodata"}
    ratio = [sw[-n + i] / semi[-n + i] * 100 for i in range(n)]
    cur = ratio[-1]
    win = ratio[-120:]
    q = sum(1 for x in win if x <= cur) / len(win) * 100
    status = "amber" if q <= 20 else "ok"
    return {"value": round(cur / 100, 2), "quantile": round(q), "status": status,
            "spark": [round(x / 100, 2) for x in win]}


def _b2_capex_ocf() -> dict:
    """SEC XBRL:四家最新季帧 capex/OCF;>70 黄 / >100 红"""
    ciks = {"MSFT": "0000789019", "AMZN": "0001018724",
            "GOOGL": "0001652044", "META": "0001326801"}

    import datetime as _dt
    def _fresh(x) -> bool:
        return (tz.today() - dt.date.fromisoformat(x["end"])).days <= 400
    def latest_q(cik, tags):
        """按序尝试 tag 列表:先取带权威季帧(frame)的最新行;若无 400 天内的
        frame 行则回退最新 10-Q 窗口行(AMZN 的 capex 记在
        PaymentsToAcquireProductiveAssets,标准 tag 无近期 frame,实测踩坑)。"""
        best = None
        for tag in tags:
            r = requests.get(f"https://data.sec.gov/api/xbrl/companyconcept/"
                             f"CIK{cik}/us-gaap/{tag}.json", headers=SEC_UA, timeout=25)
            if r.status_code != 200:
                continue
            units = r.json().get("units", {}).get("USD", [])
            fr = [x for x in units if x.get("frame") and "Q" in x["frame"] and _fresh(x)]
            if fr:
                return max(fr, key=lambda x: x["end"])
            qs = [x for x in units if x.get("form") == "10-Q" and _fresh(x)
                  and 80 <= (int(x["end"].replace("-", ""))
                             - int(x["start"].replace("-", ""))) <= 200]
            if qs:
                cand = max(qs, key=lambda x: x["end"])
                if best is None or cand["end"] > best["end"]:
                    best = {**cand, "_tag": tag}
        return best

    rows, frame_ref = [], None
    for co, cik in ciks.items():
        cap = latest_q(cik, ["PaymentsToAcquirePropertyPlantAndEquipment",
                             "PaymentsToAcquireProductiveAssets"])
        ocf = latest_q(cik, ["NetCashProvidedByUsedInOperatingActivities"])
        if not (cap and ocf):
            continue
        rows.append({"sym": co, "frame": ocf["frame"],
                     "capex": round(cap["val"] / 1e9, 1),
                     "ocf": round(ocf["val"] / 1e9, 1),
                     "ratio": round(cap["val"] / ocf["val"] * 100)})
    if not rows:
        return {"rows": [], "status": "nodata"}
    frame_ref = rows[-1]["frame"]
    worst = max(rows, key=lambda r: r["ratio"])
    status = "red" if worst["ratio"] >= 100 else "amber" if worst["ratio"] >= 70 else "ok"
    return {"rows": rows, "status": status, "worst": worst, "frame": frame_ref}


def _b1_second_derivative() -> dict:
    g = CAPEX_GROWTH
    d2 = [g[i + 1] - g[i] for i in range(len(g) - 1)]      # [-44, -33]
    status = "amber" if all(x < 0 for x in d2) else "ok"
    return {"growth": g, "d2": d2, "status": status,
            "source": "高盛 2026-09-23(台账/常量,人工更新)"}


def _b4_from_db(con) -> dict:
    try:
        rows = con.execute(
            "SELECT ticker, period, value_musd, yoy_pct FROM dc_revenue "
            "ORDER BY filed_at DESC").fetchall()
    except Exception:
        return {"status": "nodata"}
    seen, out = set(), []
    for r in rows:
        if r["ticker"] in seen:
            continue
        seen.add(r["ticker"])
        out.append({"ticker": r["ticker"], "period": r["period"],
                    "musd": r["value_musd"], "yoy": r["yoy_pct"]})
        if len(out) == 3:
            break
    return {"rows": out, "status": "ok" if out else "nodata"}


def _score_from_status(st) -> int:
    return {"ok": 10, "amber": 60, "red": 90, "nodata": 30}.get(st, 30)


def compute(con) -> dict:
    a1 = _a1_drawdown()
    a2 = _a2_ratio_quantile()
    b1 = _b1_second_derivative()
    b2 = _b2_capex_ocf()
    b4 = _b4_from_db(con)
    a3 = {"status": "nodata", "note": "待人工事件表"}

    layer_a_items = {"A1": a1, "A2": a2, "A3": a3}
    layer_b_items = {"B1": b1, "B2": b2, "B3": {"status": "nodata", "note": "台账人工"},
                     "B4": b4}
    w_a = {"A1": 20, "A2": 15, "A3": 10}
    w_b = {"B1": 15, "B2": 15, "B3": 5, "B4": 5}

    def layer_score(items, weights):
        num = den = 0
        for k, w in weights.items():
            if items[k].get("status") != "nodata":
                num += _score_from_status(items[k]["status"]) * w
                den += w
        return round(num / den) if den else 30

    sa, sb = layer_score(layer_a_items, w_a), layer_score(layer_b_items, w_b)
    sc = 10  # C 层 v1 无自动观测,按正常基线;人工事件表建成后接真值
    total = round(sa * 0.45 + sb * 0.40 + sc * 0.15)

    def layer_status(s):
        return "red" if s >= 80 else "amber" if s >= 40 else "ok"

    return {
        "at": tz.now().isoformat(timespec="seconds"),
        "total": total,
        "verdict": ("行动级信号存在(跨层共振)" if sum(
            x["status"] == "red" for x in [a1, a2, b1, b2, b4]) >= 2
            else "观察中 · 无红色行动信号" if max(sa, sb, sc) >= 40
            else "三层均无异常"),
        "layers": {
            "A": {"score": sa, "status": layer_status(sa), "weight": 45,
                  "items": {"A1": a1, "A2": a2, "A3": a3}},
            "B": {"score": sb, "status": layer_status(sb), "weight": 40,
                  "items": {"B1": b1, "B2": b2, "B3": {"status": "nodata"}, "B4": b4}},
            "C": {"score": sc, "status": layer_status(sc), "weight": 15,
                  "note": "人工事件表未建,基线正常"},
        },
        "disclaimer": "机器只统计现象与状态灯,不输出退出概率;行动由人决定",
    }


def refresh(con, verbose: bool = True) -> dict:
    state = compute(con)
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
    if verbose:
        print(f"[signals] 读数 {state['total']} · {state['verdict']} "
              f"(A {state['layers']['A']['score']} / "
              f"B {state['layers']['B']['score']} / C {state['layers']['C']['score']})")
    return state



def _butler_ping(task):
    """管家心跳(fail-open):butler 桥接器未开时静默跳过。"""
    try:
        import urllib.request
        urllib.request.urlopen(f"http://127.0.0.1:8890/ping/{task}?state=ok", timeout=2)
    except Exception:
        pass

if __name__ == "__main__":
    import sqlite3
    con = sqlite3.connect(ROOT / "data" / "signal.db")
    con.row_factory = sqlite3.Row
    refresh(con)
    con.close()
    _butler_ping("ai_signal_morning")
