# Architecture

每块看板 = 同一套五层管线,自包含于 `boards/<name>/`:

```
tracker/*.py          抓取层:每源一个模块(cfmdram/hdd/lcsc…),内建
                      重试、熔断(验证码→冷却 N 天)、skip-unchanged
      ↓
data/<name>.db        SQLite:quotes/products/anchors/... 自动建表
      ↓
tracker/audit.py      审计门:硬 FAIL 规则(阶梯单调/双源价差/覆盖度/
                      陈旧度),FAIL 时退出码 1,交付前必跑
      ↓
dashboard/data.js     导出层:update 末尾把库内数据写成一个 js 变量
      ↓
dashboard/index.html  看板:纯静态本地页(echarts + lightweight-charts
                      已 vendor,零 CDN),python serve.py 起端口
      ↓
调度                  Windows schtasks / Linux cron —— 每日一次,足够
```

## 设计纪律(全板强制)

1. **锚点制**:免费源无历史接口的品类,用「带出处的新闻/财报锚点」补历史,
   绝不插值造曲线。
2. **口径分列**:现货/合约/渠道/挂牌/财报口径各自成序列,绝不连线混算。
3. **skip-unchanged**:源报价与库内最新值一致时不新增行(不制造虚假日更);
   副作用是 health 巡检按频率分档判定,见 `tracker/tz.py` 与 update.py 注释。
4. **熔断纪律**:验证码/反爬命中即冷却(1-2 天),绝不高频重试。
5. **机器呈现,人下结论**:结论横幅只陈述现象与状态灯,不输出交易建议。

## 板间关系

四板相互独立(各自 tracker/dashboard/db),共享的只有:
`shared/design-system.md`(视觉规范,内嵌复制)与同构的工程模式
(store/audit/serve 代码为 fork-and-tune 复制,有意不做成公共库——
各板品类差异大,公共抽象反而脆)。
