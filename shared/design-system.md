# 本地看板体系 · 全站统一设计系统 v1(方案一报表风)

> 2026-09-28 定稿。真源文档;各板以「内嵌复制」方式引用 §6 标准片段(单文件零 CDN 纪律不变)。
> 上游依据:8802 design_spec_v2(已验收)+ 两路代码级调研(dub 24.8k★ / maybe 54.3k★ / shadcn dashboard-01 / Carbon / AntD / Primer / Geist / Polaris,均实访核验)。
> 全站适用:8800 hub + 8790/8792/8793/8794/8795/8796/8797/8798/8802。学术衬线风(booktabs/衬线标题/uppercase 分区)**自本日起仅约束导出图表与报告插图,不约束看板 UI**。

## 1. 设计总纲

浅色报表感数据终端:底色差分层 + indigo 单强调色 + 无衬线 + 等宽数字 + 徽章化状态 + 卡片流。数据色可精致渐变,UI 骨架无彩;每板保留一个 accent 色相用于身份识别,浓度压低。

## 2. Token(唯一真源,与 8802 v2 一致)

```
--bg:#fafafa        页面底(zinc-50)      --card:#ffffff
--line:#e5e5e5      边框(neutral-200)    --line-2:#f4f4f5   行线/次分隔
--txt:#18181b       主文字(zinc-900)     --sub:#737373      次文字(neutral-500)
--sub-dim:rgba(24,24,27,.45)  脚注/口径(AntD colorTextDescription 同档)
--blue:#4f46e5      主色(indigo-600)     --blue-dk:#4338ca  --blue-bg:#eef2ff  --blue-bg2:#f5f7ff
--red:#dc2626 / --green:#059669  涨跌(A股红涨绿跌,只给文字上色,底色用中性阶)
--amber:#d97706     派生线/警示
--r-card:12px  --r-btn:8px  --r-pill:999px
--s-card:0 1px 2px rgba(0,0,0,.04)
--s-hover:0 1px 2px rgba(0,0,0,.06), 0 4px 12px rgba(0,0,0,.08)
--ease:cubic-bezier(0.215,0.61,0.355,1)(easeOut)  --t-fast:.12s  --t-mid:.18s
字体:正文 -apple-system,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif
      数字 .num / td.num { font-variant-numeric:tabular-nums }  长数字可加 ui-monospace 栈
```

## 3. 组件规范

### 3.1 顶栏(每板统一,含 8802 换掉深蓝)
52-56px 白底 + 1px 底边框;左=板名(15px/600)+分类小胶囊(11px 灰边);右=数据时点(12px --sub)+「⌂ 总入口」链接(12px,hover indigo)。不玻璃、不深色。

### 3.2 页头三段式(顶栏之下)
标题(18-20px/600)+ 一句副标题(13px --sub,含数据时点/口径)+ 右侧动作区(筛选/按钮)。

### 3.3 卡片
白底 + --line 边 + 12px 圆角 + --s-card;hover 换 --s-hover + 边框 #d4d4d8,**不动 transform**(dub:全程零 shadow,我们保留极轻阴影作辅助;分层主力=底色差)。卡头需要分隔时用 `border-bottom:1px solid var(--line)` + 左右 padding(dub 手法),不用色条。
过渡 `transition: box-shadow var(--t-mid) var(--ease), border-color var(--t-mid) var(--ease)`。

### 3.4 KPI 卡三段式(maybe/tremor)
灰标签(11px --sub)→ 大数字(22-26px/700 tabular-nums,PC 着色)→ (可选 sparkline/徽章)→ 口径小字(11px --sub)。徽章=胶囊浅底。

### 3.5 表格(Carbon/AntD 工艺)
- 表头:12.5px/600 --sub、底 #fafafa(AntD)、1px 底边框;数值列表头同右对齐。
- 行:全表一档密度(行高 32-36px,padding 6-7px 10px);只横线无竖线;行线 --line-2。
- hover:底 --row-hover(#f4f4f5)且**文字从 --sub 升为 --txt**(Carbon 信息层级细节,仅对含次灰文字的表)。
- 空单元格一律 "—";超宽列 ellipsis+title;斑马纹禁用(行 hover 已够)。
- 数值列右对齐 + tabular-nums;负号完整渲染。

### 3.6 状态徽章(Primer 三件套)
浅底 + 同族深字 + 圆点(色盲安全:徽章必带圆点或文字)。全站四档:live 绿 / ok 蓝 / warn 琥珀 / dead 灰(与 8802 §4.3 同款)。图例与徽章同一 token。

### 3.7 布局
主区 gap 单轴堆叠(shadcn):块间距一律 14px,不用 margin 混用。**分区小标题 sentence case、不加 uppercase/大字距**(五系统无一使用,现 hub/学术风待改):12.5px/600 --sub。
空态(Carbon 五件套):正向标题+下一步说明,居中,等高占位防跳动。加载:已知布局用骨架/占位,>1s 配文案。

### 3.8 时间与元信息
数据时点放页头副标题;卡片级元信息放卡右上/底部 11px --sub-dim;等宽渲染。30 天内可相对时间+title 绝对时间(本期可选)。

### 3.9 图表(lightweight-charts)
8802 §4.2 全站适用:主次线规则、面积渐变主线、对照线 50% 透明细线、去轴线、网格 #f1f3f7、水印。各板图表迁移时照抄。

## 4. accent 系(每板身份色,浓度压低)
hub 卡片与板内小元素可用:8790 #1f77b4 / 8792 #d9822b / 8793 #0d9488 / 8794 #7c3aed / 8795 #dc2626 / 8796 #0e7490 / 8797 #8c564b / 8798 #059669 / 8802 #4f46e5(=主色)。用途限:状态点、hover 边、"打开"链接 hover;禁大面积色条/色块。

## 5. 迁移规则(逐板)
1. `:root` 换 §6 token 块;删除各板自造灰阶/衬线字体声明。
2. 顶栏/页头按 §3.1/3.2 重排;加「⌂ 总入口」链接。
3. 表格套 §3.5;状态文字套 §3.6 徽章;KPI/大数字套 §3.4。
4. 数据逻辑/接口/审计断言零改动;有审计门的板(8796/8797/8790)改后必须重跑 audit。
5. 每板改完浏览器截图留档。

### 迁移状态(2026-09-28)
| 板 | 状态 | 方式 | 审计 |
|---|---|---|---|
| 8800 hub | ✅ 重做(状态带+徽章卡) | 整页重写 | - |
| 8802 | ✅ v2+顶栏浅色化 | 手工 | v2 验收 10 项过 |
| 8796 | ✅ 手工(顶栏+token+去衬线/uppercase) | 手工 | audit_check 5 门 PASS |
| 8795 | ✅ 手工 | 手工 | - |
| 8790 | ✅ 手工(顺手修 html color-scheme:dark 假暗色 bug) | 手工 | tracker.audit 14 项 PASS |
| 8792/8793/8794/8798 | ✅ 批量(migrate_v3.py:token块+覆盖层+顶栏) | 脚本 | 各板 auditLamp 正常显示 |
| 8797 | ⏸ 待单独一轮 | **index.html 是 scenario_fan.py 每日重建生成,须改生成器模板** | 19 断言审计门,动前必读 SCORING_RULES |

**批量法说明**:migrate_v3.py 用「token 块替换 + `</style>` 前追加 v3 覆盖层(后写覆盖 editorial v2)+ `<body>` 后注入顶栏」三步,不删不改任何既有规则,幂等(有标记位)。新增板子直接复用。

## 6. 标准内嵌片段(复制到各板 `<style>` 顶部)

```css
:root{
  --bg:#fafafa; --card:#fff; --line:#e5e5e5; --line-2:#f4f4f5;
  --txt:#18181b; --sub:#737373; --sub-dim:rgba(24,24,27,.45);
  --blue:#4f46e5; --blue-dk:#4338ca; --blue-bg:#eef2ff; --blue-bg2:#f5f7ff;
  --red:#dc2626; --green:#059669; --amber:#d97706;
  --row-hover:#f4f4f5;
  --r-card:12px; --r-btn:8px; --r-pill:999px;
  --s-card:0 1px 2px rgba(0,0,0,.04);
  --s-hover:0 1px 2px rgba(0,0,0,.06), 0 4px 12px rgba(0,0,0,.08);
  --ease:cubic-bezier(.215,.61,.355,1); --t-fast:.12s; --t-mid:.18s;
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--txt);
  font-family:-apple-system,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;font-size:13px}
.num,.tabnum{font-variant-numeric:tabular-nums}
.card{background:var(--card);border:1px solid var(--line);border-radius:var(--r-card);
  box-shadow:var(--s-card);transition:box-shadow var(--t-mid) var(--ease),border-color var(--t-mid) var(--ease)}
.card:hover{box-shadow:var(--s-hover);border-color:#d4d4d8}
table{border-collapse:collapse}
th{font-size:12.5px;font-weight:600;color:var(--sub);background:#fafafa;text-align:left;padding:7px 10px;border-bottom:1px solid var(--line)}
td{padding:6px 10px;border-bottom:1px solid var(--line-2);font-variant-numeric:tabular-nums}
tbody tr:hover td{background:var(--row-hover)}
.num{ text-align:right }
.bdg{display:inline-flex;align-items:center;gap:5px;padding:2px 9px;border-radius:var(--r-pill);font-size:11px;white-space:nowrap}
.bdg i{width:6px;height:6px;border-radius:50%;flex-shrink:0}
.bdg.live{background:#ecfdf5;color:#047857}.bdg.live i{background:#10b981}
.bdg.ok{background:var(--blue-bg);color:var(--blue-dk)}.bdg.ok i{background:var(--blue)}
.bdg.warn{background:#fffbeb;color:#b45309}.bdg.warn i{background:#f59e0b}
.bdg.dead{background:#f4f4f5;color:#71717a}.bdg.dead i{background:#a1a1aa}
a,button{transition:color var(--t-fast) var(--ease),background var(--t-fast) var(--ease),border-color var(--t-fast) var(--ease)}
```

## 7. 与旧定案的关系
- 推翻全站"学术论文风"在看板 UI 的适用(白底保留、衬线/uppercase/booktabs 退出 UI 层);导出图表与论文插图继续学术风。
- 8802 design_spec_v2 是本系统在 8802 的实例;冲突处(顶栏深蓝)以本系统 §3.1 为准修齐。
