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
CREATE TABLE IF NOT EXISTS b2b_listings(
  date        TEXT NOT NULL,
  keyword     TEXT NOT NULL,           -- 展示名(7628 电子布 等)
  title       TEXT NOT NULL,
  supplier    TEXT,
  price       REAL NOT NULL,
  currency    TEXT NOT NULL DEFAULT 'CNY',
  unit        TEXT NOT NULL,           -- 规范化单位(㎡/张/kg)
  moq         TEXT,
  url         TEXT NOT NULL,
  fetched_at  TEXT NOT NULL,
  PRIMARY KEY(date, url)
);
CREATE TABLE IF NOT EXISTS b2b_daily(
  date        TEXT NOT NULL,
  keyword     TEXT NOT NULL,
  n           INTEGER NOT NULL,
  p25         REAL,
  median      REAL NOT NULL,
  p75         REAL,
  unit        TEXT NOT NULL,
  fetched_at  TEXT NOT NULL,
  PRIMARY KEY(date, keyword)
);
CREATE TABLE IF NOT EXISTS weekly_reviews(
  date  TEXT NOT NULL,            -- 周评期末(卓创,标题区间)或发布日(百川)
  src   TEXT NOT NULL,            -- 卓创资讯/百川盈孚
  title TEXT NOT NULL,            -- 周评标题全文(方向语义,无数字)
  url   TEXT NOT NULL,            -- 原文链接(可溯源)
  PRIMARY KEY(date, src, title)
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
CREATE TABLE IF NOT EXISTS fetch_log(
  fetched_at TEXT PRIMARY KEY,
  sources TEXT, items INTEGER, rows INTEGER, notes TEXT
);
"""


def replace_b2b(con, day: str, keyword: str, listings: list, daily: dict | None):
    """重放安全:先删当日该关键词再写入(幂等)。listings 元素含 fetched_at。"""
    con.execute("DELETE FROM b2b_listings WHERE date=? AND keyword=?",
                (day, keyword))
    for r in listings:
        con.execute(
            "INSERT OR REPLACE INTO b2b_listings"
            "(date,keyword,title,supplier,price,currency,unit,moq,url,fetched_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?)",
            (r["date"], r["keyword"], r["title"], r.get("supplier"),
             r["price"], r["currency"], r["unit"], r.get("moq"),
             r["url"], r["fetched_at"]))
    if daily:
        con.execute(
            "INSERT OR REPLACE INTO b2b_daily"
            "(date,keyword,n,p25,median,p75,unit,fetched_at) VALUES(?,?,?,?,?,?,?,?)",
            (daily["date"], daily["keyword"], daily["n"], daily["p25"],
             daily["median"], daily["p75"], daily["unit"], daily["fetched_at"]))
    con.commit()


def connect(db_path: pathlib.Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    # 来源分级(2026-10-11):anchors 表补 grade 列(旧库迁移)+ 空值回填。
    # 等级=证据硬度:一手公告 > 主流媒体 > 公众号转述;核验验证的是传播链
    # 一致性而非数据真实性,等级徽章让人一眼知道每条数字的硬度。
    cols = [r["name"] for r in con.execute("PRAGMA table_info(anchors)")]
    if "grade" not in cols:
        con.execute("ALTER TABLE anchors ADD COLUMN grade TEXT NOT NULL DEFAULT ''")
    con.execute("UPDATE anchors SET grade='公众号转述' WHERE grade='' AND source LIKE '%公众号%'")
    con.execute("UPDATE anchors SET grade='一手公告' WHERE grade='' AND (source LIKE '%公告%' OR source LIKE '%半年报%' OR source LIKE '%年报%' OR source LIKE '%季报%')")
    con.execute("UPDATE anchors SET grade='主流媒体' WHERE grade=''")
    con.commit()
    return con


def seed_anchors(con, anchors) -> int:
    for a in anchors:
        con.execute("INSERT OR IGNORE INTO anchors VALUES(?,?,?,?,?,?,?,?)", a)
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


def upsert_weekly(con, rows) -> tuple[int, int]:
    new = 0
    for r in rows:
        cur = con.execute("INSERT OR IGNORE INTO weekly_reviews VALUES(?,?,?,?)",
                          (r["date"], r["src"], r["title"], r["url"]))
        new += cur.rowcount
    con.commit()
    total = con.execute("SELECT COUNT(*) FROM weekly_reviews").fetchone()[0]
    return new, total


def log_fetch(con, sources: str, items: int, rows: int, notes: str):
    # 毫秒级时间戳：一次 update 会连写 cninfo+b2b 两条，秒级 PK 会同秒互覆
    con.execute("INSERT OR REPLACE INTO fetch_log VALUES(?,?,?,?,?)",
                (tz.now().isoformat(timespec="milliseconds"),
                 sources, items, rows, notes))
    con.commit()


def dumps(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
