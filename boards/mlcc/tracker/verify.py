"""全量核算：库内报价 vs 原始快照逐一回放比对（快照=抓取时点的源真相）。

与 audit.py 的分工：audit 查阶梯单调性/双源价差等规则；verify 把每条库内行
对回它的原始快照重放一遍——解析→入库→导出任何一环改动/损坏都会现形。

核对面：
1. 立创：快照目录里全部 lcsc_{stamp}_{pn}.html 重解析（lcsc.parse），逐行比对
   price/stock/moq/ladder；快照解析为 None（当日无货/无匹配）而库内有行 = EXTRA-DB；
2. 云汉：ickey_{stamp}.jsonl 回放（仅成功报价入档），与库内 ICKey 行比对；
3. Mouser：mouser_{stamp}.jsonl 回放，与库内 Mouser 行比对；
4. 退役料号：库内必须 active=0（历史保留），最后行日期不得晚于退役切换日；
5. 跨源对照（INFO）：同日 ICKey×LCSC 价差（同 audit 口径，仅报不判）。

用法：python -m tracker.verify
退出码：任何 MISMATCH → 1。
"""

from . import tz
import datetime as dt
import json
import pathlib
import re
import sys

from . import lcsc, store
from .parts import PARTS

# ---- Windows GBK 控制台防御:中文输出强制 UTF-8(开源跨平台,2026-10-12) ----
import sys as _sys
try:
    _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    _sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


ROOT = pathlib.Path(__file__).resolve().parent.parent
SNAP = ROOT / "data" / "snapshots"
RETIRED_SWITCH_DATE = "2026-10-05"   # MA12D→KA12D 切换日，其后不得再有退役号新行


def _meta_by_part(con) -> dict:
    return {r["part"]: r for r in con.execute(
        "SELECT DISTINCT part, brand, seg, descr FROM products")}


def verify_lcsc(con, db_quotes: dict, problems: list, n_ok: list) -> None:
    meta = _meta_by_part(con)
    files = sorted(SNAP.glob("lcsc_*_*.html"))
    for f in files:
        m = re.match(r"^lcsc_(\d{8})_(.+)\.html$", f.name)
        if not m or m.group(2).startswith("probe"):
            continue
        stamp, pn = m.group(1), m.group(2)
        date = f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:]}"
        md = meta.get(pn)
        q = lcsc.parse(pn, md["brand"] if md else "", md["seg"] if md else "",
                       (md["descr"] if md else "") or "", date,
                       f.read_text(encoding="utf-8"))
        if q is None:
            if (date, "LCSC", pn) in db_quotes:
                problems.append(
                    f"EXTRA-DB   LCSC {pn} {date}: 快照无精确匹配/无货，库内却有行")
            continue
        want = db_quotes.get((date, "LCSC", pn))
        if want is None:
            problems.append(f"MISSING-DB LCSC {pn} {date}: 快照有报价，库内无行")
            continue
        d_date, d_price, d_stock, d_moq, d_ladder = want
        # 入库前是 [(qty, price)] 元组列表，落库 JSON 后是 [[qty, price]]——归一后比较
        ladder_a = [[x, y] for x, y in (q.extra.get("ladder") or [])]
        ladder_b = json.loads(d_ladder) if d_ladder else None
        # 库存容差 ±3%(同日多抓库存自然漂移,2026-10-05 三跑实测最大 2.1%);
        # 价格/moq/阶梯仍零容差——钱数不许漂
        if (abs(q.price - d_price) > 1e-9
                or abs(q.stock - d_stock) > max(2, d_stock * 0.03)
                or q.moq != d_moq or ladder_a != ladder_b):
            problems.append(
                f"MISMATCH  LCSC {pn} {date}: 库=({d_price},{d_stock},{d_moq},{ladder_b})"
                f" vs 快照=({q.price},{q.stock},{q.moq},{ladder_a})")
        else:
            n_ok.append(1)


def verify_jsonl_source(con, db_quotes: dict, source: str,
                        problems: list, n_ok: list) -> None:
    """source=库内来源名（ICKey/Mouser）；快照文件名约定为小写。"""
    for f in sorted(SNAP.glob(f"{source.lower()}_*[0-9].jsonl")):
        stamp = re.search(r"_(\d{8})\.jsonl$", f.name).group(1)
        date = f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:]}"
        for line in f.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            q = json.loads(line)
            pn = q.get("part")
            want = db_quotes.get((date, source, pn))
            if want is None:
                problems.append(f"MISSING-DB {source} {pn} {date}: 快照有报价，库内无行")
                continue
            _, d_price, d_stock, d_moq, _ = want
            if (abs(float(q["price"]) - d_price) > 1e-9
                    or abs(int(q.get("stock") or 0) - d_stock) > max(2, d_stock * 0.03)
                    or int(q.get("moq") or 0) != (d_moq or 0)):
                problems.append(
                    f"MISMATCH  {source} {pn} {date}: 库=({d_price},{d_stock},{d_moq})"
                    f" vs 快照=({q['price']},{q.get('stock')},{q.get('moq')})")
            else:
                n_ok.append(1)


def verify_retired(con, problems: list, n_ok: list) -> None:
    from .store import RETIRED_PARTS
    for part in RETIRED_PARTS:
        rows = con.execute(
            "SELECT p.id, p.active, MAX(q.date) md FROM products p "
            "LEFT JOIN quotes q ON q.product_id=p.id WHERE p.part=? GROUP BY p.id",
            (part,)).fetchall()
        if not rows:
            continue
        for r in rows:
            if not r["active"]:
                n_ok.append(1)
            else:
                problems.append(f"NOT-RETIRED {part}: products.active 仍为 1")
            if r["md"] and r["md"] > RETIRED_SWITCH_DATE:
                problems.append(
                    f"POST-RETIRED {part}: 退役切换日 {RETIRED_SWITCH_DATE} 后仍有新行 {r['md']}")
            else:
                n_ok.append(1)


def cross_source_info(con) -> list[str]:
    out = []
    latest = con.execute("SELECT MAX(date) d FROM quotes").fetchone()["d"]
    ickey = {r["part"]: r["price"] for r in con.execute(
        "SELECT p.part, q.price FROM quotes q JOIN products p ON p.id=q.product_id "
        "WHERE q.date=? AND p.source='ICKey'", (latest,))}
    lcsc_p = {r["part"]: r["price"] for r in con.execute(
        "SELECT p.part, q.price FROM quotes q JOIN products p ON p.id=q.product_id "
        "WHERE q.date=? AND p.source='LCSC'", (latest,))}
    for pn in sorted(set(ickey) & set(lcsc_p)):
        dev = abs(ickey[pn] - lcsc_p[pn]) / min(ickey[pn], lcsc_p[pn]) * 100
        out.append(f"INFO-CROSS {pn}: 云汉 ¥{ickey[pn]} vs 立创 ¥{lcsc_p[pn]} 价差 {dev:.0f}%")
    return out


def main():
    con = store.connect(ROOT / "data" / "mlcc.db")
    db_quotes = {}
    for r in con.execute(
            "SELECT p.source, p.part, q.date, q.price, q.stock, q.moq, q.ladder "
            "FROM quotes q JOIN products p ON p.id=q.product_id"):
        db_quotes[(r["date"], r["source"], r["part"])] = (
            r["date"], r["price"], r["stock"], r["moq"], r["ladder"])

    problems, n_ok = [], []
    verify_lcsc(con, db_quotes, problems, n_ok)
    verify_jsonl_source(con, db_quotes, "ICKey", problems, n_ok)
    verify_jsonl_source(con, db_quotes, "Mouser", problems, n_ok)
    verify_retired(con, problems, n_ok)

    print()
    for line in cross_source_info(con):
        print(line)
    print()
    print(f"=== 核对 {len(n_ok)} 项一致，{len(problems)} 项异常 ===")
    for p in problems[:40]:
        print(" ", p)
    if len(problems) > 40:
        print(f"  ...（其余 {len(problems) - 40} 条略）")
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
