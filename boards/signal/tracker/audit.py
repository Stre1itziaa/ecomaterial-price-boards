"""AI 需求与退出信号板审计:需求一线台账 + ABF 锚点完整性 + 退出信号覆盖。

2026-09-24 改版:公告流判死(连接器企业公告=不产出价格/不预警/纯冗余),
相关 4 项检查移除;cninfo 表仅存档不再更新。
"""
from . import tz
# ---- Windows GBK 控制台防御:中文输出强制 UTF-8(开源跨平台) ----
import sys as _sys
try:
    _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    _sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
import datetime as dt
import pathlib
import sqlite3
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "signal.db"


def run_checks(con: sqlite3.Connection, today: dt.date, csp_rows=None, dc_rows=None) -> list[dict]:
    checks = []

    def check(name, ok, note="", status=None):
        checks.append({"name": name,
                       "status": status or ("PASS" if ok else "FAIL"),
                       "note": note})

    # 0. 需求一线台账(CSP capex)——量级/存在性检查全部硬 FAIL:自检灯必须对失明免疫
    csp_rows = csp_rows or []
    check("CSP capex 台账 ≥6 条(需求一线)", len(csp_rows) >= 6, f"{len(csp_rows)} 条")
    bad_csp = [r for r in csp_rows if not (r.get("source") or "").strip()]
    check("CSP 台账条目带出处", not bad_csp, f"缺失 {len(bad_csp)} 条")
    has_next = any(r.get("basis") == "calendar" or "财报" in (r.get("item") or "") + (r.get("value") or "")
                   for r in csp_rows)
    check("台账含下一数据点日历", has_next, "须有一条财报日历项")
    # 台账日期合理性:calendar 行必须在未来,event/period/state 必须不在未来
    bad_ledger_date = []
    for r in csp_rows:
        d = (r.get("date") or "").strip()
        basis = (r.get("basis") or "event").strip()
        if not d:
            bad_ledger_date.append(f"{r.get('item','?')}:无日期")
            continue
        future = d > today.isoformat()
        if (basis == "calendar") != future:
            bad_ledger_date.append(f"{d}({basis})")
    check("台账日期合理性(basis 与时点自洽)", not bad_ledger_date,
          "异常: " + "; ".join(bad_ledger_date) if bad_ledger_date else "全部自洽")

    # 0.5 二线:DC 收入序列(L1 机读)
    dc_rows = dc_rows or []
    by_t = {}
    for r in dc_rows:
        by_t.setdefault(r["ticker"], []).append(r)
    check("DC 收入三家各 ≥4 期", all(len(v) >= 4 for v in by_t.values()) and len(by_t) == 3,
          " / ".join(f"{k} {len(v)}期" for k, v in sorted(by_t.items())) or "空")
    bad_dc = [r["ticker"] + r["filed_at"] for r in dc_rows
              if r["value_musd"] is not None and float(r["value_musd"]) <= 0]
    n_yoyonly = sum(1 for r in dc_rows if r["value_musd"] is None)
    check("DC 收入值为正(NULL=仅增速期)", not bad_dc,
          f"异常 {len(bad_dc)} 行;仅增速期 {n_yoyonly} 期")
    latest_dc = max((r["filed_at"] for r in dc_rows), default=None)
    if latest_dc:
        lag = (tz.today() - dt.date.fromisoformat(latest_dc)).days
        check("DC 收入最新期 ≤110 天(季历)", lag <= 110,
              f"最新 filing {latest_dc}(距今 {lag} 天;超限=该补新季度 URL)")

    # 1. 锚点完整性
    bad_date = con.execute("SELECT COUNT(*) FROM anchors WHERE date > ?",
                           (today.isoformat(),)).fetchone()[0]
    check("锚点无未来日期", bad_date == 0, f"异常 {bad_date} 条")
    bad = con.execute("SELECT COUNT(*) FROM anchors WHERE source='' OR caliber='' OR value=''").fetchone()[0]
    check("锚点出处/口径/数值非空", bad == 0, f"异常 {bad} 条")

    # 2. 口径白名单
    from .parts import CALIBERS
    bad_cal = [r["caliber"] for r in con.execute("SELECT DISTINCT caliber FROM anchors")
               if r["caliber"] not in CALIBERS]
    check("锚点口径全部在白名单", not bad_cal,
          "异常口径: " + "; ".join(bad_cal) if bad_cal else f"全部命中 {len(CALIBERS)} 项口径表")

    # 3. 域覆盖:ABF ≥5 + 退出信号 ≥3
    n_abf = con.execute("SELECT COUNT(*) FROM anchors WHERE item LIKE 'ABF%'").fetchone()[0]
    check("ABF 锚点 ≥5", n_abf >= 5, f"{n_abf} 条")
    n_exit = con.execute("SELECT COUNT(*) FROM anchors WHERE cat='退出日历'").fetchone()[0]
    check("退出信号 ≥3 条(全清单共享)", n_exit >= 3, f"{n_exit} 条")
    # 近重复:正文前 40 字相同 = 同一信号重复入库,计数型检查会被喂饱
    dup = []
    seen = {}
    for r in con.execute("SELECT date, item, value FROM anchors ORDER BY date"):
        key = (r["value"] or "")[:40]
        if key in seen:
            dup.append(f"{seen[key]} ↔ {r['date']}·{r['item']}")
        else:
            seen[key] = f"{r['date']}·{r['item']}"
    check("锚点无近重复(正文前40字唯一)", not dup,
          "; ".join(dup) if dup else "无重复")

    # 4. 连接器判死执行核验(锚点层不得再回流)
    n_conn = con.execute("SELECT COUNT(*) FROM anchors WHERE item LIKE '连接器%'").fetchone()[0]
    check("连接器域已清出(判死 2026-09-24)", n_conn == 0, f"残留 {n_conn} 条")

    return checks


def main():
    import csv as _csv
    con0 = sqlite3.connect(DB)
    con0.row_factory = sqlite3.Row
    dc_rows = [dict(r) for r in con0.execute("SELECT * FROM dc_revenue")]
    con0.close()
    csp_path = ROOT / "data" / "csp_ledger.csv"
    csp_rows = []
    if csp_path.exists():
        with open(csp_path, encoding="utf-8-sig", newline="") as f:
            csp_rows = list(_csv.DictReader(f))
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    checks = run_checks(con, tz.today(), csp_rows, dc_rows)
    con.close()
    n_fail = sum(1 for c in checks if c["status"] == "FAIL")
    n_warn = sum(1 for c in checks if c["status"] == "WARN")
    lines = [f"# AI 需求与退出信号板审计报告 {tz.now():%Y-%m-%d %H:%M}", "",
             f"结论:{'❌ 存在 FAIL' if n_fail else '✅ 通过'}" + (f"(含 {n_warn} 项 WARN)" if n_warn else ""), ""]
    for c in checks:
        lines.append(f"- [{c['status']}] {c['name']}" + (f" —— {c['note']}" if c["note"] else ""))
    report = "\n".join(lines)
    print(report)
    (ROOT / "data" / "audit_report.md").write_text(report, encoding="utf-8")
    sys.exit(1 if n_fail else 0)


if __name__ == "__main__":
    main()
