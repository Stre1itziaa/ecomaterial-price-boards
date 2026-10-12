"""B2B 台阶线离线重算:按 ali.py 当前过滤规则重放全部历史挂牌。

为什么存在:过滤规则升级(如 2026-10-11 加建材级 E 玻璃纱排除词)后,
b2b_daily 里的历史聚合仍是旧规则产物——原始挂牌行全量在 b2b_listings 表,
本工具对它们重套规则重聚合后 REPLACE b2b_daily。这是修正过滤器,不是造数据:
任何一天的聚合都只来自该日真实抓到的挂牌行,可随时重放、可审计。

用法:
  python -m tracker.rebuild_b2b            # 重算全部日期,打印前后对照
  python -m tracker.rebuild_b2b --dry      # 只打印对照,不写库
"""

from . import tz
import argparse
import datetime as dt
import pathlib
import statistics

from . import store
from .ali import EXCLUDE_COMMON, KEYWORDS

ROOT = pathlib.Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "fabric.db"


def keep(row, cfg) -> bool:
    """对一条已入库挂牌行重套当日规则(标题过滤 + 币种 + 单位 + 价格带)。"""
    _q, _name, must, must_any, agg_unit, lo, hi = cfg
    low = row["title"].lower()
    if not any(t in low for t in must):
        return False
    if not any(t in low for t in must_any):
        return False
    if any(t in low for t in EXCLUDE_COMMON):
        return False
    if row["currency"] != "CNY":
        return False
    price, unit = row["price"], row["unit"]
    if unit == "ton":
        price, unit = price / 1000.0, "kg"
    if unit != agg_unit:
        return False
    return lo <= price <= hi


def _aggregate(rows: list, unit: str):
    ps = sorted(r["price"] for r in rows)
    if not ps:
        return None
    n = len(ps)
    pick = lambda q: round(ps[min(n - 1, int(round(q * (n - 1))))], 4)
    return {"n": n, "p25": pick(0.25), "median": round(statistics.median(ps), 4),
            "p75": pick(0.75), "unit": unit}


def rebuild(con, dry: bool = False):
    cfg_by_kw = {k[1]: k for k in KEYWORDS}
    days = [r["date"] for r in con.execute(
        "SELECT DISTINCT date FROM b2b_listings ORDER BY date")]
    print(f"待重算 {len(days)} 天 × {len(KEYWORDS)} 品名")
    changed = 0
    for day in days:
        for name, cfg in cfg_by_kw.items():
            rows = [dict(r) for r in con.execute(
                "SELECT * FROM b2b_listings WHERE date=? AND keyword=?",
                (day, name))]
            kept = [r for r in rows if keep(r, cfg)]
            old = con.execute(
                "SELECT n, median FROM b2b_daily WHERE date=? AND keyword=?",
                (day, name)).fetchone()
            agg = _aggregate(kept, cfg[4])
            new = (agg["n"], agg["median"]) if agg else None
            if new and (not old or old["n"] != new[0]
                        or abs(old["median"] - new[1]) > 1e-9):
                changed += 1
                print(f"  {day} {name}: n={old['n'] if old else '-'}→{new[0]} "
                      f"med={old['median'] if old else '-'}→{new[1]}")
            if not dry and agg:
                now = tz.now().isoformat(timespec="seconds")
                con.execute(
                    "INSERT OR REPLACE INTO b2b_daily"
                    "(date,keyword,n,p25,median,p75,unit,fetched_at) "
                    "VALUES(?,?,?,?,?,?,?,?)",
                    (day, name, agg["n"], agg["p25"], agg["median"],
                     agg["p75"], agg["unit"], now))
            elif not dry and not agg and old:
                # 该日该品名按新规则全军覆没:删旧聚合(挂牌行保留可追溯)
                con.execute("DELETE FROM b2b_daily WHERE date=? AND keyword=?",
                            (day, name))
                print(f"  {day} {name}: 规则后 0 条,删除旧聚合(原 n={old['n']})")
    if not dry:
        con.commit()
    print(f"完成:{'dry-run 未写库' if dry else '已写库'},变动 {changed} 个日×品名")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args()
    con = store.connect(DB)
    rebuild(con, dry=args.dry)
    con.close()
