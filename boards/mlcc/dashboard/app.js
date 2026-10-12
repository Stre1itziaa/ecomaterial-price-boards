/* MLCC 价格趋势看板 —— 三源（立创 LCSC 日频主力 / 云汉 ICKey 周一交叉 / Mouser 缺货参照）
   视觉语言沿用存储版：深色+蓝强调、红涨绿跌配▲▼、tabular-nums。 */
(function () {
  const D = window.MLCC_DATA;
  if (!D) return;

  const SRC_LABEL = { ICKey: "云汉芯城", LCSC: "立创商城", Mouser: "Mouser 中国站" };
  const SRC_TAG = { ICKey: "云汉", LCSC: "立创", Mouser: "Mouser" };
  const SEG_ORDER = ["高容", "中容", "低容", "车规"];

  // 数据整形：quotes = [pid, date, avg(price), chg, high, low, stock, moq]
  const byId = new Map(D.products.map(p => [p.id, p]));
  const series = new Map();   // pid -> [{date, price, stock, moq, high, low}]
  for (const [pid, date, price, , high, low, stock, moq] of D.quotes) {
    if (!series.has(pid)) series.set(pid, []);
    series.get(pid).push({ date, price, stock, moq, high, low });
  }
  for (const arr of series.values()) arr.sort((a, b) => a.date < b.date ? -1 : 1);
  const last = new Map();
  for (const [pid, arr] of series) last.set(pid, arr[arr.length - 1]);

  // 涨跌幅由相邻两期推算（首日为 null）
  const chgOf = new Map();    // pid -> 最新涨跌幅
  for (const [pid, arr] of series) {
    if (arr.length < 2) continue;
    const a = arr[arr.length - 2].price, b = arr[arr.length - 1].price;
    chgOf.set(pid, (b / a - 1) * 100);
  }

  const allDates = [...new Set(D.quotes.map(q => q[1]))].sort();
  const latestDate = allDates[allDates.length - 1];

  // 分组：seg -> [products]
  const groups = new Map();
  for (const p of D.products) {
    if (!groups.has(p.seg)) groups.set(p.seg, []);
    groups.get(p.seg).push(p);
  }
  const groupKeys = [...groups.keys()].sort(
    (a, b) => SEG_ORDER.indexOf(a) - SEG_ORDER.indexOf(b));

  // 默认精选而非全选:19 条序列价差 13 倍,线性轴全选必成面条。
  // 规则=双源重合的立创腿(日频对照) ∪ 当期异动(|chg|≥1%) ∪ Mouser 缺货参照腿;
  // 全选按钮仍在左侧,深挖自取。
  const _ickeyParts = new Set(D.products.filter(p => p.source === "ICKey").map(p => p.part));
  const _defaultSel = new Set(D.products
    .filter(p => p.active !== 0 && (
      (p.source === "LCSC" && _ickeyParts.has(p.part)) ||
      (p.source === "Mouser") ||
      (() => { const arr = series.get(p.id); if (!arr || arr.length < 2) return false;
        return Math.abs(arr[arr.length-1].price / arr[arr.length-2].price - 1) >= 0.01; })()
    )).map(p => p.id));
  const selected = _defaultSel;
  let query = "", sortKey = null, sortDir = -1, focusPid = null;

  // ---- 工具 ----
  const fmtNum = n => {
    if (n == null) return "-";
    const a = Math.abs(n);
    if (a >= 1e8) return (n / 1e8).toFixed(2) + "亿";
    if (a >= 1e4) return (n / 1e4).toFixed(1) + "万";
    if (a >= 1000) return n.toLocaleString("zh-CN", { maximumFractionDigits: 0 });
    return String(Math.round(n * 10000) / 10000);
  };
  const fmtPct = v => (v > 0 ? "▲ +" : v < 0 ? "▼ " : "— ") + Math.abs(v).toFixed(2) + "%";
  const chgCls = v => v > 0 ? "up" : v < 0 ? "down" : "flat";

  function sparkSVG(pts, w = 100, h = 24) {
    if (!pts || pts.length < 2) return `<span class="hint-small">首日</span>`;
    const vs = pts.map(p => p.price);
    const mn = Math.min(...vs), mx = Math.max(...vs), span = (mx - mn) || 1;
    const step = w / (vs.length - 1);
    const xy = vs.map((v, i) => [(i * step).toFixed(1), (h - 3 - (v - mn) / span * (h - 6)).toFixed(1)]);
    const [lx, ly] = xy[xy.length - 1];
    const col = vs[vs.length - 1] > vs[0] ? "var(--up)" : vs[vs.length - 1] < vs[0] ? "var(--down)" : "var(--flat)";
    return `<svg width="${w}" height="${h}"><polyline points="${xy.map(p => p.join(',')).join(' ')}"
      fill="none" stroke="${col}" stroke-width="1.4"/><circle cx="${lx}" cy="${ly}" r="2" fill="${col}"/></svg>`;
  }

  // ---- 顶栏 ----
  const audit = D.audit || { pass: true, n: 0, items: [], at: "" };
  document.getElementById("asof").textContent = latestDate;
  document.getElementById("gen").textContent = D.generatedAt.replace("T", " ");
  const lamp = document.getElementById("auditLamp");
  lamp.className = "lamp " + (audit.pass ? "ok" : "warn");
  document.getElementById("auditTxt").textContent =
    `审计 ${audit.pass ? "PASS" : "FAIL"} ${audit.n} 项`;
  lamp.onclick = () => { const d = document.getElementById("caliber"); d.open = true; d.scrollIntoView({ behavior: "smooth" }); };

  document.getElementById("caliberBody").innerHTML = `
    <b>价格口径</b>
    <li>起订档单价（￥/颗，CNY）：立创=1+ 档，云汉=最小起订量档。两家定价策略不同，
        同料号价差属正常（审计第 5 项列出最大价差供核对）。</li>
    <li>库存为抓取时点数（立创精确值 / 云汉页面值），库存骤降+价格上行=紧缺信号。</li>
    <li>搜索为模糊匹配，解析按料号精确匹配；无精确现货的料号不入库（缺货本身是信号，
        见"双源无货"清单）。</li>
    <b>审计（${audit.pass ? "PASS" : "FAIL"} ${audit.n} 项 · ${audit.at.replace("T", " ")}）</b>
    <li>${audit.items.map(c => `[${c.status}] ${c.name}——${c.note || ""}`).join("</li><li>")}</li>
    <b>背景</b>
    <li>2026 高容 MLCC 涨价周期：AI 服务器需求爆发，交期 10→20 周，原厂调价 15-35%
        （TrendForce/证券时报报道）。本板自 ${allDates[0]} 起累积，趋势随时间显现。</li>`;
  document.getElementById("foot").innerHTML =
    `· 数据源：云汉芯城 ickey.cn（JSON-LD）+ 立创商城 szlcsc.com（__NEXT_DATA__），均为公开零售现货口径。` +
    `每日运行 <code>python -m tracker.update</code>（约 5 分钟）。华强北指数（东财页）当前页面损坏，待修复后接入。` +
    `<div class="sibnav" style="margin-top:8px">姊妹板：<a href="http://127.0.0.1:8800/">总入口 8800</a> · <a href="http://127.0.0.1:8790/">存储 8790</a> · <a href="http://127.0.0.1:8793/">电子布 8793</a> · <a href="http://127.0.0.1:8794/">信号 8794</a> ·（本板 8792）</div>`;

  // ---- KPI(现象统计,v4:label→大数字→注→spark;状态=徽章+线色,卡永远白底)----
  function spark4(id, data, color) {
    const el = document.getElementById(id);
    if (!el) return;
    const c = echarts.init(el, null, {height: 32});
    c.setOption({grid:{left:0,right:0,top:3,bottom:0},
      xAxis:{type:'category',show:false,data:data.map((_,i)=>i)},
      yAxis:{type:'value',show:false,scale:true},
      series:[{type:'line',data,smooth:.3,symbol:'none',lineStyle:{width:1.6,color},
        areaStyle:{color:new echarts.graphic.LinearGradient(0,0,0,1,
          [{offset:0,color:color+'38'},{offset:1,color:color+'00'}])}}]});
  }
  function renderKpis() {
    const parts = D.products;
    const priced = parts.filter(p => last.has(p.id));
    const chgs = [...chgOf.entries()].filter(([pid]) => last.has(pid));
    // 双源价差:基线日(=云汉最新日,周一交叉点)两源同料号对比 —— MLCC 板灵魂指标
    const baseDate = (() => {
      let m = null;
      for (const p of parts) {
        if (p.source !== 'ICKey') continue;
        for (const r of (series.get(p.id) || [])) if (!m || r.date > m) m = r.date;
      }
      return m;
    })();
    const priceAt = (pid, date) => { const r = (series.get(pid)||[]).find(x => x.date === date); return r ? r.price : null; };
    const gaps = [];
    const ickeyPrice = {};
    for (const p of parts) if (p.source === 'ICKey') {
      const v = priceAt(p.id, baseDate);
      if (v != null) ickeyPrice[p.part] = v;
    }
    for (const p of parts) if (p.source === 'LCSC' && ickeyPrice[p.part] != null) {
      const v = priceAt(p.id, baseDate);
      if (v != null) gaps.push({part: p.part, pct: Math.abs(v / ickeyPrice[p.part] - 1) * 100});
    }
    gaps.sort((a, b) => b.pct - a.pct);
    // 最大日涨跌(绝对值最大者;异动明细唯一出处=下方异动条)
    let mover = null;
    for (const [pid, v] of chgs)
      if (mover == null || Math.abs(v) > Math.abs(mover.v)) mover = {p: byId.get(pid), v};
    const nUp = chgs.filter(([, v]) => v > 0).length, nDn = chgs.filter(([, v]) => v < 0).length;
    const lowStock = priced.filter(p => { const r = last.get(p.id); return r.stock > 0 && r.stock < 10000; });
    const oos = priced.filter(p => last.get(p.id).stock === 0);

    const cards = [
      mover ? { l: `最大日涨跌`, v: `<span style="color:${mover.v > 0 ? 'var(--up)' : mover.v < 0 ? 'var(--dn)' : 'var(--sub)'}">${mover.v > 0 ? '+' : ''}${mover.v.toFixed(2)}</span><small>%</small>`,
        d: `${mover.p.part} · ${mover.p.brand}${last.get(mover.p.id).stock === 0 ? ' · <b style="color:#b91c1c">双源无货</b>' : ''}`,
        spark: {id: 'sp_max', pid: mover.p.id, color: mover.v < 0 ? '#10b981' : '#ef4444'},
        badge: `<span class="bdg4 ${Math.abs(mover.v) >= 10 ? 'al' : 'wa'}"><i></i>${Math.abs(mover.v) >= 10 ? '异动' : '波动'}</span>` } : null,
      { l: `双源价差(基线 ${baseDate || '—'})`, v: gaps.length ? `<span class="num">${gaps[0].pct.toFixed(0)}</span><small>%</small>` : '—',
        d: gaps.length
          ? gaps.map(g => `<div class="gap-row"><span class="pn">${g.part}</span><div class="bar"><i style="width:${Math.min(100, g.pct * 2)}%;background:${g.pct > 40 ? '#ef4444' : g.pct > 20 ? '#f59e0b' : '#d9822b'}"></i></div><span class="gv num">${g.pct.toFixed(0)}%</span></div>`).join('')
          : '暂无双源对照', spark: null,
        badge: `<span class="bdg4 ${gaps.some(g => g.pct > 50) ? 'al' : 'ok'}"><i></i>${gaps.some(g => g.pct > 50) ? '超阈' : '<50% 全过'}</span>` },
      { l: `低库存预警(<1 万颗)`, v: lowStock.length ? `<span class="num">${fmtNum(Math.min(...lowStock.map(p => last.get(p.id).stock)))}</span><small> 颗</small>` : '0',
        d: lowStock.length
          ? '最紧 ' + lowStock.slice().sort((a,b)=>last.get(a.id).stock-last.get(b.id).stock)[0].part + ' · ' +
            lowStock.slice(0, 2).map(p => `${p.part} ${fmtNum(last.get(p.id).stock)}`).join(' · ')
            + (oos.length ? ` · <b style="color:#b91c1c">${oos.length} 只无货</b>` : '')
            + '<br><span style="color:#92400e">阈值 1 万为初始值,待分位数校准</span>'
          : '无', spark: null,
        badge: `<span class="bdg4 ${lowStock.length > 3 ? 'wa' : 'nt'}"><i></i>${lowStock.length} 只</span>` },
      { l: `18 天异动回顾`, v: `<span class="num">${nUp + nDn}</span><small> 次</small>`,
        d: `${nUp} 涨 · ${nDn} 跌 · 其余横盘 — 零售端先行持稳;分布统计待累积 60 天后启用`,
        spark: null, badge: `<span class="bdg4 nt"><i></i>17 可比</span>` },
    ].filter(Boolean);
    document.getElementById("kpis").innerHTML = cards.map((c, i) =>
      `<div class="kpi4"><div class="l"><span>${c.l}</span><span class="sp"></span>${c.badge || ''}</div>
       <div class="v">${c.v}</div><div class="d">${c.d}</div>
       ${c.spark ? `<div class="spark" id="${c.spark.id}"></div>` : `<div style="height:8px"></div>`}</div>`).join("");
    if (mover) {
      const arr = (series.get(mover.p.id) || []).map(r => r.price);
      if (arr.length > 1) spark4('sp_max', arr, mover.v < 0 ? '#10b981' : '#ef4444');
    }
  }

  // ---- 异动条（涨价周期看板：列出双源重合料号价差 + 库存骤变）----
  function renderMovers() {
    const box = document.getElementById("movers");
    const items = [];
    for (const pid of chgOf.keys()) {
      const p = byId.get(pid);
      if (!p || !last.has(pid)) continue;
      items.push({ p, r: last.get(pid), chg: chgOf.get(pid) });
    }
    if (!items.length) {
      box.innerHTML = `<span class="mt">首日累积</span><span class="hint-small">涨跌自第二个数据日起可计算</span>`;
      return;
    }
    items.sort((a, b) => Math.abs(b.chg) - Math.abs(a.chg));
    box.innerHTML = `<span class="mt">最新涨跌</span>`
      + items.slice(0, 6).map(i =>
        `<span class="chip" data-pid="${i.p.id}">${SRC_TAG[i.p.source]}·${i.p.part}
         <span class="chg ${chgCls(i.chg)}">${fmtPct(i.chg)}</span>
         <span class="hint-small">库存 ${fmtNum(i.r.stock)}</span></span>`).join("")
      + `<span class="hint-small" style="margin-left:auto">点击条目聚焦图表</span>`;
    box.querySelectorAll(".chip").forEach(c =>
      c.addEventListener("click", () => setFocus(+c.dataset.pid)));
  }

  // ---- 侧栏 ----
  const tree = document.getElementById("tree");
  function renderTree() {
    let html = "";
    for (const k of groupKeys) {
      const items = groups.get(k)
        .filter(p => !query || p.part.toLowerCase().includes(query) || p.brand.toLowerCase().includes(query))
        .sort((a, b) => a.part.localeCompare(b.part));
      if (!items.length) continue;
      html += `<div class="grp"><div class="gtitle">${k} <span>${items.length}</span></div>`;
      for (const p of items) {
        const c = chgOf.get(p.id);
        html += `<label class="item"><input type="checkbox" data-pid="${p.id}"
          ${selected.has(p.id) ? "checked" : ""}>
          <span class="nm" title="${p.part} · ${SRC_LABEL[p.source]} · ${p.descr || ''}">${SRC_TAG[p.source]}·${p.part}</span>
          ${c != null ? `<span class="badge ${chgCls(c)}">${c > 0 ? "▲" : "▼"}${Math.abs(c).toFixed(1)}%</span>` : ""}</label>`;
      }
      html += `</div>`;
    }
    tree.innerHTML = html || `<div style="color:var(--muted);padding:10px">无匹配</div>`;
  }
  tree.addEventListener("change", e => {
    const pid = +e.target.dataset.pid;
    e.target.checked ? selected.add(pid) : selected.delete(pid);
    renderChart();
  });
  document.getElementById("filter").addEventListener("input", e => {
    query = e.target.value.trim().toLowerCase(); renderTree();
  });
  document.getElementById("all").onclick = () => { D.products.forEach(p => selected.add(p.id)); renderTree(); renderChart(); };
  document.getElementById("none").onclick = () => { selected.clear(); renderTree(); renderChart(); };

  // ---- 对数轴切换 ----
  let logView = false;

  // ---- 图表(lightweight-charts + 自研增强包) ----
  // 实例损坏自愈:lightweight-charts 4.2.3 实测存在「canvas 在但渲染面空白」的
  // 实例状态损坏(2026-10-12 复现),故 renderChart 每次销毁重建实例。
  const chartEl = document.getElementById("chart");
  let chart = null;
  const CHART_OPTS = () => ({
    width: chartEl.clientWidth, height: chartEl.clientHeight || 380,
    layout: { background: { type: "solid", color: "#ffffff" }, textColor: "#555555", fontSize: 11,
      fontFamily: "-apple-system,'Segoe UI','PingFang SC','Microsoft YaHei',sans-serif" },
    grid: { vertLines: { color: "#f0f0eb" }, horzLines: { color: "#f0f0eb" } },
    rightPriceScale: { borderColor: "#d5d5cf", mode: logView
      ? LightweightCharts.PriceScaleMode.Logarithmic
      : LightweightCharts.PriceScaleMode.Normal },
    timeScale: { borderColor: "#d5d5cf", rightOffset: 2,
      tickMarkFormatter: t => { const s = String(t); return s.length >= 10 ? s.slice(5).replace("-", "/") : s; } },
    crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
    localization: { locale: "zh-CN" },
  });
  function ensureChart() {
    if (chart) return chart;
    chart = LightweightCharts.createChart(chartEl, CHART_OPTS());
    document.getElementById("logBtn").onclick = () => {
      logView = !logView;
      document.getElementById("logBtn").classList.toggle("on", logView);
      chart.applyOptions({ rightPriceScale: { mode: logView
        ? LightweightCharts.PriceScaleMode.Logarithmic
        : LightweightCharts.PriceScaleMode.Normal } });
    };
  chart.subscribeCrosshairMove(param => {
    if (!param.time || !param.point || !param.seriesData.size) { tt.style.display = "none"; return; }
    let html = `<div style="color:#8a8a84;margin-bottom:3px">${param.time}</div>`;
    lwMeta.forEach(m => {
      const d = param.seriesData.get(m.se);
      if (d && d.value != null)
        html += `<div style="display:flex;justify-content:space-between;gap:12px;margin:1px 0">` +
          `<span style="color:${m.color}">■ ${m.name}</span>` +
          `<b style="font-variant-numeric:tabular-nums">￥${(+d.value).toFixed(4).replace(/0+$/, "").replace(/\.$/, "")}</b></div>`;
    });
    tt.innerHTML = html;
    tt.style.display = "block";
    const wrap = chartEl.getBoundingClientRect();
    let x = param.point.x + 16, y = param.point.y + 12;
    if (x + 190 > wrap.width) x = param.point.x - 200;
    if (y + 46 + lwMeta.length * 18 > wrap.height) y = param.point.y - 36 - lwMeta.length * 18;
    tt.style.left = Math.max(4, x) + "px"; tt.style.top = Math.max(4, y) + "px";
  });
    return chart;
  }
  function destroyChart() {
    if (chart) { try { chart.remove(); } catch (e) {} chart = null; }
    lwSeries.clear(); lwMeta.length = 0;
  }
  const PAL = ["#1f77b4", "#d9822b", "#2ca02c", "#e377c2", "#9467bd", "#17becf",
    "#bcbd22", "#d62728", "#6acc64", "#8c613c", "#4878d0", "#dc7ec0"];
  const lwSeries = new Map();   // pid -> series
  const lwMeta = [];            // {se, name, color} 联动 tooltip 用
  function hexA(hex, a) {
    const n = parseInt(hex.slice(1), 16);
    return `rgba(${n >> 16 & 255},${n >> 8 & 255},${n & 255},${a})`;
  }
  // 异动标记聚类:±3% 起报,14 天窗内只保留最大一次,单序列至多 6 枚
  function pickMarks(pts) {
    const raw = [];
    for (let k = 1; k < pts.length; k++) {
      const chg = pts[k - 1].price ? (pts[k].price / pts[k - 1].price - 1) * 100 : null;
      if (chg != null && Math.abs(chg) >= 3) raw.push({ time: pts[k].date, chg });
    }
    raw.sort((a, b) => a.time < b.time ? -1 : 1);
    const kept = [];
    for (const m of raw) {
      const last = kept[kept.length - 1];
      if (last && new Date(m.time) - new Date(last.time) < 14 * 86400e3) {
        if (Math.abs(m.chg) > Math.abs(last.chg)) kept[kept.length - 1] = m;
        continue;
      }
      kept.push(m);
    }
    return kept.sort((a, b) => Math.abs(b.chg) - Math.abs(a.chg)).slice(0, 6)
      .sort((a, b) => a.time < b.time ? -1 : 1)
      .map(m => ({ time: m.time, position: m.chg > 0 ? "belowBar" : "aboveBar",
        color: m.chg > 0 ? "#d62728" : "#1a7f4b",
        shape: m.chg > 0 ? "arrowUp" : "arrowDown",
        text: (m.chg > 0 ? "▲" : "▼") + Math.abs(m.chg).toFixed(1) + "%" }));
  }
  // 跨序列联动 tooltip
  const tt = document.createElement("div");
  tt.style.cssText = "position:absolute;display:none;pointer-events:none;z-index:5;background:rgba(255,255,255,.97);" +
    "border:1px solid #d5d5cf;border-radius:6px;padding:7px 10px;font-size:11.5px;box-shadow:0 3px 10px rgba(0,0,0,.10);min-width:150px;";
  chartEl.style.position = "relative";
  chartEl.appendChild(tt);
  function setFocus(pid) { focusPid = focusPid === pid ? null : pid; renderChart(); renderTable(); }
  window.addEventListener("keydown", e => {
    if (e.key === "Escape" && focusPid != null) { focusPid = null; renderChart(); renderTable(); }
  });
  function renderChart() {
    destroyChart(); ensureChart();   // 销毁重建,规避实例状态损坏
    const dates = allDates;
    let idx = 0;
    for (const pid of selected) {
      const p = byId.get(pid);
      const pts = series.get(pid) || [];
      if (!pts.length) continue;
      const dim = focusPid != null && pid !== focusPid;
      const base = PAL[idx % PAL.length];
      const name = `${SRC_TAG[p.source]}·${p.part}`;
      const se = chart.addLineSeries({
        color: dim ? hexA(base, .15) : base,
        lineWidth: focusPid === pid ? 2.6 : 1.8,
        priceLineVisible: false, lastValueVisible: !dim,
        crosshairMarkerRadius: focusPid === pid ? 5 : 3.5,
      });
      se.setData(pts.map(r => ({ time: r.date, value: r.price })));
      const marks = pickMarks(pts);
      if (marks.length) se.setMarkers(marks);
      lwSeries.set(pid, se);
      lwMeta.push({ se, name, color: dim ? hexA(base, .4) : base });
      idx++;
    }
    document.getElementById("chartTip").textContent =
      (focusPid != null ? `聚焦：${byId.get(focusPid).part}（Esc 退出） · ` : "")
      + (dates.length < 4 ? `日更累积中（第 ${dates.length} 天）· 成线前以下方明细表为准 · ` : "")
      + `${selected.size} 条序列 · ${dates.length} 天`;
    // lightweight-charts 4.2.3 实测:不加 fitContent 时 auto visible range 会
    // 塌缩掉头部区段(2026-10-11:18 天数据只见 ~10 天),每次重绘强制全览。
    chart.timeScale().fitContent();
  }
  window.addEventListener("resize", () => { if (chart) chart.applyOptions({ width: chartEl.clientWidth }); });

  // ---- 明细表 ----
  function ladderBar(high, low, cur) {
    if (high == null || low == null || high <= low) return `<span class="hint-small">—</span>`;
    const pos = Math.max(0, Math.min(1, (cur - low) / (high - low)));
    return `<span class="ladderbar" title="首档 ￥${high} — 末档 ￥${low}"><i style="left:${(pos*100).toFixed(0)}%"></i></span>`;
  }
  function renderTable() {
    document.querySelectorAll("#snap th").forEach(th => {
      const arr = th.querySelector(".arr"); if (arr) arr.remove();
      if (sortKey && th.dataset.k === sortKey)
        th.insertAdjacentHTML("beforeend", `<span class="arr">${sortDir > 0 ? "▲" : "▼"}</span>`);
    });
    const rows = [];
    for (const p of D.products) {
      const r = last.get(p.id);
      if (!r) continue;
      rows.push({ p, r, price: r.price, chg: chgOf.get(p.id), stock: r.stock,
        src: SRC_TAG[p.source], name: p.part, date: r.date });
    }
    if (sortKey) rows.sort((a, b) => {
      const va = a[sortKey], vb = b[sortKey];
      if (va == null) return 1; if (vb == null) return -1;
      return (typeof va === "number" ? va - vb : String(va).localeCompare(String(vb))) * sortDir;
    });
    let html = "";
    const emit = ({ p, r }) => {
      const c = chgOf.get(p.id);
      const high = series.get(p.id) && r.moq;
      return `<tr class="prow ${focusPid === p.id ? "focused" : ""}" data-pid="${p.id}"
        title="${p.descr || ''}">
        <td>${p.part}</td>
        <td class="num price">￥${fmtNum(r.price)}</td>
        <td class="num">${c == null ? `<span class="hint-small">首日</span>`
          : `<span class="chg ${chgCls(c)}">${fmtPct(c)}</span>`}</td>
        <td class="num">${r.stock > 0 ? fmtNum(r.stock) : `<span class="chg up">无货</span>`}</td>
        <td><span class="src-tag src-${p.source.toLowerCase()}">${SRC_TAG[p.source]}</span></td>
        <td>${ladderBar(r.high, r.low, r.price)}</td>
        <td class="datecell">${r.date}</td></tr>`;
    };
    if (sortKey) { html = rows.map(x => emit(x)).join(""); }
    else {
      for (const k of groupKeys) {
        const items = groups.get(k).filter(p => last.has(p.id))
          .sort((a, b) => a.part.localeCompare(b.part));
        if (!items.length) continue;
        html += `<tr class="sec"><td colspan="7">${k}</td></tr>` + items.map(p => emit({ p, r: last.get(p.id) })).join("");
      }
    }
    document.getElementById("snapBody").innerHTML = html;
  }
  document.getElementById("snapBody").addEventListener("click", e => {
    const tr = e.target.closest("tr.prow");
    if (tr) setFocus(+tr.dataset.pid);
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

  // ---- CSV ----
  document.getElementById("csvBtn").onclick = () => {
    const lines = ["source,part,brand,seg,desc,date,price_cny,stock,moq"];
    for (const [pid, arr] of series) {
      const p = byId.get(pid);
      for (const r of arr) lines.push(
        [p.source, p.part, p.brand, p.seg, `"${(p.descr||'').replace(/"/g,'""')}"`,
         r.date, r.price, r.stock, r.moq ?? ""].join(","));
    }
    lines.push(`# 口径：起订档单价CNY；立创=1+档 云汉=MOQ档；库存为抓取时点数`);
    lines.push(`# 审计：${audit.pass ? "PASS" : "FAIL"} ${audit.n} 项 @ ${audit.at}`);
    const blob = new Blob(["\uFEFF" + lines.join("\n")], { type: "text/csv;charset=utf-8" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `mlcc_${latestDate.replace(/-/g, "")}.csv`;
    a.click(); URL.revokeObjectURL(a.href);
  };

  // ---- 历史锚点时间线（新闻考古层）----
  function renderAnchors() {
    const CAT = { "现货锚点": ["spot", "acat-spot"], "原厂调价": ["oem", "acat-oem"], "交期": ["lead", "acat-lead"] };
    const anchors = (D.newsAnchors || []).slice().sort((a, b) => a.date < b.date ? 1 : -1);
    const grades = new Set((D.newsAnchors || []).map(a => a.grade).filter(Boolean));
    const showGrade = grades.size > 1;   // 全同级时徽章列是纯噪声,隐藏
    document.getElementById("anchorLine").innerHTML = anchors.map(a => {
      const [cls, catCls] = CAT[a.cat] || ["", ""];
      const g = showGrade ? (a.grade || "") : "";
      return `<div class="anchor ${cls}">
        <span class="ad">${a.date}</span><span class="acat ${catCls}">${a.cat}</span>
        ${g ? `<span class="grade grade-${g === "一手公告" ? "hi" : g === "主流媒体" ? "mid" : "low"}" title="来源分级=证据硬度">${g}</span>` : ""}
        <span class="atext"><b>${a.item}</b>：${a.value}${a.perUnit != null ? `（≈￥${a.perUnit}/颗）` : ""}</span>
        <span class="asrc">口径：${a.caliber} · ${a.source}</span>
      </div>`;
    }).join("") || `<div class="hint-small">无锚点</div>`;
  }

  // ---- 结论横幅(红绿灯先行:灯只管数据健康度;全绿显式展示) ----
  function renderConclusion() {
    const c = D.conclusion;
    const el = document.getElementById("concl");
    if (!el || !c) { if (el) el.style.display = "none"; return; }
    const LN = { fresh: "新鲜度", cover: "覆盖", pipe: "管线" };
    const bulbs = Object.entries(c.lights).map(([k, v]) => {
      const cls = v === "ok" ? "green" : v === "wa" ? "amber" : "red";
      return `<div class="lg"><span class="bulb ${cls}"></span><span>${LN[k]}</span></div>`;
    }).join("");
    const verdict = c.level === "ok"
      ? `<span class="verdict">${c.verdict}</span>`
      : `<span class="verdict" style="color:#b45309">${c.verdict}</span>`;
    const body = c.level === "ok"
      ? `<div class="norm">${c.normals.map(n => `<b>${n}</b>`).join('<br>')}</div>`
      : `<div class="norm"><b>驱动项:</b>${c.drivers.join(' · ')}</div>`;
    el.innerHTML = `<div class="concl">
      <div class="lights">${bulbs}<span class="verdict">${verdict}</span></div>
      ${body}
      <div class="meta">最后复核 ${c.lastReview.replace("T", " ")}<br>下次自动扫描 每日 20:10</div>
    </div>`;
  }

  // ---- 待核验锚点候选(搜狗微信扫描层,机器发现/人工定价) ----
  function renderPending() {
    const pending = D.pending || [];
    const tip = document.getElementById("pendTip");
    const body = document.getElementById("pendBody");
    const st = D.pendingState;
    if (!pending.length) {
      tip.textContent = st && st.cooldown
        ? `扫描冷却中(上次命中反爬 ${st.last}),${st.until} 后自动重试;可 --reset-flag 人工放行`
        : "尚无候选(每日任务自动扫描)";
      body.innerHTML = `<tr><td colspan="6" class="hint-small" style="padding:12px">${st && st.cooldown
        ? `候选队列为空 · 扫描熔断至 ${st.until}` : "候选队列为空"}</td></tr>`;
      return;
    }
    const stCls = st => st === "已采纳" ? "up" : st === "已否决" ? "down" : "flat";
    body.innerHTML = pending.map(p => `<tr>
        <td class="datecell">${p.pubDate || p.foundAt.slice(0, 10)}</td>
        <td>${p.account || "—"}</td>
        <td class="wrap"><a href="${p.url.startsWith("sogou:") ? "#" : p.url}" target="_blank" rel="noopener">${p.title}</a></td>
        <td class="hint-small">${p.items.join("、") || "—"}</td>
        <td class="wrap hint-small">${p.nums.slice(0, 3).join(" ┋ ") || "—"}</td>
        <td><span class="chg ${stCls(p.status)}">${p.status}</span></td></tr>`).join("");
    tip.textContent = `候选 ${pending.length} 条,待人工核验 ${pending.filter(p => p.status === "待核验").length} 条(机器不定价)`;
  }

  // 逐函数容错:单面板异常不拖垮整页(错误写进对应容器与标题)
  const SAFE = (name, fn, container) => {
    try { fn(); }
    catch (e) {
      console.error('[' + name + ']', e);
      const el = container && document.getElementById(container);
      if (el) el.innerHTML = `<div class="hint-small" style="padding:10px">[${name}] 渲染异常: ${e.message}</div>`;
      else document.title = 'ERR:' + name;
    }
  };
  SAFE('conclusion', renderConclusion, 'concl');
  SAFE('kpis', renderKpis, 'kpis');
  SAFE('movers', renderMovers, 'movers');
  SAFE('anchors', renderAnchors, 'anchorLine');
  SAFE('tree', renderTree, 'tree');
  SAFE('table', renderTable, 'snapBody');
  SAFE('chart', renderChart, 'chart');
  SAFE('pending', renderPending, 'pendBody');
})();
