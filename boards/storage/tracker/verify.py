"""全量核算：库内行情 vs 原始快照逐一回放比对（快照=抓取时点的源真相）。

与 audit.py 的分工：audit 查内部自洽与锚点；verify 把每条库内行对回它的原始
快照重放一遍——解析→入库→导出全链路任何一环改动/损坏都会在这里现形。

核对面：
1. TrendForce 中文页：最近 SNAPSHOT_DAYS 张 {stamp}_dram/flash.html 全量重解析，
   与库内同 (产品,日期) 行比对 high/low/avg/change_pct；
2. DRAMeXchange 英文首页（dxen 救援腿）：最近一张 dxi_en 快照重解析——值有变化
   应有当日行，同值跳过规则下应无当日行，违反即链路不一致；
3. SPD：最近一张 spd_*.json 回放 parse_products，与库内同日行比对；
4. CFM：最近一批 cfm_{stamp}_cat/detail 快照回放（家族按当时品类页链接归属），
   与库内同 (产品,日期) 行比对 avg；
5. 跨源互证（INFO）：TF vs CFM vs DXI-EN 同族最新值偏离度——不同评估方口径，
   只报不判。

用法：python -m tracker.verify [--days 3]
退出码：任何 MISMATCH → 1。
"""
from . import tz
# ---- Windows GBK 控制台防御:中文输出强制 UTF-8(开源跨平台) ----
import sys as _sys
try:
    _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    _sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
import argparse
import datetime as dt
import json
import pathlib
import re
import sys

from . import dxen, hdd, parse, store
from .cfm import parse_sample_data, CATEGORY_PAGES

ROOT = pathlib.Path(__file__).resolve().parent.parent
SNAP = ROOT / "data" / "snapshots"
TOL = 1e-9


def _latest_stamps(pattern: str, n: int) -> list[str]:
    stamps = sorted({m.group(1) for p in SNAP.glob(pattern)
                     if (m := re.match(r"^(\d{8})_", p.name))})
    return stamps[-n:]


def _db_rows(con) -> dict:
    """(source, family, section, name, date) -> (high, low, avg, change_pct)。"""
    out = {}
    for r in con.execute(
            "SELECT p.source, p.family, p.section, p.name, q.date, q.high, q.low, q.avg, "
            "q.change_pct FROM quotes q JOIN products p ON p.id=q.product_id"):
        out[(r["source"], r["family"], r["section"], r["name"], r["date"])] = \
            (r["high"], r["low"], r["avg"], r["change_pct"])
    return out


def _cmp(name: str, date: str, got, want, problems: list, n_ok: list) -> None:
    if want is None:
        problems.append(f"MISSING-DB  {name} {date}: 快照有值 {got}，库内无行")
        return
    if got is None:
        return
    fields = []
    for k, g, w in zip(("high", "low", "avg", "chg"), got, want):
        if g is None and w is None:
            continue
        if g is None or w is None or abs(g - w) > TOL:
            fields.append(f"{k}: 库={w} vs 快照={g}")
    if fields:
        problems.append(f"MISMATCH    {name} {date}: " + "；".join(fields))
    else:
        n_ok.append(1)


def verify_tf(db, days: int) -> tuple[list, list]:
    problems, n_ok = [], []
    stamps = sorted(set(_latest_stamps("*_dram.html", days))
                    & set(_latest_stamps("*_flash.html", days)))[-days:]
    for stamp in stamps:
        pages = {}
        for key in ("dram", "flash"):
            pages[key] = (SNAP / f"{stamp}_{key}.html").read_text(encoding="utf-8")
        date = f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:]}"
        for r in parse.parse_snapshots(pages):
            key = (r.source, r.family, r.section, r.name, r.date)
            _cmp(f"TF {r.family}·{r.section}·{r.name}", r.date,
                 (r.high, r.low, r.avg, r.change_pct), db.get(key), problems, n_ok)
        print(f"[tf] {stamp} 快照回放完成（数据日期 {date}）")
    return problems, n_ok


def verify_dxi(con, db: dict) -> tuple[list, list]:
    problems, n_ok = [], []
    stamps = _latest_stamps("*_dxi_en.html", 1)
    if not stamps:
        print("[dxen] 无英文首页快照，跳过")
        return problems, n_ok
    stamp = stamps[-1]
    date = f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:]}"
    html = (SNAP / f"{stamp}_dxi_en.html").read_text(encoding="utf-8")
    idx = dxen.product_index(con)
    for item in dxen.parse_home(html):
        p = idx.get(item["name"])
        if not p:
            continue
        key = ("TrendForce", p["family"], p["section"], p["name"], date)
        triple = (item["high"], item["low"], item["avg"])
        if key in db:
            _cmp(f"DXI-EN {p['name']}", date, triple, db[key][:3], problems, n_ok)
        else:
            # 无当日行：必须恰好命中 skip-unchanged（与库内最新一行全等），否则链路不一致
            last = con.execute(
                "SELECT high, low, avg, date FROM quotes WHERE product_id=? "
                "ORDER BY date DESC LIMIT 1", (p["id"],)).fetchone()
            if last and all(abs(a - b) < TOL for a, b in zip(triple, tuple(last)[:3])):
                n_ok.append(1)
            else:
                problems.append(
                    f"SKIP-RULE   DXI-EN {p['name']} {date}: 快照有新值 {triple} "
                    f"但库内无当日行（最新 {tuple(last)[:3] if last else None} @"
                    f" {last['date'] if last else '-'}）——救援腿漏写")
    print(f"[dxen] {stamp} 快照回放完成")
    return problems, n_ok


def verify_spd(con, db: dict) -> tuple[list, list]:
    problems, n_ok = [], []
    stamps = sorted({m.group(1) for p in SNAP.glob("spd_*.json")
                     if (m := re.search(r"spd_(\d{8})\.json$", p.name))})
    if not stamps:
        print("[spd] 无 SPD 快照，跳过")
        return problems, n_ok
    stamp = stamps[-1]
    date = f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:]}"
    pages = json.loads((SNAP / f"spd_{stamp}.json").read_text(encoding="utf-8"))
    products = [p for page in pages for p in (page.get("products") or [])]
    pid_by_name = {r["name"]: r["id"] for r in con.execute(
        "SELECT id, name FROM products WHERE source='SPD'")}
    for r in hdd.parse_products(products, date):
        # 涨跌幅是 update.py 入库后按库内前值回填的，快照里没有——按同规则重算期望值
        pid = pid_by_name.get(r.name)
        prev = con.execute(
            "SELECT avg FROM quotes WHERE product_id=? AND date<? ORDER BY date DESC LIMIT 1",
            (pid, r.date)).fetchone() if pid else None
        exp_chg = round(100.0 * (r.avg / prev["avg"] - 1), 2) if prev else None
        key = ("SPD", r.family, "零售现货", r.name, r.date)
        _cmp(f"SPD {r.name}", r.date, (None, None, r.avg, exp_chg), db.get(key),
             problems, n_ok)
    print(f"[spd] {stamp} 快照回放完成（{len(products)} 产品目）")
    return problems, n_ok


def verify_cfm(db: dict) -> tuple[list, list]:
    problems, n_ok = [], []
    stamps = sorted({m.group(1) for p in SNAP.glob("cfm_*_cat_*.html")
                     if (m := re.match(r"^cfm_(\d{8})_", p.name))})
    if not stamps:
        print("[cfm] 无 CFM 快照，跳过")
        return problems, n_ok
    stamp = stamps[-1]
    today = tz.today()
    # 家族归属：按当时品类页里的详情链接
    link_family = {}
    for p in SNAP.glob(f"cfm_{stamp}_cat_*.html"):
        cat = re.search(r"_cat_(.+)\.html$", p.name).group(1)
        for link in re.findall(r'href="(/price/(?:sz|in|ews|w3t|ems)/\d+)"',
                               p.read_text(encoding="utf-8")):
            link_family[link] = CATEGORY_PAGES.get(cat, cat)
    n = 0
    for p in sorted(SNAP.glob(f"cfm_{stamp}_detail_*.html")):
        link = "/" + p.name.split("_detail_")[1].replace(".html", "").replace("_", "/")
        family = link_family.get(link)
        if family is None:
            continue
        for r in parse_sample_data(p.read_text(encoding="utf-8"), today):
            r.family = family
            key = (r.source, r.family, r.section, r.name, r.date)
            _cmp(f"CFM {family}·{r.name}", r.date,
                 (r.high, r.low, r.avg, r.change_pct), db.get(key), problems, n_ok)
            n += 1
    print(f"[cfm] {stamp} 快照回放完成（{n} 行）")
    return problems, n_ok


def cross_source_info(con) -> list[str]:
    """同族跨源最新值偏离（不同评估方，只报不判）。LIKE 模式必须指名道姓——
    模糊前缀会把 RDIMM 32GB 错配去和 UDIMM 16GB 比（2026-10-05 首跑踩过）。"""
    out = []
    pairs = [
        ("512Gb TLC 晶圆", "Wafer", "现货价", "%512Gb TLC%", "NAND Wafer", "%512Gb TLC%"),
        ("DDR5 16Gb 现货(主力)", "DRAM", "现货价", "%DDR5 16Gb (2Gx8) 4800%", "DRAM 颗粒", "%DDR5 16Gb Major%"),
        ("DDR5 UDIMM 16GB", "Module", "现货价", "%DDR5 UDIMM 16GB%", "内存条(渠道)", "%DDR5 UDIMM 16GB%"),
    ]
    for label, fam, sec, tf_like, cfm_fam, cfm_like in pairs:
        a = con.execute(
            "SELECT q.date, q.avg FROM quotes q JOIN products p ON p.id=q.product_id "
            "WHERE p.source='TrendForce' AND p.family=? AND p.section=? AND p.name LIKE ? "
            "ORDER BY q.date DESC LIMIT 1", (fam, sec, tf_like)).fetchone()
        b = con.execute(
            "SELECT q.date, q.avg FROM quotes q JOIN products p ON p.id=q.product_id "
            "WHERE p.source='CFM' AND p.family=? AND p.name LIKE ? "
            "ORDER BY q.date DESC LIMIT 1", (cfm_fam, cfm_like)).fetchone()
        if a and b and a["avg"] and b["avg"]:
            dev = abs(a["avg"] - b["avg"]) / min(a["avg"], b["avg"]) * 100
            out.append(f"INFO-CROSS {label}: TF {a['avg']}（{a['date']}）vs CFM {b['avg']}"
                       f"（{b['date']}）偏离 {dev:.1f}%")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=3, help="TF 快照回看天数")
    args = ap.parse_args()

    con = store.connect(ROOT / "data" / "storage.db")
    db = _db_rows(con)

    problems, n_ok = [], []
    for fn in (lambda: verify_tf(db, args.days),
               lambda: verify_dxi(con, db),
               lambda: verify_spd(con, db),
               lambda: verify_cfm(db)):
        p_, ok = fn()
        problems += p_
        n_ok += ok

    print()
    for line in cross_source_info(con):
        print(line)
    print()
    print(f"=== 核对 {len(n_ok)} 行一致，{len(problems)} 行异常 ===")
    for p in problems[:40]:
        print(" ", p)
    if len(problems) > 40:
        print(f"  ...（其余 {len(problems) - 40} 条略）")
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
