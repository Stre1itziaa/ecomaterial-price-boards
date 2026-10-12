/* 存储价格趋势看板 —— 双数据源（CFM 闪存市场 / TrendForce 集邦）
   设计准则（正反方 5 轮辩论冻结版）：
   - 红涨绿跌必配 ▲▼；全数字 tabular-nums；涨跌幅必须带基线（·日/·周/·季）
   - 涨跌幅分"源"（页面自带）与"算"（相邻点推算）两种出处，单点序列不硬算
   - 视觉族用全史窗口、统计族（动量/区间/异动）统一 13 周窗口
   - 两源口径独立：不混算、不跨源衍生；对照只并排 */
(function () {
  const D = window.STORAGE_DATA;
  if (!D) return;

  const SRC_ORDER = ["CFM", "TrendForce", "SPD"];
  const SRC_LABEL = { CFM: "CFM 闪存市场", TrendForce: "TrendForce 集邦咨询", SPD: "ServerPartDeals 零售" };
  const SRC_TAG = { CFM: "CFM", TrendForce: "TF", SPD: "SPD" };
  const SRC_CALIBER = { CFM: "CFM评估价", TrendForce: "TF盘均/合约", SPD: "SPD零售价" };  // N4 口径短句 ≤15字
  const srcCls = s => s === "CFM" ? "src-cfm" : s === "SPD" ? "src-spd" : "src-tf";
  const FREQ_LBL = { daily: "日", weekly: "周", monthly: "月", quarterly: "季", index: "指" };
  // X3 三态文案表（全组件统一套用，禁止自造）
  const TRI_STATE = {
    ok: { txt: "巡检正常", cls: "ok" },
    warn: { txt: "巡检 WARN", cls: "warn" },
    error: { txt: "巡检 ERROR", cls: "error" },
    short: { txt: "样本不足", cls: "flat" },
    accum: { txt: "累积中", cls: "flat" },
  };
  const FAMILY_ORDER = ["CFM 指数", "DRAM 颗粒", "NAND Wafer", "DRAM", "NAND",
    "内存条", "SSD", "Wafer", "Module", "GDDR", "Memory Card", "HDD 企业盘", "HDD NAS盘"];
  const SECTION_TITLES = { "现货价": "现货", "合约价": "合约", "市场价": "市场价",
    "现货(日)": "现货", "报价(周)": "周价", "价格指数": "" };
  const CORE_NAMES = ["512Gb TLC", "256Gb TLC", "1Tb QLC",
    "DDR5 16Gb (2Gx8) 4800/5600", "DDR4 16Gb (2Gx8) 3200", "DDR4 8Gb (1Gx8) 3200",
    "DDR4 16Gb 3200", "DDR5 16Gb Major", "SLC 2Gb 256MBx8"];
  const INDEX_NAMES = ["NAND指数", "DRAM指数"];
  const WIN13 = 91;   // 统计族窗口：13 周
  const WIN13_HALF = 45;

  // ---------- 数据整形 ----------
  const byId = new Map(D.products.map(p => [p.id, p]));
  const seriesData = new Map();
  for (const [pid, date, avg, chg, high, low] of D.quotes) {
    if (!seriesData.has(pid)) seriesData.set(pid, []);
    seriesData.get(pid).push({ date, avg, chg, high, low, chgSrc: null });
  }
  for (const arr of seriesData.values()) arr.sort((a, b) => a.date < b.date ? -1 : 1);
  // X1：涨跌幅出处分离——"源"=页面自带；"算"=相邻点推算（仅 n≥2）；单点且无源值则 null
  for (const arr of seriesData.values()) {
    for (let i = 0; i < arr.length; i++) {
      if (arr[i].chg != null) { arr[i].chgSrc = "源"; continue; }
      if (i > 0 && arr[i - 1].avg) {
        arr[i].chg = (arr[i].avg / arr[i - 1].avg - 1) * 100;
        arr[i].chgSrc = "算";
      }
    }
  }
  const last = new Map(), nPoints = new Map();
  for (const [pid, arr] of seriesData) { last.set(pid, arr[arr.length - 1]); nPoints.set(pid, arr.length); }

  const allDates = [...new Set(D.quotes.map(q => q[1]))].sort();
  const latestDate = allDates[allDates.length - 1];

  const groups = new Map();
  for (const p of D.products) {
    if (p.tier !== 1) continue;
    const k = [p.source, p.family, p.section].join("|");
    if (!groups.has(k)) groups.set(k, []);
    groups.get(k).push(p);
  }
  const famRank = f => {
    const i = FAMILY_ORDER.indexOf(f);
    if (i >= 0) return i;
    const loose = FAMILY_ORDER.findIndex(o => f.includes(o));
    return loose >= 0 ? loose : 90;
  };
  const groupKeys = [...groups.keys()].sort((a, b) => {
    const [sa, fa, ea] = a.split("|"), [sb, fb, eb] = b.split("|");
    return SRC_ORDER.indexOf(sa) - SRC_ORDER.indexOf(sb)
      || famRank(fa) - famRank(fb) || (ea || "").localeCompare(eb || "");
  });
  const tier2 = D.products.filter(p => p.tier === 2);

  // ---------- 状态 ----------
  const selected = new Set(
    // 默认"核心"档（N5 核心 9 序列），开屏即可读；"全部"按钮一键展开
    D.products.filter(p => p.tier === 1 && p.unit !== "index" && CORE_NAMES.some(n => p.name.includes(n))).map(p => p.id)
  );
  let rangeDays = 0, mode = "price", scale = "log", query = "";
  let sortKey = null, sortDir = -1;
  let focusPid = null;           // Q4：临时聚焦，不改写勾选集
  let widthFilter = null;        // R3：涨/平/跌筛选

  // ---------- 工具 ----------
  const fmtNum = n => {
    if (n == null || (typeof n === "number" && !isFinite(n))) return "-";
    const a = Math.abs(n);
    if (a >= 1000) return n.toLocaleString("zh-CN", { maximumFractionDigits: 0 });
    if (a >= 100) return n.toFixed(1);
    return String(Math.round(n * 100) / 100);
  };
  const fmtPct = v => (v > 0 ? "▲ +" : v < 0 ? "▼ " : "— ") + Math.abs(v).toFixed(2) + "%";
  const chgCls = v => v > 0 ? "up" : v < 0 ? "down" : "flat";
  const dayDiff = (a, b) => Math.round((new Date(a) - new Date(b)) / 86400e3);

  function sparkSVG(pts, w = 104, h = 26) {
    if (!pts || pts.length < 2) return `<span class="hint-small" title="新接入：满 2 期出走势，动量/异动信号需 13 周">新接入</span>`;
    const vs = pts.map(p => p.avg);
    const mn = Math.min(...vs), mx = Math.max(...vs), span = (mx - mn) || 1;
    const step = w / (pts.length - 1);
    const xy = vs.map((v, i) => [(i * step).toFixed(1), (h - 3 - (v - mn) / span * (h - 6)).toFixed(1)]);
    const line = xy.map(p => p.join(",")).join(" ");
    const [lx, ly] = xy[xy.length - 1];
    const col = vs[vs.length - 1] > vs[0] ? "var(--up)" : vs[vs.length - 1] < vs[0] ? "var(--down)" : "var(--flat)";
    return `<svg class="spark" width="${w}" height="${h}">
      <polyline points="${line}" fill="none" stroke="${col}" stroke-width="1.4"/>
      <circle cx="${lx}" cy="${ly}" r="2" fill="${col}"/></svg>`;
  }
  // 13 周区间条（统计族窗口）：返回 {bar, lowD, highD} 或 null
  function range13(pid) {
    const arr = seriesData.get(pid) || [];
    const L = arr[arr.length - 1];
    if (!L || arr.length < 2) return null;
    const win = arr.filter(r => dayDiff(L.date, r.date) <= WIN13);
    if (win.length < 2) return null;
    let lo = win[0], hi = win[0];
    for (const r of win) { if (r.avg < lo.avg) lo = r; if (r.avg > hi.avg) hi = r; }
    const span = hi.avg - lo.avg;
    const pos = span ? Math.max(0, Math.min(1, (L.avg - lo.avg) / span)) : .5;
    return { lo, hi, pos };
  }
  // 动量（Q1）：目标点=≤(最新-窗口日) 的最近一点；距最新<半窗或为同点 → null
  function momentum(pid, days) {
    const arr = seriesData.get(pid) || [];
    if (arr.length < 2) return null;
    const L = arr[arr.length - 1];
    const half = days === 28 ? 14 : WIN13_HALF;
    let cand = null;
    for (const r of arr) {
      const d = dayDiff(L.date, r.date);
      if (d >= days && (!cand || r.date > cand.date)) cand = r;
    }
    if (!cand) return null;
    const gap = dayDiff(L.date, cand.date);
    if (gap > days + half || gap < half) return null;
    if (cand === L || !cand.avg) return null;
    return { pct: (L.avg / cand.avg - 1) * 100, from: cand.date, to: L.date };
  }
  // 异动 z 分（Q2）：13 周窗剔除最新点；n≥5 且 std>0
  function zScore(pid) {
    const arr = seriesData.get(pid) || [];
    if (arr.length < 6) return null;
    const L = arr[arr.length - 1];
    const win = arr.filter(r => r !== L && dayDiff(L.date, r.date) <= WIN13);
    if (win.length < 5) return null;
    const vs = win.map(r => r.avg);
    const mean = vs.reduce((a, b) => a + b, 0) / vs.length;
    const std = Math.sqrt(vs.reduce((a, b) => a + (b - mean) ** 2, 0) / vs.length);
    if (!std) return null;
    return { z: (L.avg - mean) / std, n: win.length };
  }

  // ---------- 顶栏 ----------
  const health = D.health || { status: "ok", stale: [] };
  const audit = D.audit || { pass: true, n: 0, items: [], at: "" };
  document.getElementById("asof").textContent = latestDate;
  document.getElementById("gen").textContent = D.generatedAt.replace("T", " ");
  const lamp = document.getElementById("healthLamp");
  const tri = TRI_STATE[health.status] || TRI_STATE.ok;
  lamp.className = "lamp " + tri.cls;
  document.getElementById("healthTxt").textContent =
    tri.txt + (health.stale && health.stale.length ? `（${health.stale.length} 项待更新）` : "");
  if (health.status !== "ok") {
    document.title = "[!] " + document.title;
    lamp.title = "待更新：" + health.stale.map(s => `${s.name}（${s.age}天）`).join("、");
  }
  lamp.addEventListener("click", () => {
    const d = document.getElementById("caliber");
    d.open = true; d.scrollIntoView({ behavior: "smooth" });
  });
  document.getElementById("foot").innerHTML =
    `· CFM 闪存市场：产品历史自详情页公开图表回填（现货类约 65 个交易日 / 周价类约 13 周），NAND/DRAM 指数自 2026-02 起；` +
    `TrendForce：现货日更、其余周/月/季更，自 2026-09-18 起累积；中文免费页停更板块（SLC/MLC/GDDR/晶圆/MicroSD/品牌 SSD 现货）自 2026-10-05 起由 DRAMeXchange 英文站首页接续（同口径、不带页面日期、同值跳过不造日更）。两源口径独立，不混算、无跨源衍生值。` +
    `SPD：HDD 企业/NAS 盘零售价（New/翻新/Recertified 三档，档间单调性入审计），自 2026-09-24 起累积。` +
    `每日运行 <code>python -m tracker.update</code>，每周建议 <code>--with-cfm</code>；交付前跑 <code>python -m tracker.audit</code>。` +
    `<div class="sibnav" style="margin-top:8px">姊妹板：<a href="http://127.0.0.1:8800/">总入口 8800</a> · <a href="http://127.0.0.1:8792/">MLCC 8792</a> · <a href="http://127.0.0.1:8793/">电子布 8793</a> · <a href="http://127.0.0.1:8794/">信号 8794</a> ·（本板 8790）</div>`;

  // 口径折叠区（P3/N3/N4 同源文案）
  document.getElementById("caliberBody").innerHTML = `
    <b>价格口径</b>
    <li>CFM 闪存市场：现货评估价（渠道/行业分市场），日度序列来自其公开图表。</li>
    <li>TrendForce 免费页"盘平均"：与新闻快讯引用口径存在正常差异（如 512Gb TLC 9/16 新闻 20.083 vs 免费页 9/17 盘均 20.146），两序列不混用。</li>
    <li>DDR5 RDIMM 32GB 约 $1,910 为<b>合约口径 + 2026 供给紧缺超级周期</b>背景，非数据错误（审计锚点已核）。</li>
    <b>窗口口径</b>
    <li>走势线 = 各序列<b>全史</b>；"13周区间 / 4周动量 / 异动 z 分"统一使用 <b>13 周（91 天）</b>窗口，一处定义。</li>
    <b>涨跌幅出处</b>
    <li>角标「源」= 页面自带涨跌；「算」= 由相邻两期均价推算。单点序列不推算（显示 —）。</li>
    <b>审计（${audit.pass ? '<span class="audit-pass">PASS</span>' : '<span class="audit-fail">FAIL</span>'} ${audit.n} 项 · ${audit.at.replace("T", " ")}</b>
    <li>${audit.items.map(c => `[${c.status}] ${c.name}`).join("</li><li>")}</li>
    ${health.stale && health.stale.length ? `<b>巡检待更新</b><li>${health.stale.map(s => `${s.name}：${s.age} 天未更新`).join("</li><li>")}</li>` : ""}`;

  // ---------- KPI（4 卡：双指数 + 512Gb TLC + 异动TOP1） ----------
  function kpiInfo(namePick) {
    const cands = D.products.filter(p => namePick.some(n => p.name.includes(n)) && p.tier === 1);
    if (!cands.length) return null;
    const p = cands.sort((a, b) => (seriesData.get(b.id) || []).length - (seriesData.get(a.id) || []).length)[0];
    const arr = seriesData.get(p.id) || [];
    const cur = arr[arr.length - 1], prev = arr[arr.length - 2];
    const chg = cur && cur.chg != null ? cur.chg : (cur && prev ? (cur.avg / prev.avg - 1) * 100 : null);
    return { p, cur, chg, base: prev ? prev.avg : null, hist: arr };
  }
  function sinceFirst(info) {
    const arr = info.hist;
    if (arr.length < 2) return null;
    return { pct: (arr[arr.length - 1].avg / arr[0].avg - 1) * 100, from: arr[0].date };
  }
  function renderKpis(top1) {
    const cards = [];
    for (const [nm, lbl] of [["DRAM指数", "DRAM 指数（CFM·周）"], ["NAND指数", "NAND 指数（CFM·周）"]]) {
      const k = kpiInfo([nm]);
      if (!k) continue;
      const since = sinceFirst(k);
      cards.push({ label: lbl, k,
        extra: since ? `<span class="chg ${chgCls(since.pct)}">自${since.from.slice(0, 7)} ${fmtPct(since.pct)}</span>` : "" });
    }
    const w = kpiInfo(["512Gb TLC"]);
    if (w) cards.push({ label: "512Gb TLC 晶圆现货（CFM·日）", k: w, extra: "" });
    if (top1) {
      const p = top1.p, r = last.get(p.id);
      cards.push({ label: `最大异动 · ${SRC_TAG[p.source]}·${p.name}（${r.date}）`, top1,
        extra: `<span>z=${top1.z.toFixed(1)} · ${SRC_CALIBER[p.source] || ""}</span>` });
    }
    /* v4 现象卡:sparkline 升级 ECharts 渐变面积 */
    window.__KSP = [];
    const ACCENT = "#1f77b4";
    document.getElementById("kpis").innerHTML = cards.map((c, ci) => {
      if (c.top1) {
        const p = c.top1.p, r = last.get(p.id);
        const cls = chgCls(r.chg);
        return `<div class="kpi" title="点击聚焦该序列" style="cursor:pointer" onclick="window.__focus(${p.id})">
          <div class="l">${c.label}</div>
          <div class="v">${fmtNum(r.avg)}<small>${p.unit === "CNY" ? "￥" : "$"}</small></div>
          <div class="d"><span class="chg ${cls}">${fmtPct(r.chg)}<span class="baseline">·${FREQ_LBL[p.freq] || ""}</span></span>
          <span>${c.extra}</span>${(()=>{ const pts=(seriesData.get(p.id)||[]).map(x=>x.avg); const col=Math.abs(c.top1.z)>=3?"#ef4444":Math.abs(c.top1.z)>=2?"#f59e0b":"#1f77b4"; window.__KSP.push({id:"ksp_"+ci,pts,color:col}); return ""; })()}<div class="kspark" id="ksp_${ci}"></div></div></div>`;
      }
      const k = c.k, cls = k.chg == null ? "flat" : chgCls(k.chg);
      return `<div class="kpi"><div class="l">${c.label}</div>
        <div class="v">${fmtNum(k.cur.avg)}<small>${k.p.unit === "index" ? "点" : k.p.unit === "CNY" ? "￥" : "$"}</small></div>
        <div class="d"><span class="chg ${cls}">${k.chg == null ? "—" : fmtPct(k.chg)}</span>
        <span>${k.base != null ? "前值 " + fmtNum(k.base) : ""}</span>${c.extra}${(()=>{ const pts=(k.hist||[]).slice(-31).map(x=>x.avg); window.__KSP.push({id:"ksp_"+ci,pts,color:"#1f77b4"}); return ""; })()}<div class="kspark" id="ksp_${ci}"></div></div></div>`;
    }).join("");
    (window.__KSP_E || []).forEach(c => { try { c.dispose(); } catch (e) {} });
    window.__KSP_E = window.__KSP.filter(s => s.pts.length >= 2).map(s => {
      const el = document.getElementById(s.id); if (!el || !window.echarts) return null;
      const c = echarts.init(el, null, { height: 34 });
      c.setOption({ grid: { left: 0, right: 0, top: 3, bottom: 0 },
        xAxis: { type: "category", show: false, data: s.pts.map((_, i) => i) },
        yAxis: { type: "value", show: false },
        series: [{ type: "line", data: s.pts, smooth: .35, symbol: "none",
          lineStyle: { width: 1.6, color: s.color },
          areaStyle: { color: new echarts.graphic.LinearGradient(0, 0, 0, 1,
            [{ offset: 0, color: s.color + "38" }, { offset: 1, color: s.color + "00" }]) } }] });
      return c;
    }).filter(Boolean);
  }

  // ---------- 异动速览（Q2：13周 z 分，剔最新点，季更/单点不参与） ----------
  function moversList() {
    const items = [];
    for (const p of D.products) {
      if (p.tier !== 1 || p.unit === "index" || p.freq === "quarterly" || p.freq === "monthly") continue;
      const z = zScore(p.id);
      if (!z) continue;
      const r = last.get(p.id);
      items.push({ p, r, z: z.z, n: z.n });
    }
    items.sort((a, b) => Math.abs(b.z) - Math.abs(a.z));
    window.__MOVERS_Z = items;   // 结论横幅 A 层同源复用(勿重复实现 z 算法)
    return items;
  }
  function renderMovers(items) {
    const box = document.getElementById("movers");
    if (!items.length) {
      box.innerHTML = `<span class="mt">最新异动</span><span class="hint-small">样本积累中</span>`;
      return;
    }
    const ups = items.filter(i => i.z > 0).slice(0, 3);
    const dns = items.filter(i => i.z < 0).slice(0, 3);
    const chip = i => `<span class="chip ${Math.abs(i.z) >= 3 ? "chip-hot" : Math.abs(i.z) >= 2 ? "chip-warm" : ""}" data-pid="${i.p.id}">
      <span class="dot" style="background:${i.p.source === "CFM" ? "#b8860b" : i.p.source === "SPD" ? "#9467bd" : "#1f77b4"}"></span>
      ${SRC_TAG[i.p.source]}·${i.p.name}
      <span class="chg ${chgCls(i.r.chg)}">${fmtPct(i.r.chg)}<span class="baseline">·${FREQ_LBL[i.p.freq] || ""}${i.r.chgSrc === "源" ? "源" : ""}</span></span>
      <span class="z">${i.r.date} · z=${i.z.toFixed(1)}</span></span>`;
    box.innerHTML = `<span class="mt">最新异动 · 13周z分</span>`
      + (ups.length ? `<span class="hint-small">强</span>` + ups.map(chip).join("") : "")
      + (dns.length ? `<span class="hint-small">弱</span>` + dns.map(chip).join("") : "")
      + `<span class="hint-small" style="margin-left:auto">点击条目聚焦图表 · 季更序列不参与</span>`;
    box.querySelectorAll(".chip").forEach(c => c.addEventListener("click", () => {
      setFocus(+c.dataset.pid);
    }));
  }

  // ---------- 侧栏 ----------
  const tree = document.getElementById("tree");
  function badgeHtml(chg) {
    if (chg == null) return "";
    return `<span class="badge ${chgCls(chg)}">${fmtPct(chg)}</span>`;
  }
  function renderTree() {
    let html = "", lastSrc = null;
    for (const k of groupKeys) {
      const [source, family, section] = k.split("|");
      const items = groups.get(k)
        .filter(p => !query || p.name.toLowerCase().includes(query))
        .sort((a, b) => a.name.localeCompare(b.name));
      if (!items.length) continue;
      if (source !== lastSrc) {
        html += `<div class="grp-src">${SRC_LABEL[source] || source}</div>`;
        lastSrc = source;
      }
      const secTxt = SECTION_TITLES[section] || section;
      html += `<div class="grp"><div class="gtitle">${family}${secTxt ? " · " + secTxt : ""}
               <span class="cnt">${items.length}</span></div>`;
      for (const p of items) {
        const r = last.get(p.id);
        html += `<label class="item"><input type="checkbox" data-pid="${p.id}"
                 ${selected.has(p.id) ? "checked" : ""}>
                 <span class="nm" title="${p.name}">${p.name}</span>${badgeHtml(r && r.chg)}</label>`;
      }
      html += `</div>`;
    }
    tree.innerHTML = html || `<div style="color:var(--muted);padding:10px">无匹配产品</div>`;
    // 二梯队（默认折叠、默认不勾选）
    const list = tier2.filter(p => !query || p.name.toLowerCase().includes(query));
    document.getElementById("tier2list").innerHTML = list.map(p => {
      const r = last.get(p.id);
      return `<label class="item"><input type="checkbox" data-pid="${p.id}"
        ${selected.has(p.id) ? "checked" : ""}>
        <span class="nm" title="${p.family}">${p.name}</span>${badgeHtml(r && r.chg)}</label>`;
    }).join("") || `<div class="hint-small" style="padding:4px 6px">无匹配</div>`;
  }
  tree.addEventListener("change", e => {
    const pid = +e.target.dataset.pid;
    e.target.checked ? selected.add(pid) : selected.delete(pid);
    renderChart();
  });
  document.getElementById("tier2list").addEventListener("change", e => {
    const pid = +e.target.dataset.pid;
    e.target.checked ? selected.add(pid) : selected.delete(pid);
    renderChart();
  });
  document.getElementById("filter").addEventListener("input", e => {
    query = e.target.value.trim().toLowerCase();
    renderTree();
  });
  const reselect = pred => {
    selected.clear();
    D.products.filter(pred).forEach(p => selected.add(p.id));
    renderTree(); renderChart();
  };
  document.getElementById("all").onclick = () => reselect(() => true);
  document.getElementById("none").onclick = () => { selected.clear(); renderTree(); renderChart(); };
  document.getElementById("core").onclick = () => reselect(p => CORE_NAMES.some(n => p.name.includes(n)));
  document.getElementById("idx").onclick = () => {
    reselect(p => INDEX_NAMES.some(n => p.name.includes(n)));
    // 双指数同数量级，线性轴比对数轴更可读
    if (mode === "price" && scale === "log") {
      scale = "linear";
      [...document.querySelectorAll('#scale button')].forEach(b =>
        b.classList.toggle("on", b.dataset.s === "linear"));
      renderChart();
    }
  };

  // ---------- 图表(lightweight-charts + 自研增强包) ----------
  const chartEl = document.getElementById("chart");
  const chart = LightweightCharts.createChart(chartEl, {
    width: chartEl.clientWidth, height: chartEl.clientHeight || 380,
    layout: { background: { type: "solid", color: "#ffffff" }, textColor: "#555555", fontSize: 11,
      fontFamily: "-apple-system,'Segoe UI','PingFang SC','Microsoft YaHei',sans-serif" },
    grid: { vertLines: { color: "#f0f0eb" }, horzLines: { color: "#f0f0eb" } },
    rightPriceScale: { borderColor: "#d5d5cf" },
    timeScale: { borderColor: "#d5d5cf", rightOffset: 2,
      tickMarkFormatter: t => { const s = String(t); return s.length >= 10 ? s.slice(5).replace("-", "/") : s; } },
    crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
    localization: { locale: "zh-CN",
      priceFormatter: p => {
        if (mode === "norm") return (+p).toFixed(2);
        if (scale === "log") return fmtNum(Math.pow(10, p));
        return fmtNum(p);
      } },
  });
  const PALETTE = ["#1f77b4", "#d62728", "#2ca02c", "#9467bd", "#d9822b", "#17becf",
    "#bcbd22", "#8c613c", "#e377c2", "#4878d0", "#6acc64", "#dc7ec0",
    "#b8860b", "#1a7f4b", "#8c564b", "#5bc0de", "#e377c2", "#7f7f7f"];
  const lwList = [];        // {se, name}
  let seriesMeta = {};      // name -> {base, baseDate, caliber, unit}
  function hexA(hex, a) {
    const n = parseInt(hex.slice(1), 16);
    return `rgba(${n >> 16 & 255},${n >> 8 & 255},${n & 255},${a})`;
  }
  // 跨序列联动 tooltip(对数模式显示还原值)
  const tt = document.createElement("div");
  tt.style.cssText = "position:absolute;display:none;pointer-events:none;z-index:5;background:rgba(255,255,255,.97);" +
    "border:1px solid #d5d5cf;border-radius:6px;padding:7px 10px;font-size:11.5px;box-shadow:0 3px 10px rgba(0,0,0,.10);min-width:170px;";
  chartEl.style.position = "relative";
  chartEl.appendChild(tt);
  chart.subscribeCrosshairMove(param => {
    if (!param.time || !param.point || !param.seriesData.size) { tt.style.display = "none"; return; }
    let html = `<div style="color:#8a8a84;margin-bottom:3px">${param.time}</div>`;
    lwList.forEach(({ se, name }) => {
      const m = seriesMeta[name];
      const d = param.seriesData.get(se);
      if (!d || d.value == null) return;
      let val;
      if (mode === "norm") {
        val = (+d.value).toFixed(2) + "%" +
          (m.baseDate ? ` <span style="color:#8a8a84">(基期 ${m.baseDate}=100)</span>` : "");
      } else {
        const real = scale === "log" ? Math.pow(10, d.value) : d.value;
        val = fmtNum(real) + (m.unit === "CNY" ? "￥" : m.unit === "index" ? " 点" : " $");
      }
      html += `<div style="display:flex;justify-content:space-between;gap:12px;margin:1px 0">` +
        `<span style="color:#8a8a84">【${m.caliber || ""}】${name}</span><b style="font-variant-numeric:tabular-nums">${val}</b></div>`;
    });
    tt.innerHTML = html;
    tt.style.display = "block";
    const wrap = chartEl.getBoundingClientRect();
    let x = param.point.x + 16, y = param.point.y + 12;
    if (x + 210 > wrap.width) x = param.point.x - 220;
    if (y + 40 + lwList.length * 18 > wrap.height) y = param.point.y - 30 - lwList.length * 18;
    tt.style.left = Math.max(4, x) + "px"; tt.style.top = Math.max(4, y) + "px";
  });

  function windowDates() {
    if (!rangeDays) return allDates;
    const cutoff = new Date(allDates[allDates.length - 1]);
    cutoff.setDate(cutoff.getDate() - rangeDays);
    return allDates.filter(d => new Date(d) >= cutoff);
  }
  function setFocus(pid) {
    focusPid = focusPid === pid ? null : pid;
    renderChart();
    renderTable();
  }
  window.__focus = pid => setFocus(pid);

  function renderChart() {
    const dates = windowDates();
    const dset = new Set(dates);
    for (const { se } of lwList) chart.removeSeries(se);
    lwList.length = 0; seriesMeta = {};
    let pi = 0;
    for (const pid of selected) {
      const p = byId.get(pid);
      const pts = (seriesData.get(pid) || []).filter(r => dset.has(r.date));
      if (!pts.length) continue;
      const base = pts[0].avg || 1, baseDate = pts[0].date;
      let data = pts.map(r => ({ time: r.date, value: r.avg }));
      if (mode === "norm") data = data.map(r => ({ time: r.time, value: +(r.value / base * 100).toFixed(2) }));
      else if (scale === "log") data = data.map(r => ({ time: r.time, value: Math.log10(r.value) }));
      const name = `${SRC_TAG[p.source]}·${p.name}`;
      seriesMeta[name] = { base, baseDate, caliber: SRC_CALIBER[p.source] || "", unit: p.unit };
      const dim = focusPid != null && pid !== focusPid;
      const color = PALETTE[pi % PALETTE.length];
      const se = chart.addLineSeries({
        color: dim ? hexA(color, .12) : color,
        lineWidth: focusPid === pid ? 2.6 : 1.6,
        priceLineVisible: false, lastValueVisible: !dim,
        crosshairMarkerRadius: 4,
      });
      se.setData(data.filter(r => r.value != null));
      lwList.push({ se, name });
      pi++;
    }
    // 窗口-频率失配提示(X3 三态"样本不足"):所选序列在当前窗口内不足 2 期时明示
    const shortSeries = [];
    for (const pid of selected) {
      const p = byId.get(pid);
      const n = (seriesData.get(pid) || []).filter(r => dset.has(r.date)).length;
      if (p && n < 2) shortSeries.push({ name: p.name, freq: FREQ_LBL[p.freq] || "", n });
    }
    const winNote = document.getElementById("winNote");
    if (shortSeries.length) {
      winNote.style.display = "block";
      winNote.textContent = `⚠ 样本不足：当前窗口 ${dates.length} 期内有 ${shortSeries.length} 条序列仅 `
        + `${shortSeries[0].n} 期（${[...new Set(shortSeries.map(s => s.freq))].join("/")}频数据的最小可视窗口约 13 周）`
        + `——建议切换到 3月 或 全部 查看完整走势。`;
    } else {
      winNote.style.display = "none";
    }
    document.getElementById("normNote").style.display = mode === "norm" ? "block" : "none";
    document.getElementById("chartTip").textContent = (focusPid != null
      ? `聚焦：${byId.get(focusPid).name}（Esc 退出） · ` : "")
      + `${selected.size} 条序列 · ${dates.length} 期`;
  }

  document.getElementById("range").addEventListener("click", e => {
    if (!e.target.dataset.r) return;
    rangeDays = +e.target.dataset.r;
    [...e.currentTarget.children].forEach(b => b.classList.toggle("on", b === e.target));
    renderChart(); syncHash();
  });
  document.getElementById("mode").addEventListener("click", e => {
    if (!e.target.dataset.m) return;
    mode = e.target.dataset.m;
    [...e.currentTarget.children].forEach(b => b.classList.toggle("on", b === e.target));
    document.querySelectorAll("#scale button").forEach(b =>
      b.style.opacity = mode === "norm" ? .35 : 1);
    renderChart(); syncHash();
  });
  document.getElementById("scale").addEventListener("click", e => {
    if (!e.target.dataset.s || mode === "norm") return;
    scale = e.target.dataset.s;
    [...e.currentTarget.children].forEach(b => b.classList.toggle("on", b === e.target));
    renderChart();
  });
  window.addEventListener("keydown", e => {
    if (e.key === "Escape" && focusPid != null) { focusPid = null; renderChart(); renderTable(); }
  });
  window.addEventListener("resize", () => {
    chart.applyOptions({ width: chartEl.clientWidth });
    (window.__KSP_E || []).forEach(c => { try { c.resize(); } catch (e) {} });
  });
  
  // ---------- 明细表 ----------
  const staleNames = new Set((health.stale || []).map(s => s.name));
  function chgCell(p, r) {
    if (r == null || r.chg == null) return `<span class="hint-small">—</span>`;
    const basis = r.chgSrc === "源" ? `<span class="basis" title="页面自带涨跌">源</span>`
      : r.chgSrc === "算" ? `<span class="basis" title="由相邻两期推算">算</span>` : "";
    return `<span class="chg ${chgCls(r.chg)}">${fmtPct(r.chg)}</span><span class="baseline">·${FREQ_LBL[p.freq] || ""}</span>${basis}`;
  }
  function w4Cell(p) {
    const m4 = momentum(p.id, 28), m13 = momentum(p.id, WIN13);
    if (!m4 && !m13) {
      return (nPoints.get(p.id) || 0) < 2
        ? `<span class="hint-small" title="新接入：满 2 期后出动量，满 13 周出完整信号">新接入</span>`
        : `<span class="hint-small">—</span>`;
    }
    const main = m4 ? `<span class="chg ${chgCls(m4.pct)}">${fmtPct(m4.pct)}</span>` : `<span class="hint-small">—</span>`;
    const tip = `4周：${m4 ? fmtPct(m4.pct) + `（自${m4.from}）` : "样本不足"}\n13周：${m13 ? fmtPct(m13.pct) + `（自${m13.from}）` : "样本不足"}`;
    return `<span title="${tip}">${main}</span>`;
  }
  function rowHtml({ p }) {
    const r = last.get(p.id);
    if (!r) return "";
    const r13 = range13(p.id);
    const focused = focusPid === p.id;
    const stale = staleNames.has(p.name);
    const hist = seriesData.get(p.id);
    return `<tr class="prow ${focused ? "focused" : ""}" data-pid="${p.id}" title="本地历史 ${nPoints.get(p.id)} 期 · ${p.vendors ? "原厂: " + p.vendors : ""}">
      <td>${p.name}</td>
      <td class="num price">${fmtNum(r.avg)}</td>
      <td class="num">${chgCell(p, r)}</td>
      <td class="num">${w4Cell(p)}</td>
      <td>${r13 ? `<span class="rangebar" title="13周低 ${fmtNum(r13.lo.avg)}（${r13.lo.date}）— 高 ${fmtNum(r13.hi.avg)}（${r13.hi.date}）；页报区间 ${r.low ?? "-"}~${r.high ?? "-"}"><i style="left:${(r13.pos * 100).toFixed(0)}%"></i></span>`
              : `<span class="hint-small" title="${TRI_STATE.accum.txt}">—</span>`}</td>
      <td>${sparkSVG(hist)}</td>
      <td><span class="src-tag ${srcCls(p.source)}">${SRC_TAG[p.source] || p.source}</span>${p.freq !== "daily" ? `<span class="freq-tag ${stale ? "stale" : ""}">${FREQ_LBL[p.freq] || ""}更</span>` : ""}</td>
      <td class="datecell ${stale ? "stale" : ""}" title="${stale ? "超 1.5 倍更新周期未更新" : ""}">${r.date}</td>
    </tr>`;
  }
  function renderTable() {
    document.querySelectorAll("#snap th").forEach(th => {
      const arr = th.querySelector(".arr");
      if (arr) arr.remove();
      if (sortKey && th.dataset.k === sortKey) {
        th.insertAdjacentHTML("beforeend", `<span class="arr">${sortDir > 0 ? "▲" : "▼"}</span>`);
      }
    });
    const body = document.getElementById("snapBody");
    const matchFilter = p => {
      if (!widthFilter) return true;
      const r = last.get(p.id);
      if (!r || r.chg == null) return widthFilter === "flat" && false;
      return widthFilter === "up" ? r.chg > 0 : widthFilter === "down" ? r.chg < 0 : r.chg === 0;
    };
    if (sortKey) {
      const rows = [];
      for (const p of D.products) {
        if (p.tier !== 1 && !selected.has(p.id)) continue;
        if (!matchFilter(p)) continue;
        const r = last.get(p.id);
        rows.push({ p, price: r && r.avg, chg: r && r.chg, date: r && r.date,
          src: SRC_TAG[p.source] || p.source, name: p.name,
          w4: (() => { const m = momentum(p.id, 28); return m ? m.pct : null; })() });
      }
      rows.sort((a, b) => {
        const va = a[sortKey], vb = b[sortKey];
        if (va == null) return 1; if (vb == null) return -1;
        return (typeof va === "number" ? va - vb : String(va).localeCompare(String(vb))) * sortDir;
      });
      body.innerHTML = rows.map(rowHtml).join("");
      return;
    }
    let html = "";
    for (const k of groupKeys) {
      const [source, family, section] = k.split("|");
      const items = groups.get(k).slice().sort((a, b) => a.name.localeCompare(b.name)).filter(matchFilter);
      if (!items.length) continue;
      html += `<tr class="sec"><td colspan="8">${SRC_LABEL[source] || source} · ${family}${section ? " · " + (SECTION_TITLES[section] || section) : ""}</td></tr>`;
      html += items.map(p => rowHtml({ p })).join("");
    }
    // 二梯队
    const t2 = tier2.filter(matchFilter).sort((a, b) => a.name.localeCompare(b.name));
    if (t2.length) {
      html += `<tr class="sec"><td colspan="8">更多品种 · 二梯队（默认折叠）</td></tr>`;
      html += t2.map(p => rowHtml({ p })).join("");
    }
    body.innerHTML = html;
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
      else if (sortDir === -1) { sortDir = 1; }
      else { sortKey = null; }
      renderTable();
    });
  });

  // 宽度小条（降级到表头，标有效样本 N；点击筛选）
  function renderWidthStrip() {
    const vals = [...selected].map(id => last.get(id)).filter(r => r && r.chg != null);
    const up = vals.filter(r => r.chg > 0).length;
    const dn = vals.filter(r => r.chg < 0).length;
    const fl = vals.length - up - dn;
    const seg = (key, label, n, cls) =>
      `<span class="btn" data-wf="${key}" style="${widthFilter === key ? "color:var(--text);border-color:var(--accent)" : ""}">${label} ${n}</span>`;
    document.getElementById("widthStrip").innerHTML =
      `<span class="hint-small">有效样本 ${vals.length}：</span>
       <span class="chg up">▲ ${up} 涨</span><span class="chg flat">— ${fl} 平</span><span class="chg down">▼ ${dn} 跌</span>
       ${seg("up", "筛涨", up)}${seg("flat", "筛平", fl)}${seg("down", "筛跌", dn)}
       ${widthFilter ? `<span class="btn" data-wf="">取消</span>` : ""}`;
  }
  document.getElementById("widthStrip").addEventListener("click", e => {
    const k = e.target.dataset ? e.target.dataset.wf : null;
    if (k === undefined || k === null) return;
    widthFilter = k === "" || k === widthFilter ? null : k;
    renderWidthStrip(); renderTable();
  });

  // ---------- 导出（Q3 CSV / M1 晨报） ----------
  function chgBasisOf(arr, i) {
    return arr[i].chgSrc ? (arr[i].chgSrc === "源" ? "source" : "derived") : "";
  }
  document.getElementById("csvBtn").onclick = () => {
    const lines = ["source,family,section,name,unit,freq,tier,date,avg,high,low,change_pct,chg_basis"];
    for (const p of D.products) {
      const arr = seriesData.get(p.id) || [];
      for (let i = 0; i < arr.length; i++) {
        const r = arr[i];
        const esc = s => /[",]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
        lines.push([p.source, p.family, p.section, esc(p.name), p.unit, p.freq, p.tier,
          r.date, r.avg, r.high ?? "", r.low ?? "", r.chg ?? "", chgBasisOf(arr, i)].join(","));
      }
    }
    lines.push(`# 口径：CFM=评估价，TF=盘平均/合约口径，两源独立不混算`);
    lines.push(`# 统计窗口：13周区间/4周动量/异动z分统一91天；走势线=全史`);
    lines.push(`# 审计：${audit.pass ? "PASS" : "FAIL"} ${audit.n} 项 @ ${audit.at}`);
    const blob = new Blob(["\uFEFF" + lines.join("\n")], { type: "text/csv;charset=utf-8" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `sp_${latestDate.replace(/-/g, "")}.csv`;
    a.click();
    URL.revokeObjectURL(a.href);
  };
  document.getElementById("reportBtn").onclick = () => {
    const idxK = [kpiInfo(["DRAM指数"]), kpiInfo(["NAND指数"])];
    const items = moversList().slice(0, 3);
    const since = k => {
      const arr = k.hist;
      return arr.length > 1 ? fmtPct((arr[arr.length - 1].avg / arr[0].avg - 1) * 100).replace("▲ ", "").replace("▼ ", "-") : "—";
    };
    const md = [
      `**存储价格晨报 · 数据截止 ${latestDate}**`,
      `${tri.txt} · 审计 ${audit.pass ? "PASS" : "FAIL"} ${audit.n} 项 · 生成 ${D.generatedAt.replace("T", " ")}`,
      "",
      `指数：DRAM ${fmtNum(kpiInfo(["DRAM指数"]).cur.avg)}（自${kpiInfo(["DRAM指数"]).hist[0].date.slice(0, 7)} ${since(kpiInfo(["DRAM指数"]))}）｜NAND ${fmtNum(kpiInfo(["NAND指数"]).cur.avg)}（自${kpiInfo(["NAND指数"]).hist[0].date.slice(0, 7)} ${since(kpiInfo(["NAND指数"]))}）`,
      items.length ? `最新异动（13周z分）：\n${items.map((i, ix) =>
        `${ix + 1}. ${i.z > 0 ? "▲" : "▼"} ${SRC_TAG[i.p.source]}·${i.p.name} ${fmtPct(i.r.chg)}（z=${i.z.toFixed(1)}，${i.r.date}）`).join("\n")}` : "",
      "",
      `> 口径：CFM=评估价，TF=盘平均/合约口径，两源独立不混算；明细见看板。`,
    ].filter(Boolean).join("\n");
    navigator.clipboard.writeText(md).then(
      () => { document.getElementById("reportBtn").textContent = "已复制 ✓";
              setTimeout(() => document.getElementById("reportBtn").textContent = "复制晨报", 1500); },
      () => alert(md));
  };

  // ---------- hash v1（队尾实现：三键 + v1 前缀 + 静默回退） ----------
  function syncHash() {
    try {
      location.replace(`#v1=` + encodeURIComponent(
        `s=${[...selected].join(",")}|r=${rangeDays}|m=${mode}`));
    } catch (e) { /* 静默 */ }
  }
  function loadHash() {
    try {
      if (!location.hash.startsWith("#v1=")) return;
      const parts = decodeURIComponent(location.hash.slice(4)).split("|");
      for (const part of parts) {
        const [k, v] = part.split("=");
        if (k === "s") {
          const ids = v.split(",").map(Number).filter(id => byId.has(id));
          if (ids.length) { selected.clear(); ids.forEach(id => selected.add(id)); }
        } else if (k === "r" && ["0", "7", "30", "90"].includes(v)) {
          rangeDays = +v;
        } else if (k === "m" && ["price", "norm"].includes(v)) {
          mode = v;
        }
      }
    } catch (e) { /* 静默回默认 */ }
  }

  // ---------- 初始化 ----------
  loadHash();
  // 窗口按钮实际天数（N5）
  const spanDays = dayDiff(allDates[allDates.length - 1], allDates[0]);
  document.querySelector('#range [data-r="0"]').textContent = `全部(${spanDays}天)`;
  // 恢复 hash 对应的按钮高亮
  document.querySelectorAll('#range button').forEach(b => b.classList.toggle("on", +b.dataset.r === rangeDays));
  document.querySelectorAll('#mode button').forEach(b => b.classList.toggle("on", b.dataset.m === mode));

  const movers = moversList();
  renderKpis(movers[0] || null);
  renderMovers(movers);
  renderTree();
  renderTable();
  renderWidthStrip();
  renderChart();
})();
