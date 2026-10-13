// Three views of the deal on the Investing tab: what the mortgage rate does, which inputs matter most, and what the
// home would have made over each past decade. In a file of their own because the dashboard refuses any one page file
// over 256 KB; index.html loads this before app.js, and app.js calls window.DPM_DEAL once its own helpers exist. Every
// figure comes from app.js's own deal functions (projectDeal, yearCalc), so these views can't disagree with the tiles.
window.DPM_DEAL = (h) => {
  const { $, gbp, gbpK, pct, fix0, num, fresh, tip, cleanAxis, motionOK, onFirstView, state, yearCalc, projectDeal, DEAL_CHECKS, getNb, homeReturn, LA_CODE, renderInvest, failed } = h;
  const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));
  const svgIn = (box, W, H, label) => d3.select(box).append('svg').attr('width', '100%').attr('viewBox', `0 0 ${W} ${H}`).attr('role', 'img').attr('aria-label', label);
  const caption = (sel) => sel.style('font-size', 'var(--cds-font-size-caption)');
  const halo = (sel) => sel.attr('stroke', 'var(--color-panel)').attr('stroke-width', 4).attr('stroke-linejoin', 'round').attr('paint-order', 'stroke');   // legible over lines
  const legend = (el, items) => {           // items: [name, colour, 'line' | 'dash' | 'box' | 'band', band opacity]
    if (!el) return; el.replaceChildren();
    items.forEach(([name, color, kind, op = 0.35]) => {
      const s = document.createElement('span'), i = document.createElement('i');
      if (kind === 'dash') i.style.cssText = `height:0;border-top:2px dashed ${color};border-radius:0;width:14px`;
      else if (kind === 'line') i.style.cssText = `height:2px;background:${color};border-radius:1px;width:14px`;
      else if (kind === 'band') i.style.cssText = `background:${color};opacity:${op}`;
      else i.style.background = color;
      s.append(i, name); el.appendChild(s);
    });
  };
  const year1 = (d, A, o = {}) => yearCalc(d, A, { rent: d.rent, costMult: 1, balance: d.price * (1 - d.dep), year2027: d.taxYear === '2027', ...o });
  const stressOf = (d, A) => {               // the same lender test as the deal: rent must cover icr x interest at the stress rate
    const icr = (d.owner === 'higher' ? A.icr_higher.v : A.icr_basic.v) / 100, loan = d.price * (1 - d.dep), floor = A.stress_rate.v / 100;
    if (!(loan > 0)) return { none: true };
    const cover = d.rent * 12 / (loan * icr);   // the highest stress rate the rent covers
    if (cover < floor) return { failsAll: true };
    return { maxRate: cover - 0.02 };            // the rate tested is the larger of the floor and the rate + 2 points
  };

  // ================= 1. the mortgage rate =================
  const slider = $('#b-rate-slider'), out = $('#b-rate-out');
  // a drag sends many inputs a frame; the deal is worked out once a frame, at the latest rate
  let pendingRate = null;
  // a new rate can add or drop a line in the cards above (interest relief capped at about the break-even rate, say),
  // which would move the slider under the pointer, and back again: the page shook while dragging. So the page scrolls
  // by whatever the redraw moved the slider, and the slider stays where it was on screen. The browser's own scroll
  // anchoring is off meanwhile, so the two don't both correct the same move.
  const steady = (draw) => {
    if (!slider || !slider.offsetParent) { draw(); return; }
    const root = document.documentElement, before = slider.getBoundingClientRect().top;
    root.style.overflowAnchor = 'none'; draw();
    const moved = slider.getBoundingClientRect().top - before; if (Math.abs(moved) >= 0.5) window.scrollBy(0, moved);
    requestAnimationFrame(() => { root.style.overflowAnchor = ''; });
  };
  const setRate = (v) => {
    const r = Math.round(clamp(v, 0, 25) * 20) / 20; if (String(r) === $('#b-rate').value && pendingRate === null) return;
    if (pendingRate === null) requestAnimationFrame(() => { const x = pendingRate; pendingRate = null; if (String(x) !== $('#b-rate').value) { $('#b-rate').value = String(x); steady(renderInvest); } });
    pendingRate = r;
  };
  // the axis (and the slider's range) stays put while a drag is under way, and grows to fit a high rate once it ends;
  // growing mid-drag would move the slider under the pointer and run the rate away
  let rateDrag = false;
  const endDrag = () => { if (!rateDrag) return; rateDrag = false; requestAnimationFrame(() => steady(renderInvest)); };
  if (slider) {
    slider.addEventListener('input', () => setRate(num(slider.value)));
    slider.addEventListener('pointerdown', () => { rateDrag = true; });
    ['pointerup', 'pointercancel', 'change'].forEach((ev) => slider.addEventListener(ev, endDrag));
  }
  const drawRate = (d, A, y1) => {
    const box = $('#rate-chart'); if (!box) return;
    const top = rateDrag && box._top ? box._top : Math.min(25, Math.max(12, Math.ceil(d.rate * 100 + 3))); box._top = top; slider.max = String(top); slider.value = String(fix0(d.rate * 100, 2)); out.textContent = pct(d.rate * 100, 2);
    $('#rate-top').textContent = pct(top, 0);
    const loan = d.price * (1 - d.dep), st = stressOf(d, A), W = Math.max(300, box.clientWidth), H = 230, m = { t: 22, r: 14, b: 28, l: 10 };
    // the curves don't change while only the rate moves, so dragging moves the marker along them without redrawing
    const key = JSON.stringify({ ...d, rate: 0, st: [A.stress_rate.v, A.icr_basic.v, A.icr_higher.v], c: dash.colors.slice(0, 2) }) + W + top;
    const pts = box._key === key ? box._pts : d3.range(0, top + 0.001, 0.05).map((r) => { const y = year1(d, A, { rateAdj: r / 100 - d.rate }); return { r, pre: y.pre / 12, post: y.post / 12 }; });
    const crossing = (() => { for (let i = 1; i < pts.length; i++) if (pts[i - 1].post >= 0 && pts[i].post < 0) return pts[i - 1].r + 0.05 * pts[i - 1].post / (pts[i - 1].post - pts[i].post); return NaN; })();
    const here = { r: d.rate * 100, pre: y1.pre / 12, post: y1.post / 12 };
    const stTxt = st.none ? '' : st.failsAll ? ` The lender's stress test fails at every rate: the rent is too low for this loan.` : st.maxRate * 100 >= top ? '' : ` The lender's stress test fails above ${pct(st.maxRate * 100, 2)}.`;
    const beTxt = loan > 0 ? (isFinite(crossing) ? ` After tax it breaks even at ${pct(crossing, 2)}.` : pts[0].post < 0 ? ' After tax it is below £0 even at 0%.' : ` After tax it stays positive up to ${pct(top, 0)}.`) + (d.mtype === 'rep' ? ' On a repayment mortgage the capital repaid counts as money out, though it adds to your equity.' : '') : '';
    $('#rate-note').textContent = loan > 0 ? `At ${pct(here.r, 2)}: ${gbp(here.post)} a month after tax, ${gbp(here.pre)} before.${beTxt}${stTxt}` : 'A cash purchase: there is no mortgage, so the rate changes nothing.';
    if (box._key === key && box._move) { box._move(here); return; }
    fresh(box); box._key = key; box._pts = pts;
    legend($('#rate-legend'), [['After tax', dash.colors[0], 'line'], ['Before tax', dash.colors[1], 'line'], ...(st.none || (!st.failsAll && st.maxRate * 100 >= top) ? [] : [['Stress test fails', 'var(--cds-chart-reference)', 'band', 0.4]])]);
    const y = d3.scaleLinear([Math.min(0, d3.min(pts, (p) => Math.min(p.pre, p.post))), Math.max(0, d3.max(pts, (p) => Math.max(p.pre, p.post)))], [H - m.b, m.t]).nice();
    const svg = svgIn(box, W, H, 'Monthly cash flow in year 1 against the mortgage rate');
    const ga = svg.append('g').call(d3.axisLeft(y).ticks(5).tickFormat(gbp)); cleanAxis(ga); let wl = 0; ga.selectAll('text').each(function () { wl = Math.max(wl, this.getComputedTextLength()); }); ga.remove(); m.l = wl + 12;
    const x = d3.scaleLinear([0, top], [m.l, W - m.r]);
    if (!st.none && (st.failsAll || st.maxRate * 100 < top)) {
      const x0 = st.failsAll ? x(0) : x(Math.max(0, st.maxRate * 100));
      svg.append('rect').attr('x', x0).attr('y', m.t).attr('width', W - m.r - x0).attr('height', H - m.t - m.b).attr('fill', 'var(--cds-chart-reference)').attr('opacity', 0.16);
      caption(svg.append('text').attr('x', W - m.r - 4).attr('y', m.t + 12).attr('text-anchor', 'end').attr('fill', 'var(--color-fg-muted)')).text('Stress test fails');
    }
    const gy = svg.append('g').attr('transform', `translate(${m.l},0)`).call(d3.axisLeft(y).ticks(5).tickFormat(gbp).tickSize(-(W - m.l - m.r))); cleanAxis(gy); gy.select('.domain').remove();
    const gx = svg.append('g').attr('transform', `translate(0,${H - m.b})`).call(d3.axisBottom(x).ticks(Math.min(top, Math.floor((W - m.l - m.r) / 50))).tickFormat((v) => v + '%').tickSizeOuter(0)); cleanAxis(gx);
    svg.append('line').attr('x1', m.l).attr('x2', W - m.r).attr('y1', y(0)).attr('y2', y(0)).attr('stroke', 'var(--color-fg-muted)').attr('stroke-width', 1);
    const line = (k) => d3.line().x((p) => x(p.r)).y((p) => y(p[k]));
    [['pre', dash.colors[1]], ['post', dash.colors[0]]].forEach(([k, c]) => svg.append('path').datum(pts).attr('fill', 'none').attr('stroke', c).attr('stroke-width', 2).attr('stroke-linejoin', 'round').attr('d', line(k)));
    const g = svg.append('g'), rule = g.append('line').attr('y1', m.t).attr('y2', H - m.b).attr('stroke', 'var(--color-fg)').attr('stroke-width', 1.5);
    const dPre = g.append('circle').attr('r', 5).attr('fill', dash.colors[1]).attr('stroke', 'var(--color-panel)').attr('stroke-width', 2);
    const dPost = g.append('circle').attr('r', 5).attr('fill', dash.colors[0]).attr('stroke', 'var(--color-panel)').attr('stroke-width', 2);
    const lab = halo(caption(g.append('text').attr('y', m.t - 8).attr('fill', 'var(--color-fg)')));
    box._move = (p) => {
      const px = x(clamp(p.r, 0, top)); rule.attr('x1', px).attr('x2', px); dPre.attr('cx', px).attr('cy', y(p.pre)); dPost.attr('cx', px).attr('cy', y(p.post));
      lab.attr('x', px).attr('text-anchor', px > W - 90 ? 'end' : px < m.l + 60 ? 'start' : 'middle').text(`Your rate ${pct(p.r, 2)}`);
    };
    box._move(here);
    if (isFinite(crossing)) {
      const cx = x(crossing), end = cx > W - 150;
      svg.append('circle').attr('cx', cx).attr('cy', y(0)).attr('r', 4).attr('fill', 'var(--color-panel)').attr('stroke', 'var(--color-fg)').attr('stroke-width', 1.5);
      halo(caption(svg.append('text').attr('x', end ? cx - 8 : cx + 8).attr('y', end ? y(0) + 16 : y(0) - 8).attr('text-anchor', end ? 'end' : 'start').attr('fill', 'var(--color-fg)'))).text(`Breaks even at ${pct(crossing, 2)}`);
    }
    // hover reads any rate; pressing and dragging sets it (the slider below does the same from the keyboard)
    const t = tip(box), hov = svg.append('line').attr('y1', m.t).attr('y2', H - m.b).attr('stroke', 'var(--cds-chart-reference)').attr('opacity', 0);
    const at = (e) => { const [px] = d3.pointer(e); return pts[clamp(Math.round(x.invert(px) / 0.05), 0, pts.length - 1)]; };
    let dragging = false, press = null;
    svg.append('rect').attr('x', m.l).attr('y', m.t).attr('width', W - m.l - m.r).attr('height', H - m.t - m.b).attr('fill', 'transparent').style('cursor', loan > 0 ? 'ew-resize' : 'default').style('touch-action', 'pan-y')
      .on('pointerdown', function (e) {
        if (!(loan > 0)) return;
        if (e.pointerType === 'touch') { press = { x: e.clientX, y: e.clientY, id: e.pointerId, el: this }; return; }
        dragging = true; rateDrag = true; this.setPointerCapture(e.pointerId); setRate(at(e).r);
      })
      .on('pointermove', (e) => {
        if (press && !dragging) {
          const dx = Math.abs(e.clientX - press.x), dy = Math.abs(e.clientY - press.y);
          if (dy > 8 && dy > dx) press = null;
          else if (dx >= 8 && dx > dy) { dragging = true; rateDrag = true; press.el.setPointerCapture(press.id); }
        }
        const p = at(e); if (dragging) { setRate(p.r); return; }
        hov.attr('x1', x(p.r)).attr('x2', x(p.r)).attr('opacity', 1);
        const [bx, by] = d3.pointer(e, box); t.show([['t', `Mortgage rate ${pct(p.r, 2)}`], ['', `After tax ${gbp(p.post)} a month`], ['', `Before tax ${gbp(p.pre)} a month`]], bx, by);
      })
      .on('pointerup pointercancel', () => { press = null; if (dragging) { dragging = false; endDrag(); } })
      .on('pointerleave', () => { hov.attr('opacity', 0); t.hide(); });
  };

  // ================= 2. what matters most =================
  // each input moved down and up by the swing in config/assumptions.csv, one at a time, everything else as entered
  state.torMetric = 'irr';
  document.querySelectorAll('#tor-metric button').forEach((b) => b.addEventListener('click', () => {
    state.torMetric = b.dataset.m; document.querySelectorAll('#tor-metric button').forEach((x) => x.setAttribute('aria-pressed', String(x === b))); renderInvest();
  }));
  // values: the home's value each year as entered. Paying 10% less doesn't make the home worth 10% less, so the price
  // row keeps it; the deposit isn't lowered past the usual buy-to-let minimum (lenders rarely lend more than 75%)
  const SWINGS = (d, A, values) => {
    const s = (k, dflt) => (A[k] ? A[k].v : dflt), [rLo, rHi] = DEAL_CHECKS.rate, minDep = s('btl_min_deposit', 25) / 100;
    const p = s('sens_price_pct', 10) / 100, rt = s('sens_rent_pct', 10) / 100, rr = s('sens_rate_pts', 1) / 100, gp = s('sens_price_growth_pts', 1) / 100, gr = s('sens_rent_growth_pts', 1) / 100;
    const gc = s('sens_cost_growth_pts', 1) / 100, vw = s('sens_voids_weeks', 2), mt = s('sens_maint_pct', 50) / 100, dp = s('sens_deposit_pts', 10) / 100;
    const g = (v) => (isFinite(v) ? v : 0);
    return [
      { key: 'price', name: `Price paid ±${pct(p * 100, 0)}`, lo: { price: d.price * (1 - p) }, hi: { price: d.price * (1 + p) }, values, show: (x) => `${gbp(x.price)} paid, same value` },
      { key: 'rent', name: `Rent ±${pct(rt * 100, 0)}`, lo: { rent: d.rent * (1 - rt) }, hi: { rent: d.rent * (1 + rt) }, show: (x) => gbp(x.rent) + ' a month' },
      { key: 'rate', name: `Mortgage rate ±${fix0(rr * 100, 2)} pt`, lo: { rate: clamp(d.rate - rr, rLo, rHi) }, hi: { rate: clamp(d.rate + rr, rLo, rHi) }, show: (x) => pct(x.rate * 100, 2) },
      { key: 'gPrice', name: `Price growth ±${fix0(gp * 100, 2)} pt`, lo: { gPrice: g(d.gPrice) - gp }, hi: { gPrice: g(d.gPrice) + gp }, show: (x) => pct(x.gPrice * 100, 1) + ' a year' },
      { key: 'gRent', name: `Rent growth ±${fix0(gr * 100, 2)} pt`, lo: { gRent: g(d.gRent) - gr }, hi: { gRent: g(d.gRent) + gr }, show: (x) => pct(x.gRent * 100, 1) + ' a year' },
      { key: 'gCost', name: `Cost inflation ±${fix0(gc * 100, 2)} pt`, lo: { gCost: g(d.gCost) - gc }, hi: { gCost: g(d.gCost) + gc }, show: (x) => pct(x.gCost * 100, 1) + ' a year' },
      { key: 'voids', name: `Void weeks ±${vw}`, lo: { voids: clamp(d.voids - vw, 0, 52) }, hi: { voids: clamp(d.voids + vw, 0, 52) }, show: (x) => `${fix0(x.voids, 1)} weeks` },
      { key: 'maint', name: `Maintenance ±${pct(mt * 100, 0)}`, lo: { maint: d.maint * (1 - mt) }, hi: { maint: Math.min(1 - d.letting, d.maint * (1 + mt)) }, show: (x) => pct(x.maint * 100, 1) + ' of rent' },
      (() => { const lo = Math.max(Math.min(d.dep, minDep), d.dep - dp), hi = clamp(d.dep + dp, 0, 1), canLower = lo < d.dep - 1e-9, canRaise = hi > d.dep + 1e-9;
        return { key: 'dep', name: `Deposit ${canLower && canRaise ? '±' : canLower ? '−' : '+'}${fix0(dp * 100, 0)} pt`, lo: { dep: lo }, hi: { dep: hi },
          show: (x) => pct(x.dep * 100, 0) + ' deposit' + (x.dep === lo && !canLower ? ` (not lowered: ${pct(minDep * 100, 0)} is the usual minimum)` : '') }; })()
    ];
  };
  const drawTornado = (d, A, P, y1) => {
    const box = $('#tor-chart'); if (!box) return;
    const asked = state.torMetric, useIrr = asked === 'irr' && isFinite(P.irr), cashOnly = asked === 'irr' && !useIrr;
    const measure = (x, values) => (useIrr ? projectDeal(x, A, values).irr : year1(x, A).post / 12), fmt = (v) => (useIrr ? pct(v * 100, 1) : gbp(v));
    const base = useIrr ? P.irr : y1.post / 12, eps = useIrr ? 5e-5 : 0.5, dev = (r) => Math.max(Math.abs(r.vLo - base), Math.abs(r.vHi - base));
    const all = SWINGS(d, A, P.proj.map((p) => p.value)).map((s) => {
      const lo = { ...d, ...s.lo }, hi = { ...d, ...s.hi };
      return { ...s, loD: lo, hiD: hi, vLo: measure(lo, s.values), vHi: measure(hi, s.values) };
    });
    const noRate = all.filter((r) => !isFinite(r.vLo) || !isFinite(r.vHi)).map((r) => r.name.split(/ [±+−]/)[0].toLowerCase());
    // longest bar first: the furthest either end moves from the figure as entered
    const rows = all.filter((r) => isFinite(r.vLo) && isFinite(r.vHi) && dev(r) > eps).sort((a, b) => dev(b) - dev(a));
    const noEffect = all.filter((r) => isFinite(r.vLo) && isFinite(r.vHi) && dev(r) <= eps).map((r) => r.name.split(/ [±+−]/)[0].toLowerCase());
    $('#tor-note').textContent = (cashOnly ? 'This deal has no single IRR, so the chart shows the year-1 cash flow instead. ' : '')
      + (rows.length ? `${rows[0].name.split(/ [±+−]/)[0]} moves the ${useIrr ? '10-year IRR' : 'monthly cash flow'} most: ${fmt(Math.min(rows[0].vLo, rows[0].vHi))} to ${fmt(Math.max(rows[0].vLo, rows[0].vHi))}, against ${fmt(base)} as entered.` : '')
      + (noEffect.length ? ` Not shown, as they don't change this figure${useIrr ? '' : ' in the first year'}: ${noEffect.join(', ')}.` : '')
      + (noRate.length ? ` Not shown, as one end has no single IRR: ${noRate.join(', ')}.` : '');
    legend($('#tor-legend'), [['Input lowered', dash.colors[1], 'box'], ['Input raised', dash.colors[0], 'box']]);
    const W = Math.max(300, box.clientWidth), bh = 18, gap = 10, top = 22, H = top + rows.length * (bh + gap) + 4;
    // keep the chart and move its bars when only the figures change (dragging the rate, typing a price)
    let svg = d3.select(box).select('svg');
    const sig = rows.map((r) => r.key).join() + W + useIrr + dash.colors.slice(0, 2);
    if (svg.empty() || box._sig !== sig) { fresh(box); svg = svgIn(box, W, H, 'Change in the result from each input, lowered and raised'); box._sig = sig; box.style.minHeight = H + 'px'; }
    svg.attr('viewBox', `0 0 ${W} ${H}`);
    const width = (text) => { const tx = caption(svg.append('text').text(text)); const w = tx.node().getComputedTextLength(); tx.remove(); return w; };
    const maxw = d3.max(rows, (r) => width(r.name)) || 0, vals = rows.flatMap((r) => [r.vLo, r.vHi]).concat(base);
    const left = Math.min(maxw + 10, W * 0.46), lw = (d3.max(vals, (v) => width(fmt(v))) || 30) + 8;   // room for the names, and for a value at each end
    const lo = d3.min(vals), hi = d3.max(vals), x = d3.scaleLinear(hi > lo ? [lo, hi] : [lo - 1, hi + 1], [left + lw, W - lw]);
    const T = svg.transition().duration(motionOK() ? 280 : 0).ease(d3.easeCubicOut);
    const baseG = svg.selectAll('g.base').data([base]).join((e) => { const g = e.append('g').attr('class', 'base'); g.append('line').attr('stroke', 'var(--color-fg)').attr('stroke-width', 1.5); caption(g.append('text').attr('fill', 'var(--color-fg)').attr('text-anchor', 'middle').attr('y', 12)); return g; });
    baseG.select('line').attr('y1', top - 4).attr('y2', H);
    baseG.transition(T).select('line').attr('x1', x(base)).attr('x2', x(base));
    baseG.select('text').text(`As entered ${fmt(base)}`).transition(T).attr('x', clamp(x(base), left + 50, W - 50));
    const t = tip(box);
    const rowG = svg.selectAll('g.row').data(rows, (r) => r.key).join((e) => {
      const g = e.append('g').attr('class', 'row');
      caption(g.append('text').attr('class', 'nm').attr('text-anchor', 'end').attr('dy', '0.35em').attr('fill', 'var(--color-fg-muted)'));
      ['lo', 'hi'].forEach((k) => { g.append('rect').attr('class', k).attr('rx', 4).attr('height', bh); caption(g.append('text').attr('class', 'v' + k).attr('dy', '0.35em').attr('fill', 'var(--color-fg)').style('font-variant-numeric', 'tabular-nums')); });
      g.append('rect').attr('class', 'hit').attr('fill', 'transparent');
      return g;
    });
    rowG.each(function (r, i) {
      const g = d3.select(this), yy = top + i * (bh + gap);
      const nm = g.select('.nm').attr('x', left - 6).attr('y', yy + bh / 2).text(r.name);
      for (let k = r.name.length; k > 4 && nm.node().getComputedTextLength() > left - 8; k--) nm.text(r.name.slice(0, k - 1).trimEnd() + '…');   // narrow screens
      g.select('.hit').attr('x', 0).attr('y', yy - gap / 2).attr('width', W).attr('height', bh + gap)
        .on('mousemove', (e) => { const [bx, by] = d3.pointer(e, box); t.show([['t', r.name], ['', `Lowered (${r.show(r.loD)}): ${fmt(r.vLo)}`], ['', `Raised (${r.show(r.hiD)}): ${fmt(r.vHi)}`], ['', `As entered: ${fmt(base)}`]], bx, by); })
        .on('mouseleave', () => t.hide());
      [['lo', r.vLo], ['hi', r.vHi]].forEach(([k, v]) => {
        const x0 = Math.min(x(base), x(v)), moved = Math.abs(v - base) > eps, w = moved ? Math.max(2, Math.abs(x(v) - x(base))) : 0, right = v >= base, bar = g.select('rect.' + k).attr('fill', k === 'lo' ? dash.colors[1] : dash.colors[0]), lab = g.select('text.v' + k);
        if (bar.attr('y') == null) { bar.attr('y', yy).attr('x', x(base)).attr('width', 0); lab.attr('y', yy + bh / 2).attr('x', x(base)); }   // new: grow from the line
        bar.transition(T).attr('y', yy).attr('x', x0).attr('width', w);
        // a pair on the same side (both lower the result) stacks its labels: the longer bar's at its end, the shorter's inside
        const other = k === 'lo' ? r.vHi : r.vLo, sameSide = (other >= base) === right, inner = sameSide && Math.abs(v - base) < Math.abs(other - base);
        lab.text(fmt(v)).attr('text-anchor', inner ? (right ? 'end' : 'start') : right ? 'start' : 'end').attr('opacity', !moved || (inner && Math.abs(x(v) - x(base)) < 44) ? 0 : 1)
          .attr('fill', inner ? 'var(--color-panel)' : 'var(--color-fg)').transition(T).attr('y', yy + bh / 2).attr('x', inner ? (right ? x(v) - 5 : x(v) + 5) : right ? x(v) + 5 : x(v) - 5);
      });
      const shorter = Math.abs(r.vLo - base) < Math.abs(r.vHi - base) ? 'lo' : 'hi';
      g.select('rect.' + shorter).raise(); g.selectAll('text').raise(); g.select('.hit').raise();
    });
    baseG.raise();
  };

  // ================= 3. past decades =================
  // the home's value if its price followed each 10-year stretch of the area's repeat-sales index since 1995, with the
  // deal's rent, costs and mortgage as entered: how much the timing of a purchase has mattered here, not a forecast
  const pastPaths = (d) => {
    const N = getNb(), H = homeReturn(); if (!N) return null;
    const ms = H && H.nb ? H.ms : LA_CODE, idx = N.idx.get(ms) || N.idx.get(LA_CODE); if (!idx) return null;
    const by = new Map(idx.filter((p) => isFinite(p.v) && p.v > 0).map((p) => [p.year, p.v])), years = [...by.keys()].sort((a, b) => a - b);
    const paths = years.filter((s) => d3.range(1, 11).every((t) => by.has(s + t))).map((s) => ({ from: s, to: s + 10, values: d3.range(1, 11).map((t) => d.price * by.get(s + t) / by.get(s)) }));
    return { name: H && H.nb ? H.nbName : 'Doncaster', paths };
  };
  const drawFan = (d, A, P) => {
    const box = $('#fan-chart'), sbox = $('#fan-irr'); if (!box || !sbox) return;
    if (failed(box, ['nbhd_index', 'neighbourhoods'])) { fresh(sbox); $('#fan-note').textContent = ''; return; }
    const PP = pastPaths(d); if (!PP || PP.paths.length < 5) { fresh(box); fresh(sbox); $('#fan-note').textContent = ''; return; }
    const runs = PP.paths.map((p) => { const R = projectDeal(d, A, p.values); return { ...p, R, irr: R.irr, growth: (p.values[9] / d.price) ** 0.1 - 1 }; });
    const bal = [d.price * (1 - d.dep), ...P.proj.map((p) => p.loan)];
    const eq = (vals, t) => (t === 0 ? d.price - bal[0] : vals[t - 1] - bal[t]);
    const yrs = d3.range(0, 11), q = yrs.map((t) => { const s = runs.map((r) => eq(r.values, t)).sort((a, b) => a - b); return { t, min: s[0], q25: d3.quantileSorted(s, 0.25), med: d3.quantileSorted(s, 0.5), q75: d3.quantileSorted(s, 0.75), max: s.at(-1) }; });
    const mine = yrs.map((t) => ({ t, v: t === 0 ? d.price - bal[0] : P.proj[t - 1].equity }));
    // a purchase year "beats the gilt" when its after-tax cash flows have a positive NPV at the gilt: the same as an IRR
    // above it when there is one IRR, and still defined when there isn't (cash flows that change sign twice, or never)
    const og = A.opp_gilt_10y && isFinite(A.opp_gilt_10y.v) ? A.opp_gilt_10y.v / 100 : NaN, ok_ = runs.filter((r) => isFinite(r.irr)), noIrr = runs.filter((r) => !isFinite(r.irr));
    const npv = (cf, r) => cf.reduce((a, c, t) => a + c / (1 + r) ** t, 0);
    runs.forEach((r) => { r.beats = isFinite(og) && npv(r.R.cfsT, og) > 0; });
    const beat = runs.filter((r) => r.beats).length;
    const sorted = ok_.slice().sort((a, b) => a.irr - b.irr), worst = sorted[0], best = sorted.at(-1), medIrr = d3.median(ok_, (r) => r.irr);
    const span = (r) => `${r.from} to ${r.to}`, moveTxt = (r) => `prices ${r.growth >= 0 ? 'up' : 'down'} ${pct(Math.abs(r.growth) * 100, 1)} a year`;
    $('#fan-sub').textContent = `The equity in this deal if its price had followed ${PP.name}'s prices over the 10 years after each purchase year from ${PP.paths[0].from} to ${PP.paths.at(-1).from} (${PP.paths.length} overlapping stretches, the last ${span(PP.paths.at(-1))}), with your rent growth, costs and mortgage as entered.`;
    const yrsList = (L) => { const y = L.map((r) => r.from); return y.length > 4 ? y.slice(0, 3).join(', ') + ` and ${y.length - 3} more` : y.length > 1 ? y.slice(0, -1).join(', ') + ' and ' + y.at(-1) : String(y[0]); };
    const noTxt = noIrr.length ? ` ${noIrr.length === 1 ? 'One purchase year' : noIrr.length + ' purchase years'} (${yrsList(noIrr)}) ${noIrr.length === 1 ? 'has' : 'have'} no single IRR, shown on the left; total profit after tax ${noIrr.length === 1 ? gbp(noIrr[0].R.profit) : `from ${gbp(d3.min(noIrr, (r) => r.R.profit))} to ${gbp(d3.max(noIrr, (r) => r.R.profit))}`}.` : '';
    $('#fan-note').textContent = (ok_.length ? `After tax, the 10-year IRR runs from ${pct(worst.irr * 100, 1)} (bought ${worst.from}, ${moveTxt(worst)}) to ${pct(best.irr * 100, 1)} (bought ${best.from}, ${moveTxt(best)}); the median is ${pct(medIrr * 100, 1)}`
      + (isFinite(P.irr) ? `, and your growth figure gives ${pct(P.irr * 100, 1)}` : '') + '.' : '') + noTxt
      + (isFinite(og) ? ` ${beat} of ${runs.length} purchase years beat the 10-year gilt (${pct(og * 100, 2)}).` : '')
      + ' Neighbouring stretches share 9 of their 10 years, so this is a few distinct market cycles seen from every starting point, not 22 separate decades. Past decades had their own interest rates and inflation: it shows how much timing has mattered here, not a forecast.';
    // ---- the fan ----
    fresh(box);
    legend($('#fan-legend'), [['Every purchase year', dash.colors[0], 'band', 0.22], ['Middle half', dash.colors[0], 'band', 0.5], ['Median', dash.colors[0], 'line'], ['Your growth figure', 'var(--color-fg)', 'dash']]);
    const W = Math.max(300, box.clientWidth), H = 250, m = { t: 12, r: 64, b: 28, l: 10 };
    const y = d3.scaleLinear([Math.min(0, d3.min(q, (p) => p.min), d3.min(mine, (p) => p.v)), Math.max(d3.max(q, (p) => p.max), d3.max(mine, (p) => p.v))], [H - m.b, m.t]).nice();
    const svg = svgIn(box, W, H, `Equity over 10 years if prices followed each past decade in ${PP.name}`);
    const ga = svg.append('g').call(d3.axisLeft(y).ticks(5).tickFormat(gbpK)); cleanAxis(ga); let wl = 0; ga.selectAll('text').each(function () { wl = Math.max(wl, this.getComputedTextLength()); }); ga.remove(); m.l = wl + 12;
    const x = d3.scaleLinear([0, 10], [m.l, W - m.r]);
    const gy = svg.append('g').attr('transform', `translate(${m.l},0)`).call(d3.axisLeft(y).ticks(5).tickFormat(gbpK).tickSize(-(W - m.l - m.r))); cleanAxis(gy); gy.select('.domain').remove();
    const gx = svg.append('g').attr('transform', `translate(0,${H - m.b})`).call(d3.axisBottom(x).ticks(Math.min(10, Math.floor((W - m.l - m.r) / 55))).tickFormat((t) => (t === 0 ? 'Now' : 'Year ' + t)).tickSizeOuter(0)); cleanAxis(gx);
    const clipId = 'fan-clip-' + Math.random().toString(36).slice(2, 8);
    const clip = svg.append('clipPath').attr('id', clipId).append('rect').attr('x', 0).attr('y', 0).attr('height', H).attr('width', W);
    const plot = svg.append('g').attr('clip-path', `url(#${clipId})`);
    const area = (a, b) => d3.area().x((p) => x(p.t)).y0((p) => y(p[a])).y1((p) => y(p[b])).curve(d3.curveMonotoneX);
    plot.append('path').datum(q).attr('fill', dash.colors[0]).attr('fill-opacity', 0.14).attr('d', area('min', 'max'));
    plot.append('path').datum(q).attr('fill', dash.colors[0]).attr('fill-opacity', 0.3).attr('d', area('q25', 'q75'));
    plot.append('path').datum(q).attr('fill', 'none').attr('stroke', dash.colors[0]).attr('stroke-width', 2).attr('d', d3.line().x((p) => x(p.t)).y((p) => y(p.med)).curve(d3.curveMonotoneX));
    plot.append('path').datum(mine).attr('fill', 'none').attr('stroke', 'var(--color-fg)').attr('stroke-width', 1.5).attr('stroke-dasharray', '5 4').attr('d', d3.line().x((p) => x(p.t)).y((p) => y(p.v)));
    const ends = [{ v: q[10].max, text: gbpK(q[10].max) }, { v: q[10].med, text: gbpK(q[10].med) }, { v: q[10].min, text: gbpK(q[10].min) }].map((e) => ({ ...e, y: y(e.v) })).sort((a, b) => a.y - b.y);
    for (let i = 1; i < ends.length; i++) if (ends[i].y - ends[i - 1].y < 14) ends[i].y = ends[i - 1].y + 14;
    const endG = svg.append('g').attr('class', 'ends'); ends.forEach((e) => caption(endG.append('text').attr('x', W - m.r + 6).attr('y', e.y).attr('dy', '0.35em').attr('fill', 'var(--color-fg)')).text(e.text));
    // reveal from now to year 10 the first time the chart is on screen (once per visit; never with reduced motion). The
    // chart is often redrawn before then (data arriving, inputs changing), so the reveal plays on whichever drawing is current
    if (motionOK() && !state.fanRevealed && 'IntersectionObserver' in window) {
      clip.attr('width', m.l); endG.attr('opacity', 0);
      if (!box._io) { box._io = true; onFirstView(box, () => { state.fanRevealed = true; const sv = d3.select(box).select('svg');
        sv.select('clipPath rect').transition().duration(1400).ease(d3.easeCubicInOut).attr('width', +sv.attr('viewBox').split(' ')[2]); sv.select('g.ends').transition().delay(1200).duration(400).attr('opacity', 1); }); }
    }
    const t = tip(box), rule = svg.append('line').attr('y1', m.t).attr('y2', H - m.b).attr('stroke', 'var(--cds-chart-reference)').attr('opacity', 0);
    svg.append('rect').attr('x', m.l).attr('y', m.t).attr('width', W - m.l - m.r).attr('height', H - m.t - m.b).attr('fill', 'transparent')
      .on('mousemove', (e) => {
        const [px] = d3.pointer(e), k = clamp(Math.round(x.invert(px)), 0, 10), p = q[k]; rule.attr('x1', x(k)).attr('x2', x(k)).attr('opacity', 1);
        const [bx, by] = d3.pointer(e, box);
        t.show([['t', k === 0 ? 'Now (your deposit)' : `Equity after ${k} year${k > 1 ? 's' : ''}`], ['', `Median ${gbp(p.med)}`], ['', `Middle half ${gbp(p.q25)} to ${gbp(p.q75)}`], ['', `Every purchase year ${gbp(p.min)} to ${gbp(p.max)}`], ['', `Your growth figure ${gbp(mine[k].v)}`]], bx, by);
      })
      .on('mouseleave', () => { rule.attr('opacity', 0); t.hide(); });
    // ---- one dot per past decade: its after-tax IRR, against the gilt ----
    fresh(sbox);
    if (!ok_.length && !noIrr.length) return;
    const SW = Math.max(300, sbox.clientWidth), r0 = 5, sm = { l: m.l, r: m.r, t: 18, b: 24 }, noW = noIrr.length ? 52 : 0;
    const marks = [...(isFinite(og) ? [og] : []), ...(isFinite(P.irr) ? [P.irr] : [])], ext = d3.extent([...ok_.map((r) => r.irr), ...marks]);
    const xs = d3.scaleLinear(isFinite(ext[0]) ? ext : [0, 0.1], [sm.l + noW, SW - sm.r]).nice();
    // stack dots that would overlap, in rows above the axis
    const placed = []; ok_.slice().sort((a, b) => a.irr - b.irr).forEach((r) => { let row = 0; while (placed.some((p) => p.row === row && Math.abs(xs(p.r.irr) - xs(r.irr)) < 2 * r0 + 2)) row++; placed.push({ r, row }); });
    const rowsN = Math.max(noIrr.length, d3.max(placed, (p) => p.row + 1) || 0), SH = sm.t + rowsN * (2 * r0 + 2) + sm.b + 4;
    const s2 = svgIn(sbox, SW, SH, '10-year IRR after tax for each past decade'), base = SH - sm.b;
    const gx2 = s2.append('g').attr('transform', `translate(0,${base})`).call(d3.axisBottom(xs).ticks(Math.min(8, Math.floor((SW - sm.l - sm.r) / 60))).tickFormat((v) => pct(v * 100, 0)).tickSizeOuter(0)); cleanAxis(gx2);   // pct: −5%, not -5%
    // the gilt's and your figure's labels sit either side of their lines when the two are close
    const close = isFinite(og) && isFinite(P.irr) && Math.abs(xs(P.irr) - xs(og)) < 120, side = (v, other) => (close ? (v < other ? 'end' : 'start') : xs(v) > SW - 80 ? 'end' : xs(v) < sm.l + 60 ? 'start' : 'middle');
    const markAt = (v, text, dashArr, anchor) => { s2.append('line').attr('x1', xs(v)).attr('x2', xs(v)).attr('y1', 4).attr('y2', base).attr('stroke', 'var(--color-fg)').attr('stroke-width', 1).attr('stroke-dasharray', dashArr);
      caption(s2.append('text').attr('x', xs(v) + (anchor === 'end' ? -4 : anchor === 'start' ? 4 : 0)).attr('y', 12).attr('text-anchor', anchor).attr('fill', 'var(--color-fg)')).text(text); };
    if (isFinite(og)) markAt(og, `Gilt ${pct(og * 100, 2)}`, null, side(og, P.irr));
    const t2 = tip(sbox);
    s2.append('g').selectAll('circle').data(placed).join('circle').attr('cx', (p) => xs(p.r.irr)).attr('cy', (p) => base - r0 - 2 - p.row * (2 * r0 + 2)).attr('r', r0)
      .attr('fill', (p) => (p.r.beats ? dash.colors[0] : 'var(--color-fg-muted)')).attr('stroke', 'var(--color-panel)').attr('stroke-width', 2)
      .on('mousemove', (e, p) => { const [bx, by] = d3.pointer(e, sbox); t2.show([['t', `Bought ${p.r.from}, sold ${p.r.to}`], ['', `Prices ${p.r.growth >= 0 ? 'up' : 'down'} ${pct(Math.abs(p.r.growth) * 100, 1)} a year`], ['', `IRR after tax ${pct(p.r.irr * 100, 1)}`], ['', `Equity at the end ${gbp(p.r.R.proj[9].equity)}`]], bx, by); })
      .on('mouseleave', () => t2.hide());
    if (isFinite(P.irr)) markAt(P.irr, `Yours ${pct(P.irr * 100, 1)}`, '4 3', side(P.irr, og));
    if (noIrr.length) {
      const cx = sm.l + 12;
      s2.append('g').selectAll('circle').data(noIrr).join('circle').attr('cx', cx).attr('cy', (r, i) => base - r0 - 2 - i * (2 * r0 + 2)).attr('r', r0 - 1)
        .attr('fill', 'var(--color-panel)').attr('stroke', 'var(--color-fg-muted)').attr('stroke-width', 1.5)
        .on('mousemove', (e, r) => { const [bx, by] = d3.pointer(e, sbox); t2.show([['t', `Bought ${r.from}, sold ${r.to}`], ['', moveTxt(r)], ['', 'No single IRR'], ['', `Total profit after tax ${gbp(r.R.profit)}`], ['', `Equity at the end ${gbp(r.R.proj[9].equity)}`]], bx, by); })
        .on('mouseleave', () => t2.hide());
      caption(s2.append('text').attr('x', cx).attr('y', base + 16).attr('text-anchor', 'middle').attr('fill', 'var(--color-fg-muted)')).text('No IRR');
    }
  };

  return {
    draw(d, A, P, y1) {
      [['the mortgage rate chart', () => drawRate(d, A, y1)], ['the sensitivity chart', () => drawTornado(d, A, P, y1)], ['the past-decades chart', () => drawFan(d, A, P)]]
        .forEach(([name, f]) => { try { f(); } catch (e) { console.error(`Couldn't draw ${name}:`, e); } });
    },
    // invalid deal inputs: nothing from the last valid deal may stay on screen
    clear() {
      ['#rate-chart', '#tor-chart', '#fan-chart', '#fan-irr'].forEach((s) => { const b = $(s); if (b) { fresh(b); b._key = null; b._move = null; b._sig = null; } });
      ['#rate-note', '#tor-note', '#fan-note', '#rate-legend', '#tor-legend', '#fan-legend'].forEach((s) => { const e = $(s); if (e) e.replaceChildren(); });
      if (out) out.textContent = '—';
    }
  };
};
