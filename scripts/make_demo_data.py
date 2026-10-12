# -*- coding: utf-8 -*-
"""Seed synthetic demo data into all four boards' SQLite databases.

Purpose: let a fresh clone show a working dashboard WITHOUT hitting any live
source (polite-by-default; also works offline). Data is a deterministic random
walk shaped like the real thing (60 days, mild trend + weekly noise).
Real data replaces it on the first `python -m tracker.update`.

Usage:  python -m scripts.make_demo_data
"""
import datetime as dt
import pathlib
import random
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

ROOT = pathlib.Path(__file__).resolve().parent.parent
DAYS = 60

random.seed(20260101)


def walk(start, days, drift=0.0, vol=0.02, lo=None, hi=None, step_day=1):
    vals, v = [], start
    for i in range(days):
        v *= 1 + random.gauss(drift, vol)
        if lo is not None:
            v = max(lo, v)
        if hi is not None:
            v = min(hi, v)
        vals.append(round(v, 4))
    dates = []
    today = dt.date.today()
    d = today - dt.timedelta(days=days * 7 // 5)  # 60 工作日 ≈ 84 自然日起算
    while len(dates) < days and d <= today:        # 不越今天(demo 不该有未来行)
        d += dt.timedelta(days=1)
        if d.weekday() < 5 and d <= today:         # business days only
            dates.append(d.isoformat())
    return list(zip(dates, vals))


def seed_storage():
    import sqlite3
    db = ROOT / "boards" / "storage" / "data" / "storage.db"
    db.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db)
    con.executescript(open(ROOT / "boards" / "storage" / "tracker" / "store.py").read()
                      .split('SCHEMA = """')[1].split('"""')[0])
    specs = [("DDR5 16Gb (2Gx8) 4800/5600", 5.5, 0.05), ("DDR4 16Gb (2Gx8) 3200", 3.2, 0.03),
             ("512Gb TLC", 22.0, 0.04)]
    for i, (name, start, vol) in enumerate(specs, 1):
        con.execute("INSERT OR IGNORE INTO products(id,source,family,section,name,vendors,unit,freq) "
                    "VALUES(?,?,?,?,?,?,?,?)",
                    (1000 + i, "Demo", "NAND" if "TLC" in name else "DRAM", "demo", name,
                     "DemoVendor", "USD", "daily"))
        series = walk(start, DAYS, drift=0.004, vol=vol)
        for d, v in series:
            con.execute("INSERT OR REPLACE INTO quotes(date,product_id,high,low,avg,change_pct,fetched_at) "
                        "VALUES(?,?,?,?,?,?,?)", (d, 1000 + i, round(v * 1.05, 2), round(v * 0.95, 2),
                                                  v, None, dt.datetime.now().isoformat()))
    con.commit()
    n = con.execute("SELECT COUNT(*) FROM quotes").fetchone()[0]
    con.close()
    return n


def seed_mlcc():
    import sqlite3
    db = ROOT / "boards" / "mlcc" / "data" / "mlcc.db"
    db.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db)
    con.executescript(open(ROOT / "boards" / "mlcc" / "tracker" / "store.py").read()
                      .split('SCHEMA = """')[1].split('"""')[0])
    specs = [("CL31A106KBHNNNE", 1.4, 0.03), ("CL10B105KA8NNNC", 0.11, 0.05)]
    for i, (name, start, vol) in enumerate(specs, 1):
        con.execute("INSERT OR IGNORE INTO products(id,source,part,brand,seg,descr,unit,freq) "
                    "VALUES(?,?,?,?,?,?,?,?)",
                    (2000 + i, "Demo", name, "Demo", "高容", "demo MLCC", "￥/颗", "daily"))
        series = walk(start, DAYS, drift=0.003, vol=vol)
        for d, v in series:
            con.execute("INSERT OR REPLACE INTO quotes(date,product_id,price,stock,moq,fetched_at) "
                        "VALUES(?,?,?,?,?,?)", (d, 2000 + i, v, 50000, 1,
                                                dt.datetime.now().isoformat()))
    con.commit()
    return con.execute("SELECT COUNT(*) FROM quotes").fetchone()[0]


def main():
    print("[demo] storage quotes:", seed_storage())
    print("[demo] mlcc quotes:", seed_mlcc())
    # fabric(电子布)为锚点制板:python -m boards.fabric.tracker.update --seed-anchors-only
    # 即可离线 seed 全部新闻锚点;B2B 挂牌序列需真实抓取,不做合成。
    print("[demo] 完成。注意:这是合成演示数据;真实数据从 python -m tracker.update 开始累积。")


if __name__ == "__main__":
    main()
