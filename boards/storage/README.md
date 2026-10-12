# storage-price-tracker 存储价格趋势看板

跟踪存储行业核心品类价格行情（DRAM / NAND / SSD / 内存条 / eMMC / **Nearline HDD**），
双数据源 + 真实历史回填 + 每日累积，本地 ECharts 看板展示走势。

## HDD 线（2026-09-23 并入）

- **数据源**：ServerPartDeals（Shopify 店，products.json 公开）——企业盘/NAS 盘 USD 零售挂牌价，
  **New 与 Refurbished/Recertified 分档入库**，近线盘 ≥14TB、NAS 盘 ≥16TB。状态判定以标题后缀为准
  （New 卡标题不带状态词，以 HDD/Hard Drive 结尾），接口（SAS/SATA）入名避免混 SKU。
- **强审计**：同型同日 New 价 ≥ 翻新/再制造价（档位单调，倒挂=FAIL，同 MLCC 阶梯单调性位置）。
- **中国零售源 2026-09-23 实测全灭**（京东搜索登录墙 / p.3.cn 000 / Newegg 人机墙 / 慢慢买 000+404 /
  ZOL 404），单源如实标注；SPD 实测盘中实时调价（同日两抓 HC590 26TB Recertified $799→$5443），
  恰是本板要捕捉的波动。
- **事件锚点（README 级，人工维护）**：希捷 FY26Q4（2026-07-28）营收 $3.6B +48%、毛利率 >52%、
  EPS +121%，nearline 锁量至 2029 且含增量定价承诺；**证伪监控 = QLC 大碟 SSD（122TB+）在超大规模
  客户的试点/订单公告**——替代不需要复刻十年制造壁垒。
- 看板 HDD 家族自动分组（HDD 企业盘 / HDD NAS盘），update 默认抓取，`--no-hdd` 可跳过。

## 快速使用

```bash
# 每日更新（TrendForce 2 页，约 5 秒）
python -m tracker.update

# 每周建议（同时全量抓 CFM 闪存市场，约 3 分钟，延长/刷新历史序列）
python -m tracker.update --with-cfm

# 交付审计（数据真实性核查，FAIL 则数据不可信）
python -m tracker.audit

# 看板（二选一）
python serve.py                # http://127.0.0.1:8790
# 或直接双击 dashboard/index.html（纯静态，无需服务）
```

依赖：`pip install -r requirements.txt`（requests + beautifulsoup4）

## 数据源（全部为公开页、无需登录）

### CFM 闪存市场（chinaflashmarket.com，深圳市闪存市场资讯有限公司）

| 内容 | 历史深度 | 说明 |
|---|---|---|
| 产品价格序列（约 100 个产品） | 现货类约 65 个交易日（日度收盘/开盘/日低点），部分产品回溯到 2025-10；周价类约 13 周 | 详情页公开图表数据（`sampleData`）回填 |
| NAND 指数 / DRAM 指数 | 2026-02 至今，周度 | 品类页"价格指数"公开图表 |

### TrendForce 集邦咨询（trendforce.cn/price）

DRAM/NAND/Wafer/存储卡现货价（日更 ~18:10）、合约价（月更）、SSD 市场价（周更）等
10 板块。**免费页无历史接口，该源自 2026-09-18 起每日累积**；原始 HTML 全部存档
`data/snapshots/`，可 `--reparse` 重放。

### DRAMeXchange 英文站首页（dramexchange.com，2026-10-05 接入的救援腿）

TrendForce 中文免费页 2026-08-31 起合约板块停更、09-21 起多个现货小节停更
（SLC/MLC/GDDR/晶圆/MicroSD/品牌 SSD——页面自身停更，非解析故障）。英文首页免费表
仍在更新同一批品种（同一家、同口径），纯 HTML 无反爬、无需登录。救援规则：

- 只对回库内已有 TrendForce 产品（归一化名精确匹配），不新建产品、序列无缝续接；
- 英文页不带数据日期，语义=最新 session，落库用抓取日；
- **high/low/avg 与库内最新一行完全一致时跳过——不制造虚假日更**；
- change_pct 置空（skip-unchanged 语义下相邻库行非页面相邻 session，不污染涨跌幅自洽审计）。

### 序列退役政策（products.active=0，历史保留、仅导出隐藏）

- TrendForce 合约价全族：免费页 2026-08-31 停更且免费渠道无替代（宏观面由 CFM
  行业价+指数承接）；
- SPD 下架 SKU：WD HC580 22TB SAS Refurb / HC590 26TB SATA New（店家目录移除；
  goHDD 实测最高 20TB 替不了，若需 22TB+ 零售参照需另找源）；
- CFM 现货(日) 家族（晶圆/存储卡/U盘）freq 按**交付节奏**记 weekly（密集历史来自
  首次详情图回填，此后仅 cfm-weekly 每周续行）。

## 数据真实性审计

```bash
python -m tracker.audit    # 规则审计：内部自洽 + 外部锚点（FAIL 禁交付）
python -m tracker.verify   # 全量核算：TF/DXI-EN/SPD/CFM 最近快照全量重放，逐行比对库值
```

audit 核查：

1. 完整性：均价为正、日期合法无未来值、来源标注齐全；
2. 源内自洽：TrendForce 涨跌幅与前后均价互推一致（如 9/17 DDR5 16Gb 55.233
   (+0.73%) 回推前值 54.833，与搜索引擎缓存的更早页面值完全一致；512Gb TLC
   9/17 隐含前值 20.708 与 DRAMeXchange 首页显示值一致）；
3. 锚点对照：用户快讯截图（9/16 512Gb TLC 报 20.083 美元为 TrendForce 新闻口径，
   与免费页"盘平均"口径存在正常差异，两序列不混用、均标注来源）。

verify 核对面（2026-10-05 新增）：TF 中文页最近 3 天快照全量重解析逐行比对、
DXI 英文首页回放（含 skip-unchanged 规则反向检查：快照有新值而库内无当日行即漏写）、
SPD products.json 回放（涨跌幅按库内前值回填规则重算）、CFM 最近一批品类+详情快照
回放（约 2700 行）、同族跨源偏离 INFO（不同评估方只报不判）。任何 MISMATCH 退出码 1。

任何 FAIL 即数据不可信，禁止交付。

## 核心白名单

看板只展示 `tracker/update.py: CORE_SPECS` 里的核心产品
（双指数、DRAM 颗粒现货 3、NAND 晶圆 3、内存条 4、SSD 3）与全部 HDD 行，
且仅限 `products.active=1`（退役政策见上）。
采集端仍全量入库，改白名单后重新导出即可：

```bash
python -c "from tracker import update, store; update.export_dashboard(store.connect(update.DB))"
```

## 数据结构

- `data/storage.db`（SQLite）
  - `products`：source（TrendForce/CFM）/ family / section / name / unit / freq
  - `quotes`：date + product_id 主键，high / low / avg / change_pct / extra(JSON)
- `dashboard/data.js`：由 update 自动导出

## 定时（已挂载，2026-09-23 起）

```bat
schtasks /create /tn "storage-price-daily" /sc daily /st 18:40 ^
  /tr "cmd /c cd /d <repo>/storage && python -m tracker.update >> data/schtasks.log 2>&1" /f
schtasks /create /tn "storage-price-cfm-weekly" /sc weekly /d FRI /st 19:30 ^
  /tr "cmd /c cd /d <repo>/storage && python -m tracker.update >> data/schtasks.log 2>&1" /f
```

- `storage-price-daily`：每天 18:40（TF 现货 ~18:10 更新后）抓 TF 两页；
- `storage-price-cfm-weekly`：每周五 19:30 全量爬 CFM（约 115 请求）；
- 运行日志：`data/schtasks.log`；免费页只展示最新一期，**漏跑一天的中间日无法回补**，
  靠每日任务保证连续性。

## 源收缩记录(2026-10-12 诊断)

TrendForce 中文免费页 2026-09-29 后结构性收缩:Module 现货板块更新日期停在 09-28
(DDR5/DDR4 UDIMM 价格横盘无新值)、LPDDR现货/eMMC现货/eMMC/UFS合约等板块退化为
无数值 chips(parse 按设计跳过)、渠道 SSD/内存条周价同期断更——11 条 weekly 序列
WARN 属**源停更**,非抓取故障。已建 DXEN(dramexchange 英文页)救援腿覆盖部分
(DDR5 RDIMM/GDDR6 正常);Samsung 990 Pro 周价断更 11 个工作日仍在观察。
巡检阈值 2026-10-12 起按**工作日**计并排除当日未到更新时点(此前周末误伤 9 条 daily)。

## 已知边界

- TrendForce 免费页 LPDDR/Mobile DRAM/eMMC/Wafer 合约板块仅产品名无数值（会员交互层）。
- CFM 部分品类报价以人民币计（U盘/闪存卡渠道价），看板已标注单位；两个来源口径
  各自独立，不做跨源换算。
- CFM 品类页历史图表数据（登录后）更深，免费层以上述深度为限。

## 2026-10-11 全面 review 修复记录

逐模块截图走查 + 管线体检后修复:

1. **走势图时间轴塌缩**(lightweight-charts 4.2.3 auto visible range 丢头部区段,
   18 天数据只显示 ~10 天):`renderChart()` 末尾补 `timeScale().fitContent()`;
2. **阶梯区间列恒空**:app.js 硬编码 `ladderBar(null,null,·)`,现接通 quotes 的
   high/low(首档/末档价),立创阶梯条正常显示;
3. **audit 覆盖数踩 SQLite 列作用域陷阱**:`part IN (SELECT part FROM quotes)`
   中子查询列静默回溯外层使条件恒真,数成全表 DISTINCT part——改 JOIN;
   note 措辞同步改准(latest=min(两源最新日)是**对照基线日**非最新日);
4. **verify 同日多跑 MISMATCH**:库存比对加 ±3% 容差(10-05 三跑实测最大漂移
   2.1%),价格/moq/阶梯维持零容差;292 项一致 0 异常恢复为可用门禁;
5. **KPI 平盘日语义**:"最大涨幅 0.00%"改为无上涨时报最大跌幅;
6. **锚点补录 9→12 条**:AI 高容原厂 15-35%(央视财经 09-20)、三星电机 Q4
   再涨 10-30%(证券日报 09-21)、三环集团 +30-80% 自 10/1 生效(同文);
7. **新增心跳** `data/heartbeat.json`(update 末尾,待接 butler 白名单);
8. **新增搜狗微信候选层** `tracker/wxscan.py`(MLCC 关键词组,pending_anchors
   表,机器只发现不定价;CLI `--review`/`--mark`;`--no-wx` 跳过);
9. `data.js` 变量名 STORAGE_DATA→MLCC_DATA(消除与存储版重名);
10. `update --export-only` 子命令(跳抓取仅重导出,离线调试用)。

存储板 8790 同日排查:直给原始点+多刻度正常+各序列起点符合业务,未见同款病灶,不改动。
