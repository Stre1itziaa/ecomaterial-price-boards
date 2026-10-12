# Data sources

All sources are public pages, no login, no API keys. Collected data stays on
your machine (git-ignored) and remains the property of the providers.

| Source | Boards | What | Cadence | Free tier notes |
|---|---|---|---|---|
| CFM 闪存市场 (chinaflashmarket.com) | storage | DDR/NAND/eMMC/LPDDR/SSD 渠道与现货报价、指数 | daily/weekly | 免费页含全品类频道 |
| TrendForce 中文站 (trendforce.cn) | storage, fabric | DRAM/NAND 现货与合约、Module 周价、玻纤布 | daily/weekly | 免费页 2026-09-29 起部分板块收缩(见 storage README) |
| DRAMeXchange 英文首页 | storage | 救援腿:TF 停更板块的现货均价 | daily | 免费首页表格 |
| ServerPartDeals | storage | HDD/SSD 渠道零售(二手/翻新) | daily | products.json 公开 |
| LCSC 立创商城 | mlcc | MLCC 分销现货价+库存阶梯 | daily | Playwright 渲染 |
| ICKey 云汉芯城 | mlcc | MLCC 交叉校验 | weekly | 搜索页 JSON-LD |
| Mouser 中国站 | mlcc | 缺货料号参照价 | daily | DataDome 概率通过 |
| 阿里国际站 | fabric | 电子布出口挂牌 | daily | 匿名搜索;验证码熔断 |
| 巨潮资讯 cninfo | fabric, signal | 公司公告流(调价/经营数据) | daily | 公开接口 |
| 新浪美股 | signal | AI 硬件贝塔股行情+52 周高 | daily | 免费接口 |
| SEC EDGAR XBRL / 8-K | signal | hyperscaler capex/OCF、DC 收入 | quarterly | 匿名机读 |

## Redistribution notice

Collected price data is for **personal research only** and is git-ignored.
Manual ledger CSVs (csp_ledger / ccl_ledger) are the author's original
research notes and are distributed. This project is not affiliated with any
data provider.
