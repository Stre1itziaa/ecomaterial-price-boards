# mlcc-price-tracker MLCC 价格趋势看板

跟踪 MLCC（多层陶瓷电容）代表性料号的分销现货价与库存，多源每日累积，
本地 ECharts 看板。与 storage-price-tracker 同一套管线架构（抓取→SQLite→审计→看板→schtasks）。

## 快速使用

```bash
python -m tracker.update          # 全量：立创（日）+ Mouser（日）+ 云汉（仅周一交叉）
python -m tracker.update --ickey-only   # 手动跑云汉交叉校验
python -m tracker.audit           # 数据审计（阶梯单调性/双源对照等）
python serve.py                   # 看板 http://127.0.0.1:8792
```

依赖：`requests`、`playwright`（`playwright install chromium` 已就绪）

## 数据源（均为公开零售现货，无需登录）

| 源 | 频率 | 通道 | 数据 | 口径 |
|---|---|---|---|---|
| 立创商城 szlcsc.com | 日频主力 | Playwright headless（页内 __NEXT_DATA__） | 完整价格阶梯 + 精确库存 | 分销现货零售，起订档单价 |
| 云汉芯城 ickey.cn | 周一交叉校验 | 纯 requests（搜索页 JSON-LD） | 起订档单价 + 库存 + MOQ | 上市分销商现货 |
| Mouser 中国站 | 日频（限缺货料号） | Playwright headless（等 DataDome 挑战重载，10-25s） | 单件挂牌价 + 库存 + 在途状态 | 单件价≠起订档，**仅缺货料号参照，不与上两源比价** |

- **源分工（2026-10-05 定）**：ICKey 限流退化（17 料号日频只回 3 条、无独家覆盖）降为周一
  交叉校验；LCSC 为日频主力；Mouser 只补国内双源同时缺货且其确有报价的料号
  （现 1 只：CGA3E2X7R1H104K080AA）。
- 同料号 ICKey×LCSC 对照 = 审计锚点（两家定价策略不同，价差列出供核对，>50% WARN）。
- 搜索是模糊的（同系列会混入），解析按料号精确匹配；**无精确现货的料号不入库——
  缺货本身是涨价周期信号**（如 CL10A106KO8NNNC 0603 10μF 双源均无精确现货）。

## 料号清单（tracker/parts.py）

16 个候选，覆盖品牌（三星电机/村田/国巨/TDK/风华）× 容值段（高容 ≥10μF / 中容 / 低容 /
车规）× 封装（0603/0805/1206）。验证后三源合计 19 条序列在库（退役号历史保留不导出）。

**换号记录**：GRM188R61E105MA12D（0603 1μF 25V X5R **±20%**）→ **GRM188R61E105KA12D**
（同系列同规格，容差 ±10%），2026-10-05 切换。原因：±20% M 系建号停产（LCSC 缺货自
2026-09 底、mouser.cn 无报价详情页仅剩相似品）；KA12D 为家族唯一在架活号（实测库存
8.7 万颗）。旧号 products.active=0 退役，历史保留、导出隐藏。

## 审计（交付前必跑）

```bash
python -m tracker.audit    # 规则审计：阶梯单调性/双源价差/覆盖度
python -m tracker.verify   # 全量核算：每条库内行对回原始快照重放比对（解析→入库→导出全链路）
```

verify 核对面：立创全部快照逐日重解析逐行比对（含"快照无货而库内有行"反向检查）、
云汉/Mouser JSONL 回放比对、退役号不得有切换日后新行、同日跨源价差 INFO。任何
MISMATCH 退出码 1。

## 已知边界（诚实声明）

- **无历史回填**：分销现货页只显示当前价，趋势自 2026-09-23 起每日累积（同存储版 TF 免费页）；
- **零售口径**：起订档单价 ≠ 原厂 OEM 合约价（后者无免费公开源），涨价周期里零售价
  先于合约价反应，方向一致、弹性更大；
- 华强北电子元器件指数（东财页）当前页面数据脚本损坏（`cn/.js` 404、无 canvas），
  待其修复后接入作指数层；
- 立创连续抓取有风控：每料号新开 context + 9-12s 随机间隔可稳定通过（实测 14/16）；
- **Mouser DataDome 通过是概率性的**：headless 挑战页 10-25s 自动解开重载，未解开则
  换 context 重试（最多 3 次）；连续大流量抓取会整段 403，故本腿只挂 1 只料号；
- **GRM188R61E105MA12D 已于 2026-10-05 退役换号**（mouser.cn 无报价、LCSC 缺货，判停产），
  由 GRM188R61E105KA12D 接替；其余已知边界同上。

## 定时（schtasks 已挂载）

```bat
schtasks /create /tn "mlcc-price-daily" /sc daily /st 20:10 ^
  /tr "cmd /c cd /d <repo>/mlcc && python -m tracker.update >> data/schtasks.log 2>&1" /f
```

（与存储版 18:40 错峰；漏跑之日无法回补，靠每日任务保证连续。）

## 历史数据边界与新闻考古层

- **料号级同口径历史无法回填**：立创/云汉只显示当前价，无历史接口；
  Wayback/archive.ph 本机与 WebFetch 服务端双路径均不可达（2026-09-23 实测）；
  东财华强北指数页数据脚本损坏（`cn/.js` 404），指数层待其修复后接入。
- **替代：新闻考古锚点层**（`tracker/news_anchors.py`）：2026 涨价周期中公开报道里
  带日期的价格数字（如村田 1206-476：6 月 ~300 → 650-720 → 725-755 元/2000颗），
  看板顶部时间线展示，每条带口径与出处。**口径（华强北渠道现货/原厂合约）与本板
  日更序列（分销零售起订档）不同，分开展示绝不混算。**
- 新闻明星料 GRM31CE70J476ME01L（1206 47μF）已加入每日追踪，与锚点衔接。

## 数据结构

- `data/mlcc.db`：products(source, part, brand, seg) + quotes(date, price, stock, moq, ladder)
- `dashboard/data.js`：update 自动导出
- `data/snapshots/`：原始快照（lcsc HTML / ickey JSONL）
