"""SQLite 存储：products + quotes 两张主表，UPSERT 幂等。"""

from . import tz
import datetime as dt
import json
import pathlib
import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS products(
  id       INTEGER PRIMARY KEY AUTOINCREMENT,
  source   TEXT NOT NULL DEFAULT 'TrendForce',
  family   TEXT NOT NULL,
  section  TEXT NOT NULL,
  name     TEXT NOT NULL,
  vendors  TEXT,
  unit     TEXT NOT NULL DEFAULT 'USD',
  freq     TEXT NOT NULL DEFAULT 'daily',
  active   INTEGER NOT NULL DEFAULT 1,
  UNIQUE(source, family, section, name)
);
CREATE TABLE IF NOT EXISTS quotes(
  date        TEXT NOT NULL,
  product_id  INTEGER NOT NULL REFERENCES products(id),
  high        REAL, low REAL, avg REAL NOT NULL,
  change_pct  REAL,
  extra       TEXT,
  fetched_at  TEXT NOT NULL,
  PRIMARY KEY(date, product_id)
);
CREATE TABLE IF NOT EXISTS fetch_log(
  fetched_at TEXT PRIMARY KEY,
  pages      TEXT, products INTEGER, quotes INTEGER, notes TEXT
);
"""


# 退役策略（历史保留、停更即真相，仅导出层隐藏）：
# - TrendForce 合约价：免费页合约板块 2026-08-31 起停更，免费渠道无替代（CFM 行业价承接）
# - SPD 下架 SKU：店家目录已移除，无可比替代（goHDD 最高 20TB，覆盖不了 22/26TB）
RETIRED_SECTIONS = [("TrendForce", "合约价")]
RETIRED_NAMES = [
    ("SPD", "WD ULTRASTAR DC HC580 22TB SAS · Refurbished"),
    ("SPD", "WD ULTRASTAR DC HC590 26TB SATA · New"),
]


def _apply_retirements(con) -> None:
    for source, section in RETIRED_SECTIONS:
        con.execute("UPDATE products SET active=0 WHERE source=? AND section=?",
                    (source, section))
    for source, name in RETIRED_NAMES:
        con.execute("UPDATE products SET active=0 WHERE source=? AND name=?",
                    (source, name))
    con.commit()


def connect(db_path: pathlib.Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    cols = {r[1] for r in con.execute("PRAGMA table_info(products)")}
    if "active" not in cols:
        con.execute("ALTER TABLE products ADD COLUMN active INTEGER NOT NULL DEFAULT 1")
        con.commit()
    _apply_retirements(con)
    return con


def upsert_rows(con: sqlite3.Connection, rows) -> tuple[int, int]:
    """返回 (产品数, 行情行数)。同 (date, product) 重跑覆盖。"""
    now = tz.now().isoformat(timespec="seconds")
    products, quotes = 0, 0
    for r in rows:
        cur = con.execute(
            "INSERT INTO products(source, family, section, name, vendors, unit, freq) "
            "VALUES(?,?,?,?,?,?,?) "
            "ON CONFLICT(source, family, section, name) DO UPDATE SET vendors=excluded.vendors, "
            "freq=excluded.freq "
            "RETURNING id", (r.source, r.family, r.section, r.name, r.vendors, r.unit, r.freq))
        pid = cur.fetchone()[0]
        products += 1
        con.execute(
            "INSERT INTO quotes(date, product_id, high, low, avg, change_pct, extra, fetched_at) "
            "VALUES(?,?,?,?,?,?,?,?) "
            "ON CONFLICT(date, product_id) DO UPDATE SET high=excluded.high, low=excluded.low, "
            "avg=excluded.avg, change_pct=excluded.change_pct, extra=excluded.extra, "
            "fetched_at=excluded.fetched_at",
            (r.date, pid, r.high, r.low, r.avg, r.change_pct,
             json.dumps(r.extra, ensure_ascii=False) if r.extra else None, now))
        quotes += 1
    con.commit()
    return products, quotes


def log_fetch(con: sqlite3.Connection, pages: str, products: int, quotes: int, notes: str):
    con.execute("INSERT OR REPLACE INTO fetch_log VALUES(?,?,?,?,?)",
                (tz.now().isoformat(timespec="seconds"), pages, products, quotes, notes))
    con.commit()
