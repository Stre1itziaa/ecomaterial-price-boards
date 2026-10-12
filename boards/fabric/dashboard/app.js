/* 电子布价格趋势看板 —— 巨潮公告流 + 新闻考古锚点
   视觉语言沿用 mlcc/storage 版:深色+蓝强调、红涨绿跌配▲▼、tabular-nums。 */
(function () {
  const D = window.STORAGE_DATA;
  if (!D) return;

  const CAT = {
    "现货锚点": ["spot", "acat-spot"],
    "原厂调价": ["oem", "acat-oem"],
    "财报锚点": ["fin", "acat-fin"],
    "交期": ["lead", "acat-lead"],
  };
  // 口径 → (系列名, 轴, 单位)。左轴=元/米,右轴=元/吨。
  const CAL_AXIS = cal => (cal.includes("吨") ? "right" : "left");

  const anchors = D.anchors || [];
  const anns = D.announcements || [];
  const companies = D.companies || [];
  const b2b = D.b2b || { series: [], latest: [] };
  const weekly = D.weekly || [];
  const pending = D.pending || [];

  // 按锚点日期排序(字符串日期已规范)
  const aSorted = anchors.slice().sort((a, b) => a.date < b.date ? -1 : 1);
  const latestAnchor = aSorted.length ? aSorted[aSorted.length - 1].date : "—";
  // 锚点滞后(定价机制给的天花板:月调品 35 天超窗才视为失联,见 parts.PACE)
  const anchorLagDays = (() => {
    if (latestAnchor === "—") return null;
    const gen = D.generatedAt ? D.generatedAt.slice(0, 10) : new Date().toISOString().slice(0, 10);
    return Math.round((new Date(gen) - new Date(latestAnchor)) / 864e5);
  })();

  // ---- 口径系列(有主数值的锚点才入图)----
  // seriesKey = item|caliber;同一系列内同口径可连线,口径间绝不混算。
  const seriesMap = new Map();  // key -> {item, caliber, pts:[{date,v}], axis}
  for (const a of aSorted) {
    if (a.perUnit == null) continue;
    const key = a.item + "|" + a.caliber;
    if (!seriesMap.has(key))
      seriesMap.set(key, { item: a.item, caliber: a.caliber, axis: CAL_AXIS(a.caliber), pts: [] });
    seriesMap.get(key).pts.push({ date: a.date, v: a.perUnit });
  }
  const sKeys = [...seriesMap.keys()];
  const selected = new Set(sKeys);
  let focusKey = null, sortKey = null, sortDir = -1;

  // ---- 工具 ----
  const fmtNum = n => {
    if (n == null) return "-";
    if (n >= 1e4) return n.toLocaleString("zh-CN", { maximumFractionDigits: 0 });
    return String(Math.round(n * 100) / 100);
  };
  const fmtPct = v => (v > 0 ? "▲ +" : v < 0 ? "▼ " : "— ") + Math.abs(v).toFixed(1) + "%";
  const chgCls = v => v > 0 ? "up" : v < 0 ? "down" : "flat";

  // ---- 顶栏 ----
  const audit = D.audit || { pass: true, n: 0, items: [], at: "" };
  document.getElementById("asof").textContent = latestAnchor;
  document.getElementById("gen").textContent = D.generatedAt.replace("T", " ");
  if (anchorLagDays != null) {
    const el = document.getElementById("anchorLag");
    const over = anchorLagDays > 35;
    el.innerHTML = `<b style="${over ? "color:#dc2626" : ""}">最新锚点距今 ${anchorLagDays} 天${over ? "(超窗,检查候选层或补考古)" : ""}</b>`;
  }
  const lamp = document.getElementById("auditLamp");
  lamp.className = "lamp " + (audit.pass ? "ok" : "warn");
  document.getElementById("auditTxt").textContent =
    `审计 ${audit.pass ? "PASS" : "FAIL"} ${audit.n} 项`;
  lamp.onclick = () => { const d = document.getElementById("caliber"); d.open = true; d.scrollIntoView({ behavior: "smooth" }); };

  // 7628 年内涨幅(出厂口径首尾)
  const s7628 = seriesMap.get("7628 厚布|工厂出厂价");
  let ytd7628 = null;
  if (s7628 && s7628.pts.length >= 2) {
    const a = s7628.pts[0].v, b = s7628.pts[s7628.pts.length - 1].v;
    ytd7628 = (b / a - 1) * 100;
  }
  // G75 最新(元/吨)
  const g75 = aSorted.filter(a => a.item.startsWith("G75") && a.perUnit != null).pop();

  document.getElementById("caliberBody").innerHTML = `
    <b>B2B 挂牌价层(2026-09-24 起)</b>
    <li>阿里国际站(alibaba.com)匿名搜索,中国供应商<b>出口挂牌价</b>,免登录无个人信息;
        标题严格过滤(必含规格号+电子/PCB/CCL 词,排除涂层/铝箔/高硅/清洁布),
        聚合同单位挂牌取 P25/中位/P75——中位线为台阶信号,挂牌随涨价潮调价,
        非成交价,与锚点口径分列绝不混算。</li>
    <li>风控纪律:命中验证码即熔断冷却 48h 不再访问;多日被拦时用
        <code>python -m tracker.ali unlock</code> 人工拖一次滑块(免账号)写 anti-bot cookie。</li>
    <b>为什么 2026-09-24 之前没有连续价格曲线</b>
    <li>电子布是中间材料:零售分销渠道无 SKU(云汉实测 302),1688 强制登录+补个人信息,
        卓创/百川现货库为付费源——历史段只入库有公开出处的价格锚点,绝不插值造曲线。</li>
    <li>同品目不同口径(工厂出厂/经销商/成交/财报)分列展示,图中同口径才连线,
        跨口径对比请在锚点表核对口径列。</li>
    <b>周评方向层(周频,2026-09-26 起)</b>
    <li>卓创资讯(nonmetal.sci99.com)与百川盈孚(baiinfo.com)玻纤频道页免费直连,
        抓「玻璃纤维周评/周评:」标题全文——标题=方向语义(暂稳/提涨/供应紧),
        <b>无数字,不入价格连线</b>,与锚点/B2B 层分列;方向标签由标题语义词匹配,
        仅作导读,宁缺毋滥(匹配不到显示 —)。</li>
    <b>待核验候选层(搜狗微信,2026-10-11 起)</b>
    <li>免费世界的成交价数字以公众号转述卓创/百川周评的形态存在(周频)。扫描器每日
        发现带数字文章入候选表,<b>绝不自动入锚点</b>;人工核验后走 news_anchors 正常
        流程入库。风控对齐 ali.py:命中反爬即熔断 2 天。</li>
    <b>品类真实调价节奏(采样频率的上限由定价机制给出)</b>
    <li>7628/G75/薄布:原厂<b>月度调价</b>(巨石 9 月例调、10 月再调)+ 卓创周评周频;
        FR-4:<b>调价函事件驱动</b>(建滔年内 7 轮);特种布散单已从季度调改为月度。
        故锚点层月调品 35 天无新锚点即视为失联,而非日更中断。</li>
    <b>审计(${audit.pass ? "PASS" : "FAIL"} ${audit.n} 项 · ${audit.at.replace("T", " ")})</b>
    <li>${audit.items.map(c => `[${c.status}] ${c.name}——${c.note || ""}`).join("</li><li>")}</li>`;
  document.getElementById("foot").innerHTML =
    `· 数据源:巨潮资讯 cninfo 公告流(结构化) + 新闻考古锚点(每经/财联社/上证报/证券日报/卓创,全部带出处)` +
    ` + 阿里国际站 B2B 挂牌价(匿名,出口口径,日频台阶线)` +
    ` + 玻纤周评方向层(卓创/百川频道页免费标题,周频)。` +
    `每日运行 <code>python -m tracker.update</code>。` +
    `<div class="sibnav" style="margin-top:8px">姊妹板：<a href="http://127.0.0.1:8800/">总入口 8800</a> · <a href="http://127.0.0.1:8790/">存储 8790</a> · <a href="http://127.0.0.1:8792/">MLCC 8792</a> · <a href="http://127.0.0.1:8794/">信号 8794</a> ·（本板 8793）</div>`;

  // ---- KPI ----
  function renderKpis() {
    const nKey = anns.filter(a => a.tag !== "常规").length;
    const items = new Set(anchors.map(a => a.item));
    // B2B 7628 最新挂牌中位
    const s7628b2b = (b2b.series || []).find(s => s.kw.includes("7628"));
    const last7628 = s7628b2b && s7628b2b.pts.length ? s7628b2b.pts[s7628b2b.pts.length - 1] : null;
    const cards = [
      { l: "7628 厚布 年内涨幅(出厂口径)", v: ytd7628 != null ? `+${ytd7628.toFixed(0)}%` : "—",
        d: ytd7628 != null ? `约 4.6 → ${s7628.pts[s7628.pts.length - 1].v} 元/米(2026-01-01 起)` : "锚点不足" },
      { l: "7628 出口挂牌中位(阿里)", v: last7628 ? fmtNum(last7628.med) : "—",
        d: last7628 ? `${last7628.d} · ${last7628.n} 家挂牌 · ${s7628b2b.unit}` : "B2B 层累积中" },
      { l: "G75 电子纱最新(元/吨)", v: g75 ? fmtNum(g75.perUnit) : "—",
        d: g75 ? `${g75.date} · ${g75.value.length > 26 ? "成交均价口径" : g75.value}` : "无锚点" },
      { l: "锚点覆盖", v: anchors.length,
        d: `${items.size} 品目 · 距最新 ${anchorLagDays != null ? anchorLagDays + " 天" : "—"}(月调品超 35 天视为失联)` },
      { l: "公告流(四家合计)", v: fmtNum(anns.length > 0 ? companies.reduce((s, c) => s + c.n, 0) : 0),
        d: `重要打标 ${companies.reduce((s, c) => s + c.nKey, 0)} 条 · 展示最近 ${anns.length} 条` },
    ];
    document.getElementById("kpis").innerHTML = cards.map(c =>
      `<div class="kpi"><div class="l">${c.l}</div><div class="v">${c.v}</div>
       <div class="d">${c.d}</div></div>`).join("");
  }

  // ---- 最新锚点条 ----
  function renderMovers() {
    const box = document.getElementById("movers");
    const latest = aSorted.slice(-6).reverse();
    box.innerHTML = `<span class="mt">最新锚点</span>`
      + latest.map(a => {
        const [cls, catCls] = CAT[a.cat] || ["", ""];
        return `<span class="chip"><span class="acat ${catCls}">${a.cat}</span>
          <b>${a.item}</b>
          <span class="hint-small">${a.date}</span></span>`;
      }).join("")
      + `<span class="hint-small" style="margin-left:auto">完整数值见下方锚点时间线与明细表</span>`;
  }

  // ---- 锚点时间线 ----
  function renderAnchorLine() {
    const desc = aSorted.slice().reverse();
    document.getElementById("anchorLine").innerHTML = desc.map(a => {
      const [cls, catCls] = CAT[a.cat] || ["", ""];
      const g = a.grade || "";
      return `<div class="anchor ${cls}">
        <span class="ad">${a.date}</span><span class="acat ${catCls}">${a.cat}</span>
        ${g ? `<span class="grade grade-${g.length > 3 ? "low" : g === "一手公告" ? "hi" : "mid"}" title="来源分级=证据硬度">${g}</span>` : ""}
        <span class="atext"><b>${a.item}</b>:${a.value}${a.perUnit != null ? `(主数值 ${fmtNum(a.perUnit)})` : ""}</span>
        <span class="asrc">口径:${a.caliber} · ${a.source}</span>
      </div>`;
    }).join("") || `<div class="hint-small">无锚点</div>`;
  }

  // ---- 侧栏(口径系列选择)----
  const tree = document.getElementById("tree");
  function renderTree() {
    const groups = new Map();
    for (const key of sKeys) {
      const s = seriesMap.get(key);
      if (!groups.has(s.caliber)) groups.set(s.caliber, []);
      groups.get(s.caliber).push(key);
    }
    let html = "";
    for (const [cal, keys] of groups) {
      html += `<div class="grp"><div class="gtitle">${cal} <span>${keys.length}</span></div>`;
      for (const key of keys) {
        const s = seriesMap.get(key);
        html += `<label class="item"><input type="checkbox" data-key="${key}"
          ${selected.has(key) ? "checked" : ""}>
          <span class="nm" title="${s.item}">${s.item}
          <span class="hint-small">${s.pts.length}点</span></span></label>`;
      }
      html += `</div>`;
    }
    tree.innerHTML = html || `<div style="color:var(--muted);padding:10px">无有主数值的锚点</div>`;
  }
  tree.addEventListener("change", e => {
    const key = e.target.dataset.key;
    e.target.checked ? selected.add(key) : selected.delete(key);
    renderChart();
  });
  document.getElementById("all").onclick = () => { sKeys.forEach(k => selected.add(k)); renderTree(); renderChart(); };
  document.getElementById("none").onclick = () => { selected.clear(); renderTree(); renderChart(); };

  // ---- 主图 ----
  const chart = echarts.init(document.getElementById("chart"));
  const PALETTE = ["#1f77b4", "#d9822b", "#2ca02c", "#e377c2", "#9467bd", "#17becf",
    "#bcbd22", "#d62728", "#6acc64", "#8c613c", "#4878d0", "#dc7ec0"];
  function setFocus(key) { focusKey = focusKey === key ? null : key; renderChart(); }
  window.addEventListener("keydown", e => {
    if (e.key === "Escape" && focusKey != null) { focusKey = null; renderChart(); }
  });
  function renderChart() {
    const dates = aSorted.map(a => a.date);
    const slist = [];
    let colorIdx = 0;
    for (const key of sKeys) {
      const s = seriesMap.get(key);
      if (!selected.has(key)) continue;
      const dim = focusKey != null && key !== focusKey;
      const vals = s.pts.map(p => p.v);
      const rising = vals.length < 2 || vals[vals.length - 1] >= vals[0];
      slist.push({
        name: `${s.item}·${s.caliber}`,
        type: "line",
        yAxisIndex: s.axis === "right" ? 1 : 0,
        data: s.pts.map(p => [p.date, p.v]),
        symbol: "circle", symbolSize: 7, clip: false,
        lineStyle: { width: focusKey === key ? 2.6 : 1.6, type: s.pts.length >= 2 ? "solid" : undefined, opacity: dim ? .12 : 1 },
        itemStyle: { color: rising ? "#d62728" : "#1a7f4b", opacity: dim ? .12 : 1 },
        z: focusKey === key ? 10 : 3,
      });
      colorIdx++;
    }
    chart.setOption({
      backgroundColor: "transparent", color: PALETTE,
      tooltip: { trigger: "axis", confine: true, backgroundColor: "#ffffff",
        borderColor: "#b4b4ae", textStyle: { color: "#1a1a1a", fontSize: 12 } },
      legend: { type: "scroll", top: 2, textStyle: { fontSize: 11, color: "#555555" }, pageIconSize: 9 },
      grid: { left: 56, right: 62, top: 42, bottom: 40 },
      xAxis: { type: "time",
        min: dates.length ? +new Date(dates[0]) - 12 * 3600e3 : null,
        max: dates.length ? +new Date(dates[dates.length - 1]) + 12 * 3600e3 : null,
        axisLine: { lineStyle: { color: "#b4b4ae" } },
        axisLabel: { fontSize: 11, color: "#555555",
          formatter: v => echarts.time.format(v, "{yyyy}-{MM}", false) },
        splitLine: { show: false } },
      yAxis: [
        { type: "value", scale: true, name: "元/米",
          nameTextStyle: { color: "#555555", fontSize: 11 },
          axisLabel: { fontSize: 11, color: "#555555", formatter: v => "￥" + v },
          splitLine: { lineStyle: { color: "#ececea" } } },
        { type: "value", scale: true, name: "元/吨",
          nameTextStyle: { color: "#555555", fontSize: 11 },
          axisLabel: { fontSize: 11, color: "#555555", formatter: v => fmtNum(v) },
          splitLine: { show: false } },
      ],
      series: slist,
    }, { notMerge: true });
    document.getElementById("chartTip").textContent =
      (focusKey != null ? "聚焦一个口径系列(Esc 退出) · " : "")
      + `${selected.size}/${sKeys.length} 系列 · 同口径连线,跨口径断开`;
  }
  window.addEventListener("resize", () => chart.resize());

  // ---- B2B 挂牌价面板(阿里国际站,台阶线) ----
  const b2bChart = LightweightCharts.createChart(document.getElementById("b2bChart"), {
    width: document.getElementById("b2bChart").clientWidth,
    height: document.getElementById("b2bChart").clientHeight || 300,
    layout: { background: { type: "solid", color: "#ffffff" }, textColor: "#555555", fontSize: 11 },
    // 注意:此处的 grid 配置在 lightweight-charts 4.2.3 实测会导致 series 线
    // 不渲染(轴与标签正常、线消失,2026-10-11 复现并二分定位),故不配置。
    rightPriceScale: { borderColor: "#d5d5cf" },
    timeScale: { borderColor: "#d5d5cf", rightOffset: 2,
      tickMarkFormatter: t => { const s = String(t); return s.length >= 10 ? s.slice(5).replace("-", "/") : s; } },
    crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
    localization: { locale: "zh-CN" },
  });
  let b2bActive = null;
  let b2bBuilt = false;
  const b2bSeriesRefs = [];
  // 台阶补点:当前值延伸到下一点前一日(严格升序)。v4.2.3 实测 setData 含
  // 重复时间戳时 data() 正常但渲染层线/刻度全不画(2026-10-11 定位),禁止重复。
  function stepify(pts, key) {
    const out = [];
    const prevDay = d => {
      const t = new Date(d + "T00:00:00Z");
      t.setUTCDate(t.getUTCDate() - 1);
      return t.toISOString().slice(0, 10);
    };
    for (let i = 0; i < pts.length; i++) {
      out.push({ time: pts[i].d, value: pts[i][key] });
      if (i + 1 < pts.length) {
        const ext = prevDay(pts[i + 1].d);
        if (ext > pts[i].d) out.push({ time: ext, value: pts[i][key] });
      }
    }
    return out;
  }
  function renderB2bChips() {
    const box = document.getElementById("b2bChips");
    if (!b2b.series.length) {
      box.innerHTML = `<span class="hint-small">累积中</span>`;
      return;
    }
    box.innerHTML = b2b.series.map(s => {
      const last = s.pts[s.pts.length - 1];
      return `<button class="btn ${b2bActive === s.kw ? "on" : ""}" data-kw="${s.kw}">${s.kw} <span class="hint-small">n=${last.n}</span></button>`;
    }).join("");
    box.querySelectorAll("button").forEach(btn => btn.onclick = () => {
      b2bActive = btn.dataset.kw; renderB2bChips(); renderB2bChart();
    });
  }
  function renderB2bChart() {
    const tip = document.getElementById("b2bTip");
    if (!b2b.series.length) {
      b2bChart.applyOptions({ width: document.getElementById("b2bChart").clientWidth });
      tip.textContent = "等待首批数据";
      return;
    }
    const s = b2b.series.find(x => x.kw === b2bActive) || b2b.series[0];
    b2bActive = s.kw;
    b2bSeriesRefs.forEach(se => { try { b2bChart.removeSeries(se); } catch (e) {} });
    b2bSeriesRefs.length = 0;
    const med = b2bChart.addLineSeries({ color: "#d9822b", lineWidth: 2.4,
      priceLineVisible: false, lastValueVisible: true,
      crosshairMarkerRadius: 5 });
    med.setData(stepify(s.pts, "med"));
    const band = key => {
      const se = b2bChart.addLineSeries({ color: "#d9822b", lineWidth: 1,
        lineStyle: LightweightCharts.LineStyle.Dashed, priceLineVisible: false,
        lastValueVisible: false, crosshairMarkerVisible: false });
      se.setData(stepify(s.pts, key));
      b2bSeriesRefs.push(se);
      return se;
    };
    b2bSeriesRefs.push(med);
    band("p75"); band("p25");
    chart.tipData = s;   // tooltip 取数
    const last = s.pts[s.pts.length - 1];
    tip.textContent = `最新 ${last.d} · 中位 ${last.med} ${s.unit} · ${last.n} 家挂牌 · 出口挂牌口径(非成交价)`;
    // v4.2.3 实测:多日数据下 auto visible range 会塌缩到最后一天,图面只剩
    // 最后值标签(2026-10-11)。渲染后强制全览修复。
    b2bChart.timeScale().fitContent();
  }
  b2bChart.subscribeCrosshairMove(param => {
    const s = chart.tipData; if (!s || !param.time || !param.seriesData.size) return;
    const hit = s.pts.find(p => p.d === param.time);
    if (!hit) return;
    tip2.textContent = `${hit.d} · 中位 ${hit.med} ${s.unit} · P25~P75: ${hit.p25} ~ ${hit.p75} · 挂牌家数: ${hit.n}`;
  });
  const tip2 = document.getElementById("b2bTip");
  window.addEventListener("resize", () => b2bChart.applyOptions({ width: document.getElementById("b2bChart").clientWidth }));

  // ---- 周评方向层(卓创/百川,周频) ----
  function renderWeekly() {
    const tip = document.getElementById("wkTip");
    if (!weekly.length) {
      tip.textContent = "等待首批数据(每日任务自动抓取)";
      document.getElementById("wkBody").innerHTML =
        `<tr><td colspan="4" class="hint-small" style="padding:14px">周评层尚无数据</td></tr>`;
      return;
    }
    const DIR = { "涨": ["up", "▲"], "跌": ["down", "▼"], "稳": ["flat", "—"] };
    document.getElementById("wkBody").innerHTML = weekly.map(w => {
      const [cls, sym] = DIR[w.dir] || ["flat", "·"];
      return `<tr>
        <td class="datecell">${w.date}</td>
        <td>${w.src}</td>
        <td class="wrap"><a href="${w.url}" target="_blank" rel="noopener">${w.title}</a></td>
        <td><span class="chg ${cls}">${sym} ${w.dir}</span></td></tr>`;
    }).join("");
    tip.textContent = `最新 ${weekly[0].date} · 展示最近 ${weekly.length} 期(入库全量在库)`;
  }

  // ---- 锚点明细表 ----
  function renderTable() {
    document.querySelectorAll("#snap th").forEach(th => {
      const arr = th.querySelector(".arr"); if (arr) arr.remove();
      if (sortKey && th.dataset.k === sortKey)
        th.insertAdjacentHTML("beforeend", `<span class="arr">${sortDir > 0 ? "▲" : "▼"}</span>`);
    });
    let rows = aSorted.map(a => ({ ...a }));
    if (sortKey) rows.sort((a, b) => {
      const va = a[sortKey], vb = b[sortKey];
      if (va == null) return 1; if (vb == null) return -1;
      return (typeof va === "number" ? va - vb : String(va).localeCompare(String(vb))) * sortDir;
    });
    document.getElementById("snapBody").innerHTML = rows.map(a => {
      const [, catCls] = CAT[a.cat] || ["", ""];
      const g = a.grade || "";
      return `<tr class="prow" data-key="${a.item}|${a.caliber}" title="${a.value.replace(/"/g, "&quot;")}">
        <td class="datecell">${a.date}</td>
        <td><span class="acat ${catCls}">${a.cat}</span></td>
        <td><b>${a.item}</b></td>
        <td class="wrap">${a.value}</td>
        <td class="num">${a.perUnit != null ? fmtNum(a.perUnit) : `<span class="hint-small">—</span>`}</td>
        <td><span class="cal">${a.caliber}</span></td>
        <td>${g ? `<span class="grade grade-${g.length > 3 ? "low" : g === "一手公告" ? "hi" : "mid"}">${g}</span>` : ""}</td>
        <td class="wrap hint-small">${a.source}</td></tr>`;
    }).join("");
  }
  document.getElementById("snapBody").addEventListener("click", e => {
    const tr = e.target.closest("tr.prow");
    if (tr) setFocus(tr.dataset.key);
  });
  document.querySelectorAll("#snap th").forEach(th => {
    if (!th.dataset.k) return;
    th.addEventListener("click", () => {
      const k = th.dataset.k;
      if (sortKey !== k) { sortKey = k; sortDir = -1; }
      else if (sortDir === -1) sortDir = 1; else sortKey = null;
      renderTable();
    });
  });

  // ---- 公告流 ----
  const TAGS = ["全部", "重要-调价", "重要-经营数据", "重要-定期报告", "重要-扩产", "常规"];
  let tagFilter = "全部", companyFilter = "全部";
  function renderAnnFilters() {
    const box = document.getElementById("annFilters");
    box.innerHTML = TAGS.map(t =>
      `<button class="btn ${tagFilter === t ? "on" : ""}" data-tag="${t}">${t}</button>`).join("")
      + `<select id="coSel" class="btn" style="padding:4px 6px">
          <option>全部</option>${companies.map(c =>
            `<option ${companyFilter === c.name ? "selected" : ""}>${c.name}</option>`).join("")}</select>`;
    box.querySelectorAll("button").forEach(b => b.onclick = () => { tagFilter = b.dataset.tag; renderAnnFilters(); renderAnns(); });
    box.querySelector("#coSel").onchange = e => { companyFilter = e.target.value; renderAnns(); };
  }
  function renderAnns() {
    const rows = anns.filter(a =>
      (tagFilter === "全部" || a.tag === tagFilter) &&
      (companyFilter === "全部" || a.company === companyFilter));
    document.getElementById("annBody").innerHTML = rows.map(a => {
      const cls = "tag-" + a.tag;
      return `<tr>
        <td class="datecell">${a.date}</td>
        <td>${a.company}</td>
        <td class="wrap">${a.title}</td>
        <td><span class="tag ${cls}">${a.tag}</span></td>
        <td><a href="${a.url}" target="_blank" rel="noopener">PDF</a></td></tr>`;
    }).join("") || `<tr><td colspan="5" class="hint-small" style="padding:14px">无匹配公告</td></tr>`;
    document.getElementById("annHint").textContent =
      `${rows.length} 条入库展示(全量在库 ${companies.reduce((s, c) => s + c.n, 0)},data.js 保留最近 400)`;
  }

  // ---- CSV ----
  document.getElementById("csvBtn").onclick = () => {
    const lines = ["date,cat,item,value,per_unit,caliber,source"];
    for (const a of aSorted) lines.push(
      [a.date, a.cat, `"${a.item}"`, `"${a.value.replace(/"/g, '""')}"`,
       a.perUnit ?? "", `"${a.caliber}"`, `"${a.source.replace(/"/g, '""')}"`].join(","));
    lines.push(`# 口径分列绝不混算;主数值为锚点折算中值,单位随口径(元/米 或 元/吨)`);
    lines.push(`# 审计:${audit.pass ? "PASS" : "FAIL"} ${audit.n} 项 @ ${audit.at}`);
    const blob = new Blob(["\uFEFF" + lines.join("\n")], { type: "text/csv;charset=utf-8" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `fabric_anchors_${latestAnchor.replace(/-/g, "")}.csv`;
    a.click(); URL.revokeObjectURL(a.href);
  };

  // ---- 待核验锚点候选(搜狗微信扫描层) ----
  function renderPending() {
    const tip = document.getElementById("pendTip");
    const body = document.getElementById("pendBody");
    if (!pending.length) {
      tip.textContent = "尚无候选(每日任务自动扫描,或扫描层熔断中)";
      body.innerHTML = `<tr><td colspan="6" class="hint-small" style="padding:14px">候选队列为空</td></tr>`;
      return;
    }
    const stCls = s => s === "已采纳" ? "up" : s === "已否决" ? "down" : "flat";
    body.innerHTML = pending.map(p => `<tr>
        <td class="datecell">${p.pubDate || p.foundAt.slice(0, 10)}</td>
        <td>${p.account || "—"}</td>
        <td class="wrap"><a href="${p.url.startsWith("sogou:") ? "#" : p.url}" target="_blank" rel="noopener">${p.title}</a></td>
        <td class="hint-small">${p.items.join("、") || "—"}</td>
        <td class="wrap hint-small">${p.nums.slice(0, 3).join(" ┋ ") || "—"}</td>
        <td><span class="chg ${stCls(p.status)}">${p.status}</span></td></tr>`).join("");
    const nWait = pending.filter(p => p.status === "待核验").length;
    tip.textContent = `候选 ${pending.length} 条,待人工核验 ${nWait} 条(机器不定价,采纳后入锚点层)`;
  }

  renderKpis(); renderMovers(); renderAnchorLine(); renderTree(); renderTable(); renderAnnFilters(); renderAnns(); renderChart(); renderB2bChips(); renderB2bChart(); renderWeekly(); renderPending();
})();
