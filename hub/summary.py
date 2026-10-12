"""看板要点计算:本地 /api/summary 与 Vercel 静态发布(summary.json)共用。"""
import json
import pathlib
import sqlite3
import time

P = pathlib.Path(__file__).resolve().parents[1]
PB = P / "boards"
# monorepo 短目录名映射(开源版目录:storage/mlcc/fabric/signal;factor/scenario 为可选非开源板)
_D = {"storage-price-tracker": "storage", "mlcc-price-tracker": "mlcc",
      "fabric-price-tracker": "fabric", "ai-signal-tracker": "signal"}

def ro(db):
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=2)
    con.row_factory = sqlite3.Row
    return con


def sum_storage():
    con = ro(PB / _D["storage-price-tracker"] + "/data/storage.db")
    rows = con.execute("SELECT q.date d, q.avg v FROM quotes q "
                       "JOIN products p ON p.id=q.product_id "
                       "WHERE p.name='DRAM指数' ORDER BY q.date").fetchall()
    pct = (rows[-1]["v"] / rows[0]["v"] - 1) * 100 if len(rows) > 1 and rows[0]["v"] else None
    asof = con.execute("SELECT MAX(date) m FROM quotes").fetchone()["m"]
    head = f"DRAM 指数 {rows[-1]['v']:.0f} 点" + (f" · 自{rows[0]['d'][:7]} {pct:+.1f}%" if pct is not None else "")
    n = con.execute("SELECT COUNT(*) n FROM products").fetchone()["n"]
    return dict(ok=True, headline=f"{head} · 在库 {n} 品", asof=asof, nxt="每日 18:40")


def sum_mlcc():
    con = ro(PB / _D["mlcc-price-tracker"] + "/data/mlcc.db")
    low = con.execute("SELECT COUNT(*) n FROM quotes WHERE date=(SELECT MAX(date) FROM quotes) "
                      "AND stock>0 AND stock<10000").fetchone()["n"]
    total = con.execute("SELECT COUNT(*) n FROM products").fetchone()["n"]
    asof = con.execute("SELECT MAX(date) m FROM quotes").fetchone()["m"]
    head = f"{low} 个料号低库存（<1万颗）" if low else "库存水位正常"
    return dict(ok=True, headline=f"{head} · {total} 序列日更累积中", asof=asof, nxt="每日 20:10")


def sum_fabric():
    con = ro(PB / _D["fabric-price-tracker"] + "/data/fabric.db")
    n = con.execute("SELECT COUNT(*) n FROM anchors").fetchone()["n"]
    last = con.execute("SELECT date d, item i FROM anchors ORDER BY date DESC LIMIT 1").fetchone()
    imp7 = con.execute("SELECT COUNT(*) n FROM announcements WHERE tag LIKE '重要%' "
                       "AND date >= date('now','-7 day')").fetchone()["n"]
    asof = con.execute("SELECT MAX(date) m FROM announcements").fetchone()["m"]
    return dict(ok=True, headline=f"锚点 {n} 条 · 近7日重要公告 {imp7} 条 · 最新：{last['i']}",
                asof=max(asof, last["d"]), nxt="每日 20:40")


def sum_signal():
    con = ro(PB / _D["ai-signal-tracker"] + "/data/signal.db")
    n_abf = con.execute("SELECT COUNT(*) n FROM anchors WHERE item LIKE 'ABF%'").fetchone()["n"]
    n_exit = con.execute("SELECT COUNT(*) n FROM anchors WHERE cat='退出日历'").fetchone()["n"]
    last = con.execute("SELECT date d, item i FROM anchors ORDER BY date DESC LIMIT 1").fetchone()
    n_csp = 0
    try:
        import csv as _csv
        with open(PB / _D["ai-signal-tracker"] + "/data/csp_ledger.csv", encoding="utf-8-sig", newline="") as f:
            n_csp = sum(1 for _ in _csv.DictReader(f))
    except Exception:
        pass
    return dict(ok=True,
                headline=f"ABF 锚点 {n_abf} · 退出日历 {n_exit} · capex 台账 {n_csp} 条 · 最新：{last['i']}",
                asof=last["d"] or "", nxt="人工台账,无定时刷新")


def sum_factor():
    """因子失效监测台：读 factor-monitor 的 state.json（无 SQLite）。"""
    j = json.load(open(PB / "factor-monitor/data/state.json", encoding="utf-8"))  # 可选非开源板
    c = j.get("counts") or {}
    head = f"在产 {c.get('green', 0)} · 观察 {c.get('amber', 0)} · 预警 {c.get('red', 0)}"
    if j.get("ongoing"):
        head += f" · 持续中失效集 {j['ongoing']}"
    return dict(ok=True, headline=head, asof=j.get("factor_asof", ""), nxt="每日 19:20")


def sum_scenario():
    """情景推演台(多标的 v1.2): 读 scenario_fan/data/state_<code>.json;
    只信 audit==PASS; 主标的镜像 state.json 兼容旧路径; FAIL 夜刷写 *_FAIL 不覆盖 last-good。"""
    import glob as _glob
    states, fail_n = [], 0
    for sp in sorted(_glob.glob(str(PB / "scenario_fan/data/state_*.json"))):
        if "_FAIL" in pathlib.Path(sp).name:
            fail_n += 1
            continue
        try:
            j = json.load(open(sp, encoding="utf-8"))
            if j.get("audit") == "PASS":
                states.append(j)
        except Exception:
            pass
    if not states:
        return dict(ok=False, error=f"audit FAIL ×{max(fail_n, 1)}" if fail_n else "no state")
    parts = []
    for j in states[:3]:
        t, a = j["tp_last"], j.get("ann_last", {})
        ann = a.get("base")
        parts.append(f"{j['name']}{t.get('base', 0):.0f}元"
                     + (f"({ann:+.0%}/年)" if ann is not None else ""))
    head = " · ".join(parts) + (f" 等{len(states)}标的" if len(states) > 3 else "")
    try:
        hb = json.load(open(PB / "scenario_fan/data/heartbeat.json", encoding="utf-8"))
        if hb.get("fail_streak", 0) > 0:
            head = f"⚠刷新失败×{hb['fail_streak']} · " + head
        else:
            age_h = time.time() - time.mktime(time.strptime(hb["last_run"], "%Y-%m-%dT%H:%M:%S"))
            if age_h > 26 * 3600:
                head = f"⚠上次刷新{age_h / 3600:.0f}h前(可能漏跑) · " + head
    except Exception:
        pass
    return dict(ok=True, headline=head, asof=states[0].get("base_date", ""), nxt="每日 19:45")


def sum_rental():
    """算力租价板：prices(七源日频) + anchors + tenders。"""
    con = ro(PB / "rental-price-tracker/data/rental.db")
    asof = con.execute("SELECT MAX(date) m FROM prices").fetchone()["m"]
    n_src = con.execute("SELECT COUNT(DISTINCT source) n FROM prices").fetchone()["n"]
    n_anch = con.execute("SELECT COUNT(*) n FROM anchors").fetchone()["n"]
    n_tender = con.execute("SELECT COUNT(*) n FROM tenders").fetchone()["n"]
    return dict(ok=True,
                headline=f"{n_src} 源日频在录 · 锚点 {n_anch} 条 · 中标/招标 {n_tender} 条",
                asof=asof, nxt="每日 19:40")


def sum_desk():
    """投资研究室(三agent黑板)：读 investor_desk/results/statements.jsonl 每人最新发言。"""
    import json as _json
    f = PB / "investor_desk/results/statements.jsonl"
    if not f.exists():
        return dict(ok=True, headline="筹建中：三位投资者尚未开班", asof="", nxt="每交易日 09:30/14:50")
    latest = {}
    total = 0
    for line in f.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            j = _json.loads(line)
        except Exception:
            continue
        total += 1
        latest[j.get("agent")] = j
    order = ["t1", "weekly", "monthly"]
    parts = []
    for a in order:
        j = latest.get(a)
        if j:
            txt = (j.get("text") or "").replace("\n", " ")[:38]
            parts.append(f"{'t1' if a=='t1' else a}: {txt}")
    if not parts:
        return dict(ok=True, headline="开业待首班：尚无发言", asof="", nxt="每交易日 09:30/14:50")
    return dict(ok=True, headline=" · ".join(parts),
                asof=max(latest[a]["ts"][:10] for a in latest if latest.get(a)),
                nxt="每交易日 09:30/14:50")


SUMMARIES = [
    (8790, sum_storage), (8792, sum_mlcc), (8793, sum_fabric),
    (8794, sum_signal), (8796, sum_factor),
    (8797, sum_scenario), (8798, sum_rental), (8804, sum_desk),
]



_cache = {"t": 0, "data": {}}


def build_summary():
    if time.time() - _cache["t"] > 60:
        out = {}
        for port, fn in SUMMARIES:
            try:
                out[str(port)] = fn()
            except Exception as e:
                out[str(port)] = dict(ok=False, error=str(e))
        _cache["data"], _cache["t"] = out, time.time()
    return _cache["data"]
