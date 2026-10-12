"""抓取 TrendForce 中文站价格页，原始 HTML 存档到 data/snapshots/。

免费页无历史接口，快照即原始备份：解析器日后改进时可对快照重解析。
"""
from . import tz
import datetime as dt
import pathlib
import time

import requests

PAGES = {
    "dram": "https://www.trendforce.cn/price/dram/dram_spot",
    "flash": "https://www.trendforce.cn/price/flash/flash_spot",
}

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")


def fetch_all(snapshot_dir: pathlib.Path, retries: int = 3, pause: float = 2.0) -> dict[str, str]:
    """返回 {page_key: html}，并把原始 HTML 落盘到 snapshot_dir/YYYYMMDD_key.html。"""
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    today = tz.now().strftime("%Y%m%d")
    headers = {"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"}
    out = {}
    for key, url in PAGES.items():
        last_err = None
        for attempt in range(1, retries + 1):
            try:
                r = requests.get(url, headers=headers, timeout=30)
                r.raise_for_status()
                if len(r.content) < 50_000:
                    raise RuntimeError(f"页面过小({len(r.content)}B)，疑似反爬拦截")
                out[key] = r.text
                break
            except Exception as e:  # noqa: BLE001 - 记录后重试
                last_err = e
                time.sleep(pause * attempt)
        else:
            raise RuntimeError(f"抓取 {url} 失败(重试{retries}次): {last_err}")
        path = snapshot_dir / f"{today}_{key}.html"
        path.write_text(out[key], encoding="utf-8")
        time.sleep(pause)
    return out
