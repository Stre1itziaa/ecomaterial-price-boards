"""巨潮资讯网(cninfo)公告流抓取:纯 requests,公开接口无需登录。

口径:公告标题+披露日期+PDF 链接(不解析 PDF 正文,正文价格经人工核验后
进 news_anchors 锚点层)。窗口 2026-01-01 至今(与本板锚点周期一致)。
实测 2026-09-23:四家全通,单家单页 30 条,大几页取完。
"""
from . import tz
import datetime as dt
import json
import pathlib
import re
import time
from dataclasses import dataclass

import requests

QUERY_URL = "http://www.cninfo.com.cn/new/hisAnnouncement/query"
PDF_BASE = "http://static.cninfo.com.cn/"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
REFERER = "http://www.cninfo.com.cn/new/commonUrl/pageOfSearch?url=disclosure/list/search"
WINDOW_START = "2026-01-01"


@dataclass
class Ann:
    url: str
    date: str
    code: str
    company: str
    title: str
    tag: str


def tag_of(title: str, rules) -> str:
    for tag, keywords in rules:
        if any(k in title for k in keywords):
            return tag
    return "常规"


def fetch_company(s: requests.Session, code: str, org_id: str, company: str,
                  today: str, rules, page_size: int = 30) -> list[Ann]:
    out, page = [], 1
    while True:
        r = s.post(QUERY_URL, data={
            "pageNum": page, "pageSize": page_size, "column": "szse",
            "tabName": "fulltext", "plate": "", "stock": f"{code},{org_id}",
            "searchkey": "", "secid": "", "category": "", "trade": "",
            "seDate": f"{WINDOW_START}~{today}",
            "sortName": "", "sortType": "", "isHLtitle": "false",
        }, headers={"User-Agent": UA, "Referer": REFERER}, timeout=30)
        r.raise_for_status()
        payload = r.json()
        anns = payload.get("announcements") or []
        if not anns:
            break
        for a in anns:
            raw = a.get("announcementTitle") or ""
            title = re.sub(r"<[^>]+>", "", raw).strip()
            adjunct = a.get("adjunctUrl") or ""
            if not title or not adjunct:
                continue
            ts = a.get("announcementTime")
            date = dt.datetime.fromtimestamp(ts / 1000).strftime("%Y-%m-%d") if ts else ""
            out.append(Ann(url=PDF_BASE + adjunct, date=date, code=code,
                           company=company, title=title,
                           tag=tag_of(title, rules)))
        total = payload.get("totalAnnouncement") or 0
        if page * page_size >= total:
            break
        page += 1
        time.sleep(2.0)
    return out


def crawl(snapshot_dir: pathlib.Path, companies, rules, today: str,
          pause: float = 3.0) -> list[Ann]:
    """companies: parts.COMPANIES;rules: parts.TAG_RULES。"""
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    s = requests.Session()
    out = []
    for code, org_id, name, _desc in companies:
        anns = fetch_company(s, code, org_id, name, today, rules)
        print(f"[cninfo] {name}({code}) {len(anns)} 条")
        out.extend(anns)
        time.sleep(pause)
    stamp = today.replace("-", "")
    (snapshot_dir / f"cninfo_{stamp}.jsonl").write_text(
        "\n".join(json.dumps(a.__dict__, ensure_ascii=False) for a in out),
        encoding="utf-8")
    return out
