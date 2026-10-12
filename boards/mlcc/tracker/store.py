"""MLCC 报价 SQLite 存储。"""

from . import tz
import datetime as dt
import json
import pathlib
import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS products(
  id       INTEGER PRIMARY KEY AUTOINCREMENT,
  source   TEXT NOT NULL,          -- ICKey / LCSC / Mouser
  part     TEXT NOT NULL,          -- 料号
  brand    TEXT NOT NULL,
  seg      TEXT NOT NULL,          -- 高容/中容/低容/车规
  descr    TEXT,
  unit     TEXT NOT NULL DEFAULT 'CNY',
  freq     TEXT NOT NULL DEFAULT 'daily',
  active   INTEGER NOT NULL DEFAULT 1,
  UNIQUE(source, part)
);
CREATE TABLE IF NOT EXISTS quotes(
  date        TEXT NOT NULL,
  product_id  INTEGER NOT NULL REFERENCES products(id),
  price       REAL NOT NULL,       -- 起订档单价 CNY
  stock       INTEGER NOT NULL DEFAULT 0,
  moq         INTEGER,
  ladder      TEXT,                -- 完整阶梯 JSON [[qty, price], ...]
  fetched_at  TEXT NOT NULL,
  PRIMARY KEY(date, product_id)
);
CREATE TABLE IF NOT EXISTS fetch_log(
  fetched_at TEXT PRIMARY KEY,
  sources    TEXT, parts INTEGER, quotes INTEGER, notes TEXT
);
CREATE TABLE IF NOT EXISTS pending_anchors(
  url         TEXT PRIMARY KEY,   -- 微信原文链接(或 sogou:标题 兜底)
  found_at    TEXT NOT NULL,      -- 扫描日
  pub_date    TEXT,               -- 公众号发布日(可空)
  account     TEXT,               -- 公众号名
  title       TEXT NOT NULL,
  excerpt     TEXT,               -- 搜狗摘要
  nums        TEXT,               -- 正文抽取的数字片段(JSON 数组,机器不定价)
  items       TEXT,               -- 命中品目(JSON 数组)
  status      TEXT NOT NULL DEFAULT '待核验',  -- 待核验/已采纳/已否决
  fetched_at  TEXT NOT NULL
);
"""


# 退役料号（历史保留、仅导出隐藏）：
# - GRM188R61E105MA12D：Murata ±20% 建号停产（LCSC 缺货 2026-09 底起、mouser.cn 无报价），
#   2026-10-05 切换至在架活号 GRM188R61E105KA12D（±10%，同系列同规格）
RETIRED_PARTS = ("GRM188R61E105MA12D",)


def _apply_retirements(con) -> None:
    for part in RETIRED_PARTS:
        con.execute("UPDATE products SET active=0 WHERE part=?", (part,))
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


def upsert(con: sqlite3.Connection, quotes) -> tuple[int, int]:
    now = tz.now().isoformat(timespec="seconds")
    parts_n = rows_n = 0
    for q in quotes:
        cur = con.execute(
            "INSERT INTO products(source, part, brand, seg, descr) VALUES(?,?,?,?,?) "
            "ON CONFLICT(source, part) DO UPDATE SET brand=excluded.brand, seg=excluded.seg, "
            "descr=excluded.descr RETURNING id",
            (q.source, q.part, q.brand, q.seg, q.desc))
        pid = cur.fetchone()[0]
        parts_n += 1
        ladder = json.dumps(q.extra.get("ladder"), ensure_ascii=False) if q.extra.get("ladder") else None
        con.execute(
            "INSERT INTO quotes(date, product_id, price, stock, moq, ladder, fetched_at) "
            "VALUES(?,?,?,?,?,?,?) "
            "ON CONFLICT(date, product_id) DO UPDATE SET price=excluded.price, "
            "stock=excluded.stock, moq=excluded.moq, ladder=excluded.ladder, "
            "fetched_at=excluded.fetched_at",
            (q.date, pid, q.price, q.stock, q.moq, ladder, now))
        rows_n += 1
    con.commit()
    return parts_n, rows_n


def log_fetch(con, sources: str, parts: int, quotes: int, notes: str):
    con.execute("INSERT OR REPLACE INTO fetch_log VALUES(?,?,?,?,?)",
                (tz.now().isoformat(timespec="seconds"), sources, parts, quotes, notes))
    con.commit()
