/* AI 需求监控 · 信号板 —— 结论横幅 / 三层状态矩阵 / capex·WDC 图 / DC 序列 / 锚点 / CSP 台账 */
(function () {
  const D = window.SIGNAL_DATA || window.STORAGE_DATA;
  if (!D) return;
  const FONT = { fontFamily: '-apple-system,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif', fontSize: 10.5, color: '#94a3b8' };
  const $ = id => document.getElementById(id);
  const fmtN = n => n == null ? '—' : Number(n).toLocaleString('zh-CN', { maximumFractionDigits: 1 });

  const S = D.signals || {};
  const L = S.layers || {};
  const stCls = s => ({ ok: 'ok', amber: 'wa', red: 'al', nodata: 'nt' }[s] || 'nt');
  const stTxt = s => ({ ok: '正常', amber: '观察', red: '行动', nodata: '无数据' }[s] || s);
  const stTone = s => ({ ok: 'st-ok-t', amber: 'st-wa-t', red: 'st-al-t' }[s] || '');
  const bulbCls = s => ({ ok: 'green', amber: 'amber', red: 'red' }[s] || 'amber');

  /* ---- 顶栏 + 结论横幅 ---- */
  document.getElementById('gen').textContent = (D.generatedAt || '').replace('T', ' ');
  const audit = D.audit || { pass: true, n: 0, items: [], at: '' };
  if (S.total != null) {
    const la = L.A || { score: 30, status: 'nodata' }, lb = L.B || { score: 30, status: 'nodata' },
      lc = L.C || { score: 10, status: 'ok' };
    for (const [id, ly] of [['bulbA', la], ['bulbB', lb], ['bulbC', lc]])
      $(id).className = 'bulb ' + bulbCls(ly.status);
    $('verdict').textContent = S.verdict || '—';
    const drivers = [];
    const walk = (items) => {
      for (const [k, it] of Object.entries(items || {})) {
        if (it.status === 'red') drivers.push(`<b>${k}</b> 行动级`);
        else if (it.status === 'amber') {
          const note = { A1: `篮子中位 ${it.value}%(WDC ${it.worst ? it.worst.dd : '?'}%)`,
            A2: `120 日通道 ${it.quantile}% 分位`, B1: `二阶导 ${(it.d2 || []).join('/')}`,
            B2: `最紧 ${it.worst ? it.worst.sym + ' ' + it.worst.ratio + '%' : ''}` }[k];
          if (note) drivers.push(`<b>${k}</b> ${note}`);
        }
      }
    };
    walk(la.items); walk(lb.items);
    $('drv').innerHTML = drivers.length
      ? `<b>驱动项:</b>${drivers.join(' · ')}`
      : '当前无观察/行动级指标';
    $('cmeta').innerHTML = `最后复核 ${(S.at || '').replace('T', ' ').slice(0, 16)}<br>下次自动:随每日 update`;
    $('total').innerHTML = `${S.total}<small> /100</small>`;
    $('thermoFill').style.width = S.total + '%';
    $('tiers').innerHTML = [['A 定价', la, 45], ['B 质量', lb, 40], ['C 结构', lc, 15]].map(([n, ly, w]) =>
      `<div class="trow"><span style="width:56px;color:var(--sub)">${n}</span>
       <div class="bar"><i style="width:${ly.score}%;background:${{ ok: '#10b981', amber: '#f59e0b', red: '#ef4444', nodata: '#94a3b8' }[ly.status]}"></i></div>
       <span class="num">${ly.score}</span><span class="bdg ${stCls(ly.status)}"><i></i>${stTxt(ly.status)}</span>
       <span class="wt" style="margin-left:2px">${w}%</span></div>`).join('');
    for (const [id, ly] of [['stA', la], ['stB', lb], ['stC', lc]]) {
      $(id).className = 'st ' + stTone(ly.status);
      $(id).textContent = (ly.status === 'nodata' ? '— 无数据' : `${stTxt(ly.status)} ${ly.score}`);
    }
  }
  $('caliberBody').innerHTML =
    `<b>读数规则</b>:单层触发 = 黄;同层两项或跨层一项 = 橙;<b>跨层共振 = 红</b>,行动由人决定。
     状态灯按固定阈值(A1 回撤中位 ≥25% 黄 / ≥40% 或单只 ≤-45% 红;B2 ≥70% 黄 / ≥100% 红;B1 二阶导 <0 黄),
     数据累积后切换历史分位数。综合读数 = 三层加权和(A45/B40/C15),权重随调研滚动修正;<b>机器只统计现象,不输出退出概率</b>。<br>
     <b>数据源</b>:A 层新浪美股(免费匿名,日频);B1 高盛台账常量(人工);B2 SEC XBRL companyconcept(免费机读,注意 AMZN capex 记在
     PaymentsToAcquireProductiveAssets tag);B4 dc.py(SEC 8-K,季度人工追加 URL);C 层人工台账(v2 建自动观测)。<br>
     <b>审计</b>(${audit.pass ? 'PASS' : 'FAIL'} ${audit.n} 项 · ${(audit.at || '').replace('T', ' ')}):
     <li>${(audit.items || []).map(c => `[${c.status}] ${c.name}——${c.note || ''}`).join('</li><li>')}</li>`;

  /* ---- ECharts 公共 ---- */
  function spark(id, data, color) {
    if (!data || !data.length) return;
    echarts.init($(id), null, { height: 34 }).setOption({
      grid: { left: 0, right: 0, top: 2, bottom: 0 },
      xAxis: { type: 'category', show: false, data: data.map((_, i) => i) },
      yAxis: { type: 'value', show: false },
      series: [{ type: 'line', data, smooth: .35, symbol: 'none',
        lineStyle: { width: 1.6, color },
        areaStyle: { color: new echarts.graphic.LinearGradient(0, 0, 0, 1,
          [{ offset: 0, color: color + '38' }, { offset: 1, color: color + '00' }]) } }]
    });
  }

  /* ---- A/B/C 卡 ---- */
  const A = (L.A && L.A.items) || {}, B = (L.B && L.B.items) || {};
  if (A.A1 && A.A1.value != null) {
    $('v_a1').textContent = A.A1.value + '%';
    $('v_a1').style.color = { red: 'var(--up)', amber: 'var(--wa)' }[A.A1.status] || 'var(--txt)';
    $('d_a1').textContent = A.A1.worst ? `篮内最差 ${A.A1.worst.sym} ${A.A1.worst.dd}% · ${A.A1.rows.length} 只` : `${A.A1.rows.length} 只`;
  }
  if (A.A2 && A.A2.value != null) {
    $('v_a2').textContent = A.A2.value;
    $('d_a2').textContent = `120 日通道 ${A.A2.quantile}% 分位`;
    spark('sp_a2', A.A2.spark, '#f59e0b');
  }
  if (B.B1) {
    $('v_b1').textContent = (B.B1.d2 || []).join(' / ') || '—';
    $('d_b1').textContent = `增速序列 ${B.B1.growth.join('% → ')}% · ${B.B1.source}`;
    spark('sp_b1', B.B1.growth, '#f59e0b');
  }
  if (B.B2 && B.B2.rows && B.B2.rows.length) {
    $('v_b2').textContent = B.B2.rows.map(r => r.ratio).join('·') + '%';
    $('v_b2').style.color = B.B2.status === 'red' ? 'var(--up)' : 'var(--txt)';
    $('d_b2').textContent = B.B2.rows.map(r => `${r.sym} ${r.ratio}%`).join(' · ') + `(frame ${B.B2.frame})`;
    spark('sp_b2', B.B2.rows.map(r => r.ratio), '#ef4444');
  }
  if (B.B4 && B.B4.rows && B.B4.rows.length) {
    const r0 = B.B4.rows[0];
    $('v_b4').innerHTML = r0.yoy != null ? (r0.yoy > 0 ? '+' : '') + r0.yoy + '%' : '—';
    $('d_b4').textContent = B.B4.rows.map(r => `${r.ticker} ${fmtN(r.musd)}M`).join(' · ');
    spark('sp_b4', B.B4.rows.map(r => r.musd), '#10b981');
  }

  /* ---- capex 柱图(B1) ---- */
  if (B.B1 && B.B1.growth) {
    echarts.init($('ch_capex')).setOption({
      grid: { left: 46, right: 16, top: 28, bottom: 26 },
      tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' }, backgroundColor: '#fff',
        borderColor: '#e5e7eb', textStyle: { color: '#0f172a', fontSize: 11.5, ...FONT } },
      xAxis: { type: 'category', data: ['2026E', '2027E', '2028E'], axisTick: { show: false },
        axisLine: { show: false }, axisLabel: { ...FONT, fontSize: 11, color: '#64748b' } },
      yAxis: { type: 'value', max: 100, axisLabel: { ...FONT, formatter: v => '+' + v + '%' },
        splitLine: { lineStyle: { color: '#eef2f6' } } },
      series: [{ type: 'bar', barWidth: '42%',
        data: B.B1.growth.map((g, i) => ({ value: g,
          itemStyle: { color: ['#4f46e5', '#818cf8', '#c7d2fe'][i] } })),
        itemStyle: { borderRadius: [6, 6, 0, 0] },
        label: { show: true, position: 'top', font: { fontWeight: 650, size: 12 }, color: '#0f172a',
          formatter: p => '+' + p.value + '%' } }]
    });
  }

  /* ---- WDC 价格先杀线 ---- */
  const a1w = A.A1 || {};
  if (a1w.worst_daily && a1w.worst_daily.length > 5) {
    $('wdc_dd').textContent = `距 52 周高 ${a1w.worst.dd}%`;
    echarts.init($('ch_wdc')).setOption({
      grid: { left: 52, right: 14, top: 14, bottom: 24 },
      tooltip: { trigger: 'axis', backgroundColor: '#fff', borderColor: '#e5e7eb',
        textStyle: { color: '#0f172a', fontSize: 11.5, ...FONT } },
      xAxis: { type: 'category', data: a1w.worst_daily.map(x => x.d), boundaryGap: false,
        axisTick: { show: false }, axisLine: { show: false }, axisLabel: { ...FONT, fontSize: 10.5 } },
      yAxis: { type: 'value', scale: true, axisLabel: { ...FONT, formatter: v => '$' + v },
        splitLine: { lineStyle: { color: '#eef2f6' } } },
      series: [{ type: 'line', data: a1w.worst_daily.map(x => x.c), smooth: .25,
        symbol: 'circle', symbolSize: 4, showSymbol: false,
        lineStyle: { width: 1.8, color: '#ef4444' },
        areaStyle: { color: new echarts.graphic.LinearGradient(0, 0, 0, 1,
          [{ offset: 0, color: '#ef444426' }, { offset: 1, color: '#ef444400' }]) },
        markLine: { silent: true, symbol: 'none',
          lineStyle: { color: '#ef4444', type: 'dashed', width: 1 },
          label: { show: true, position: 'insideStartTop', color: '#b91c1c', fontSize: 10.5,
            formatter: `52 周高 $${a1w.worst.high52w}` },
          data: [{ yAxis: a1w.worst.high52w }] } }]
    });
  } else {
    $('wdc_dd').textContent = '待日线数据';
  }

  /* ---- DC 收入序列 ---- */
  const dc = D.dcSeries || [];
  $('dcBody').innerHTML = dc.slice().sort((a, b) => a.ticker < b.ticker ? -1 : 1)
    .map(r => `<tr>
      <td><b>${r.ticker}</b></td><td class="num">${r.period}</td><td>${r.metric}</td>
      <td class="num">${r.value_musd != null ? fmtN(r.value_musd) : '<span style="color:var(--faint)">仅披露增速</span>'}</td>
      <td class="num">${r.yoy_pct != null ? (r.yoy_pct > 0 ? '+' : '') + r.yoy_pct + '%' : '—'}</td>
      <td class="wrap"><a href="${r.url}" target="_blank" rel="noopener">${(r.text || '').slice(0, 60)}</a></td></tr>`).join('');

  /* ---- 锚点时间线 + 明细 ---- */
  const anchors = (D.anchors || []).slice().sort((a, b) => a.date < b.date ? 1 : -1);
  $('anchorLine').innerHTML = anchors.map(a => `<div class="anchor">
      <span class="ad">${a.date}</span><span class="atext"><b>${a.item}</b>：${a.value}</span>
      <span class="asrc">口径：${a.caliber} · ${a.source}</span></div>`).join('')
    || '<div class="hint-small">无锚点</div>';
  $('anchorBody').innerHTML = anchors.map(a => `<tr>
      <td class="num">${a.date}</td><td>${a.cat}</td><td><b>${a.item}</b></td>
      <td class="wrap">${a.value}</td><td>${a.caliber}</td>
      <td class="wrap" style="color:var(--faint)">${a.source}</td></tr>`).join('');

  /* ---- CSP 台账 ---- */
  const BASIS = { event: '事件', period: '期间', state: '状态', calendar: '日历' };
  $('cspBody').innerHTML = (D.cspLedger || []).slice()
    .sort((a, b) => a.date < b.date ? 1 : -1)
    .map(r => `<tr>
      <td class="num">${r.date}</td><td>${BASIS[r.basis] || r.basis || '—'}</td>
      <td class="wrap"><b>${r.entity}</b> · ${r.item}:${r.value}</td>
      <td class="wrap" style="color:var(--faint)">${r.source}${r.confidence ? ' · ' + r.confidence : ''}</td></tr>`).join('');
})();
