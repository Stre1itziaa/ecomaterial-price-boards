"""电子布 tracker SQLite 存储。

与 mlcc/storage 版同构(管线→库→审计→看板),表结构按品类适配:
- anchors      新闻考古锚点(非连续价格证据,口径分列)
- announcements 巨潮公告流(结构化自动线)
- fetch_log     抓取日志
本品类免费源下无连续日频价格序列(见 parts.py 说明),故无 products/quotes 表。
"""
from . import tz
import datetime as dt
import json
import pathlib
import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS anchors(
  date        TEXT NOT NULL,
  cat         TEXT NOT NULL,           -- 现货锚点/原厂调价/财报锚点/交期
  item        TEXT NOT NULL,           -- 品目(parts.ITEMS)
  value       TEXT NOT NULL,           -- 数值文本(原样保留)
  per_unit    REAL,                    -- 主数值折算中值(单位随口径)
  caliber     TEXT NOT NULL,           -- 口径(parts.CALIBERS),口径间绝不混算
  source      TEXT NOT NULL,           -- 出处(可溯源)
  PRIMARY KEY(date, item, value)
);
CREATE TABLE IF NOT EXISTS announcements(
  url         TEXT PRIMARY KEY,        -- 公告 PDF 路径(全局唯一)
  date        TEXT NOT NULL,
  code        TEXT NOT NULL,
  company     TEXT NOT NULL,
  title       TEXT NOT NULL,
  tag         TEXT NOT NULL DEFAULT '常规',
  fetched_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS dc_revenue(
  ticker      TEXT NOT NULL,
  filed_at    TEXT NOT NULL,
  period      TEXT NOT NULL,
  metric      TEXT NOT NULL,
  value_musd  REAL,            -- NULL=该期仅披露增速(AVGO FY25Q4)
  yoy_pct     INTEGER,
  text        TEXT NOT NULL,
  url         TEXT NOT NULL,
  fetched_at  TEXT NOT NULL,
  PRIMARY KEY(ticker, filed_at)
);
CREATE TABLE IF NOT EXISTS fetch_log(
  fetched_at TEXT PRIMARY KEY,
  sources TEXT, items INTEGER, rows INTEGER, notes TEXT
);
"""


def connect(db_path: pathlib.Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con


def seed_anchors(con, anchors) -> int:
    for a in anchors:
        con.execute("INSERT OR IGNORE INTO anchors VALUES(?,?,?,?,?,?,?)", a)
    con.commit()
    return con.execute("SELECT COUNT(*) FROM anchors").fetchone()[0]


def upsert_announcements(con, anns) -> tuple[int, int]:
    now = tz.now().isoformat(timespec="seconds")
    new = 0
    for a in anns:
        cur = con.execute(
            "INSERT OR IGNORE INTO announcements(url,date,code,company,title,tag,fetched_at) "
            "VALUES(?,?,?,?,?,?,?)", (a.url, a.date, a.code, a.company, a.title, a.tag, now))
        new += cur.rowcount
    con.commit()
    total = con.execute("SELECT COUNT(*) FROM announcements").fetchone()[0]
    return new, total


def log_fetch(con, sources: str, items: int, rows: int, notes: str):
    con.execute("INSERT OR REPLACE INTO fetch_log VALUES(?,?,?,?,?)",
                (tz.now().isoformat(timespec="seconds"),
                 sources, items, rows, notes))
    con.commit()


def dumps(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def upsert_dc(con, rows) -> int:
    now = tz.now().isoformat(timespec="seconds")
    for r in rows:
        con.execute(
            "INSERT INTO dc_revenue(ticker,filed_at,period,metric,value_musd,yoy_pct,text,url,fetched_at) "
            "VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(ticker, filed_at) DO UPDATE SET "
            "value_musd=excluded.value_musd, yoy_pct=excluded.yoy_pct, text=excluded.text",
            (r["ticker"], r["filed_at"], r["period"], r["metric"], r["value_musd"],
             r.get("yoy_pct"), r["text"], r["url"], now))
    con.commit()
    return len(rows)
