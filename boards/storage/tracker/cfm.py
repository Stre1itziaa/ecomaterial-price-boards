"""CFM 闪存市场（chinaflashmarket.com）真实历史回填。

数据来源（均为 CFM 公开页、无需登录）：
- 品类页 /price/<cat>：周度产品报价表（本周价/上周价/周高低点）+ 每行"走势"详情链接；
  页面还内嵌全站价格指数序列（NAND指数 / DRAM指数，周度，约 31 周）。
- 产品详情页 /price/<type>/<id>：内嵌 var sampleData = [{date,value,category}, ...]，
  即该产品自己的历史序列（现货类为日度 收盘/开盘/日低点，约 65 个交易日；
  周价类为 本周价/周高点/周低点，约 13 周）。

所有原始 HTML 存档到 data/snapshots/cfm_，可重解析。
"""
from . import tz
import datetime as dt
import json
import pathlib
import re
import time

import requests

from .parse import QuoteRow

BASE = "https://www.chinaflashmarket.com"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/126.0 Safari/537.36")

# 品类页 -> (family, section_hint)
CATEGORY_PAGES = {
    "ddr": "DRAM 颗粒",
    "nandflash": "NAND Wafer",
    "ddrchannel": "内存条(渠道)",
    "ddroem": "内存条(行业)",
    "rdimmcontract": "内存条(服务器)",
    "ssdchannel": "SSD(渠道)",
    "ssdoem": "SSD(行业)",
    "emmc": "eMMC",
    "emcp": "eMCP",
    "lpddr": "LPDDR",
    "ufs": "UFS",
    "umcp": "uMCP",
    "flashcard": "闪存卡",
    "usb2": "U盘 USB2.0",
    "usb3": "U盘 USB3.0",
}

SAMPLE_RE = re.compile(r"var\s+sampleData\s*=\s*(\[.*?\]);", re.S)
INDEX_RE = re.compile(r"var\s+(data1?)\s*=\s*(\[\{.*?\}\])", re.S)


def _get(url, retries=3):
    last = None
    for i in range(1, retries + 1):
        try:
            r = requests.get(url, headers={"User-Agent": UA}, timeout=30)
            r.raise_for_status()
            return r.text
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(1.5 * i)
    raise RuntimeError(f"抓取失败 {url}: {last}")


def _to_date(s: str, today: dt.date) -> str:
    """容错解析 CFM 日期格式：'6/18'、'2025-10-14'、'2026-1-06' 等。"""
    s = s.strip()
    if "/" in s:  # M/D，默认当年；若超过今天视为上一年
        m, d = (int(x) for x in s.split("/"))
        year = today.year if (m, d) <= (today.month, today.day) else today.year - 1
        return f"{year:04d}-{m:02d}-{d:02d}"
    y, m, d = (int(x) for x in s.split("-"))
    return f"{y:04d}-{m:02d}-{d:02d}"


def _iso_date(md_dash: str, today: dt.date) -> str:
    """'02-03' -> '2026-02-03'（指数页日期格式）。"""
    m, d = (int(x) for x in md_dash.split("-"))
    year = today.year if (m, d) <= (today.month, today.day) else today.year - 1
    return f"{year:04d}-{m:02d}-{d:02d}"


def parse_sample_data(html: str, today: dt.date) -> list[QuoteRow]:
    """详情页 sampleData -> QuoteRow 列表（单产品多日期多系列）。"""
    m = SAMPLE_RE.search(html)
    if not m:
        return []
    arr = json.loads(m.group(1))
    title_m = re.search(r"<title>([^<]*?)(?:价格)_报价中心", html)
    name = title_m.group(1).strip() if title_m else "CFM产品"
    by_date = {}
    for x in arr:
        by_date.setdefault(_to_date(x["date"], today), {})[x["category"]] = x["value"]
    rows = []
    daily = any("收盘价" in k for k in next(iter(by_date.values())).keys())
    usd = any("($)" in k for k in next(iter(by_date.values())).keys())
    for date in sorted(by_date):
        vals = by_date[date]
        close = vals.get("收盘价($)") or vals.get("收盘价(￥)") or vals.get("本周价($)") or vals.get("本周价(￥)")
        if close is None:
            continue
        rows.append(QuoteRow(
            family="CFM", section="detail", name=name, vendors="CFM闪存市场",
            unit="USD" if usd else "CNY",
            date=date,
            high=vals.get("周高点($)") or vals.get("周高点(￥)"),
            low=vals.get("周低点($)") or vals.get("周低点(￥)") or vals.get("日低点($)") or vals.get("日低点(￥)"),
            avg=float(close),
            change_pct=None,
            extra={k: v for k, v in vals.items()
                   if k not in ("收盘价($)", "收盘价(￥)", "本周价($)", "本周价(￥)")},
        ))
    # 标记 section/freq：日度序列(>=20个日期) or 周度报价
    sec = "现货(日)" if len(by_date) >= 20 else "报价(周)"
    freq = "daily" if len(by_date) >= 20 else "weekly"
    for r in rows:
        r.section = sec
        r.freq = freq
        r.source = "CFM"
    return rows


def parse_indices(html: str, today: dt.date) -> list[QuoteRow]:
    """品类页内嵌的两个全站价格指数：data=NAND指数，data1=DRAM指数。"""
    rows = []
    for name, var in (("NAND指数", "data"), ("DRAM指数", "data1")):
        m = re.search(rf"var\s+{var}\s*=\s*(\[\{{.*?\}}\])", html, re.S)
        if not m:
            continue
        for x in json.loads(m.group(1)):
            rows.append(QuoteRow(
                family="CFM 指数", section="价格指数", name=name, vendors="CFM闪存市场",
                unit="index", date=_iso_date(x["date"], today),
                high=None, low=None, avg=float(x["index"]), change_pct=None, extra={},
                source="CFM", freq="index"))
    return rows


def crawl(snapshot_dir: pathlib.Path, categories=None, pause=1.0):
    """全量抓取：品类页 -> 产品详情页。返回 QuoteRow 列表。"""
    snapshot_dir = pathlib.Path(snapshot_dir)
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    today = tz.today()
    stamp = today.strftime("%Y%m%d")
    cats = categories or list(CATEGORY_PAGES)
    rows = []

    # 1) 品类页（拿指数 + 产品详情链接）
    detail_links = []
    for cat in cats:
        html = _get(f"{BASE}/price/{cat}")
        (snapshot_dir / f"cfm_{stamp}_cat_{cat}.html").write_text(html, encoding="utf-8")
        rows.extend(parse_indices(html, today))
        for link in re.findall(r'href="(/price/(?:sz|in|ews|w3t|ems)/\d+)"', html):
            if (cat, link) not in detail_links:
                detail_links.append((cat, link))
        time.sleep(pause)
    print(f"[cfm] 品类页 {len(cats)} 个，详情链接 {len(detail_links)} 个")

    # 2) 详情页（产品历史序列）
    seen = set()
    n = 0
    for cat, link in detail_links:
        if link in seen:
            continue
        seen.add(link)
        html = _get(BASE + link)
        (snapshot_dir / f"cfm_{stamp}_detail{link.replace('/', '_')}.html").write_text(html, encoding="utf-8")
        for r in parse_sample_data(html, today):
            r.family = CATEGORY_PAGES.get(cat, cat)
            rows.append(r)
        n += 1
        time.sleep(pause)
        if n % 20 == 0:
            print(f"[cfm] 详情页进度 {n}/{len(seen)}")
    print(f"[cfm] 详情页 {n} 个完成")
    return rows
