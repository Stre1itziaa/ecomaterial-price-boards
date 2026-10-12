# ai-signal-tracker AI 需求与退出信号看板

**2026-09-24 改版定案**:连接器企业公告流判死下线——按涨价监控的目的衡量,
它不产出价格、不预警周期(公告滞后+互动平台只发利好)、其价值点(224G 量产、
H1 业绩)已静态收录进锚点层,每日抓取管线纯属冗余;schtasks 已删,cninfo 501 条
公告仅存档。本板收窄为两件事:

1. **一线 · 需求源头**:海外 CSP capex 台账(筛子 9,全清单唯一共享贝塔,拐头=全品类退出);
2. **二线 · ABF 证据与退出信号**:高盛 2031/缺口序列(双转述)、机制(DIGITIMES),
   加上全清单共用的退出信号清单(LTA 锁价翻转 / HDD QLC 替代 / 电源侧铜 2027 / 自愈型排除)。

## 快速使用

```bash
python -m tracker.update    # 锚点 seed + CSP 台账 + 导出(秒级,无网络请求)
python -m tracker.audit     # 审计(11 项,量级/日期/去重全硬 FAIL)
python serve.py             # http://127.0.0.1:8794
```

依赖:`requests`(仅历史公告抓取用过,已停用)

## 需求一线 · 海外 CSP capex(筛子 9 落地,2026-09-24 补建)

- **定位**:全清单九品类共享的唯一边际买单人=海外 CSP 资本开支,capex 拐头=所有品类同时退出——
  它是一线预警;连接器/ABF 公告流是二线(供给侧兑现验证);价格锚点是三线。
- **数据**:`data/csp_ledger.csv` 人工台账(8 条起步):四家 2026 合计指引年内三次上修
  $700B(CNBC 2 月)→ $725B +77% YoY(Yahoo 6 月)→ $760B(Statista 7 月)→ 共识 $800B(8 月);
  MSFT 2026 至多 $185B;资金质量情绪信号(AI 营收能否匹配 capex 的辩论)单列一条=筛子 9 主观测点。
- **节奏**:10 月底四家 Q3 财报=下一个人工更新点(capex 实际+2027 首份指引),到期须追加台账。
- **机器路径实测**:Wind 全球财务插件 3/4 家返回 null、1 家口径存疑——不可用,退 L2 台账起步;
  SEC 10-Q 现金流解析留待后续(见 backlog)。
- **看板**:8794 顶部"一线·需求源头"区块;审计含台账条数与出处两项。

## 二线 · 需求实现(SEC 8-K DC 收入,2026-09-25 上线)

- **序列**:`tracker/dc.py` 直拉三家 8-K EX-99.1 press release,regex 提取首段明文,
  2025-02 至 2026-09 共 21 期(NVDA 7 / AMD 7 / AVGO 7)。**全清单第一条 L1 机读序列**
  (SEC 原文,零转述);YoY 直接存原文百分比,不自行重算。
- **口径**:NVDA=Data Center(market platform)/ AMD=Data Center(reportable segment)/
  AVGO=AI semiconductor(管理层口径,各期句式五变,含 FY25Q4 仅披露 +74% 无绝对值→
  value NULL 落库,审计单列)。
- **最新读数**:NVDA $89.0B(+117%)· AMD $6.7B(+107%)· AVGO $16.7B——
  capex(意图)→DC 收入(实现)的传导有 L1 证据。
- **维护节奏**:每季财报后(2/5/8/9/12 月初)在 `dc.py: DC_URLS` 追加 3 行 URL 再跑
  `python -m tracker.update`(与 CSP 台账同节奏);URL 由 sec-search 全文检索定位。

## 两域定义

| 域 | 逻辑 | 退出信号 |
|---|---|---|
| 高速连接器(112G/224G) | 筛子 2+7 独立成立:交期 30 周+、速率认证壁垒;与铜价传导的通用连接器是两个市场 | 交期回落 <20 周;224G 产能释放(华丰/鼎通量产公告是进程信号) |
| ABF 载板 | 「设备垄断+已知到期日」:压膜机 95% 单厂份额+交期 2031、缺口 14%→34%→51%(高盛,双转述) | **LTA 从锁量不锁价翻成锁价=见顶第一信号**;日历退出点 2031;AI capex 拐头 |

## 数据源

- **锚点 13 条**(ABF 研判 9 + 退出日历 4,源=`tracker/news_anchors.py`,seed 进库):
  全部带出处;口径白名单 9 项;研报转述(L2.5)载荷数字须双独立转述
  (2031 交期与缺口序列已双转述:财联社/新浪+富途;95% 垄断者**定名**仍单源,待高盛原文)。
- **CSP 台账 8 条**(`data/csp_ledger.csv`,basis 四类口径:event 事件/period 期间/state 状态/calendar 日历):
  日历行必须在未来、其余行不得在未来,审计强制。
- cninfo 公告流管线已停:鼎通/华丰/兆龙/深南/兴森五家 501 条公告仅存档于 signal.db,页面不再展示。

## 审计(11 项,全部硬 FAIL,无 WARN 摆设)

CSP 台账 ≥6 / 台账条目带出处 / 台账含下一数据点日历 / **台账日期合理性(basis 与时点自洽)** /
锚点无未来日期 / 锚点出处口径数值非空 / 口径白名单 / ABF 锚点 ≥5 / 退出信号 ≥3 /
**锚点无近重复(正文前 40 字唯一)** / 连接器域已清出(防回流)。
量级检查曾用 WARN 档导致绿灯对失明免疫(2026-09-24 评审发现),已全部改硬 FAIL。

## 已知边界

- 无连续价格序列(连接器/载板均无免费零售价),证据形态=锚点+公告流——同 fabric 纪律,不造曲线;
- PDF 正文不机器解析,公告中的价格/交期数字人工核验后才进锚点层;
- 待办:高盛原文定名 95% 压膜机垄断者;L5 两轮调价找第二转述;欣兴/Ibiden 无 A 股,
  台股公告需 TWSE 通道(出口被拦,同 fabric 已知问题)。

## 维护节奏(无自动任务)

- 本板无 schtasks:capex 台账人工季度维护(10 月底四家 Q3 财报为下一点);
  ABF 锚点在有新研报证据时手工追加 `tracker/news_anchors.py` 后跑 update。
- 五板体系自动任务余四条:存储 18:40 / MLCC 20:10 / 电子布 20:40 / 电力每月 8 日。

## 数据结构

- `data/signal.db`:anchors + announcements(五家,url 主键)+ fetch_log
- `dashboard/data.js`:update 自动导出(锚点 13 + cspLedger 8 + 审计内嵌;window.SIGNAL_DATA)
- `data/snapshots/`:cninfo 每日 JSONL

## 2026-10-11 改版:AI 需求监控面板(v4 UI + 信号层)

受《AI 资本定价权的第二次迁移》(公众号「贝叶斯之美」2026-10-11)启发重构。
核心思想:市场对退出的定价先于产业事实——看板检测对象从「产业拐点」换为
「定价结构的四个二阶量」。

- **三层监控**(shadcn/tremor/dub 三标杆视觉规格,全白卡+状态徽章+线色):
  - A 定价行为(日频自动,45%):A1 硬件贝塔篮子回撤(WDC/SMH/NVDA/MU/AMD,
    新浪美股)、A2 软件/半导体比价 120 日分位、A3 利好弹性衰减(待人工事件表);
  - B 增长质量(季频半自动,40%):B1 capex 二阶导(高盛台账)、B2 capex/OCF
    (SEC XBRL 机读,注意 AMZN capex 记在 PaymentsToAcquireProductiveAssets)、
    B3 AI 盈利贡献集中度(台账)、B4 DC 收入 YoY(dc.py);
  - C 结构现象(人工,15%):C1 合同成色/C2 边际买家分化/C3 金融化计数。
- **结论横幅红绿灯先行**:开屏即报「哪里有问题」;单层触发=黄、跨层共振=红,
  行动由人决定;全绿时明示「三层均无异常」。
- **首个真实读数(2026-10-11)即红色**:跨层共振——A1 WDC 距 52 周高 -50.3%
  (价格先杀实证)+ B2 AMZN capex/OCF 119%(单季资本开支超经营现金流);
  capex 增速二阶导 +94→+50→+17。与文章论点互证。
- 数据源全部实测:新浪美股(免费匿名,实时+3572 根日 K)、SEC XBRL
  companyconcept/frames;Yahoo(403)/Stooq(JS 壳)/腾讯美股(覆盖随缘)已排除。
- UI 调研:外部三标杆(dub/tremor/shadcn dashboard-01)+ 8802 交叉;设计规格=
  全白卡+状态只进徽章/线色/数字色+ECharts 渐变面积;对比稿 mockup_v2/v3/v4 留档。
- 信号判定机器不输出退出概率;阈值触发状态灯,行动由人决定(候选层同纪律)。

## 数据更新节奏(2026-10-12 起)

| 数据 | 频率 | 更新方式 | 自动化状态 |
|---|---|---|---|
| A1/A2 定价行为(新浪美股) | 美股每交易日 | **schtasks `ai-signal-morning` 每日 06:00**(北京时间,美股收盘后),已配 StartWhenAvailable 开机补跑 | ✅ 已挂 |
| B2 capex/OCF(SEC XBRL) | 季频(财报后自动出新帧) | 随 06:00 任务顺带刷新(量小,常驻拉最新帧) | ✅ 自动 |
| B4 DC 收入(SEC 8-K) | 季频 | **✅ 2026-10-12 起全自动**:dc.py discover() 经 EDGAR submissions 自动发现 items 含 2.02 的新 8-K,候选 htm 交 parse 试解(解析不出自动跳过,零误入库);同 ticker+披露日去重 | ✅ 自动 |
| B1/B3 capex 预测与集中度 | 研报不定期 | 人工改 tracker/signals.py 顶部常量(CAPEX_GROWTH/AI_EARNINGS_SHARE) | ⚠️ 人工 |
| C 层(C1 成色/C2 分化/C3 金融化) | 月/事件 | 人工台账(v2 建自动观测) | ⚠️ 人工 |
| 锚点(ABF/退出日历) | 事件 | 人工 news_anchors.py 后跑 update | ⚠️ 人工 |
| 看板 data.js | 随更新 | signals 刷新后 update --export-only 秒级重导出 | ✅ |

- 心跳=data/signal_state.json(mtime);**待接 butler 白名单**;
- schtasks 日志=data/signals_morning.log;verdict 已去 emoji(GBK 控制台编码坑,2026-10-12 修)。
