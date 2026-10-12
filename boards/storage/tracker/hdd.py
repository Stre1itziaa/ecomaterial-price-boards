"""Nearline HDD 零售现货抓取:ServerPartDeals(Shopify 店,products.json 公开)。

口径:USD 零售挂牌价(企业盘/NAS 盘),New 与 Refurbished/Recertified 分档入库——
档位是本源的自校验结构(同型号新品价 ≥ 翻新品价,违反=数据异常,audit 强校验)。
币种:products.json 必须带 &currency=USD(见 BASE 注释),并有 USD/TB 护栏兜底。

中国零售源 2026-09-23 实测全灭:京东搜索登录墙(Playwright 460KB 页含 passport
且无 data-sku)、p.3.cn 连接失败(HTTP 000)、Newegg 人机墙(areyouahuman)、
慢慢买 000/404、ZOL 列表页 404。单源入板、口径如实标注,待国内源出现再补双源。
"""

from . import tz
import datetime as dt
import json
import pathlib
import re
import time
from dataclasses import dataclass, field

import requests

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
# currency=USD 必须显式钉死:店铺开了 Shopify Markets 按 IP 币种展示,本网络出口
# 默认拿到 CNY 计价(2026-09-26 实测 3060=¥3060≈$449,差 6.8 倍),JSON 本身不带货币字段
BASE = "https://www.serverpartdeals.com/products.json?limit=250&page={page}&currency=USD"
USD_PER_TB_MAX = 150.0  # 币种护栏:近线盘美元单 TB 价上界(2026 涨价顶点实测 $44/TB,CNY 错标会到 $170+/TB)
PAGES = 3
PLACEHOLDER = 9999.0   # 店铺无货占位价,跳过

# (品牌缩写, 型号标签, family, 品牌全称, 最小容量 TB)
# 近线盘 ≥14TB、NAS 盘 ≥16TB——聚焦本轮涨价的主力容量段
MODEL_RULES = [
    ("Seagate", r"Exos\s+X(1[689]|2[0246])", "HDD 企业盘", "Seagate", 14),
    ("WD", r"Ultrastar\s+DC\s+HC5\d0", "HDD 企业盘", "Western Digital", 14),
    ("Toshiba", r"MG(09|10|11)", "HDD 企业盘", "Toshiba", 14),
    ("Seagate", r"IronWolf\s+Pro", "HDD NAS盘", "Seagate", 16),
    ("WD", r"Red\s+Pro", "HDD NAS盘", "Western Digital", 16),
    ("Toshiba", r"N300", "HDD NAS盘", "Toshiba", 16),
]
COND_RULES = [
    (r"Manufacturer Recertified|^Recertified", "Recertified"),
    (r"^Refurbished", "Refurbished"),
    (r"^New\b", "New"),
]


@dataclass
class Row:
    source: str = "SPD"
    family: str = ""      # HDD 企业盘 / HDD NAS盘
    section: str = "零售现货"
    name: str = ""        # "Seagate Exos X20 20TB · New"
    vendors: str = ""     # 品牌全称
    unit: str = "USD"
    freq: str = "daily"
    date: str = ""
    high: float = None
    low: float = None
    avg: float = 0.0      # 该型该档最低在售价
    change_pct: float = None
    extra: dict = field(default_factory=dict)


def classify(title: str):
    cap_m = re.search(r"(\d+(?:\.\d+)?)\s*TB", title, re.I)
    if not cap_m:
        return None
    cap = float(cap_m.group(1))
    for brand, pat, family, vendor, cap_min in MODEL_RULES:
        if vendor.lower() not in title.lower() and brand.lower() not in title.lower():
            continue
        m = re.search(pat, title, re.I)
        if not m or cap < cap_min:
            continue
        return brand, m.group(0).upper().replace("  ", " "), family, vendor, cap
    return None


def cond_of(title: str, tags: list) -> str | None:
    """状态以标题后缀为准(店规:New 卡标题不带状态词,以 HDD/Hard Drive 结尾);
    标题无状态词时回退 000CardTitle 标签。"""
    t = (title or "").upper()
    if "REFURBISHED" in t:
        return "Refurbished"
    if "RECERTIFIED" in t:
        return "Recertified"
    if t.rstrip().endswith(("HDD", "HARD DRIVE")):
        return "New"
    for tg in tags or []:
        m = re.match(r"000CardTitle:(.+)$", tg or "")
        head = (m.group(1) if m else (tg or "")).strip()
        for pat, cond in COND_RULES:
            if re.match(pat, head, re.I):
                return cond
    return None


def parse_products(products: list, today: str) -> list[Row]:
    best = {}  # (name, cond) -> (price, row)
    for p in products:
        info = classify(p.get("title") or "")
        if not info:
            continue
        brand, model, family, vendor, cap = info
        cond = cond_of(p.get("title") or "", p.get("tags") or [])
        if not cond:
            continue
        iface_m = re.search(r"\b(SAS|SATA)\b", p.get("title") or "", re.I)
        iface = f" {iface_m.group(1).upper()}" if iface_m else ""
        name = f"{brand} {model} {cap:g}TB{iface} · {cond}"
        price, variant_id = None, None
        for v in p.get("variants") or []:
            try:
                pv = float(v.get("price") or 0)
            except (TypeError, ValueError):
                continue
            if pv <= 0 or pv >= PLACEHOLDER:
                continue
            if v.get("available") is False:
                continue
            if price is None or pv < price:
                price, variant_id = pv, v.get("id")
        if price is None:
            continue  # 全档无货=缺货信号,无价不入库(同 MLCC 纪律)
        row = Row(family=family, name=name, vendors=vendor, date=today, avg=price,
                  extra={"condition": cond, "capacity_tb": cap,
                         "url": f"https://www.serverpartdeals.com/products/{p.get('handle')}"})
        key = (name, cond)
        if key not in best or price < best[key][0]:
            best[key] = (price, row)
    return [r for _, r in best.values()]


def crawl(snapshot_dir: pathlib.Path, today: str | None = None) -> list[Row]:
    today = today or tz.today().isoformat()
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"})
    out = []
    raw_pages = []
    for page in range(1, PAGES + 1):
        for attempt in range(3):
            try:
                r = s.get(BASE.format(page=page), timeout=30)
                r.raise_for_status()
                payload = r.json()
                raw_pages.append(payload)
                out += parse_products(payload.get("products") or [], today)
                break
            except Exception as e:  # noqa: BLE001
                print(f"[hdd] page{page} 第{attempt + 1}次失败: {e}")
                time.sleep(4 * (attempt + 1))
        if raw_pages and not (raw_pages[-1].get("products") or []):
            break
        time.sleep(2.0)
    stamp = today.replace("-", "")
    (snapshot_dir / f"spd_{stamp}.json").write_text(json.dumps(raw_pages), encoding="utf-8")
    # 币种护栏:任一在售价折算单 TB 超上界即拒收整批(防 Markets 按出口 IP 回退 CNY 计价)
    if out:
        worst = max(r.avg / r.extra["capacity_tb"] for r in out)
        if worst > USD_PER_TB_MAX:
            raise RuntimeError(
                f"[hdd] 币种护栏触发:最高 {worst:.0f} USD/TB 超上界 {USD_PER_TB_MAX:.0f},"
                "疑似非美元计价回退,整批拒收(库内保留昨日美元数据)")
    return out
