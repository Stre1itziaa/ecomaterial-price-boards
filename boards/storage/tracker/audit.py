"""交付审计：数据真实性核查。

核查项：
1. 完整性：avg>0、日期合法且不晚于今天、产品来源标注齐全。
2. 源内自洽：TrendForce 涨跌幅 × 前一日均价 ≈ 当日均价（隐含前值回推）。
3. 独立锚点：与用户截图、DRAMeXchange 首页、搜索引擎缓存页等外部数值对照。

输出：控制台 + data/audit_report.md。任何 FAIL 都表示数据不可信，必须排查。
run_checks() 供 update.py 在导出时调用，把审计结论嵌入看板数据。
"""

from . import tz
import datetime as dt
import pathlib
import re
import sqlite3
import sys

# ---- Windows GBK 控制台防御 ----
import sys as _sys
try:
    _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


ROOT = pathlib.Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "storage.db"
TOL = 0.02  # 隐含前值回推容差 2%（页面数值四舍五入到 3 位小数）


def _cap_tb(name: str) -> float:
    """"WD ULTRASTAR DC HC590 26TB SATA · New" → 26.0；解析失败返回 1.0(保守放大单价/TB)。"""
    m = re.search(r"(\d+(?:\.\d+)?)\s*TB", name)
    return float(m.group(1)) if m else 1.0


def run_checks(con: sqlite3.Connection, today: dt.date) -> list[dict]:
    """执行全部核查，返回 [{"name","status","note"}]；status ∈ PASS/FAIL。"""
    checks = []

    def check(name, ok, note=""):
        checks.append({"name": name, "status": "PASS" if ok else "FAIL", "note": note})

    # ---- 1. 完整性 ----
    bad_avg = con.execute("SELECT COUNT(*) FROM quotes WHERE avg IS NULL OR avg <= 0").fetchone()[0]
    check("行情均价均为正数", bad_avg == 0, f"异常行数={bad_avg}")

    bad_date = con.execute(
        "SELECT COUNT(*) FROM quotes WHERE date > ?", (today.isoformat(),)).fetchone()[0]
    check("无未来日期", bad_date == 0, f"未来日期行数={bad_date}")

    bad_fmt = con.execute(
        r"SELECT COUNT(*) FROM quotes WHERE date NOT GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'"
    ).fetchone()[0]
    check("日期格式统一 YYYY-MM-DD", bad_fmt == 0, f"异常行数={bad_fmt}")

    n_src = con.execute("SELECT COUNT(DISTINCT source) FROM products").fetchone()[0]
    check("产品来源标注齐全", n_src >= 2, f"来源数={n_src}")

    # ---- 2. TrendForce 源内自洽：avg_t ≈ avg_{t-1} × (1+chg%) ----
    # 仅比对间隔在该序列频率容忍窗内的相邻行对（daily≤3天跨周末、weekly≤10、
    # monthly≤45、quarterly≤100）；更长间隔为采集断档，页面涨跌幅相对的是
    # 真实上一交易日而非库内前一行，比对无意义（如 9/18-9/21 漏采期）。
    GAP = {"daily": 3, "weekly": 10, "monthly": 45, "quarterly": 100}
    rows = con.execute("""
        SELECT p.name, p.freq, q.date, q.avg, q.change_pct FROM quotes q
        JOIN products p ON p.id = q.product_id
        WHERE p.source = 'TrendForce' AND q.change_pct IS NOT NULL
        ORDER BY p.id, q.date""").fetchall()
    by_prod = {}
    for r in rows:
        by_prod.setdefault(r["name"], []).append(r)
    n_pairs = n_ok = n_skip = 0
    examples = []
    for name, arr in by_prod.items():
        gap_max = GAP.get(arr[0]["freq"] or "weekly", 10)
        for i in range(1, len(arr)):
            prev, cur = arr[i - 1], arr[i]
            gap = (dt.date.fromisoformat(cur["date"]) - dt.date.fromisoformat(prev["date"])).days
            if gap > gap_max:
                n_skip += 1
                continue
            implied_prev = cur["avg"] / (1 + cur["change_pct"] / 100)
            n_pairs += 1
            if abs(implied_prev - prev["avg"]) / prev["avg"] <= TOL:
                n_ok += 1
            elif len(examples) < 5:
                examples.append(f"{name} {cur['date']}: 回推前值 {implied_prev:.3f} vs 实际 {prev['avg']}")
    check("TrendForce 涨跌幅与前值自洽",
          n_pairs == 0 or n_ok == n_pairs,
          f"可比对 {n_pairs} 组，通过 {n_ok}；跳过断档对 {n_skip} 组"
          + ("；" + "; ".join(examples) if examples else ""))

    # 单日锚点（固定 09-07 行，防日期滚动误报）：回推前值 ≈ DRAMeXchange 首页当时显示的 20.708
    row = con.execute("""
        SELECT q.avg, q.change_pct, q.date FROM quotes q JOIN products p ON p.id=q.product_id
        WHERE p.source='TrendForce' AND p.name='512Gb TLC' AND q.date='2026-09-07'""").fetchone()
    if row and row["change_pct"]:
        implied = row["avg"] / (1 + row["change_pct"] / 100)
        check("锚点: TF 512Gb TLC(09-07) 隐含前值 ≈ DRAMeXchange 首页 20.708",
              abs(implied - 20.708) / 20.708 < TOL,
              f"{row['date']} 页面 {row['avg']} ({row['change_pct']:+.2f}%) → 前值 {implied:.3f}")
    # 锚点（用户截图新闻）：免费页 2026-09-14 期 512Gb TLC = 新闻快讯 9/16 值 20.083 (-0.31%)，
    # 且其回推前值 ≈ 库内 09-07 期 20.146 —— 数值级双重印证
    row = con.execute("""
        SELECT q.avg, q.change_pct FROM quotes q JOIN products p ON p.id=q.product_id
        WHERE p.source='TrendForce' AND p.name='512Gb TLC' AND q.date='2026-09-14'""").fetchone()
    if row:
        implied = row["avg"] / (1 + row["change_pct"] / 100)
        prev = con.execute("""
            SELECT q.avg FROM quotes q JOIN products p ON p.id=q.product_id
            WHERE p.source='TrendForce' AND p.name='512Gb TLC' AND q.date='2026-09-07'""").fetchone()
        ok_news = abs(row["avg"] - 20.083) < 0.001 and abs(row["change_pct"] + 0.31) < 0.01
        ok_chain = prev and abs(implied - prev["avg"]) / prev["avg"] <= TOL
        check("锚点: TF 512Gb TLC 09-14 期 = 用户截图新闻值 20.083 (-0.31%) 且与前值自洽",
              ok_news and bool(ok_chain),
              f"页面 {row['avg']} ({row['change_pct']:+.2f}%) → 前值 {implied:.3f}"
              + (f" vs 库内 09-07 期 {prev['avg']}" if prev else ""))
    row = con.execute("""
        SELECT q.avg, q.change_pct FROM quotes q JOIN products p ON p.id=q.product_id
        WHERE p.source='TrendForce' AND p.name LIKE 'DDR5 16Gb (2Gx8)%' AND q.date='2026-09-17'""").fetchone()
    if row and row["change_pct"]:
        implied = row["avg"] / (1 + row["change_pct"] / 100)
        check("锚点: TF DDR5 16Gb 9/17 隐含前值 ≈ 54.833（搜索引擎缓存页值）",
              abs(implied - 54.833) / 54.833 < TOL,
              f"页面 {row['avg']} ({row['change_pct']:+.2f}%) → 前值 {implied:.3f}")

    # ---- 3. CFM 序列完整性 ----
    n_cfm = con.execute("""
        SELECT COUNT(DISTINCT p.id) FROM products p
        JOIN quotes q ON q.product_id = p.id WHERE p.source='CFM'""").fetchone()[0]
    cfm_points = con.execute("""
        SELECT COUNT(*) FROM quotes q JOIN products p ON p.id=q.product_id
        WHERE p.source='CFM'""").fetchone()[0]
    check("CFM 历史回填已入库", n_cfm >= 50 and cfm_points > n_cfm * 3,
          f"CFM 产品 {n_cfm} 个，行情点 {cfm_points} 个")

    idx = con.execute("""
        SELECT p.name, MIN(q.date) a, MAX(q.date) b, COUNT(*) n FROM quotes q
        JOIN products p ON p.id=q.product_id
        WHERE p.source='CFM' AND p.family='CFM 指数' GROUP BY p.name""").fetchall()
    for r in idx:
        check(f"CFM {r['name']} 历史覆盖",
              r["n"] >= 25 and r["a"] <= "2026-03-01",
              f"{r['a']} → {r['b']}，{r['n']} 周")

    # CFM 内部一致性抽查(2026-10-12 改动态):eMMC 8GB 详情序列存在且首值>0
    # (原硬编码 6/23/20.0 版在 sampleData 13 周窗口滚动后必然查无此行而误报)
    row = con.execute("""
        SELECT MIN(q.date) a, COUNT(*) n FROM quotes q JOIN products p ON p.id=q.product_id
        WHERE p.source='CFM' AND p.name LIKE 'eMMC 8GB%'""").fetchone()
    ok = row is not None and row["n"] >= 5
    check("锚点: CFM eMMC 8GB 详情序列覆盖(≥5 期)",
          ok, f"覆盖 {row['n'] if row else 0} 期{', 自 ' + row['a'] if row and row['a'] else ''}")

    # ---- 4. HDD 档位单调性（强校验）：同型同日 New 挂牌价 ≥ Refurbished/Recertified ----
    # 档位价倒挂=抓取/解析/店铺占位价异常，同 MLCC 阶梯单调性的位置
    hdd_rows = con.execute("""
        SELECT p.name, q.date, q.avg FROM quotes q
        JOIN products p ON p.id = q.product_id
        WHERE p.source = 'SPD' AND p.family LIKE 'HDD%'""").fetchall()
    by_key = {}
    for r in hdd_rows:
        base, _, cond = r["name"].rpartition(" · ")
        by_key.setdefault((base, r["date"]), {})[cond] = r["avg"]
    n_pair = n_ok = 0
    bad_ex = []
    for (base, date), conds in by_key.items():
        if "New" in conds:
            for other in ("Refurbished", "Recertified"):
                if other in conds:
                    n_pair += 1
                    if conds["New"] >= conds[other] - 1e-9:
                        n_ok += 1
                    elif len(bad_ex) < 5:
                        bad_ex.append(f"{base} {date}: New ${conds['New']} < {other} ${conds[other]}")
    check("HDD 档位价单调（New ≥ 翻新/再制造）", n_pair == 0 or n_ok == n_pair,
          f"可比对 {n_pair} 组，通过 {n_ok}" + ("；" + "; ".join(bad_ex) if bad_ex else ""))

    # ---- 5. HDD 币种护栏（强校验）：SPD 美元单 TB 价超上界=CNY 错标复发 ----
    # 2026-09-26 事故:Shopify Markets 按出口 IP 回退 CNY 计价,12 产品全被放大 6.8 倍
    # 入库且档位单调检查免疫(比值不变号)。单 TB 上界取 2026 涨价顶点实测 $44/TB 的 3 倍余量。
    tb_rows = con.execute("""
        SELECT p.name, q.avg FROM quotes q
        JOIN products p ON p.id = q.product_id
        WHERE p.source = 'SPD' AND p.family LIKE 'HDD%'""").fetchall()
    over = [f"{r['name']} ${r['avg']:.0f}" for r in tb_rows
            if r["avg"] / _cap_tb(r["name"]) > 150.0]
    check("HDD 币种护栏（SPD 单 TB 价 ≤ $150）", not over,
          f"检查 {len(tb_rows)} 行" + ("；疑似 CNY 错标: " + "; ".join(over[:5]) if over else ""))
    return checks


def main():
    today = tz.today()
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    checks = run_checks(con, today)
    con.close()

    n_fail = sum(1 for c in checks if c["status"] == "FAIL")
    lines = [f"# 数据真实性审计报告 {tz.now():%Y-%m-%d %H:%M}", "",
             f"结论：{'❌ 存在 FAIL，数据不可信，须排查后重做' if n_fail else '✅ 全部通过'}", ""]
    for c in checks:
        lines.append(f"- [{c['status']}] {c['name']}" + (f" —— {c['note']}" if c["note"] else ""))
    report = "\n".join(lines)
    print(report)
    (ROOT / "data" / "audit_report.md").write_text(report, encoding="utf-8")
    sys.exit(1 if n_fail else 0)


if __name__ == "__main__":
    main()
