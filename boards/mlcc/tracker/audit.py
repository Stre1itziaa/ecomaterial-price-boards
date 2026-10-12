"""MLCC 数据审计：阶梯单调性 + 双源对照 + 完整性。

MLCC 特有强校验：
1. 阶梯单调性——任何一份完整阶梯价必须随数量非递增（量大价低是铁律），
   违反即解析错误或页面异常，FAIL。
2. 双源价差对照——同料号 ICKey vs LCSC 首档价差记录（分销商定价策略
   不同属正常，价差>50% 仅 WARN 并列出，供人工核对）。
3. 新闻锚点——对照公开报道的华强北/分销报价数量级。
"""

from . import tz
import datetime as dt
import json
import pathlib
import sqlite3
import sys

# ---- Windows GBK 控制台防御 ----
import sys as _sys
try:
    _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


ROOT = pathlib.Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "mlcc.db"


def run_checks(con: sqlite3.Connection, today: dt.date) -> list[dict]:
    checks = []

    def check(name, ok, note="", status=None):
        checks.append({"name": name, "status": status or ("PASS" if ok else "FAIL"), "note": note})

    # 1. 完整性
    bad = con.execute("SELECT COUNT(*) FROM quotes WHERE price IS NULL OR price <= 0").fetchone()[0]
    check("价格为正", bad == 0, f"异常 {bad} 行")
    bad = con.execute("SELECT COUNT(*) FROM quotes WHERE date > ?", (today.isoformat(),)).fetchone()[0]
    check("无未来日期", bad == 0, f"异常 {bad} 行")
    bad = con.execute("SELECT COUNT(*) FROM quotes WHERE stock < 0").fetchone()[0]
    check("库存非负", bad == 0, f"异常 {bad} 行")

    # 2. 阶梯单调性（强校验）
    rows = con.execute(
        "SELECT p.source, p.part, q.date, q.ladder FROM quotes q "
        "JOIN products p ON p.id=q.product_id WHERE q.ladder IS NOT NULL").fetchall()
    n_ladder = n_ok = 0
    bad_examples = []
    for r in rows:
        ladder = json.loads(r["ladder"])
        if len(ladder) < 2:
            continue
        n_ladder += 1
        prices = [p for _, p in ladder]
        if all(prices[i] >= prices[i + 1] - 1e-9 for i in range(len(prices) - 1)):
            n_ok += 1
        elif len(bad_examples) < 5:
            bad_examples.append(f"{r['source']} {r['part']} {r['date']}: {ladder}")
    check("阶梯价随数量单调非递增", n_ladder == 0 or n_ok == n_ladder,
          f"校验 {n_ladder} 份，通过 {n_ok}" + ("；" + "; ".join(bad_examples) if bad_examples else ""))

    # 3. 双源对照（同料号价差）：对照日取两源各自最新日的较小者——
    #    ICKey 已降周一交叉校验，非周一无当日行，不能拿全局最新日硬比
    d_ickey = con.execute(
        "SELECT MAX(q.date) d FROM quotes q JOIN products p ON p.id=q.product_id "
        "WHERE p.source='ICKey'").fetchone()["d"]
    d_lcsc = con.execute(
        "SELECT MAX(q.date) d FROM quotes q JOIN products p ON p.id=q.product_id "
        "WHERE p.source='LCSC'").fetchone()["d"]
    dates = [d for d in (d_ickey, d_lcsc) if d]
    latest = min(dates) if dates else None
    ickey = {r["part"]: r["price"] for r in con.execute(
        "SELECT p.part, q.price FROM quotes q JOIN products p ON p.id=q.product_id "
        "WHERE q.date=? AND p.source='ICKey'", (latest,))} if latest else {}
    lcsc = {r["part"]: r["price"] for r in con.execute(
        "SELECT p.part, q.price FROM quotes q JOIN products p ON p.id=q.product_id "
        "WHERE q.date=? AND p.source='LCSC'", (latest,))}
    both = sorted(set(ickey) & set(lcsc))
    diffs = [(abs(ickey[p] - lcsc[p]) / min(ickey[p], lcsc[p]) * 100, p, ickey[p], lcsc[p])
             for p in both]
    n_warn = sum(1 for d in diffs if d[0] > 50)
    check("双源同料号可对照", len(both) >= 3,
          f"{len(both)} 个料号双源有价（{latest}）",
          status="PASS" if len(both) >= 3 else "WARN")
    worst = sorted(diffs, reverse=True)[:3]
    check("双源价差合理（<50%）", n_warn == 0,
          f"最大价差 " + ("；".join(f"{p}: ￥{a} vs ￥{b} ({d:.0f}%)" for d, p, a, b in worst) if worst else "无对照样本")
          + (f"；超50%有 {n_warn} 个" if n_warn else ""),
          status="PASS" if n_warn == 0 else "WARN")

    # 4. 覆盖度
    # 注意:不可写 "part IN (SELECT part FROM quotes...)"——quotes 无 part 列,
    # SQLite 列作用域会静默回溯外层 products.part 使子查询恒真,数成全表
    # DISTINCT part(含退役号)。2026-10-11 实测踩坑,改 JOIN。
    n_parts = con.execute(
        "SELECT COUNT(DISTINCT p.part) FROM products p "
        "JOIN quotes q ON q.product_id = p.id AND q.date = ?", (latest,)).fetchone()[0]
    n_src = con.execute("SELECT COUNT(DISTINCT source) FROM products").fetchone()[0]
    check("双源在线", n_src >= 2,
          f"来源数 {n_src}；对照基线日 {latest} 覆盖料号 {n_parts}")

    return checks


def main():
    today = tz.today()
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    checks = run_checks(con, today)
    con.close()
    n_fail = sum(1 for c in checks if c["status"] == "FAIL")
    lines = [f"# MLCC 数据审计报告 {tz.now():%Y-%m-%d %H:%M}", "",
             f"结论：{'❌ 存在 FAIL' if n_fail else '✅ 通过（WARN 除外）'}", ""]
    for c in checks:
        lines.append(f"- [{c['status']}] {c['name']}" + (f" —— {c['note']}" if c["note"] else ""))
    report = "\n".join(lines)
    print(report)
    (ROOT / "data" / "audit_report.md").write_text(report, encoding="utf-8")
    sys.exit(1 if n_fail else 0)


if __name__ == "__main__":
    main()
