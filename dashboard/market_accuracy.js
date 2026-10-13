// The Market and Accuracy tabs. They sit in their own file because the dashboard refuses any one page file over 256 KB;
// index.html loads this before app.js, and app.js calls window.DPM_TABS once its own helpers exist, passing the ones
// these tabs use. Nothing else is shared, and the code is the same as when it was part of app.js.
window.DPM_TABS = (h) => {
  const { $, FEAT, TYPES, TYPE_NAME, TYPE_SHORT, bars, cell, cleanAxis, failed, fix0, fresh, gbp, gbpK, getConf, getIndex, getPoss, kv, lineChart, median, num, ok, parseMonth, pill, pts, rows, safe, sgn, state, tip, typed } = h;
  state.possMetric = 'standard';
  document.querySelectorAll('#poss-metric button').forEach((b) => b.addEventListener('click', () => {
    state.possMetric = b.dataset.m; document.querySelectorAll('#poss-metric button').forEach((x) => x.setAttribute('aria-pressed', String(x === b))); safe('court claims', renderPoss);
  }));
  const renderPoss = () => {
    const box = $('#poss-chart'); if (failed(box, ['possession'])) return;
    const P = getPoss(); if (!P) return;
    const m = state.possMetric, A3 = [['Doncaster', dash.colors[0]], ['Yorkshire and The Humber', dash.colors[1]], ['England', 'var(--cds-chart-reference)']];
    const d = P.latest('Doncaster', m), y = P.latest('Yorkshire and The Humber', m), e = P.latest('England', m), rk = P.latest('Doncaster', m + '_rank');
    const f1 = (v) => (v && isFinite(v.rate) ? d3.format('.1f')(v.rate) : '—');
    $('#poss-d').textContent = f1(d); $('#poss-y').textContent = f1(y); $('#poss-e').textContent = f1(e);
    const what = { standard: 'standard claims', accelerated: 'accelerated claims', bailiff: 'bailiff evictions' }[m];
    $('#poss-d-n').textContent = d ? `${d3.format(',')(d.count)} ${what} in the year to ${P.label(d.quarter)}` : '—';
    $('#poss-rank').textContent = rk ? `Higher than ${Math.round(rk.rate)}%` : '—';
    $('#poss-rank-n').textContent = rk ? `of ${d3.format(',')(rk.count)} English council areas` : '—';
    const series = A3.map(([a, c]) => ({ name: a, color: c, values: P.series(a, m).map((r) => ({ date: P.date(r.quarter), v: r.rate })) }));
    const lg = $('#poss-legend'); lg.replaceChildren();
    series.forEach((s) => { const sp = document.createElement('span'), ic = document.createElement('i'); ic.style.background = s.color; sp.append(ic, s.name); lg.appendChild(sp); });
    lineChart(box, series, { label: `Landlord possession ${what} per 1,000 privately rented homes`, yFmt: d3.format('.1f'), tipFmt: (v) => `${d3.format('.1f')(v)} per 1,000 rented homes`, yZero: true,
      xFmt: d3.utcFormat('%Y'), tipX: (dt) => `Year to ${d3.utcFormat('%B %Y')(dt)}`, endLabels: true, endFmt: d3.format('.1f'), height: 240 });
  };
  const renderMarket = () => {
    safe('court claims', renderPoss);
    const idx = getIndex();
    if (idx && !failed($('#index-chart'), ['price_index'])) {
      const pts = [...idx.i15.entries()].filter(([k]) => k >= '2015-01').map(([k, v]) => ({ date: parseMonth(k), v: v * 100 })).sort((a, b) => a.date - b.date);
      lineChart($('#index-chart'), [{ name: 'Index', color: dash.colors[0], values: pts }], { label: 'Doncaster house price index since 2015', yFmt: d3.format('.0f'), tipFmt: d3.format('.1f'), height: 260 });
      const last = pts.at(-1), yAgo = pts[pts.length - 13];
      $('#m-index').textContent = d3.format('.1f')(last.v); $('#m-index-note').textContent = d3.utcFormat('%B %Y')(last.date) + ' (Jan 2015 = 100)';
      $('#m-yoy').textContent = yAgo ? sgn((last.v / yAgo.v - 1) * 100) : '—';
    }
    if (ok('model_meta')) { const r = rows('model_meta').find((x) => x.key === 'n_sales_model'); if (r) $('#m-n').textContent = d3.format(',')(num(r.value)); }
    if (ok('tier_index') && !failed($('#tier-chart'), ['tier_index'])) {
      const T = ['Cheaper areas', 'Middle areas', 'Dearer areas'], tr = rows('tier_index');
      const series = T.map((name, i) => ({ name, color: dash.colors[i], values: tr.filter((r) => r.tier === name).map((r) => ({ date: parseMonth(r.month), v: num(r.index) })).sort((a, b) => a.date - b.date) }));
      const lg = $('#tier-legend'); lg.replaceChildren();
      series.forEach((s) => { const sp = document.createElement('span'), ic = document.createElement('i'); ic.style.background = s.color; sp.append(ic, s.name); lg.appendChild(sp); });
      lineChart($('#tier-chart'), series, { label: 'Price index by area tier', yFmt: d3.format('.0f'), tipFmt: d3.format('.1f'), endLabels: true, endFmt: d3.format('.0f'), height: 260 });
      const lastv = series.map((s) => s.values.at(-1)).filter(Boolean);
      if (lastv.length === 3) $('#tier-note').textContent = `Quality-adjusted price index for postcode sectors split into thirds by their 2015-2019 median price (January 2015 = 100). Since then: cheaper areas ${sgn(lastv[0].v - 100, 0)}, middle ${sgn(lastv[1].v - 100, 0)}, dearer ${sgn(lastv[2].v - 100, 0)}.`;
    }
    if (ok('market_monthly') && !failed($('#type-chart'), ['market_monthly'])) {
      const mm = rows('market_monthly'), months = [...new Set(mm.map((r) => r.month))].sort().slice(0, -1);
      const series = TYPES.map((t, i) => {
        const byM = new Map(mm.filter((r) => r.type === t).map((r) => [r.month, num(r.median_price)]));
        return { name: TYPE_SHORT[t], color: dash.colors[i], values: months.map((mo, j) => ({ date: parseMonth(mo), v: median(months.slice(Math.max(0, j - 2), j + 1).map((x) => byM.get(x))) })) };
      });
      const lg = $('#type-legend'); lg.replaceChildren();
      series.forEach((s) => { const sp = document.createElement('span'), ic = document.createElement('i'); ic.style.background = s.color; sp.append(ic, s.name); lg.appendChild(sp); });
      lineChart($('#type-chart'), series, { label: 'Median price by property type', yFmt: (v) => '£' + d3.format(',.0f')(v / 1000) + 'k', tipFmt: gbp, endLabels: true, endFmt: gbpK, yMin: 0, height: 260 });
      drawVolume(mm);
    }
  };
  const drawVolume = (mm) => {
    const box = $('#volume-chart'); fresh(box);
    const tot = new Map(); mm.forEach((r) => tot.set(r.month, (tot.get(r.month) || 0) + num(r.sales)));
    const all = [...tot.keys()].sort(), data = all.map((k) => ({ m: k, date: parseMonth(k), n: tot.get(k) }));
    const W = Math.max(280, box.clientWidth), H = 260, m = { t: 12, r: 12, b: 26, l: 40 };
    const x = d3.scaleBand(data.map((d) => d.m), [m.l, W - m.r]).padding(0.2), y = d3.scaleLinear([0, d3.max(data, (d) => d.n) * 1.05], [H - m.b, m.t]).nice();
    const svg = d3.select(box).append('svg').attr('width', '100%').attr('viewBox', `0 0 ${W} ${H}`).attr('role', 'img').attr('aria-label', 'Sales per month');
    const gy = svg.append('g').attr('transform', `translate(${m.l},0)`).call(d3.axisLeft(y).ticks(4).tickSize(-(W - m.l - m.r))); cleanAxis(gy); gy.select('.domain').remove();
    const years = data.filter((d) => d.m.endsWith('-01') && (+d.m.slice(0, 4)) % (W < 500 ? 3 : 2) === 1).map((d) => d.m);
    const gx = svg.append('g').attr('transform', `translate(0,${H - m.b})`).call(d3.axisBottom(x).tickValues(years).tickFormat((s) => s.slice(0, 4)).tickSizeOuter(0)); cleanAxis(gx);
    const t = tip(box), lastM = all.at(-1);
    svg.selectAll('rect.b').data(data).join('rect').attr('class', 'b').attr('x', (d) => x(d.m)).attr('width', x.bandwidth()).attr('y', (d) => y(d.n)).attr('height', (d) => y(0) - y(d.n))
      .attr('rx', Math.min(2, x.bandwidth() / 2)).attr('fill', (d) => (d.m === lastM ? 'var(--cds-chart-muted)' : dash.colors[2]))
      .on('mousemove', (e, d) => { const [px, py] = d3.pointer(e, box); t.show([['t', d3.utcFormat('%B %Y')(d.date)], ['', d3.format(',')(d.n) + ' sales' + (d.m === lastM ? ' (incomplete)' : '')]], px, py); })
      .on('mouseleave', () => t.hide());
  };
  const renderAccuracy = () => {
    if (ok('strict_eval')) {
      const R = rows('strict_eval'), tb = $('#strict-table tbody'); tb.replaceChildren();
      const pts = (x) => { const r = fix0(x * 100, 2); return (r > 0 ? '+' : r < 0 ? '−' : '') + d3.format('.2f')(Math.abs(r)) + ' pts'; };
      R.forEach((r) => {
        const tr = document.createElement('tr'), cur = r.variant === 'current'; cell(tr, r.label); cell(tr, d3.format(',')(num(r.n)), 'r'); cell(tr, d3.format('.2%')(num(r.mdape)), 'r');
        cell(tr, cur ? `${d3.format('.2%')(num(r.mdape_min))} to ${d3.format('.2%')(num(r.mdape_max))} over seeds` : `${pts(num(r.diff_vs_published))} (${pts(num(r.diff_min))} to ${pts(num(r.diff_max))})`, 'r');
        cell(tr, d3.format('.1%')(num(r.within10)), 'r'); tb.appendChild(tr);
      });
      const cur = R.find((r) => r.split === 'test_2025_26' && r.variant === 'current'), st = R.find((r) => r.split === 'test_2025_26' && r.variant === 'strict');
      if (cur && st) $('#strict-note').textContent = `${d3.format(',')(num(cur.n_later_cert))} of the ${d3.format(',')(num(cur.n))} test sales (${d3.format('.1%')(num(cur.n_later_cert) / num(cur.n))}) used a later certificate. Under the strict rule their median error rises from ${d3.format('.1%')(num(cur.mdape_later_cert))} to ${d3.format('.1%')(num(st.mdape_later_cert))} (averages over ${cur.seeds} seeds). Across all test sales the change is ${pts(num(st.diff_vs_published))}, against ${d3.format('.2f')((num(cur.mdape_max) - num(cur.mdape_min)) * 100)} points between seeds of the published model: little aggregate change.`;
    }
    if (ok('confidence') && ok('accuracy')) {
      const tb = $('#typed-table tbody'), Aa = rows('accuracy'); tb.replaceChildren();
      const g = (mt) => num((Aa.find((x) => x.model === 'dashboard' && x.split === 'test_2025_26' && x.metric === mt) || {}).value);
      const add = (name, md, cov) => { const tr = document.createElement('tr'); cell(tr, name); cell(tr, d3.format('.1%')(md), 'r'); cell(tr, isFinite(cov) ? d3.format('.0%')(cov) : '—', 'r'); tb.appendChild(tr); };
      add('Address picked: certificate and last sale filled in', g('mdape'), g('coverage_80'));
      rows('confidence').filter((r) => r.kind === 'typed').forEach((r) => add(r.level === 'area only' ? 'Postcode, type and floor area only' : 'Postcode and type only', num(r.mdape), num(r.coverage)));
    }
    if (ok('accuracy')) {
      const Aa = rows('accuracy'), g = (mdl, mt) => num((Aa.find((x) => x.model === mdl && x.split === 'test_2025_26' && x.metric === mt) || {}).value);
      $('#a-mdape').textContent = d3.format('.1%')(g('dashboard', 'mdape')); $('#a-w10').textContent = d3.format('.0%')(g('dashboard', 'within10'));
      $('#a-w20').textContent = d3.format('.0%')(g('dashboard', 'within20')); $('#a-cov').textContent = d3.format('.0%')(g('dashboard', 'coverage_80'));
      const tb = $('#breakdown-table tbody'); tb.replaceChildren();
      const add = (name, n, md, w10) => { const tr = document.createElement('tr'); cell(tr, name); cell(tr, d3.format(',')(n), 'r'); cell(tr, d3.format('.1%')(md), 'r'); cell(tr, d3.format('.0%')(w10), 'r'); tb.appendChild(tr); };
      add('Last sale known', g('dashboard_prior_sale', 'n'), g('dashboard_prior_sale', 'mdape'), g('dashboard_prior_sale', 'within10'));
      add('No previous sale', g('dashboard_no_prior_sale', 'n'), g('dashboard_no_prior_sale', 'mdape'), g('dashboard_no_prior_sale', 'within10'));
      rows('accuracy_breakdown').forEach((r) => add(r.dimension === 'type' ? TYPE_NAME[r.group] : r.dimension === 'band' ? 'Price ' + r.group.replace('-', '–') : r.group, num(r.n), num(r.mdape), num(r.within10)));
    }
    if (ok('ablation') && !failed($('#ablation-chart'), ['ablation'])) bars($('#ablation-chart'), rows('ablation').map((r) => ({ label: r.label.replace(/\s*\((?:v\d+)?(?:,\s*)?(?:final,\s*)?(?:3 seeds)?\)\s*$/, '').replace(/ \(v\d+\)/, ''), v: num(r.mdape) })), { fmt: d3.format('.2%'), accentLast: true, label: 'Median error by data layer', right: 60 });
    if (ok('test_sample') && !failed($('#scatter'), ['test_sample'])) {
      drawScatter(rows('test_sample'));
      const lg = $('#scatter-legend'); lg.replaceChildren();
      TYPES.forEach((t, i) => { const sp = document.createElement('span'), ic = document.createElement('i'); ic.style.background = dash.colors[i]; sp.append(ic, TYPE_NAME[t]); lg.appendChild(sp); });
    }
    renderCompare(); renderBacktest(); renderConfidence(); renderRatio();
    if (ok('feature_importance') && !failed($('#importance'), ['feature_importance'])) bars($('#importance'), rows('feature_importance').map((r) => ({ label: FEAT[r.feature] || r.feature, v: num(r.gain_share) })).sort((a, b) => b.v - a.v).slice(0, 12), { fmt: d3.format('.0%'), accentTop: 3, label: 'Feature importance' });
    if (ok('layer_tests')) {
      const tb = $('#tested-table tbody'); tb.replaceChildren();
      rows('layer_tests').forEach((r) => { const tr = document.createElement('tr'), g = num(r.gain_pts); cell(tr, r.label);
        const sd = num(r.gain_sd);
        cell(tr, (Math.abs(g) < 0.005 ? '' : g > 0 ? '−' : '+') + d3.format('.2f')(Math.abs(g)) + ' pts', 'r'); cell(tr, sd < 0.005 ? '<0.01 pts' : '±' + d3.format('.2f')(sd) + ' pts', 'r');
        const dc = cell(tr, r.decision); if (/^Kept/.test(r.decision)) dc.classList.add('good'); tb.appendChild(tr); });
    }
    if (ok('area_bias')) {
      const tb = $('#areabias-table tbody'); tb.replaceChildren();
      rows('area_bias').forEach((r) => { const tr = document.createElement('tr'); cell(tr, r.sector); cell(tr, r.wards, 'hide-narrow'); cell(tr, d3.format(',')(num(r.n)), 'r');
        const b = cell(tr, sgn(num(r.bias_before_pct)), 'r'); if (Math.abs(num(r.bias_before_pct)) >= 3) b.classList.add('warnc'); cell(tr, sgn(num(r.bias_after_pct)), 'r'); tb.appendChild(tr); });
    }
    if (ok('condition')) {
      const tb = $('#condition-table tbody'); tb.replaceChildren();
      rows('condition').forEach((r) => { const tr = document.createElement('tr'), f = (k) => (r[k] === '' ? '—' : sgn(num(r[k]))); cell(tr, r.label); cell(tr, f('adjustment_pct'), 'r'); cell(tr, f('range_low_pct'), 'r'); cell(tr, f('range_high_pct'), 'r'); cell(tr, r.adjustment_prev_pct == null ? '—' : f('adjustment_prev_pct'), 'r'); cell(tr, r.basis, 'hide-narrow'); tb.appendChild(tr); });
    }
  };
  // ---- against simple methods ----
  const renderCompare = () => {
    if (!ok('method_compare') || failed($('#compare-chart'), ['method_compare'])) return;
    const mc = rows('method_compare').map((r) => ({ ...r, md: num(r.mdape), cov: num(r.coverage), same: num(r.model_same_sales) })).sort((a, b) => a.md - b.md);
    bars($('#compare-chart'), mc.map((r) => ({ label: r.label, v: r.md, accent: r.kind === 'model',
      tip: `${r.label}: median error ${d3.format('.1%')(r.md)}, ${d3.format('.0%')(num(r.within10))} within 10%, values ${d3.format('.0%')(r.cov)} of homes` + (r.kind === 'model' ? '' : `; this model on the same homes ${d3.format('.1%')(r.same)}`) })), { fmt: d3.format('.1%'), label: 'Median error by valuation method', right: 52 });
    const hpi = mc.find((r) => r.method === 'uk_hpi');
    $('#compare-note').textContent = hpi ? `On the homes that had sold before, indexing the last sale with the UK House Price Index is off by ${d3.format('.1%')(hpi.md)} at the median; this model is off by ${d3.format('.1%')(hpi.same)} on the same homes.` : '';
  };
  // ---- year by year ----
  const renderBacktest = () => {
    const box = $('#backtest-chart');
    if (!ok('backtest') || failed(box, ['backtest'])) return;
    fresh(box);
    const d = rows('backtest').map((r) => ({ y: String(r.year), md: num(r.mdape), w10: num(r.within10), n: num(r.n), part: r.partial === '1', to: r.trained_to })).sort((a, b) => a.y.localeCompare(b.y));
    const W = Math.max(280, box.clientWidth), H = 200, m = { t: 22, r: 8, b: 26, l: 8 };
    const x = d3.scaleBand(d.map((r) => r.y), [m.l, W - m.r]).padding(0.28), y = d3.scaleLinear([0, d3.max(d, (r) => r.md) * 1.15], [H - m.b, m.t]);
    const svg = d3.select(box).append('svg').attr('width', '100%').attr('viewBox', `0 0 ${W} ${H}`).attr('role', 'img').attr('aria-label', 'Median error by year');
    svg.append('line').attr('x1', m.l).attr('x2', W - m.r).attr('y1', y(0)).attr('y2', y(0)).attr('stroke', 'var(--cds-chart-axis)');
    const gx = svg.append('g').attr('transform', `translate(0,${H - m.b})`).call(d3.axisBottom(x).tickSize(0).tickFormat((t) => (d.find((r) => r.y === t) || {}).part ? t + '*' : t)); cleanAxis(gx); gx.select('.domain').remove(); gx.selectAll('text').attr('dy', '1.1em');
    const t = tip(box), bw = Math.min(32, x.bandwidth());
    d.forEach((r) => {
      const xx = x(r.y) + (x.bandwidth() - bw) / 2;
      svg.append('rect').attr('x', xx).attr('width', bw).attr('y', y(r.md)).attr('height', y(0) - y(r.md)).attr('rx', 4).attr('fill', dash.colors[0])
        .on('mousemove', (e) => { const [px, py] = d3.pointer(e, box); t.show([['t', r.y + (r.part ? ' (January to August)' : '')], ['', `Median error ${d3.format('.1%')(r.md)}`], ['', `${d3.format('.0%')(r.w10)} within 10%`], ['', `${d3.format(',')(r.n)} sales; trained to ${r.to}`]], px, py); })
        .on('mouseleave', () => t.hide());
      svg.append('text').attr('x', xx + bw / 2).attr('y', y(r.md) - 6).attr('text-anchor', 'middle').attr('fill', 'var(--color-fg)').style('font-size', 'var(--cds-font-size-caption)').style('font-variant-numeric', 'tabular-nums').text(d3.format('.1%')(r.md));
    });
    const lo = d3.min(d, (r) => r.md), hi = d3.max(d, (r) => r.md);
    $('#backtest-note').textContent = `Between ${d3.format('.1%')(lo)} and ${d3.format('.1%')(hi)} every year since 2020, including the 2021 stamp-duty rush and the 2022-23 rate rises.${d.some((r) => r.part) ? ' * January to August.' : ''}`;
  };
  // ---- confidence ----
  const renderConfidence = () => {
    if (!ok('confidence') || failed($('#confidence-chart'), ['confidence'])) return;
    const cr = rows('confidence'), lv = cr.filter((r) => r.kind === 'level'), fl = cr.filter((r) => r.kind === 'filter');
    bars($('#confidence-chart'), lv.map((r, i) => ({ label: `${r.level} · ${d3.format('.0%')(num(r.share))} of homes`, v: num(r.mdape), accent: i === 0,
      tip: `${r.level} confidence: median error ${d3.format('.1%')(num(r.mdape))}, ${d3.format('.0%')(num(r.within10))} within 10%, 80% range held the price for ${d3.format('.0%')(num(r.coverage))}` })), { fmt: d3.format('.1%'), label: 'Median error by confidence level' });
    const k70 = fl.find((r) => num(r.kept) === 0.7), all = fl.find((r) => num(r.kept) === 1);
    const conf = getConf();
    $('#confidence-note').textContent = k70 && all ? `Keeping only the 70% of estimates it is most sure of cuts the median error from ${d3.format('.1%')(num(all.mdape))} to ${d3.format('.1%')(num(k70.mdape))}.${conf && conf.adaptive ? ' Each 80% range now widens or narrows with it.' : ''}` : '';
  };
  // ---- assessor checks ----
  const renderRatio = () => {
    if (!ok('ratio_study') || failed($('#ratio-chart'), ['ratio_study'])) return;
    const rs = rows('ratio_study'), o = rs.find((r) => r.kind === 'overall' && r.group === 'This model'), kv = $('#ratio-kv'); kv.replaceChildren();
    if (o) {
      const cod = num(o.cod), prd = num(o.prd), prb = num(o.prb);
      const add = (k, v, okk, target) => { const dt = document.createElement('dt'), dd = document.createElement('dd'); dt.textContent = k; dd.innerHTML = ''; dd.append(v + '  '); const sp = document.createElement('span'); sp.className = 'pill ' + (okk ? 'good' : 'warnc'); sp.textContent = target; dd.append(sp); kv.append(dt, dd); };
      add('Uniformity (COD)', d3.format('.1f')(cod), cod < 15, cod < 15 ? 'within IAAO standard, under 15' : 'outside IAAO standard, under 15');
      add('Price-related differential (PRD)', d3.format('.3f')(prd), prd >= 0.98 && prd <= 1.03, prd >= 0.98 && prd <= 1.03 ? 'within 0.98-1.03' : 'just outside 0.98-1.03');
      add('Price-related bias (PRB)', d3.format('+.3f')(prb), Math.abs(prb) <= 0.05, `${d3.format('+.0%')(prb)} per doubling of price`);
    }
    const bands = rs.filter((r) => r.kind === 'band');
    divBars($('#ratio-chart'), bands.map((r) => ({ label: r.group, v: num(r.median_ratio) - 1, n: num(r.n) })), { fmt: (v) => (Math.abs(v) < 0.0005 ? '0.0%' : d3.format('+.1%')(v).replace('-', '−')), label: 'Median estimate against sale price, by sale price' });
    $('#ratio-note').textContent = rs.find((r) => r.kind === 'note') ? rs.find((r) => r.kind === 'note').group : '';
  };
  // centred bars for signed values (e.g. over/under-valuation)
  const divBars = (box, d, o) => {
    fresh(box); if (!d.length) return;
    const W = Math.max(280, box.clientWidth), bh = 16, gap = 6, H = d.length * (bh + gap) + 4;
    box.style.minHeight = H + 'px';
    const svg = d3.select(box).append('svg').attr('width', '100%').attr('viewBox', `0 0 ${W} ${H}`).attr('role', 'img').attr('aria-label', o.label);
    let maxw = 0; d.forEach((r) => { const tx = svg.append('text').text(r.label).style('font-size', 'var(--cds-font-size-caption)'); maxw = Math.max(maxw, tx.node().getComputedTextLength()); tx.remove(); });
    const left = Math.min(maxw + 10, W * 0.45), mx = d3.max(d, (r) => Math.abs(r.v)) || 0.01, x = d3.scaleLinear([-mx * 1.25, mx * 1.25], [left + 40, W - 40]);
    svg.append('line').attr('x1', x(0)).attr('x2', x(0)).attr('y1', 0).attr('y2', H).attr('stroke', 'var(--cds-chart-reference)');
    d.forEach((r, i) => {
      const yy = i * (bh + gap) + 2;
      svg.append('text').attr('x', left - 8).attr('y', yy + bh / 2).attr('dy', '0.35em').attr('text-anchor', 'end').attr('fill', 'var(--color-fg-muted)').style('font-size', 'var(--cds-font-size-caption)').text(r.label);
      svg.append('rect').attr('x', Math.min(x(0), x(r.v))).attr('y', yy).attr('height', bh).attr('width', Math.max(2, Math.abs(x(r.v) - x(0)))).attr('rx', 4).attr('fill', r.v > 0 ? dash.colors[1] : dash.colors[0]);
      svg.append('text').attr('x', r.v >= 0 ? x(r.v) + 6 : x(r.v) - 6).attr('text-anchor', r.v >= 0 ? 'start' : 'end').attr('y', yy + bh / 2).attr('dy', '0.35em').attr('fill', 'var(--color-fg)').style('font-size', 'var(--cds-font-size-caption)').style('font-variant-numeric', 'tabular-nums').text(o.fmt(r.v));
    });
  };
  const drawScatter = (data) => {
    const box = $('#scatter'); fresh(box);
    const pts = data.map((r) => ({ a: num(r.price), p: num(r.predicted), t: r.type })).filter((d) => d.a > 0 && d.p > 0);
    const W = Math.max(280, box.clientWidth), H = Math.min(340, W), m = { t: 10, r: 12, b: 30, l: 48 }, lo = 30000, hi = 800000;
    const x = d3.scaleLog([lo, hi], [m.l, W - m.r]).clamp(true), y = d3.scaleLog([lo, hi], [H - m.b, m.t]).clamp(true), ticks = [50000, 100000, 200000, 400000];
    const svg = d3.select(box).append('svg').attr('width', '100%').attr('viewBox', `0 0 ${W} ${H}`).attr('role', 'img').attr('aria-label', 'Predicted against actual sale price, log scale');
    const gx = svg.append('g').attr('transform', `translate(0,${H - m.b})`).call(d3.axisBottom(x).tickValues(ticks).tickFormat(gbpK).tickSize(-(H - m.t - m.b))); cleanAxis(gx); gx.select('.domain').remove();
    const gy = svg.append('g').attr('transform', `translate(${m.l},0)`).call(d3.axisLeft(y).tickValues(ticks).tickFormat(gbpK).tickSize(-(W - m.l - m.r))); cleanAxis(gy); gy.select('.domain').remove();
    svg.append('line').attr('x1', x(lo)).attr('y1', y(lo)).attr('x2', x(hi)).attr('y2', y(hi)).attr('stroke', 'var(--cds-chart-reference)').attr('stroke-dasharray', '4 4');
    svg.append('g').selectAll('circle').data(pts).join('circle').attr('cx', (d) => x(d.a)).attr('cy', (d) => y(d.p)).attr('r', 2.5).attr('fill', (d) => dash.colors[TYPES.indexOf(d.t)] || dash.colors[0]).attr('fill-opacity', 0.45);
    svg.append('text').attr('x', W - m.r).attr('y', H - 4).attr('text-anchor', 'end').attr('fill', 'var(--color-fg-muted)').style('font-size', 'var(--cds-font-size-caption)').text('Actual price →');
    svg.append('text').attr('x', m.l + 4).attr('y', m.t + 12).attr('fill', 'var(--color-fg-muted)').style('font-size', 'var(--cds-font-size-caption)').text('↑ Predicted');
    const t = tip(box), del = d3.Delaunay.from(pts, (d) => x(d.a), (d) => y(d.p)), hl = svg.append('circle').attr('r', 5).attr('fill', 'none').attr('stroke', 'var(--color-fg)').attr('opacity', 0);
    svg.append('rect').attr('x', m.l).attr('y', m.t).attr('width', W - m.l - m.r).attr('height', H - m.t - m.b).attr('fill', 'transparent')
      .on('mousemove', (e) => { const [px, py] = d3.pointer(e), d = pts[del.find(px, py)]; if (!d) return; hl.attr('cx', x(d.a)).attr('cy', y(d.p)).attr('opacity', 1);
        const [bx, by] = d3.pointer(e, box); t.show([['t', TYPE_NAME[d.t]], ['', 'Sold ' + gbp(d.a)], ['', 'Predicted ' + gbp(d.p) + ' (' + sgn((d.p / d.a - 1) * 100, 0) + ')']], bx, by); })
      .on('mouseleave', () => { hl.attr('opacity', 0); t.hide(); });
  };

  return { renderMarket, renderAccuracy };
};
