"""SEC 8-K EX-99.1 数据中心收入抓取:NVDA / AMD / AVGO,全清单第一条 L1 机读序列。

口径(各家原文,单位统一折算为百万美元):
- NVDA  "Data Center revenue of $89.0 billion, up 117% from a year ago"(market platform)
- AMD   "Data Center segment revenue was $6.7 billion, up 107% year-over-year"(reportable segment)
- AVGO  "AI semiconductor revenue of $16.x billion"(管理层口径,press release 引语)
YoY 直接存 press release 原文百分比(不自行重算,口径=原文)。

URL 清单人工维护(与 CSP 台账同节奏:每季财报后追加 3 行再跑 update)。
2026-09-24 由 sec-search 全文检索定位,2025-02 至 2026-09 共 21 期。
"""

from . import tz
import datetime as dt
import json
import pathlib
import re
import time

import requests

import os as _os
_SEC_EMAIL = _os.environ.get("SEC_CONTACT_EMAIL", "research contact@example.com")
UA = f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) {_SEC_EMAIL}"

# (ticker, 指标名, filed_at, 期间标签, URL)
DC_URLS = [
    ("NVDA", "Data Center 收入", "2025-02-26", "FY25Q4", "https://www.sec.gov/Archives/edgar/data/1045810/000104581025000021/q4fy25pr.htm"),
    ("NVDA", "Data Center 收入", "2025-05-28", "FY26Q1", "https://www.sec.gov/Archives/edgar/data/1045810/000104581025000115/q1fy26pr.htm"),
    ("NVDA", "Data Center 收入", "2025-08-27", "FY26Q2", "https://www.sec.gov/Archives/edgar/data/1045810/000104581025000207/q2fy26pr.htm"),
    ("NVDA", "Data Center 收入", "2025-11-19", "FY26Q3", "https://www.sec.gov/Archives/edgar/data/1045810/000104581025000228/q3fy26pr.htm"),
    ("NVDA", "Data Center 收入", "2026-02-25", "FY26Q4", "https://www.sec.gov/Archives/edgar/data/1045810/000104581026000019/q4fy26pr.htm"),
    ("NVDA", "Data Center 收入", "2026-05-20", "FY27Q1", "https://www.sec.gov/Archives/edgar/data/1045810/000104581026000051/q1fy27pr.htm"),
    ("NVDA", "Data Center 收入", "2026-08-26", "FY27Q2", "https://www.sec.gov/Archives/edgar/data/1045810/000104581026000073/q2fy27pr.htm"),
    ("AMD", "Data Center 收入", "2025-02-04", "2024Q4", "https://www.sec.gov/Archives/edgar/data/2488/000000248825000009/q42024991.htm"),
    ("AMD", "Data Center 收入", "2025-05-06", "2025Q1", "https://www.sec.gov/Archives/edgar/data/2488/000000248825000045/q12025991.htm"),
    ("AMD", "Data Center 收入", "2025-08-05", "2025Q2", "https://www.sec.gov/Archives/edgar/data/2488/000000248825000106/q22025991.htm"),
    ("AMD", "Data Center 收入", "2025-11-04", "2025Q3", "https://www.sec.gov/Archives/edgar/data/2488/000000248825000163/q32025991.htm"),
    ("AMD", "Data Center 收入", "2026-02-03", "2025Q4", "https://www.sec.gov/Archives/edgar/data/2488/000000248826000014/q42025991.htm"),
    ("AMD", "Data Center 收入", "2026-05-05", "2026Q1", "https://www.sec.gov/Archives/edgar/data/2488/000000248826000072/q12026991.htm"),
    ("AMD", "Data Center 收入", "2026-08-04", "2026Q2", "https://www.sec.gov/Archives/edgar/data/2488/000000248826000121/q22026991.htm"),
    ("AVGO", "AI 半导体收入", "2025-03-06", "FY25Q1", "https://www.sec.gov/Archives/edgar/data/1730168/000173016825000009/avgo-02022025x8kxex99.htm"),
    ("AVGO", "AI 半导体收入", "2025-06-05", "FY25Q2", "https://www.sec.gov/Archives/edgar/data/1730168/000173016825000061/avgo-05042025x8kxex99.htm"),
    ("AVGO", "AI 半导体收入", "2025-09-04", "FY25Q3", "https://www.sec.gov/Archives/edgar/data/1730168/000173016825000094/avgo-08032025x8kxex99.htm"),
    ("AVGO", "AI 半导体收入", "2025-12-11", "FY25Q4", "https://www.sec.gov/Archives/edgar/data/1730168/000173016825000116/avgo-11022025x8kxex99.htm"),
    ("AVGO", "AI 半导体收入", "2026-03-04", "FY26Q1", "https://www.sec.gov/Archives/edgar/data/1730168/000173016826000011/avgo-02012026x8kxex99.htm"),
    ("AVGO", "AI 半导体收入", "2026-06-03", "FY26Q2", "https://www.sec.gov/Archives/edgar/data/1730168/000173016826000051/avgo-05032026x8kxex99.htm"),
    ("AVGO", "AI 半导体收入", "2026-09-02", "FY26Q3", "https://www.sec.gov/Archives/edgar/data/1730168/000173016826000076/avgo-08022026x8kxex99.htm"),
]

PATTERNS = {
    "NVDA": [(r"Data Center revenue of \$([\d,\.]+) (billion|million)", r"(up|down) (\d+)% from a year ago")],
    "AMD": [(r"Data Center segment revenue(?: in the quarter)? was (?:a record )?\$([\d,\.]+) (billion|million)",
             r"(up|down) (\d+)% year-over-year")],
    # AVGO 句式每期一变:of $ / from AI of $ / grew X% YoY to (over) $ / 仅增速(无绝对值)
    "AVGO": [
        (r"AI semiconductor revenue of \$([\d,\.]+) (billion|million)", None),
        (r"semiconductor revenue from AI of \$([\d,\.]+) (billion|million)", r"grew (\d+)% year-over-year"),
        (r"AI revenue of \$([\d,\.]+) (billion|million)", None),
        (r"(?:grew|accelerated to) (\d+)% year-over-year to (?:over )?\$([\d,\.]+) (billion|million)", None),
        (r"AI semiconductor revenue (?:increasing|growing) (\d+)% year-over-year", None),  # 增速-only
    ],
}
GUIDE_GUARD = re.compile(r"expect|forecast|guidance|to (?:accelerate|double)", re.I)


def to_musd(num: str, unit: str) -> float:
    v = float(num.replace(",", ""))
    return v * 1000.0 if unit == "billion" else v


def _find_value(text: str, val_pat: str):
    """返回 (value_musd, yoy_pct|None, text) 或 None;跳过命中指引语境的 match。"""
    for m in re.finditer(val_pat, text):
        ctx_before = text[max(0, m.start() - 80):m.start()]
        if GUIDE_GUARD.search(ctx_before):
            continue
        groups = m.groups()
        if len(groups) == 3:
            # 变体 4: (yoy_num, value, unit)
            return (to_musd(groups[1], groups[2]), int(groups[0]), m.group(0).strip())
        if len(groups) == 2 and groups[1] in ("billion", "million"):
            return (to_musd(groups[0], groups[1]), None, m.group(0).strip())
    return None


def _find_yoy_only(text: str, yoy_pat: str):
    m = re.search(yoy_pat, text)
    if not m:
        return None
    return {"value_musd": None, "yoy_pct": int(m.group(1)), "text": m.group(0).strip()}


def parse(ticker: str, html: str) -> dict | None:
    t = re.sub(r"<[^>]+>", " ", html)
    t = t.replace("&#36;", "$").replace("&nbsp;", " ").replace("&#8221;", '"')
    t = re.sub(r"\s+", " ", t)
    for val_pat, yoy_pat in PATTERNS[ticker]:
        hit = _find_value(t, val_pat)
        if hit:
            return {"value_musd": hit[0], "yoy_pct": hit[1], "text": hit[2]}
    # 兜底:增速-only(如 AVGO FY25Q4 引语只给 +74% 无绝对值)
    if ticker == "AVGO":
        hit = _find_yoy_only(t, r"AI semiconductor revenue (?:increasing|growing) (\d+)% year-over-year")
        if hit:
            return hit
    return None


CIK = {"NVDA": "0001045810", "AMD": "0000002488", "AVGO": "0001730168"}
METRIC = {"NVDA": "Data Center 收入", "AMD": "Data Center 收入", "AVGO": "AI 半导体收入"}


def discover(known_urls: set, known_keys: set = None,
             lookback_days: int = 100) -> list[tuple]:
    """EDGAR submissions 自动发现新财报 8-K 的 EX-99.1,返回与 DC_URLS 同构的行。

    机制:三家的 submissions JSON 过滤 items 含 2.02(经营结果)的 8-K,
    再到 filing index 里找 EX-99.1 press release;URL 已在 known_urls 的跳过。
    免费匿名(需 UA);每家 1 次 submissions + 每个新 8-K 1 次 index。
    2026-10-12 上线,替代「每季人工追加 3 行 URL」。
    """
    out = []
    s = requests.Session()
    s.headers.update({"User-Agent": UA})
    cutoff = tz.today() - dt.timedelta(days=lookback_days)
    for ticker, cik in CIK.items():
        try:
            r = s.get(f"https://data.sec.gov/submissions/CIK{cik}.json", timeout=25)
            sub = r.json().get("filings", {}).get("recent", {})
            forms = sub.get("form", [])
            accs = sub.get("accessionNumber", [])
            items_list = sub.get("items", [])
            dates = sub.get("filingDate", [])
            docs = sub.get("primaryDocument", [])
        except Exception as e:
            print(f"[dc-discover] {ticker} submissions 失败: {type(e).__name__}")
            continue
        known_keys = known_keys or set()
        for i, form in enumerate(forms):
            if form != "8-K" or "2.02" not in (items_list[i] or ""):
                continue
            fdate = dt.date.fromisoformat(dates[i])
            if fdate < cutoff:
                continue
            if (ticker, dates[i]) in known_keys:   # 同期已在库(静态清单收录),跳过
                continue
            acc_nodash = accs[i].replace("-", "")
            base = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc_nodash}"
            try:
                idx = s.get(f"{base}/index.json", timeout=20).json()
                # 2.02 8-K 的 press release 命名三家各不同(q2fy27pr.htm /
                # q22026991.htm / avgo-xxxex99.htm),index.json 的 type 字段是
                # 图标名不含文档类型——无法静态定位。策略:该 8-K 的全部 .htm
                # 都作候选交给 crawl 的 parse 试解,解析不出自动跳过(零误入库)。
                for item in idx.get("directory", {}).get("item", []):
                    name = item.get("name", "")
                    if not name.lower().endswith((".htm", ".html")):
                        continue
                    if "index" in name.lower():
                        continue
                    url = f"{base}/{name}"
                    if url in known_urls:
                        continue
                    out.append((ticker, METRIC[ticker], dates[i],
                                f"{fdate.year}Q{(fdate.month - 1) // 3 + 1}(自动)", url))
            except Exception as e:
                print(f"[dc-discover] {ticker} {accs[i]} index 失败: {type(e).__name__}")
            time.sleep(1.0)
    return out


def crawl(snapshot_dir: pathlib.Path, pause: float = 1.5,
          discover_new: bool = True) -> list[dict]:
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept": "text/html"})
    url_rows = list(DC_URLS)
    if discover_new:
        try:
            found = discover({u for *_x, u in DC_URLS},
                             {(t, d) for t, _m, d, _p, _u in DC_URLS})
            if found:
                print(f"[dc] 自动发现 {len(found)} 期新财报:")
                for r in found:
                    print(f"  + {r[0]} {r[3]} {r[4]}")
                url_rows += [r for r in found if r not in url_rows]
        except Exception as e:
            print(f"[dc] 自动发现失败(退回静态清单): {type(e).__name__}: {e}")
    out = []
    for ticker, metric, filed_at, period, url in url_rows:
        cache = snapshot_dir / f"dc_{ticker}_{filed_at.replace('-', '')}.html"
        if cache.exists():
            html = cache.read_text(encoding="utf-8", errors="ignore")
        else:
            r = s.get(url, timeout=60)
            r.raise_for_status()
            html = r.text
            cache.write_text(html, encoding="utf-8")
            time.sleep(pause)
        parsed = parse(ticker, html)
        if not parsed:
            print(f"[dc] {ticker} {period} 解析失败: {url}")
            continue
        out.append({"ticker": ticker, "metric": metric, "filed_at": filed_at,
                    "period": period, "url": url, **parsed})
        print(f"[dc] {ticker} {period}: " + (f"${parsed['value_musd']:,.0f}M" if parsed["value_musd"] is not None else "仅增速披露")
              + (f" YoY {parsed['yoy_pct']:+d}%" if parsed.get("yoy_pct") is not None else ""))
    return out
