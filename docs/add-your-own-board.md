# Add your own board

一块板 = 一个自包含目录。最小步骤:

1. `boards/<your-market>/tracker/`:拷任意现成板的 `store.py` + `audit.py`
   作骨架;每源一个抓取模块(参考 `cfm.py` 的熔断/重试/快照存档模式)。
2. `boards/<your-market>/tracker/parts.py`:定义你的监控对象清单(SKU/品类)。
3. `boards/<your-market>/dashboard/`:拷 MLCC 板的 index.html/app.js 作骨架,
   替换解析段;结论横幅照 8790 的 `#conclBanner` 段落加。
4. `serve.py`:拷任意板的,改 PORT。
5. 审计规则按你的品类改(阶梯单调?双源价差?覆盖度?)——审计是这块板的
   质量宪法,宁缺勿滥。

建议先跑通「单源单序列」最小闭环,再扩多源交叉。
