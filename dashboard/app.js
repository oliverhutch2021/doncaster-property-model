(() => {
  // ================= helpers =================
  const $ = (s) => document.querySelector(s);
  const gbp = (v) => (v == null || !isFinite(v)) ? '—' : (v < 0 ? '−' : '') + '£' + d3.format(',.0f')(Math.abs(Math.round(v)));
  const gbpK = (v) => (v == null || !isFinite(v)) ? '—' : (Math.abs(v) >= 1e6 ? '£' + d3.format('.2f')(v / 1e6) + 'm' : '£' + d3.format(',.0f')(Math.round(v / 1000)) + 'k');
  // round to the shown precision before choosing the sign, so -0.04 reads "0.0", never "−0.0"
  const fix0 = (v, d) => { const r = Math.round(v * 10 ** d) / 10 ** d; return r === 0 ? 0 : r; };
  const pct = (v, d = 1) => (v == null || !isFinite(v)) ? '—' : d3.format(`.${d}f`)(fix0(v, d)) + '%';
  const sgn = (v, d = 1) => { if (v == null || !isFinite(v)) return '—'; const r = fix0(v, d); return (r > 0 ? '+' : r < 0 ? '−' : '') + d3.format(`.${d}f`)(Math.abs(r)) + '%'; };
  const num = (x) => (x === '' || x == null) ? NaN : Number(x);
  const TYPE_NAME = { D: 'Detached', S: 'Semi-detached', T: 'Terraced', F: 'Flat / maisonette' };
  const TYPE_SHORT = { D: 'Detached', S: 'Semi', T: 'Terraced', F: 'Flat' };
  const TYPES = ['D', 'S', 'T', 'F'];
  const EPC_DISTRICTS = ['DN1', 'DN10', 'DN11', 'DN12', 'DN14', 'DN2', 'DN3', 'DN4', 'DN5', 'DN6', 'DN7', 'DN8', 'DN9', 'S64', 'S66'];
  const ok = (id) => dash.data(id).status === 'ok';
  const rows = (id) => (ok(id) ? dash.data(id).data : []);
  const normPc = (s) => { const t = String(s || '').toUpperCase().replace(/[^A-Z0-9]/g, ''); return t.length > 3 ? t.slice(0, -3) + ' ' + t.slice(-3) : t; };
  const hav = (a, b, c, d) => { const r = Math.PI / 180, x = Math.sin((c - a) * r / 2) ** 2 + Math.cos(a * r) * Math.cos(c * r) * Math.sin((d - b) * r / 2) ** 2; return 2 * 6371 * Math.asin(Math.sqrt(x)); };
  const median = (arr) => { const a = arr.filter(isFinite).sort((x, y) => x - y); if (!a.length) return NaN; const m = a.length >> 1; return a.length % 2 ? a[m] : (a[m - 1] + a[m]) / 2; };
  const monthLabel = (ym) => { const [y, m] = ym.split('-').map(Number); return new Date(Date.UTC(y, m - 1, 1)).toLocaleString('en-GB', { month: 'short', year: 'numeric', timeZone: 'UTC' }); };
  const parseMonth = (s) => new Date(Date.UTC(+s.slice(0, 4), +s.slice(5, 7) - 1, 1));
  // draw one section; if it fails, log it and let the rest of the page draw
  const safe = (name, f) => { try { f(); } catch (e) { console.error(`Couldn't draw ${name}:`, e); } };
  const cell = (tr, text, cls) => { const td = document.createElement('td'); td.textContent = text; if (cls) td.className = cls; tr.appendChild(td); return td; };
  const tip = (box) => {
    let t = box.querySelector('.tip');
    if (!t) { t = document.createElement('div'); t.className = 'tip'; t.hidden = true; box.appendChild(t); }
    return {
      show(lines, x, y) {
        t.replaceChildren();
        lines.forEach(([cls, text]) => { const d = document.createElement('div'); if (cls) d.className = cls; d.textContent = text; t.appendChild(d); });
        t.hidden = false;
        t.style.left = Math.max(0, Math.min(box.clientWidth - t.offsetWidth, x + 12)) + 'px';
        t.style.top = Math.max(0, y - 10 - t.offsetHeight) + 'px';
      },
      hide() { t.hidden = true; }
    };
  };
  const failed = (el, ids) => {
    const bad = ids.some((id) => dash.data(id).status === 'error');
    if (bad) {
      el.querySelectorAll('svg').forEach((n) => n.remove());
      if (!el.querySelector('.fail')) {
        const p = document.createElement('div'); p.className = 'fail';
        p.style.cssText = 'display:flex;align-items:center;justify-content:center;gap:6px;min-height:inherit;color:var(--color-fg-muted);font-size:var(--cds-font-size-caption)';
        const dot = document.createElement('span'); dot.style.cssText = 'width:.375rem;height:.375rem;border-radius:50%;background:var(--color-bad)';
        p.append(dot, 'Failed to load'); el.appendChild(p);
      }
    }
    return bad;
  };
  const cleanAxis = (g) => g.attr('font-size', null).attr('font-family', null)
    .call((s) => s.selectAll('text').attr('fill', 'var(--color-fg-muted)').style('font-size', 'var(--cds-font-size-caption)'))
    .call((s) => s.selectAll('line').attr('stroke', 'var(--cds-chart-grid)'))
    .call((s) => s.select('.domain').attr('stroke', 'var(--cds-chart-axis)'));
  const fresh = (box) => { box.querySelectorAll('svg, .fail').forEach((n) => n.remove()); };

  // ================= cached data =================
  const cache = {};
  // trees are stored compactly (left child = next node; default-left, kind and missing type packed in one flag):
  // internal [f, thr, right, flags, count], leaf [-1, value, count] -> [f, thr, left, right, dl, kind, mt, count]
  const expandTree = (nodes) => nodes.map((n, i) => (n.length === 8 ? n
    : n[0] === -1 ? [-1, 0, 0, 0, n[1], 0, 0, n[2]]
    : [n[0], n[1], i + 1, n[2], n[3] & 1, (n[3] >> 1) & 1, n[3] >> 2, n[4]]));
  const getModel = () => {
    if (!ok('model_trees') || !ok('model_meta')) return null;
    if (cache.model) return cache.model;
    const meta = Object.fromEntries(rows('model_meta').map((r) => [r.key, r.value]));
    cache.model = {
      trees: rows('model_trees').slice().sort((a, b) => num(a.tree) - num(b.tree)).map((r) => expandTree(JSON.parse(r.nodes))),
      features: JSON.parse(meta.features), bands: JSON.parse(meta.bands), conformal: JSON.parse(meta.conformal),
      indexLatest: num(meta.index_latest), indexMonth: meta.index_latest_month, valMonth: meta.valuation_month, nSales: num(meta.n_sales_model),
      alpha: num(meta.local_alpha), k: num(meta.local_k), poolFrom: meta.local_pool_from, groups: meta.groups ? JSON.parse(meta.groups) : null
    };
    return cache.model;
  };
  const getConf = () => {
    if (!ok('conf_trees') || !ok('model_meta')) return null;
    if (cache.conf) return cache.conf;
    const meta = Object.fromEntries(rows('model_meta').map((r) => [r.key, r.value]));
    if (!meta.conf_features) return null;
    return (cache.conf = { trees: rows('conf_trees').slice().sort((a, b) => num(a.tree) - num(b.tree)).map((r) => expandTree(JSON.parse(r.nodes))),
      features: JSON.parse(meta.conf_features), q10: num(meta.conf_q10), q90: num(meta.conf_q90), levels: JSON.parse(meta.conf_levels), adaptive: meta.conf_adaptive === 'true',
      typed: meta.conf_typed_scale ? { scale: num(meta.conf_typed_scale), q10: num(meta.conf_typed_q10), q90: num(meta.conf_typed_q90) } : null });
  };
  const getPcs = () => {
    if (!ok('postcodes')) return null;
    if (cache.pcs) return cache.pcs;
    const m = new Map(); rows('postcodes').forEach((r) => m.set(r.postcode, r)); cache.pcs = m;
    const frag = document.createDocumentFragment();
    [...m.keys()].filter((k) => m.get(k).in_doncaster !== '0').sort().forEach((k) => { const o = document.createElement('option'); o.value = k; frag.appendChild(o); });
    $('#pc-list').replaceChildren(frag);
    return m;
  };
  const getLevels = () => {
    if (!ok('levels')) return null;
    if (cache.levels) return cache.levels;
    const st = new Map(), ls = new Map();
    rows('levels').forEach((r) => (r.kind === 'sector_type' ? st.set(r.key, [num(r.level), num(r.n)]) : ls.set(r.key, num(r.level))));
    return (cache.levels = { st, ls });
  };
  const getIndex = () => {
    if (!ok('price_index')) return null;
    if (cache.index) return cache.index;
    const raw = new Map(), i15 = new Map();
    rows('price_index').forEach((r) => { raw.set(r.month, num(r.index_raw)); i15.set(r.month, num(r.index_2015)); });
    return (cache.index = { raw, i15 });
  };
  const getComps = () => {
    if (!ok('comps')) return null;
    if (cache.comps) return cache.comps;
    return (cache.comps = rows('comps').map((r) => ({ ...r, latN: num(r.lat), lonN: num(r.lon), yd: num(r.y_defl), fa: num(r.floor_area), priceN: num(r.price), res: num(r.resid) })));
  };
  // refurbishment: a kitchen and each bathroom are fixed amounts; decorating, flooring and the full-renovation trades go by floor area
  const REFURB = {
    cosmetic: { label: 'Decorating and flooring', from: 'dated', to: 'good', items: ['decor', 'floor'] },
    kb: { label: 'Kitchen and bathroom', from: 'dated', to: 'good', items: ['kitchen', 'bath'] },
    kbc: { label: 'Kitchen, bathroom, decorating and flooring', from: 'dated', to: 'recently_refurbished', items: ['kitchen', 'bath', 'decor', 'floor'] },
    full: { label: 'Full renovation', from: 'needs_full_renovation', to: 'recently_refurbished', items: ['kitchen', 'bath', 'decor', 'floor', 'rewire', 'heating', 'plaster'] }
  };
  // finish follows value: bottom of the budget range at Doncaster's 10th-percentile price, budget at the median, mid-range at the 90th
  const finishTier = (A, finish, value, key) => {
    const lo = A[`rf_${key}_low`].v, bu = A[`rf_${key}_budget`].v, mi = A[`rf_${key}_mid`].v;
    if (finish === 'budget') return bu; if (finish === 'mid') return mi; if (!(value > 0)) return bu;
    const p10 = A.rf_finish_p10.v, p50 = A.rf_finish_p50.v, p90 = A.rf_finish_p90.v, c = (x) => Math.max(0, Math.min(1, x));
    return value <= p50 ? lo + (bu - lo) * c(Math.log(value / p10) / Math.log(p50 / p10)) : bu + (mi - bu) * c(Math.log(value / p50) / Math.log(p90 / p50));
  };
  const refurbCost = (A, scope, area, finish, baths, vat, value, contPct) => {
    const S = REFURB[scope]; if (!S || !A || !A.rf_ref_area || !isFinite(area) || area <= 0) return null;
    const nb = Math.max(0, Math.round(isFinite(baths) ? baths : 1)), v = vat > 0 ? vat : 0, r = area / A.rf_ref_area.v;
    const cp = isFinite(contPct) && contPct >= 0 ? contPct : A.rf_contingency.v;
    const cost = {
      kitchen: ['Kitchen', finishTier(A, finish, value, 'kitchen') * Math.pow(r, A.rf_kitchen_pow.v)],
      bath: [nb === 1 ? 'Bathroom' : `${nb} bathrooms`, nb * finishTier(A, finish, value, 'bath')],
      decor: ['Decorating', A.rf_decor.v * area], floor: ['Flooring', A.rf_floor.v * area],
      rewire: ['Rewire', A.rf_rewire.v * Math.pow(r, A.rf_rewire_pow.v)],
      heating: ['Boiler and radiators', A.rf_boiler.v + A.rf_heating.v * area], plaster: ['Re-skim walls and ceilings', A.rf_plaster.v * area]
    };
    const items = S.items.map((k) => cost[k]).filter((it) => it[1] > 0);
    const base = d3.sum(items, (it) => it[1]), cont = base * cp / 100, tax = (base + cont) * v / 100;
    const fin = finish === 'mid' ? 'mid-range' : finish === 'budget' ? 'budget' : value > 0 ? `finish for a ${gbpK(value)} home` : 'budget';
    return { ...S, items, base, cont, tax, vat: v, contPct: cp, finish: fin, total: base + cont + tax };
  };
  const refurbText = (R) => R.items.map(([l, x]) => `${l} ${gbp(Math.round(x / 10) * 10)}`).join(' · ') + ` · contingency ${R.contPct}% ${gbp(Math.round(R.cont / 10) * 10)}` + (R.tax ? ` · VAT ${R.vat}% ${gbp(Math.round(R.tax / 10) * 10)}` : ' · no VAT added');
  const getAss = () => {
    if (!ok('assumptions')) return null;
    if (cache.ass) return cache.ass;
    return (cache.ass = Object.fromEntries(rows('assumptions').map((r) => [r.key, { v: num(r.value), label: r.label, src: r.source }])));
  };
  const getCond = () => (ok('condition') ? rows('condition').map((r) => ({ key: r.condition, label: r.label, adj: num(r.adjustment_pct), adjPrev: num(r.adjustment_prev_pct) })) : null);
  // The condition effect depends on what the model already knows (src/condition_calibration.py). With no last sale it is
  // the calibration on a model without last-sale features. With a last sale entered the model has the home's own price:
  // a worse condition is then the full model's purchase discount (measured where the earlier sale was years before), and
  // a better one is the full model's resale premium when that sale was within 18 months (a quick resale already shows
  // most of the works). Works since an older sale the model can't see, and that case isn't measured, so it keeps the
  // no-last-sale premium. Returns { adj, basis } for an estimate built from `inp`.
  const lastSaleMonths = (inp) => {
    const m = getModel(); if (!m || !inp || !(isFinite(inp.prevPrice) && inp.prevPrice > 0) || !/^\d{4}-\d{2}$/.test(inp.prevMonth || '')) return NaN;
    return (parseMonth(m.valMonth) - parseMonth(inp.prevMonth)) / (30.44 * 864e5);
  };
  const condFor = (c, inp) => {
    if (!c) return { adj: 0, basis: 'none' };
    const mo = lastSaleMonths(inp), hasPrev = isFinite(c.adjPrev);
    if (!isFinite(mo) || !c.adj || !hasPrev) return { adj: c.adj || 0, basis: 'no last sale' };
    if (c.adj < 0) return { adj: c.adjPrev, basis: 'last sale known' };
    return mo <= 18 ? { adj: c.adjPrev, basis: 'recent last sale' } : { adj: c.adj, basis: 'older last sale' };
  };
  const rentSeries = () => {
    if (!ok('rents')) return null;
    if (cache.rents) return cache.rents;
    const m = new Map();
    rows('rents').forEach((r) => { if (!m.has(r.series)) m.set(r.series, []); m.get(r.series).push({ month: r.month, v: num(r.monthly_rent) }); });
    m.forEach((a) => a.sort((x, y) => (x.month < y.month ? -1 : 1)));
    return (cache.rents = m);
  };
  const latestRent = (series) => { const m = rentSeries(); const a = m && m.get(series); return a && a.length ? a[a.length - 1] : null; };
  const getStreets = () => {
    if (!ok('street_levels')) return null;
    if (cache.streets) return cache.streets;
    const m = new Map();
    rows('street_levels').forEach((r) => {
      if (!m.has(r.postcode)) m.set(r.postcode, { pc: null, streets: new Map() });
      const e = m.get(r.postcode), v = { level: num(r.level), n: num(r.n) };
      if (r.type === '*') e.pc = v; else { if (!e.streets.has(r.street)) e.streets.set(r.street, {}); e.streets.get(r.street)[r.type] = v; }
    });
    return (cache.streets = m);
  };
  const pickStreet = (entry, epc) => {
    if (!entry || !entry.streets.size) return null;
    const names = [...entry.streets.keys()].filter(Boolean);
    if (epc && epc.address) { const a = String(epc.address).toUpperCase(); const hit = names.filter((n) => a.includes(n)).sort((x, y) => y.length - x.length)[0]; if (hit) return hit; }
    if (names.length === 1) return names[0];
    const tot = (n) => Object.values(entry.streets.get(n)).reduce((a, v) => a + (v.n || 0), 0);
    return names.sort((x, y) => tot(y) - tot(x))[0] || null;
  };
  const getCtMix = () => (ok('ct_mix') ? (cache.ct || (cache.ct = rows('ct_mix').map((r) => ({ ...r, c: num(r.count) })))) : null);
  const getPlaces = () => {
    if (!ok('places')) return null;
    if (cache.places) return cache.places;
    const by = {};
    rows('places').forEach((r) => { const o = { ...r, latN: num(r.lat), lonN: num(r.lon) }; (by[r.kind] = by[r.kind] || []).push(o); });
    return (cache.places = by);
  };
  const getExtras = () => {
    if (!ok('pc_extras')) return null;
    if (cache.extras) return cache.extras;
    const m = new Map(); rows('pc_extras').forEach((r) => m.set(r.postcode, r)); return (cache.extras = m);
  };
  const nearestPlace = (kinds, lat, lon, keep = () => true) => {
    const P = getPlaces(); if (!P) return null; let best = null;
    kinds.forEach((k) => (P[k] || []).forEach((p) => { if (!keep(p)) return; const d = hav(lat, lon, p.latN, p.lonN); if (!best || d < best.d) best = { ...p, d }; }));
    return best;
  };

  // ================= the model, in the browser =================
  const predictLog = (model, x) => {
    let s = 0;
    for (const nodes of model.trees) {
      let i = 0;
      while (nodes[i][0] !== -1) {
        const [f, thr, l, r, dl, kind, mt] = nodes[i];
        let v = x[f], nan = v == null || Number.isNaN(v), left;
        if (kind === 0 && mt === 0 && nan) { v = 0; nan = false; }
        if ((mt === 2 && nan) || (mt === 1 && (nan || v === 0))) left = dl === 1;
        else if (nan) left = false;
        else if (kind === 1) left = Math.floor(thr / 2 ** v) % 2 === 1;
        else left = v <= thr;
        i = left ? l : r;
      }
      s += nodes[i][4];
    }
    return s;
  };
  // TreeSHAP (Lundberg et al. 2018, path-dependent): exact SHAP values for the trees above; node[7] is the training count
  const goesLeft = (node, x) => {
    const [f, thr, , , dl, kind, mt] = node;
    let v = x[f], nan = v == null || Number.isNaN(v);
    if (kind === 0 && mt === 0 && nan) { v = 0; nan = false; }
    if ((mt === 2 && nan) || (mt === 1 && (nan || v === 0))) return dl === 1;
    if (nan) return false;
    if (kind === 1) return Math.floor(thr / 2 ** v) % 2 === 1;
    return v <= thr;
  };
  const treeShap = (trees, x, nFeat) => {
    const phi = new Float64Array(nFeat + 1);
    for (const nodes of trees) {
      let ev = 0, tot = 0; for (const n of nodes) if (n[0] === -1) { ev += n[4] * n[7]; tot += n[7]; }
      phi[nFeat] += ev / tot;
      const mx = 66, D = new Int32Array(mx * mx), Z = new Float64Array(mx * mx), O = new Float64Array(mx * mx), W = new Float64Array(mx * mx);
      const extend = (off, l, pz, po, pi) => {
        D[off + l] = pi; Z[off + l] = pz; O[off + l] = po; W[off + l] = l === 0 ? 1 : 0;
        for (let i = l - 1; i >= 0; i--) { W[off + i + 1] += po * W[off + i] * (i + 1) / (l + 1); W[off + i] = pz * W[off + i] * (l - i) / (l + 1); }
      };
      const unwind = (off, l, i) => {
        const o = O[off + i], z = Z[off + i]; let n = W[off + l];
        for (let j = l - 1; j >= 0; j--) {
          if (o !== 0) { const t = W[off + j]; W[off + j] = n * (l + 1) / ((j + 1) * o); n = t - W[off + j] * z * (l - j) / (l + 1); }
          else W[off + j] = (W[off + j] * (l + 1)) / (z * (l - j));
        }
        for (let j = i; j < l; j++) { D[off + j] = D[off + j + 1]; Z[off + j] = Z[off + j + 1]; O[off + j] = O[off + j + 1]; }
      };
      const unwoundSum = (off, l, i) => {
        const o = O[off + i], z = Z[off + i]; let next = W[off + l], total = 0;
        for (let j = l - 1; j >= 0; j--) {
          if (o !== 0) { const t = next * (l + 1) / ((j + 1) * o); total += t; next = W[off + j] - t * z * (l - j) / (l + 1); }
          else total += (W[off + j] / z) / ((l - j) / (l + 1));
        }
        return total;
      };
      const recurse = (j, depth, l, pz, po, pi, parentOff) => {
        const off = depth * mx;
        if (parentOff >= 0) for (let k = 0; k < l; k++) { D[off + k] = D[parentOff + k]; Z[off + k] = Z[parentOff + k]; O[off + k] = O[parentOff + k]; W[off + k] = W[parentOff + k]; }
        extend(off, l, pz, po, pi); l += 1;
        const node = nodes[j];
        if (node[0] === -1) { for (let i = 1; i < l; i++) phi[D[off + i]] += unwoundSum(off, l - 1, i) * (O[off + i] - Z[off + i]) * node[4]; return; }
        const left = goesLeft(node, x), hot = left ? node[2] : node[3], cold = left ? node[3] : node[2], f = node[0];
        let iz = 1, io = 1, k = -1;
        for (let q = 1; q < l; q++) if (D[off + q] === f) { k = q; break; }
        if (k >= 0) { iz = Z[off + k]; io = O[off + k]; unwind(off, l - 1, k); l -= 1; }
        recurse(hot, depth + 1, l, iz * nodes[hot][7] / node[7], io, f, off);
        recurse(cold, depth + 1, l, iz * nodes[cold][7] / node[7], 0, f, off);
      };
      recurse(0, 0, 0, 1, 1, -1, -1);
    }
    return phi;
  };
  const knn = (comps, lat, lon, type) => {
    const same = [], area = [];
    for (const c of comps) {
      const d = hav(lat, lon, c.latN, c.lonN);
      if (c.type === type) same.push([d, c.yd]);
      if (isFinite(c.fa) && c.fa > 0) area.push([d, c.yd - Math.log(c.fa)]);
    }
    same.sort((a, b) => a[0] - b[0]); area.sort((a, b) => a[0] - b[0]);
    const s10 = same.slice(0, 10), a15 = area.slice(0, 15);
    return {
      knn_lvl: s10.length >= 3 ? median(s10.map((p) => p[1])) : NaN,
      knn_dist: s10.length >= 3 ? d3.mean(s10, (p) => p[0]) : NaN,
      knn_ppsqm: a15.length >= 5 ? median(a15.map((p) => p[1])) : NaN
    };
  };
  // impossible inputs are refused rather than valued: a negative floor area must not give a believable price
  const LIMITS = { area: [10, 1500, 'Floor area', 'm²'], rooms: [1, 30, 'Bedrooms and living rooms', ''], plot: [0, 1000000, 'Plot size', 'm²'],
    prevPrice: [1000, 20000000, 'Last sale price', '£'], asking: [0, 20000000, 'Asking price', '£'] };
  const badInput = (inp) => {
    for (const [k, [lo, hi, name, unit]] of Object.entries(LIMITS)) {
      const v = inp[k];
      if (isFinite(v) && (v < lo || v > hi)) return `${name} must be between ${unit === '£' ? gbp(lo) : d3.format(',')(lo)} and ${unit === '£' ? gbp(hi) : d3.format(',')(hi) + (unit ? ' ' + unit : '')}. Correct it to see an estimate.`;
    }
    if (isFinite(inp.rooms) && Math.round(inp.rooms) !== inp.rooms) return 'Bedrooms and living rooms must be a whole number.';
    if (isFinite(inp.prevPrice) && inp.prevPrice > 0 && !/^\d{4}-\d{2}$/.test(inp.prevMonth || '')) return 'Give the month of the last sale as well as its price.';
    return '';
  };
  const value = (inp) => {
    const model = getModel(), pcs = getPcs(), lv = getLevels(), comps = getComps(), idx = getIndex();
    if (!model || !pcs || !lv || !comps || !idx || !getStreets()) return { status: 'loading' };
    const bad = badInput(inp); if (bad) return { status: 'invalid', msg: bad };
    const pc = pcs.get(inp.postcode);
    if (!pc) return { status: 'nopc' };
    if (pc.in_doncaster === '0') return { status: 'outside', ward: pc.ward };      // in the sales file, but its small area is in another borough
    const sector = inp.postcode.slice(0, -2), st = lv.st.get(sector + '|' + inp.type);
    const lat = num(pc.lat), lon = num(pc.lon), nn = knn(comps, lat, lon, inp.type);
    let prev_defl = NaN, years = NaN;
    if (isFinite(inp.prevPrice) && inp.prevPrice > 0 && inp.prevMonth) {
      const ir = idx.raw.get(inp.prevMonth) || idx.raw.get(model.indexMonth);
      prev_defl = Math.log(inp.prevPrice) - Math.log(ir);
      years = (parseMonth(model.valMonth) - parseMonth(inp.prevMonth)) / (365.25 * 864e5);
      if (years < 0) { prev_defl = NaN; years = NaN; }
    }
    const formDefault = { D: 0, S: 1, T: 3, F: NaN }[inp.type];
    const feat = {
      lat, lon, dist_centre_km: num(pc.dist_centre_km), imd_score: num(pc.imd_score), imd_income: num(pc.imd_income), imd_employment: num(pc.imd_employment),
      imd_education: num(pc.imd_education), imd_health: num(pc.imd_health), imd_crime: num(pc.imd_crime), imd_barriers: num(pc.imd_barriers), imd_living_env: num(pc.imd_living_env),
      lvl_sector_type: st && st[1] >= 5 ? st[0] : NaN, lvl_lsoa: lv.ls.has(pc.lsoa21) ? lv.ls.get(pc.lsoa21) : NaN, n_sector_type: st ? st[1] : 0,
      property_type: { D: 0, S: 1, T: 2, F: 3 }[inp.type], tenure: inp.tenure === 'L' ? 1 : 0, new_build: inp.newBuild ? 1 : 0,
      floor_area: inp.area, rooms: inp.rooms, age_year: inp.age, bungalow: inp.bungalow, built_form_code: isFinite(inp.form) ? inp.form : formDefault,
      extensions: inp.epc ? num(inp.epc.extensions) : NaN, sap_current: inp.sap, sap_potential: inp.sapPot, sap_gap: isFinite(inp.sapPot) && isFinite(inp.sap) ? inp.sapPot - inp.sap : NaN,
      mains_gas: inp.gas, ...nn, prev_defl, years_since_prev: years, prev_nb: isFinite(prev_defl) ? (inp.prevNew ? 1 : 0) : NaN
    };
    // plot: typed in, else the title plan behind the chosen EPC address
    const e = inp.epc || {};
    if (isFinite(inp.plot) && inp.plot > 0) Object.assign(feat, { plot_m2: inp.plot, plot_epc_homes: 1, plot_uprns: NaN, plot_m2_per_home: inp.plot });
    else Object.assign(feat, { plot_m2: num(e.plot_m2), plot_epc_homes: num(e.plot_epc_homes), plot_uprns: num(e.plot_uprns), plot_m2_per_home: num(e.plot_m2_per_home) });
    // street and postcode price levels (previous 5 years)
    const S = getStreets(), entry = S ? S.get(inp.postcode) : null, street = pickStreet(entry, inp.epc), sv = street ? entry.streets.get(street)[inp.type] : null;
    Object.assign(feat, { lvl_street_type: sv && sv.n >= 2 ? sv.level : NaN, n_street_type: sv ? sv.n : 0,
      lvl_postcode: entry && entry.pc && entry.pc.n >= 2 ? entry.pc.level : NaN, n_postcode: entry && entry.pc ? entry.pc.n : 0 });
    // extra EPC detail from the chosen address
    ['wall_type', 'ceiling_m', 'floor_level_n', 'top_floor', 'heated_rooms', 'glazed_area_n', 'fireplaces', 'wall_insulated', 'loft_mm', 'glazing',
      'elec_heating', 'heat_pump', 'woodburner', 'low_energy_light', 'solar_pv'].forEach((c) => { feat[c] = num(e[c]); });
    // certificate history as of the valuation month (why the latest one was done, tenure, lets, age, count, energy-score change)
    ['epc_reason', 'epc_tenure_n', 'epc_rental_5y', 'epc_age_y', 'epc_n', 'sap_jump'].forEach((c) => { feat[c] = num(e[c]); });
    // local correction: alpha x the model's median miss on the k nearest sales of the last 12 months
    let local = 0, spread = NaN;
    if (model.alpha > 0 && model.k > 0) {
      const near = []; for (const c of comps) if (isFinite(c.res)) near.push([hav(lat, lon, c.latN, c.lonN), c.res]);
      near.sort((a, b) => a[0] - b[0]);
      if (near.length >= model.k) {
        const rs = near.slice(0, model.k).map((p) => p[1]), md = median(rs);
        local = model.alpha * md; spread = median(rs.map((r) => Math.abs(r - md)));
      }
    }
    const est = Math.exp(predictLog(model, model.features.map((f) => feat[f])) + Math.log(model.indexLatest) + local);
    let b = 0; while (b < model.bands.length && est >= model.bands[b]) b++;
    let [qlo, qhi] = model.conformal[b + (isFinite(prev_defl) ? 5 : 0)];
    // confidence: a small second model predicts the typical size of the error for this estimate; when it is
    // there, the 80% range scales with it (calibrated on 2024 errors)
    const conf = getConf();
    let sigma = NaN, level = null;
    if (conf) {
      const cx = { pred_log: Math.log(est), corr_abs: Math.abs(local), local_spread: spread };
      sigma = predictLog(conf, conf.features.map((f) => (f in cx ? cx[f] : feat[f])));
      // typed in by hand (no certificate picked): the score was learned from sales, where missing details mean an unusual home,
      // so it is rescaled for ordinary homes with details left out (calibrated on 2024, src/model_v8_typed.py)
      const typed = !inp.epc && conf.typed, q = typed ? conf.typed : conf;
      if (typed) sigma *= conf.typed.scale;
      if (isFinite(sigma) && sigma > 0) { level = conf.levels.find(([hi]) => sigma < hi) || conf.levels.at(-1); if (conf.adaptive) { qlo = sigma * q.q10; qhi = sigma * q.q90; } }
    }
    return { status: 'ok', est, lo: est * Math.exp(qlo), hi: est * Math.exp(qhi), pc, sector, lat, lon, feat, local, street, sigma, level };
  };

  // ================= state and inputs =================
  const state = { tab: 'value', touched: {}, last: null, epc: null, epcOptions: [], listingRent: null, sapManual: false };
  const val = (s) => $(s).value;
  const inputs = () => {
    const e = state.epc;
    const ratingSel = num(val('#in-rating'));
    return {
      postcode: normPc(val('#in-postcode')), type: val('#in-type'), tenure: val('#in-tenure'), newBuild: $('#in-new').checked,
      condition: val('#in-condition') || 'average', beds: val('#in-beds'), area: num(val('#in-area')), rooms: num(val('#in-rooms')),
      form: num(val('#in-form')), age: num(val('#in-age')), bungalow: $('#in-bungalow').checked ? 1 : 0,
      sap: e && !state.sapManual && isFinite(num(e.sap_current)) ? num(e.sap_current) : ratingSel,
      sapPot: e && !state.sapManual ? num(e.sap_potential) : NaN, gas: e ? ({ Y: 1, N: 0 }[e.mains_gas] ?? NaN) : NaN, epc: e,
      prevPrice: num(val('#in-prev-price')), prevMonth: val('#in-prev-month'), asking: num(val('#in-asking')),
      plot: num(val('#in-plot')), ctband: val('#in-ctband'), sapManual: state.sapManual, prevNew: state.prevNew ? 1 : 0
    };
  };
  $('#in-postcode').value = 'DN4 7HA';

  // ================= tabs =================
  const TABS = ['value', 'invest', 'areas', 'saved', 'market', 'accuracy', 'method', 'changes'];
  // dash.setLink also rewrites the frame's address, which Safari and other WebKit browsers refuse inside the dashboard
  // ("SecurityError: The operation is insecure"); the link still reaches the dashboard, so the error is caught here
  const setLink = (id) => { try { dash.setLink(id); } catch (e) { /* address bar not updated in this browser */ } };
  const showTab = (id, push = true) => {
    if (!TABS.includes(id)) return;
    state.tab = id;
    TABS.forEach((t) => { $('#' + t).hidden = t !== id; $('#tab-' + t).setAttribute('aria-selected', String(t === id)); });
    render();                                   // draw first, so nothing the link does can stop the tab drawing
    if (push) setLink(id);
  };
  TABS.forEach((t) => $('#tab-' + t).addEventListener('click', () => showTab(t)));

  // ================= EPC address lookup =================
  const SAP_TO_SELECT = (sap) => (sap >= 92 ? '95' : sap >= 81 ? '86' : sap >= 69 ? '74.5' : sap >= 55 ? '61.5' : sap >= 39 ? '46.5' : sap >= 21 ? '29.5' : '10');
  const AGE_OPTS = [1890, 1914.5, 1939.5, 1958, 1971, 1979, 1986.5, 1993, 1999, 2004.5, 2009, 2018];
  const fillAddresses = () => {
    const pc = normPc(val('#in-postcode')), sel = $('#in-address');
    const district = pc.split(' ')[0];
    const id = EPC_DISTRICTS.includes(district) ? 'epc_' + district : null;
    const key = pc + '|' + (id && ok(id) ? 'ok' : 'wait');
    if (state.addrKey === key) return;
    if (!id) { sel.replaceChildren(new Option('No EPC addresses for this postcode', '')); sel.removeAttribute('data-source'); state.addrKey = key; return; }
    sel.setAttribute('data-source', id);
    const d = dash.data(id);
    if (d.status !== 'ok') { sel.replaceChildren(new Option(d.status === 'error' ? 'EPC addresses failed to load' : 'Loading EPC addresses…', '')); return; }
    state.addrKey = key;
    state.epcOptions = d.data.filter((r) => r.postcode === pc);
    sel.replaceChildren(new Option(state.epcOptions.length ? `Choose one of ${state.epcOptions.length} addresses, or enter details yourself` : 'No EPC addresses at this postcode: enter details yourself', ''));
    state.epcOptions.forEach((r, i) => sel.appendChild(new Option(`${r.address} · ${r.epc_type || ''} · ${r.floor_area ? Math.round(num(r.floor_area)) + ' m²' : ''} · EPC ${r.rating || '?'}`, String(i))));
  };
  const parseSales = (s) => String(s || '').split(';').filter(Boolean).map((x) => { const [date, price, nb] = x.split('|'); return { date, price: num(price), nb: nb === 'Y' }; });
  // fields a certificate fills in; when the certificate changes or is cleared, any value still as the last one set it is
  // reset, so a missing size on the new certificate shows as missing rather than the previous home's size
  const EPC_FIELDS = ['#in-area', '#in-rooms', '#in-form', '#in-age', '#in-rating', '#in-bungalow'];
  // ownership, not values, decides what a cleared certificate takes with it: state.epcAuto lists the fields the
  // certificate filled and still owns; typing in a field or a pasted listing writing it takes the field over
  const setField = (sel, v) => { const el = $(sel); if (el.type === 'checkbox') el.checked = v === 'true'; else el.value = v; state.epcAuto[sel] = true; if (state.listingOwned) delete state.listingOwned[sel]; };
  const releaseEpc = (sel) => { delete state.epcAuto[sel]; };
  state.epcAuto = {};
  EPC_FIELDS.forEach((sel) => ['input', 'change'].forEach((ev) => $(sel).addEventListener(ev, () => releaseEpc(sel))));
  // picking another address shows that address's certificate in full (blank where it has nothing); clearing the
  // address resets only the fields the certificate still owns
  const applyEpc = (r) => {
    Object.keys(state.epcAuto).forEach((sel) => { const el = $(sel); if (el.type === 'checkbox') el.checked = false; else el.value = ''; });
    state.epcAuto = {};
    state.epc = r; state.sapManual = false; $('#ext-note').textContent = '';
    if (state.prevAuto) { $('#in-prev-price').value = ''; $('#in-prev-month').value = ''; state.prevAuto = false; state.prevNew = 0; }
    if (!r) { $('#epc-note').textContent = ''; return; }
    // the home's own last sale (HM Land Registry), if any and not already typed in
    const hist = parseSales(r.sales);
    if (hist.length && $('#in-prev-price').value === '') {
      const last = hist[hist.length - 1];
      $('#in-prev-price').value = String(last.price); $('#in-prev-month').value = last.date.slice(0, 7); state.prevAuto = true; state.prevNew = last.nb ? 1 : 0;
    }
    setField('#in-area', isFinite(num(r.floor_area)) ? String(Math.round(num(r.floor_area))) : '');
    setField('#in-rooms', isFinite(num(r.rooms)) ? String(num(r.rooms)) : '');
    setField('#in-form', r.built_form_code === '' || r.built_form_code == null ? '' : String(r.built_form_code));
    const ay = num(r.age_year);
    setField('#in-age', isFinite(ay) ? String(AGE_OPTS.reduce((a, b) => (Math.abs(b - ay) < Math.abs(a - ay) ? b : a))) : '');
    setField('#in-rating', isFinite(num(r.sap_current)) ? SAP_TO_SELECT(num(r.sap_current)) : '');
    setField('#in-bungalow', String(r.epc_type === 'Bungalow'));
    const t = r.epc_type === 'Flat' || r.epc_type === 'Maisonette' ? 'F' : ({ '0': 'D', '1': 'S', '2': 'T', '3': 'T', '4': 'T', '5': 'T' }[String(r.built_form_code)] || val('#in-type'));
    $('#in-type').value = t;
    // prompts: an old certificate, or a building outline that looks bigger than the certificate's floor area
    const yrs = (parseMonth(getModel() ? getModel().valMonth : '2026-09') - parseMonth(r.lodged)) / (365.25 * 864e5), notes = [];
    const fp = num(r.footprint_m2), fa = num(r.floor_area), thr = ok('ext_flag') ? rows('ext_flag').find((x) => x.epc_type === r.epc_type) : null;
    if (thr && isFinite(fp) && isFinite(fa) && fp > 0 && fa / fp < num(thr.p10_floor_over_footprint) && yrs >= 2)
      notes.push(`The OS building outline gives about ${Math.round(fp)} m² of ground per home here, large for a ${Math.round(fa)} m² ${String(r.epc_type).toLowerCase()} (fewer than 1 in 10 recently certified homes look like this). It may have been extended since ${monthLabel(r.lodged)}: if so, enter the current floor area.`);
    else if (yrs >= 8) notes.push(`This certificate is ${Math.floor(yrs)} years old. If the home has been extended or improved since, enter the current floor area and energy rating.`);
    $('#ext-note').textContent = notes.join(' ');
    $('#epc-note').textContent = `Filled from the EPC lodged ${monthLabel(r.lodged)}: ${r.epc_type || ''}, ${r.floor_area ? Math.round(num(r.floor_area)) + ' m²' : 'size not recorded'}, ${r.rooms ? r.rooms + ' bedrooms and living rooms' : ''}, energy rating ${r.rating || 'not recorded'} (score ${r.sap_current || '?'}, potential ${r.sap_potential || '?'}).`;
  };
  $('#in-address').addEventListener('change', () => { const i = $('#in-address').value; applyEpc(i === '' ? null : state.epcOptions[+i]); propertyChanged(true); });
  $('#in-rating').addEventListener('change', () => { state.sapManual = true; propertyChanged(false); });

  // ================= listing parser =================
  // Each paste starts clean: every field the last listing filled (and you haven't changed since) goes back to its
  // default before this one is read, so one listing's bungalow, council tax band, size or price never carries into the next.
  const LISTING_FIELDS = ['#in-asking', '#in-beds', '#in-type', '#in-bungalow', '#in-form', '#in-tenure', '#in-new', '#in-plot', '#in-ctband', '#in-area', '#in-rating'];
  state.listingOwned = {};
  const resetField = (sel) => {
    const el = $(sel);
    if (el.type === 'checkbox') el.checked = el.defaultChecked;
    else if (el.tagName === 'SELECT') { const d = [...el.options].find((o) => o.defaultSelected); el.value = d ? d.value : (el.options[0] ? el.options[0].value : ''); }
    else el.value = el.defaultValue;
  };
  const fromListing = (sel, v) => { const el = $(sel); if (el.type === 'checkbox') el.checked = !!v; else el.value = String(v); state.listingOwned[sel] = true; releaseEpc(sel); };
  LISTING_FIELDS.forEach((sel) => ['input', 'change'].forEach((ev) => $(sel).addEventListener(ev, () => { delete state.listingOwned[sel]; })));
  const forgetListing = () => { Object.keys(state.listingOwned).forEach(resetField); state.listingOwned = {}; state.listingRent = null; if (state.sapFromListing) { state.sapManual = false; state.sapFromListing = false; } };
  const WORD_NUM = { one: 1, two: 2, three: 3, four: 4, five: 5, six: 6, seven: 7 };
  // property type: words that look like a type but aren't one are taken out first (flat roof, roof terrace, detached
  // garage, granny flat, a street called ... Terrace), then the type named first in the text wins, since listings lead with it
  const listingType = (low) => {
    const t = low.replace(/\bflat[\s-](?:roof\w*|garden|rate|fee|lawn|plot|land|walk|surface|pack|screen|tv|panel|access|level|lying|bed\b)/g, ' ')
      .replace(/\b(?:granny|annexe?|annex) flat\b/g, ' ')
      .replace(/\b(?:roof|patio|rooftop|garden|decked|sun|balcony)[\s-]terraces?\b/g, ' ')
      .replace(/\bdetached (?:garage|double garage|garden room|outbuilding|annexe?|workshop|office|studio|summer ?house|store|shed|building|cabin|gym)\b/g, ' ')
      .replace(/\b[a-z]+ terrace,/g, ' ');                                            // an address line: "Bass Terrace, Doncaster"
    const pats = [['S', /semi[\s-]?detached/], ['F', /\b(?:flat|apartment|maisonette|penthouse|studio (?:flat|apartment))\b/],
      ['T', /\b(?:end[\s-]of[\s-]terrace|end[\s-]terrace|mid[\s-]terrace|terraced|terrace house|town ?house|back[\s-]to[\s-]back|(?:victorian|edwardian|period|stone|brick|inner) terrace)\b/],
      ['D', /(?<!semi[\s-]?)\bdetached\b/]];
    let best = null;
    pats.forEach(([k, re]) => { const m = re.exec(t); if (m && (!best || m.index < best.at)) best = { k, at: m.index }; });
    return best ? best.k : null;
  };
  // postcode: a full postcode in the district the listing names wins; one in the agent's details (marketed by, branch,
  // call, email ...) or in another district than the one named is ignored
  const listingPostcode = (text, low, pcs) => {
    const fulls = [...text.matchAll(/\b([A-Z]{1,2}\d{1,2}[A-Z]?)\s?(\d[A-Z]{2})\b/gi)].map((m) => ({ pc: normPc(m[0]), at: m.index })).filter((x) => pcs && pcs.has(x.pc) && pcs.get(x.pc).in_doncaster !== '0');
    const lone = [...new Set([...text.matchAll(/\b(DN\d{1,2}|S6[3-6])\b(?!\s?\d[A-Z]{2})/gi)].map((m) => m[1].toUpperCase()))];
    const agentAt = [...low.matchAll(/marketed by|estate agents?\b|letting agents?\b|\bbranch\b|our office|contact (?:us|the agent)|\bcall (?:us|the|now|today)?|\btel\b|telephone|e-?mail/g)].map((m) => m.index);
    const nearAgent = (x) => agentAt.some((a) => x.at >= a && x.at - a < 220);
    const ok = fulls.filter((x) => !nearAgent(x) && (!lone.length || lone.includes(x.pc.split(' ')[0])));
    return { pc: ok.length ? ok[0].pc : null, district: lone.length === 1 ? lone[0] : null, districts: lone, skipped: fulls.filter((x) => !ok.includes(x)).map((x) => x.pc) };
  };
  const readListing = () => {
    const raw = val('#listing-text'), text = raw.replace(/\s+/g, ' '), low = text.toLowerCase(), found = [];
    forgetListing();
    const money = (s) => num(String(s).replace(/,/g, ''));
    const rentM = text.match(/£\s?([\d,]{3,6})(?:\.\d\d)?\s*(pcm|p\.c\.m|per calendar month|per month|a month|pm\b|pw|per week|a week)/i);
    let sale = null;
    for (const m of text.matchAll(/£\s?([\d,]{5,})/g)) { const after = text.slice(m.index + m[0].length, m.index + m[0].length + 25).toLowerCase(); if (!/pcm|per (calendar )?month|a month|pw|per week|a week/.test(after)) { sale = money(m[1]); break; } }
    if (rentM) { let r = money(rentM[1]); if (/w/i.test(rentM[2])) r = Math.round(r * 52 / 12); state.listingRent = r; state.touched.rent = false; found.push(`rent ${gbp(r)} pcm`); }
    if (sale && sale > 10000) { fromListing('#in-asking', sale); found.push(`asking ${gbp(sale)}`); }
    const beds = low.match(/\b(\d+|one|two|three|four|five|six|seven)\s*(?:-|\s)?\s*(?:bed|bedroom)s?\b/);
    if (beds) { const nb = WORD_NUM[beds[1]] || +beds[1]; fromListing('#in-beds', Math.min(4, Math.max(1, nb))); found.push(nb + ' bed'); }
    const type = listingType(low);
    if (type) { fromListing('#in-type', type); found.push(TYPE_NAME[type].toLowerCase()); }
    if (/\bbungalow\b/.test(low)) { fromListing('#in-bungalow', true); found.push('bungalow'); }
    if (/end[\s-](of[\s-])?terrace/.test(low)) fromListing('#in-form', '2'); else if (/mid[\s-]terrace/.test(low)) fromListing('#in-form', '3');
    if (/\bleasehold\b/.test(low)) { fromListing('#in-tenure', 'L'); found.push('leasehold'); } else if (/\bfreehold\b/.test(low)) { fromListing('#in-tenure', 'F'); found.push('freehold'); }
    if (/\bnew[\s-]build\b|\bnew home\b/.test(low)) { fromListing('#in-new', true); found.push('new build'); }
    const noPlot = low.replace(/plot[^.]{0,30}?[\d,]+\s*(?:sq\.?\s*m\b|sqm|m²|sq\.?\s*ft|sqft)/g, ' ');
    const sqm = noPlot.match(/([\d,]+(?:\.\d+)?)\s*(?:sq\.?\s*m\b|sqm|m²|m2\b|square met)/), sqft = noPlot.match(/([\d,]+(?:\.\d+)?)\s*(?:sq\.?\s*ft|sqft|ft²|square f)/);
    const acre = low.match(/(\d+(?:\.\d+)?)\s*acres?\b/), plotSq = low.match(/plot[^.]{0,30}?([\d,]+)\s*(?:sq\.?\s*m\b|sqm|m²)/);
    if (acre && +acre[1] < 20) { fromListing('#in-plot', Math.round(+acre[1] * 4046.86)); found.push(`plot ${acre[1]} acres`); }
    else if (plotSq) { fromListing('#in-plot', Math.round(money(plotSq[1]))); found.push(`plot ${plotSq[1]} m²`); }
    const ctb = text.match(/council tax(?: band)?\s*[:\-]?\s*(?:band\s*)?([A-H])\b/i); if (ctb) { fromListing('#in-ctband', ctb[1].toUpperCase()); found.push('council tax band ' + ctb[1].toUpperCase()); }
    if (sqm) { fromListing('#in-area', Math.round(money(sqm[1]))); found.push(Math.round(money(sqm[1])) + ' m²'); }
    else if (sqft) { const a = Math.round(money(sqft[1]) / 10.764); fromListing('#in-area', a); found.push(`${a} m² (from sq ft)`); }
    const epc = text.match(/\bEPC(?:\s*rating)?\s*[:\-]?\s*([A-G])\b/i) || text.match(/\benergy (?:performance )?rating\s*[:\-]?\s*([A-G])\b/i);
    if (epc) { const map = { A: '95', B: '86', C: '74.5', D: '61.5', E: '46.5', F: '29.5', G: '10' }; fromListing('#in-rating', map[epc[1].toUpperCase()]); state.sapManual = true; state.sapFromListing = true; found.push('EPC ' + epc[1].toUpperCase()); }
    // where the home is
    const chips = $('#listing-pcs'); chips.replaceChildren();
    const pcs = getPcs(), loc = listingPostcode(text, low, pcs), setPc = (pc) => { $('#in-postcode').value = pc; state.addrKey = null; applyEpc(null); };
    const prevPc = normPc(val('#in-postcode'));            // the last home's postcode: a new listing never keeps it unless you choose to
    if (loc.skipped.length) found.push(`ignored ${loc.skipped.join(', ')} (${loc.districts.length ? 'not in ' + loc.districts.join(' or ') : "the agent's details"})`);
    if (loc.pc) { setPc(loc.pc); found.push('postcode ' + loc.pc); }
    else {
      let streetFound = false;
      if (ok('streets')) {
        const cands = rows('streets').filter((r) => (!loc.districts.length || loc.districts.includes(r.district)) && r.street.length > 4 && low.includes(r.street.toLowerCase()));
        cands.sort((a, b) => num(b.sales) - num(a.sales));
        const top = cands.length ? cands[0].street : null, same = cands.filter((r) => r.street === top);
        const pcsList = [...new Set(same.flatMap((r) => String(r.postcodes).match(/[A-Z]{1,2}\d[A-Z\d]? \d[A-Z]{2}/g) || []))];
        if (pcsList.length) {
          streetFound = true;
          const nice = top.toLowerCase().replace(/\b\w/g, (c) => c.toUpperCase()), places = [...new Set(same.map((r) => r.district))];
          if (pcsList.length === 1) { setPc(pcsList[0]); found.push(`street ${nice}, postcode ${pcsList[0]}`); }
          else {
            found.push(places.length > 1 ? `street ${nice}, which is in ${places.join(' and ')}: pick the right postcode` : `street ${nice}${loc.district ? ', ' + loc.district : ''}: pick the postcode`);
            pcsList.slice(0, 24).forEach((pc) => { const b = document.createElement('button'); b.type = 'button'; b.textContent = pc; b.addEventListener('click', () => { setPc(pc); propertyChanged(true); }); chips.appendChild(b); });
            setPc('');                                          // several postcodes fit: no estimate until one is picked
          }
        }
      }
      if (!streetFound) {
        // nothing places the home: the last postcode is cleared, even in the same district, rather than valued as this listing
        setPc('');
        found.push(loc.districts.length ? `only the district ${loc.districts.join(' or ')} was found: enter the full postcode` : 'no postcode found: enter it above');
      }
      // keeping the last home's postcode is an explicit choice, offered first when it could still be right
      if (!val('#in-postcode') && prevPc && pcs && pcs.has(prevPc) && (!loc.districts.length || loc.districts.includes(prevPc.split(' ')[0]))) {
        const k = document.createElement('button'); k.type = 'button'; k.className = 'keep'; k.textContent = `Keep ${prevPc}`; k.title = 'Use the postcode of the home you were looking at before this listing';
        k.addEventListener('click', () => { setPc(prevPc); chips.replaceChildren(); propertyChanged(true); }); chips.prepend(k);
      }
    }
    if (/\b(extended|extension|loft conversion|converted loft|loft room|dormer)\b/.test(low)) found.push('mentions an extension or loft conversion: check the floor area is the current one');
    $('#listing-found').textContent = found.length ? 'Found: ' + found.join(', ') : 'Nothing recognised. Paste the full listing text.';
    $('#more-fields').open = true;
    propertyChanged(true);
  };
  $('#listing-read').addEventListener('click', readListing);
  $('#listing-clear').addEventListener('click', () => { $('#listing-text').value = ''; $('#listing-found').textContent = ''; $('#listing-pcs').replaceChildren(); forgetListing(); propertyChanged(true); });

  // ================= VALUE tab =================
  const fillCondition = () => {
    const c = getCond(), sel = $('#in-condition');
    if (!c || sel.options.length) return;
    c.forEach((x) => sel.appendChild(new Option(x.label, x.key, false, x.key === 'average'))); sel.value = 'average';
  };
  // A different home (postcode, address, listing, a saved home) starts the deal afresh; editing this home's details
  // (council tax band, condition, bedrooms, size ...) keeps any price, rent or EPC cost you typed into the deal.
  const freshDeal = () => { state.touched.price = false; state.touched.rent = false; state.touched.epcCost = false; state.touched.gPrice = false; };
  // typing redraws once you pause (each estimate, with its SHAP breakdown, takes about 0.4 s, over 1 s on a phone)
  let typingTimer = null;
  const propertyChanged = (newHome) => { clearTimeout(typingTimer); if (newHome === true) freshDeal(); render(); };
  const typed = (newHome) => { if (newHome === true) freshDeal(); clearTimeout(typingTimer); typingTimer = setTimeout(render, 220); };
  ['#in-postcode'].forEach((s) => $(s).addEventListener('input', () => { state.addrKey = null; if (state.epc) applyEpc(null); typed(true); }));
  ['#in-type', '#in-tenure', '#in-condition', '#in-beds', '#in-new', '#in-form', '#in-age', '#in-bungalow', '#in-ctband'].forEach((s) => $(s).addEventListener('change', () => propertyChanged(false)));
  ['#wi-kind', '#wi-epc', '#wi-refurb', '#wi-finish'].forEach((s) => $(s).addEventListener('input', () => render()));
  ['#wi-area', '#wi-rooms', '#wi-baths'].forEach((s) => $(s).addEventListener('input', () => typed(false)));
  ['#in-area', '#in-rooms', '#in-prev-price', '#in-prev-month', '#in-asking', '#in-plot'].forEach((s) => $(s).addEventListener('input', () => typed(false)));
  ['#in-prev-price', '#in-prev-month'].forEach((s) => $(s).addEventListener('input', () => { state.prevAuto = false; state.prevNew = 0; }));

  // no valid estimate: nothing that came from the last one may stay on screen (advice, explanation, comparables, what-if)
  const clearValuation = () => {
    ['#v-base', '#v-cond', '#v-ask', '#v-imd'].forEach((s) => { $(s).textContent = '—'; }); $('#v-ask').className = 'mid';
    ['#v-range', '#v-local', '#v-tested', '#v-ask-note', '#v-imd-note', '#v-cond-note', '#why-start', '#ct-verdict', '#hist-note', '#hist-addr', '#wi-note']
      .forEach((s) => { const el = $(s); if (el) el.textContent = ''; });
    $('#cond-row').hidden = true;
    ['#v-bar', '#v-conf', '#comps-table tbody', '#hist-table tbody'].forEach((s) => { const el = $(s); if (el) el.replaceChildren(); });
    ['#around-risk', '#around-amen', '#ct-kv', '#wi-kv'].forEach((s) => { const el = $(s); if (el) kv(el, []); });
    ['#why-chart', '#comps-map'].forEach((s) => { const el = $(s); if (el) fresh(el); });
    state.last = null;
  };
  const renderValue = () => {
    fillCondition(); getPcs(); fillAddresses();
    if (failed($('#value-tiles'), ['model_trees', 'model_meta', 'postcodes', 'levels', 'comps'])) return;
    const inp = inputs(), v = value(inp);
    $('#pc-err').textContent = v.status === 'nopc' ? (inp.postcode ? `${inp.postcode} isn't in the Doncaster postcode list. Check it, or pick one from the suggestions.` : 'Enter a Doncaster postcode.')
      : v.status === 'outside' ? `${inp.postcode} is outside Doncaster (${v.ward} ward), so the model can't value it.` : v.status === 'invalid' ? v.msg : '';
    if (v.status !== 'ok') { clearValuation(); return; }
    const c0 = (getCond() || []).find((c) => c.key === inp.condition) || { adj: 0, label: 'Average' }, cfx = condFor(c0, inp);
    const cond = { ...c0, base: c0.adj, adj: cfx.adj, basis: cfx.basis };          // adj = the effect for this estimate; base = without a last sale
    const adj = v.est * (1 + cond.adj / 100);
    state.last = { ...v, adj, inp, cond };
    const model = getModel(), round1k = (x) => Math.round(x / 1000) * 1000;
    $('#v-base').textContent = gbp(round1k(v.est));
    const missing = [!isFinite(inp.area) && 'floor area', !isFinite(inp.sap) && 'energy rating'].filter(Boolean);
    $('#v-range').textContent = `80% range ${gbpK(v.lo)} to ${gbpK(v.hi)}, at ${monthLabel(model.indexMonth)} prices, average condition.` + (missing.length ? ` Add the ${missing.join(' and ')} for a tighter estimate.` : '');
    $('#v-local').textContent = Math.abs(v.local) >= 0.0005 ? `Includes ${sgn((Math.exp(v.local) - 1) * 100)} for how prices nearby have moved lately.` : '';
    drawRangeBar($('#v-bar'), v, isFinite(inp.asking) && inp.asking > 0 ? inp.asking : null);
    const cf = $('#v-conf'); cf.replaceChildren();
    if (v.level) {
      const COL = { High: 'var(--color-ok)', Good: 'var(--color-ok)', Fair: 'var(--color-warn)', Low: 'var(--color-bad)' };
      const dot = document.createElement('i'); dot.className = 'dot'; dot.style.background = COL[v.level[1]] || 'var(--color-fg-muted)';
      const b = document.createElement('b'); b.textContent = `${v.level[1]} confidence`;
      const rest = document.createElement('span'); rest.textContent = `typical error for a home like this about ±${d3.format('.0f')((Math.exp(v.sigma) - 1) * 100)}%`;
      b.textContent += ':'; cf.append(dot, b, rest);
    }
    const tested = $('#v-tested'), TY = ok('confidence') ? rows('confidence').filter((r) => r.kind === 'typed') : [];
    if (tested) {
      const head = ok('accuracy') ? rows('accuracy').find((r) => r.model === 'dashboard' && r.split === 'test_2025_26' && r.metric === 'mdape') : null, few = !inp.epc && TY.length && head, aOnly = TY.find((r) => r.level === 'area only'), tOnly = TY.find((r) => r.level === 'type only');
      tested.textContent = few && aOnly && tOnly ? `Typed in by hand, estimates are less sure than the ${pct(num(head.value) * 100, 1)} headline: on 2025-26 test sales entered with only a floor area the median error was ${pct(num(aOnly.mdape) * 100, 1)}, and with only the type ${pct(num(tOnly.mdape) * 100, 1)}. Picking the address adds the certificate and last sale.` : '';
    }
    $('#cond-row').hidden = !cond.adj;
    $('#v-cond-label').textContent = `If ${cond.label.toLowerCase()}`;
    $('#v-cond').textContent = gbp(round1k(adj));
    $('#v-cond-note').textContent = `${sgn(cond.adj)} from the repeat-sales calibration` + ({ 'last sale known': ', for an estimate that knows the last sale',
      'recent last sale': ': the last sale is recent, and the model already reads most of a refurbishment from it',
      'older last sale': ': works since an older last sale aren\'t visible to the model, and this case isn\'t measured separately' }[cond.basis] || '');
    if (isFinite(inp.asking) && inp.asking > 0) {
      const diff = (inp.asking / adj - 1) * 100;
      $('#v-ask').textContent = sgn(diff, 0);
      const lo = v.lo * (1 + cond.adj / 100), hi = v.hi * (1 + cond.adj / 100);
      $('#v-ask-note').textContent = `Asking ${gbp(inp.asking)} vs estimate ${gbpK(adj)}: ${inp.asking < lo ? 'below the 80% range. Looks cheap, so check why' : inp.asking > hi ? 'above the 80% range. Room to negotiate, or something the data can\'t see' : 'inside the 80% range'}`;
      $('#v-ask').className = 'mid ' + (inp.asking > hi ? 'warnc' : inp.asking < lo ? 'good' : '');
    } else { $('#v-ask').textContent = '—'; $('#v-ask').className = 'mid'; $('#v-ask-note').textContent = 'Add an asking price under More details, or paste a listing'; }
    const dec = num(v.pc.imd_decile);
    $('#v-imd').textContent = isFinite(dec) ? `Decile ${dec}` : '—';
    $('#v-imd-note').textContent = `${v.pc.ward || ''}${isFinite(dec) ? ` · deprivation decile, 1 is the most deprived 10% in England` : ''}`;
    renderComps(v, inp);
    renderAround(v);
    renderWhy(v, cond);
    renderCt(v, inp);
    renderHist(inp);
    renderWhatIf(v, inp, cond);
  };
  // the 80% range as a bar, the estimate as a marker, and the asking price if given
  const drawRangeBar = (box, v, asking) => {
    box.replaceChildren();
    const W = Math.max(220, box.clientWidth || 300), H = 34, pad = 4;
    // a fixed scale around the estimate (±35%), so a tight range looks tight
    const lo = Math.min(v.lo, asking || Infinity, v.est * 0.65), hi = Math.max(v.hi, asking || 0, v.est * 1.35);
    const x = d3.scaleLinear([lo, hi], [pad, W - pad]);
    const svg = d3.select(box).append('svg').attr('width', '100%').attr('viewBox', `0 0 ${W} ${H}`).attr('role', 'img').attr('aria-label', `80% range ${gbpK(v.lo)} to ${gbpK(v.hi)}`);
    svg.append('rect').attr('x', x(v.lo)).attr('y', 8).attr('width', Math.max(2, x(v.hi) - x(v.lo))).attr('height', 8).attr('rx', 4).attr('fill', dash.colors[0]).attr('fill-opacity', 0.28);
    svg.append('circle').attr('cx', x(v.est)).attr('cy', 12).attr('r', 6).attr('fill', dash.colors[0]).attr('stroke', 'var(--color-panel)').attr('stroke-width', 2);
    const lab = (xx, t, anchor) => svg.append('text').attr('x', xx).attr('y', 31).attr('text-anchor', anchor).attr('fill', 'var(--color-fg-muted)').style('font-size', 'var(--cds-font-size-caption)').style('font-variant-numeric', 'tabular-nums').text(t);
    lab(x(v.lo), gbpK(v.lo), 'start'); lab(x(v.hi), gbpK(v.hi), 'end');
    if (asking) {
      svg.append('line').attr('x1', x(asking)).attr('x2', x(asking)).attr('y1', 2).attr('y2', 22).attr('stroke', 'var(--color-fg)').attr('stroke-width', 2).attr('stroke-linecap', 'round').append('title').text('Asking price ' + gbp(asking));
    }
  };
  const renderComps = (v, inp) => {
    const idx = getIndex(), comps = getComps(), model = getModel(), tb = $('#comps-table tbody');
    tb.replaceChildren(); if (!idx || !comps) return;
    const list = comps.filter((c) => c.type === inp.type).map((c) => {
      const i = idx.raw.get(String(c.date).slice(0, 7));
      return { ...c, dist: hav(v.lat, v.lon, c.latN, c.lonN), today: i ? c.priceN * model.indexLatest / i : NaN };
    }).sort((a, b) => a.dist - b.dist).slice(0, 12);
    list.forEach((r) => {
      const tr = document.createElement('tr');
      const where = (r.address ? r.address + ', ' : '') + r.postcode, sold = d3.utcFormat('%b %Y')(new Date(r.date)), ac = cell(tr, where); ac.title = where;
      const sl = document.createElement('span'); sl.className = 'show-narrow muted'; sl.textContent = 'Sold ' + sold; ac.appendChild(sl);       // on a phone the date sits under the address
      cell(tr, sold, 'hide-narrow'); cell(tr, gbp(r.priceN), 'r hide-narrow'); cell(tr, gbp(r.today), 'r');
      cell(tr, isFinite(r.fa) && r.fa > 0 ? gbp(r.today / r.fa) : '—', 'r hide-narrow'); cell(tr, r.dist < 1 ? Math.max(10, Math.round(r.dist * 100) * 10) + ' m' : d3.format('.1f')(r.dist) + ' km', 'r');
      tb.appendChild(tr);
    });
    drawCompsMap(v, list);
  };
  const kmTxt = (d) => (d < 1 ? Math.round(d * 1000 / 10) * 10 + ' m' : d3.format('.1f')(d) + ' km');
  const floodText = (ex) => {
    if (!ex) return ['—', ''];
    const hm = num(ex.flood_hm), an = num(ex.flood_any);
    if (hm >= 0.5) return [`High or medium for ${pct(hm * 100, 0)} of homes`, 'badc'];
    if (hm > 0) return [`High or medium for ${pct(hm * 100, 0)} of homes`, 'warnc'];
    if (an > 0) return [`Low or very low for ${pct(an * 100, 0)} of homes`, ''];
    return ['Not in an area at risk', 'good'];
  };
  const renderAround = (v) => {
    const r1 = $('#around-risk'), r2 = $('#around-amen');
    if (!getPlaces() || !getExtras()) { kv(r1, [['Loading…', '']]); kv(r2, []); return; }
    const ex = getExtras().get(v.pc.postcode), [ft, fc] = floodText(ex);
    const near = (kinds, keep) => { const p = nearestPlace(kinds, v.lat, v.lon, keep); return p ? `${p.name}, ${kmTxt(p.d)}` : '—'; };
    const school = (kinds) => { const p = nearestPlace(kinds, v.lat, v.lon); return p ? [`${p.name}, ${kmTxt(p.d)}`, p.info] : ['—', '']; };
    const goodPrim = nearestPlace(['primary', 'allthrough'], v.lat, v.lon, (p) => /Outstanding|Good/.test(p.info));
    const prim = school(['primary', 'allthrough']), sec = school(['secondary', 'allthrough']);
    const road = ex ? num(ex.dist_major_road_m) : NaN;
    kv(r1, [['Flood risk, rivers and sea', ft, fc], ['Nearest station', near(['station'])], ['Bus stops within 500 m', ex ? d3.format(',')(num(ex.bus_stops_500m)) : '—'],
      ['Nearest motorway junction', near(['junction'])], ['Motorway or trunk road', isFinite(road) ? kmTxt(road / 1000) + (road < 150 ? ' (expect traffic noise)' : '') : '—'],
      ['Area type', ex && ex.rural !== '' ? (num(ex.rural) === 1 ? 'Rural' : 'Urban') : '—']]);
    kv(r2, [['Nearest primary school', prim[0]], ['', prim[1]], ['Nearest Good or Outstanding primary', goodPrim ? `${goodPrim.name}, ${kmTxt(goodPrim.d)}` : '—'],
      ['Nearest secondary school', sec[0]], ['', sec[1]], ['Nearest supermarket', near(['supermarket'])], ['Nearest GP', near(['gp'])], ['Nearest park or green space', near(['park'])],
      ['Pubs, cafés and restaurants within 800 m', ex ? d3.format(',')(num(ex.food_drink_800m)) : '—']]);
  };
  const LOGP = ['lvl_sector_type', 'lvl_lsoa', 'knn_lvl', 'lvl_street_type', 'lvl_postcode', 'prev_defl'];
  const fmtFeat = (f, v) => {
    if (v == null || Number.isNaN(v)) return 'not known';
    const m = getModel();
    if (LOGP.includes(f)) return gbpK(Math.exp(v) * m.indexLatest) + ' today';
    if (f === 'knn_ppsqm') return gbp(Math.exp(v) * m.indexLatest) + '/m²';
    if (f.startsWith('plot_m2') || f === 'floor_area') return d3.format(',')(Math.round(v)) + ' m²';
    if (f === 'dist_centre_km' || f === 'knn_dist') return d3.format('.1f')(v) + ' km';
    if (f === 'property_type') return ['detached', 'semi', 'terraced', 'flat'][v] || String(v);
    if (f === 'age_year') return 'about ' + Math.round(v);
    if (f === 'years_since_prev') return d3.format('.1f')(v) + ' years';
    if (f === 'wall_type') return ['cavity', 'solid brick', 'system built', 'timber', 'stone'][v] || String(v);
    if (f === 'built_form_code') return ['detached', 'semi', 'end-terrace', 'mid-terrace', 'enclosed end-terrace', 'enclosed mid-terrace'][v] || String(v);
    if (f === 'tenure') return v ? 'leasehold' : 'freehold';
    if (['new_build', 'bungalow', 'mains_gas', 'top_floor', 'elec_heating', 'heat_pump', 'woodburner', 'solar_pv', 'prev_nb'].includes(f)) return v ? 'yes' : 'no';
    if (f === 'loft_mm') return Math.round(v) + ' mm';
    if (f === 'epc_reason') return ['marketed sale', 'non-marketed sale', 'rental', 'new home', 'other'][v] || String(v);
    if (f === 'epc_tenure_n') return ['owner-occupied', 'private rented', 'social rented'][v] || String(v);
    if (f === 'epc_rental_5y') return v ? 'yes' : 'no';
    if (f === 'epc_age_y') return d3.format('.1f')(v) + ' years';
    if (f === 'epc_n') return String(Math.round(v));
    if (f === 'sap_jump') return (v > 0 ? '+' : '') + Math.round(v) + ' points';
    if (f === 'ceiling_m') return d3.format('.2f')(v) + ' m';
    if (f === 'lat' || f === 'lon') return d3.format('.4f')(v);
    return d3.format(',.3~f')(v);
  };
  const renderWhy = (v, cond) => {
    const box = $('#why-chart'), model = getModel(); fresh(box);
    if (!model || !model.groups || !model.trees[0][0] || model.trees[0][0].length < 8) { $('#why-start').textContent = ''; return; }
    const nF = model.features.length, x = model.features.map((f) => v.feat[f]), phi = treeShap(model.trees, x, nF), fi = new Map(model.features.map((f, i) => [f, i]));
    const items = Object.entries(model.groups).map(([g, fs]) => ({ g, v: d3.sum(fs, (f) => phi[fi.get(f)]),
      parts: fs.map((f) => ({ f, v: phi[fi.get(f)], x: v.feat[f] })).filter((p) => Math.abs(p.v) >= 0.001).sort((a, b) => Math.abs(b.v) - Math.abs(a.v)) }));
    if (v.local) items.push({ g: 'Local correction', v: v.local, note: `${d3.format('.0%')(model.alpha)} of the model's median miss on the ${model.k} nearest sales since ${monthLabel(model.poolFrom)}`, parts: [] });
    if (cond && cond.adj) items.push({ g: 'Condition', v: Math.log(1 + cond.adj / 100), note: 'your setting, from repeat-sales calibration', parts: [] });
    items.forEach((d) => { d.p = (Math.exp(d.v) - 1) * 100; });
    items.sort((a, b) => Math.abs(b.p) - Math.abs(a.p));
    const base = Math.exp(phi[nF] + Math.log(model.indexLatest)), fin = v.est * (1 + ((cond && cond.adj) || 0) / 100);
    $('#why-start').textContent = `Starts from ${gbp(Math.round(base / 1000) * 1000)}, the model's typical Doncaster sale in today's money, and ends at ${gbp(Math.round(fin / 1000) * 1000)}. Effects multiply.`;
    const W = Math.max(280, box.clientWidth), narrow = W < 520, bh = narrow ? 14 : 20, gap = 6, lh = narrow ? 16 : 0, H = items.length * (bh + gap + lh) + 4;
    const svg = d3.select(box).append('svg').attr('width', '100%').attr('viewBox', `0 0 ${W} ${H}`).attr('role', 'img').attr('aria-label', 'What moved the estimate up or down');
    const measure = (s) => { const tx = svg.append('text').text(s).style('font-size', 'var(--cds-font-size-caption)'); const w = tx.node().getComputedTextLength(); tx.remove(); return w; };
    const lw = d3.max(items, (d) => measure(d.g)), vw = d3.max(items, (d) => measure(sgn(d.p))) + 8;
    const left = narrow ? 0 : lw + 12, mxp = d3.max(items, (d) => Math.abs(d.p)) || 1;
    const xs = d3.scaleLinear([-mxp, mxp], [left + vw, W - vw]);
    if (!narrow) svg.append('line').attr('x1', xs(0)).attr('x2', xs(0)).attr('y1', 0).attr('y2', H).attr('stroke', 'var(--cds-chart-axis)');
    const t = tip(box);
    items.forEach((d, i) => {
      const y = i * (bh + gap + lh) + 2 + lh, xa = xs(Math.min(0, d.p)), w = Math.max(2, Math.abs(xs(d.p) - xs(0)));
      if (narrow) svg.append('line').attr('x1', xs(0)).attr('x2', xs(0)).attr('y1', y - 2).attr('y2', y + bh + 2).attr('stroke', 'var(--cds-chart-axis)');
      if (narrow) svg.append('text').attr('x', 0).attr('y', y - 4).attr('fill', 'var(--color-fg-muted)').style('font-size', 'var(--cds-font-size-caption)').text(d.g);
      else svg.append('text').attr('x', left - 8).attr('y', y + bh / 2).attr('dy', '0.35em').attr('text-anchor', 'end').attr('fill', 'var(--color-fg-muted)').style('font-size', 'var(--cds-font-size-caption)').text(d.g);
      svg.append('rect').attr('x', xa).attr('y', y).attr('width', w).attr('height', bh).attr('rx', 4).attr('fill', d.p >= 0 ? dash.colors[0] : dash.colors[1])
        .on('mousemove', (e) => { const [px, py] = d3.pointer(e, box);
          const lines = [['t', `${d.g}: ${sgn(d.p)}`]].concat(d.note ? [['', d.note]] : d.parts.slice(0, 7).map((q) => ['', `${FEAT[q.f] || q.f} (${fmtFeat(q.f, q.x)}): ${sgn((Math.exp(q.v) - 1) * 100)}`]));
          t.show(lines, px, py); })
        .on('mouseleave', () => t.hide());
      svg.append('text').attr('x', d.p >= 0 ? xs(d.p) + 4 : xs(d.p) - 4).attr('y', y + bh / 2).attr('dy', '0.35em').attr('text-anchor', d.p >= 0 ? 'start' : 'end')
        .attr('fill', 'var(--color-fg)').style('font-size', 'var(--cds-font-size-caption)').style('font-variant-numeric', 'tabular-nums').text(sgn(d.p));
    });
  };
  const CT_ORDER = 'ABCDEFGH';
  const renderCt = (v, inp) => {
    const el = $('#ct-kv'), verdict = $('#ct-verdict'), mix = getCtMix();
    if (!inp.ctband) { kv(el, [['Band', 'not entered']]); verdict.textContent = ''; return; }
    if (!mix) { kv(el, [['Band', inp.ctband]]); verdict.textContent = ''; return; }
    const ptype = inp.type === 'F' ? 'flat' : (inp.bungalow ? 'bungalow' : inp.type), beds = inp.beds === '4' ? ['4', '5', '6'] : [inp.beds];
    const lsoa = v.pc.lsoa21, tname = inp.type === 'F' ? 'flats' : inp.bungalow ? 'bungalows' : { D: 'detached houses', S: 'semi-detached houses', T: 'terraced houses' }[inp.type];
    let sel = mix.filter((r) => r.lsoa21 === lsoa && r.ptype === ptype && beds.includes(r.beds)), what = `${inp.beds === '4' ? '4+' : inp.beds}-bed ${tname}`;
    if (d3.sum(sel, (r) => r.c) < 30) { sel = mix.filter((r) => r.lsoa21 === lsoa && r.ptype === ptype); what = tname; }
    if (d3.sum(sel, (r) => r.c) < 30) { sel = mix.filter((r) => r.lsoa21 === lsoa); what = 'homes'; }
    const by = d3.rollup(sel, (g) => d3.sum(g, (r) => r.c), (r) => r.band), tot = d3.sum(by.values()), bi = CT_ORDER.indexOf(inp.ctband);
    let below = 0; by.forEach((c, b) => { if (CT_ORDER.indexOf(b) < bi) below += c; });
    const bandPct = tot >= 30 ? (below + (by.get(inp.ctband) || 0) / 2) / tot * 100 : NaN;
    const idx = getIndex(), comps = getComps(), model = getModel(), est = state.last ? state.last.adj : v.est;
    const near = comps.filter((c) => c.type === inp.type && hav(v.lat, v.lon, c.latN, c.lonN) <= 1.5)
      .map((c) => { const i = idx.raw.get(String(c.date).slice(0, 7)); return i ? c.priceN * model.indexLatest / i : NaN; }).filter(isFinite);
    const pricePct = near.length >= 10 ? near.filter((p) => p < est).length / near.length * 100 : NaN;
    kv(el, [['Band', inp.ctband], [`Bands of ${what} in this neighbourhood`, tot ? [...CT_ORDER].filter((b) => by.get(b)).map((b) => `${b} ${pct(by.get(b) / tot * 100, 0)}`).join(' · ') : 'no data'],
      ['This band is above about', isFinite(bandPct) ? `${pct(bandPct, 0)} of them` : 'too few homes to say'],
      [`The estimate is above`, isFinite(pricePct) ? `${pct(pricePct, 0)} of ${near.length} recent ${TYPE_SHORT[inp.type].toLowerCase()} sales within 1.5 km` : 'too few recent sales nearby']]);
    const g = bandPct - pricePct;
    verdict.textContent = !isFinite(g) ? '' : g > 30 ? 'The band ranks this home well above where the estimate does. It may be bigger or better than the details entered: check the floor area, plot and condition.'
      : g < -30 ? 'The estimate ranks this home well above its band. Check the floor area, and whether it was extended or improved after 1991 (bands rarely change after improvements).'
        : 'The band and the estimate put this home in a similar place among its neighbours.';
  };
  const renderHist = (inp) => {
    const tb = $('#hist-table tbody'), note = $('#hist-note'), idx = getIndex(), model = getModel(); tb.replaceChildren();
    const e = inp.epc;
    $('#hist-table').setAttribute('data-source', 'price_index' + (e ? ' epc_' + inp.postcode.split(' ')[0] : ''));
    const ha = $('#hist-addr'); ha.textContent = e ? `${String(e.address).replace(/^(\d+),/, '$1')}, ${inp.postcode}` : '';
    if (!e) { note.textContent = 'Pick an address above to see its sales.'; return; }
    const h = parseSales(e.sales), upTo = model && model.indexMonth ? ` Land Registry records run to ${monthLabel(model.indexMonth)}; a sale can take a few months to appear.` : '';
    if (!h.length) { note.textContent = 'No sales of this address since 1995 in the Land Registry data (or it could not be matched to the certificate).' + upTo; return; }
    h.slice().reverse().forEach((s, i) => {
      const tr = document.createElement('tr'), ix = idx ? idx.raw.get(s.date.slice(0, 7)) : null;
      cell(tr, d3.utcFormat('%-d %b %Y')(new Date(s.date))); cell(tr, gbp(s.price), 'r'); cell(tr, ix && model ? gbp(s.price * model.indexLatest / ix) : '—', 'r');
      cell(tr, [s.nb ? 'new build' : '', i === 0 && state.prevAuto ? 'used as last sale' : ''].filter(Boolean).join(', ')); tb.appendChild(tr);
    });
    note.textContent = (h.length > 1 ? `Sold ${h.length} times since ${h[0].date.slice(0, 4)}.` : '') + upTo;
  };
  const WI_CHECKS = [['#wi-area', 0, 300, 'Floor area added (0 to 300 m²)'], ['#wi-rooms', 0, 10, 'Rooms added (0 to 10)'], ['#wi-baths', 0, 5, 'Bathrooms to refit (0 to 5)']];
  const renderWhatIf = (v, inp, cond) => {
    const el = $('#wi-kv'), A = getAss(), note = $('#wi-note');
    if (!A || !A.ext_single_m2) { kv(el, []); return; }
    for (const [sel, lo, hi, name] of WI_CHECKS) { const raw = val(sel), x = num(raw); if (String(raw).trim() !== '' && !(isFinite(x) && x >= lo && x <= hi)) { kv(el, []); note.textContent = `${name} is out of range. The comparison is cleared until it is fixed.`; return; } }
    const add = Math.max(0, num(val('#wi-area')) || 0), addRooms = Math.max(0, num(val('#wi-rooms')) || 0), kind = val('#wi-kind'), epcT = num(val('#wi-epc')), ref = val('#wi-refurb');
    const after = { ...inp };
    if ((add > 0 && !isFinite(inp.area)) || (addRooms > 0 && !isFinite(inp.rooms))) {
      kv(el, []); note.textContent = 'Enter the current floor area and number of bedrooms and living rooms above (or pick the address) first, so the comparison is like for like.'; return;
    }
    if (add > 0) after.area = inp.area + add;
    if (addRooms > 0) after.rooms = inp.rooms + addRooms;
    if (isFinite(epcT) && !(isFinite(inp.sap) && inp.sap >= epcT)) { after.sap = epcT; after.sapManual = true; if (isFinite(after.sapPot) && after.sapPot < epcT) after.sapPot = epcT; }
    // works lift the condition to what they leave only if the home starts no worse than the condition they put right:
    // decorating a home that needs a full renovation (rewiring, heating, plaster) doesn't make it "good"
    const CS = getCond() || [], toC = ref && REFURB[ref] ? CS.find((c) => c.key === REFURB[ref].to) : null, fromC = ref && REFURB[ref] ? CS.find((c) => c.key === REFURB[ref].from) : null;
    const base = cond.base != null ? cond.base : cond.adj, tooLittle = !!(toC && fromC && base < fromC.adj - 1e-9);
    const up = toC && toC.adj > base && !tooLittle, w = value(after), afterAdj = up ? condFor(toC, inp).adj : cond.adj;
    if (w.status !== 'ok') { kv(el, []); return; }
    const now = v.est * (1 + cond.adj / 100), then = w.est * (1 + afterAdj / 100);
    const rate = { single: A.ext_single_m2.v, double: A.ext_double_m2.v, loft: A.loft_m2.v }[kind], vat = kind === 'loft' ? 0 : A.vat_works.v / 100;
    const cBuild = add > 0 ? add * rate * (1 + vat) + A.ext_fees.v : 0;
    const cEpc = isFinite(epcT) && !(isFinite(inp.sap) && inp.sap >= epcT) ? Math.min(A.epc_upgrade_avg.v, now < 100000 ? now * 0.1 : A.epc_cost_cap.v) : 0;
    const area = isFinite(after.area) ? after.area : A.floor_area.v, R = ref ? refurbCost(A, ref, area, val('#wi-finish'), num(val('#wi-baths')), 0, v.est) : null;
    const cRef = R ? R.total : 0, cost = cBuild + cEpc + cRef, gain = then - now;
    kv(el, [['Value now (your condition)', gbp(Math.round(now / 1000) * 1000)], ['Value after the works', gbp(Math.round(then / 1000) * 1000)], ['Value added', gbp(gain), gain >= 0 ? 'good' : 'badc'], 'sep',
      ...(cBuild ? [[`Build: ${add} m² × ${gbp(rate)}${vat ? ' + VAT' : ''} + fees`, gbp(cBuild)]] : []), ...(cEpc ? [['Energy upgrade (average to reach C)', gbp(cEpc)]] : []),
      ...(cRef ? [[`${R.label} (${Math.round(area)} m²)`, gbp(cRef)]] : []), ['Estimated cost', gbp(cost)], 'sep',
      ['Value added less cost', gbp(gain - cost), gain - cost >= 0 ? 'good' : 'badc'], ...(cost > 0 ? [['Value added per £1 spent', d3.format('.2f')(gain / cost)]] : [])]);
    note.textContent = (R ? `${R.label}, ${R.finish}: ${refurbText(R)}. ` + (tooLittle ? `A home that ${cond.label.toLowerCase() === 'needs full renovation' ? 'needs a full renovation' : 'is in this condition'} needs more than ${R.label.toLowerCase()} to sell as ${toC.label.toLowerCase()}, so no rise in value is counted; pick Full renovation to see that. ` : toC && toC.adj <= base ? 'Your condition setting is already at or above what these works leave, so the value doesn\'t change. ' : '') : '') + (cost === 0 && gain === 0 ? 'Choose some works above.' : add > 0 && gain <= 0 ? 'The model doesn\'t value this extra space here: for about 1 home in 50 a small addition lands on one of its steps and reads as no gain. Treat it as roughly zero and compare with sold prices of extended homes nearby.' : 'The model has learned what bigger, better-rated or refurbished homes sell for nearby, not what one particular extension adds: treat this as a first check before getting quotes. Estimates move slightly with every input, so small gains are within the model\'s noise.');
  };
  const drawCompsMap = (v, list) => {
    const box = $('#comps-map'); fresh(box); if (!list.length) return;
    const W = Math.max(260, box.clientWidth), H = 260, m = 14, k = Math.cos(v.lat * Math.PI / 180);
    const pts = list.map((r) => ({ ...r, x: (r.lonN - v.lon) * k, y: r.latN - v.lat }));
    const ext = Math.max(0.002, d3.max(pts, (p) => Math.max(Math.abs(p.x), Math.abs(p.y)))) * 1.1, s = Math.min(W - 2 * m, H - 2 * m) / (2 * ext), cx = W / 2, cy = H / 2;
    const col = d3.scaleLinear().domain(d3.extent(pts, (p) => p.today)).range([0.3, 1]);
    const svg = d3.select(box).append('svg').attr('width', '100%').attr('viewBox', `0 0 ${W} ${H}`).attr('role', 'img').attr('aria-label', 'Map of comparable sales');
    [0.5, 1].forEach((f) => svg.append('circle').attr('cx', cx).attr('cy', cy).attr('r', ext * s * f).attr('fill', 'none').attr('stroke', 'var(--cds-chart-grid)'));
    svg.append('text').attr('x', cx + ext * s * 0.36 + 4).attr('y', cy - ext * s * 0.36).attr('fill', 'var(--color-fg-muted)').style('font-size', 'var(--cds-font-size-caption)').text(d3.format('.1f')(ext * 0.5 * 111.2) + ' km');
    const t = tip(box);
    svg.selectAll('circle.pt').data(pts).join('circle').attr('class', 'pt').attr('cx', (p) => cx + p.x * s).attr('cy', (p) => cy - p.y * s).attr('r', 6)
      .attr('fill', dash.colors[0]).attr('fill-opacity', (p) => (isFinite(p.today) ? col(p.today) : 0.5)).attr('stroke', 'var(--color-panel)').attr('stroke-width', 2)
      .on('mousemove', (e, p) => { const [x, y] = d3.pointer(e, box); t.show([['t', p.address || p.postcode], ['', `${gbp(p.priceN)} (${d3.utcFormat('%b %Y')(new Date(p.date))})`], ['', `${gbp(p.today)} in today's money`]], x, y); })
      .on('mouseleave', () => t.hide());
    svg.append('circle').attr('cx', cx).attr('cy', cy).attr('r', 9).attr('fill', 'none').attr('stroke', 'var(--color-fg)').attr('stroke-width', 2);
  };

  // ================= SAVED PROPERTIES (private to each viewer, in the dashboard's own store) =================
  const WL = { col: null, items: [], off: false, err: null };
  // the public stand-alone copy has no private store or address register: hide what needs them
  if (window.DPM_STANDALONE) { ['#save-card', '#tab-saved', '#hist-card'].forEach((s) => { const el = $(s); if (el) el.hidden = true; }); const al = $('#in-address').closest('label'); if (al) al.hidden = true; }
  const clean = (o) => JSON.parse(JSON.stringify(o, (k, v) => (typeof v === 'number' && !isFinite(v) ? null : v)));
  const NUMK = ['area', 'rooms', 'form', 'age', 'sap', 'sapPot', 'gas', 'prevPrice', 'asking', 'plot', 'bungalow'];
  const restore = (inp) => { const o = { ...inp }; NUMK.forEach((k) => { o[k] = o[k] == null ? NaN : Number(o[k]); }); return o; };
  const setSaveStatus = (msg) => { $('#save-status').textContent = msg != null ? msg : WL.off ? 'Saving needs you to be signed in with at least Contributor access to this dashboard.' : WL.col ? '' : 'Connecting to your saved list…'; $('#save-btn').disabled = !WL.col; };
  (async () => {
    try {
      const use = window.claude && window.claude.use; if (!use) throw new Error('none');
      const [db, user] = await Promise.all([window.claude.use('db'), window.claude.use('user')]);
      const uid = db && user ? await user.id() : null; if (!uid) throw new Error('none');
      WL.col = db.doc(`data/users/${uid}/watchlist`).collection('items');
      WL.col.onSnapshot((snap) => { WL.items = snap.docs.map((d) => ({ id: d.id, ...d.data() })); if (state.tab === 'saved') renderSaved(); },
        (e) => { WL.err = e.code; WL.col = null; setSaveStatus(`Your saved list couldn't be read (${e.code}).`); });
      setSaveStatus();
    } catch (e) { WL.off = true; setSaveStatus(); }
  })();
  setSaveStatus();
  const dealSummary = () => {
    const A = getAss(); if (!A) return {};
    syncDefaults(); const d = readDeal(); if (![d.price, d.rent, d.dep, d.rate].every(isFinite) || d.price <= 0) return {};
    const y1 = yearCalc(d, A, { rent: d.rent, costMult: 1, balance: d.price * (1 - d.dep), year2027: d.taxYear === '2027' });
    return { price: d.price, rent: d.rent, gross: y1.annualRent / d.price * 100, cash: y1.post / 12, owner: d.owner };
  };
  $('#save-btn').addEventListener('click', async () => {
    const L = state.last; if (!WL.col || !L) return;
    const inp = { ...L.inp }; const label = (inp.epc && inp.epc.address ? inp.epc.address + ', ' : '') + inp.postcode;
    const rec = clean({ savedAt: new Date().toISOString(), label, type: inp.type, inputs: inp, estimate: L.adj, low: L.lo * (1 + L.cond.adj / 100), high: L.hi * (1 + L.cond.adj / 100),
      asking: inp.asking, notes: $('#save-notes').value.slice(0, 500), ...dealSummary() });
    const id = Date.now().toString(36) + Math.random().toString(36).slice(2, 6);
    $('#save-btn').disabled = true;
    try { await WL.col.doc(id).set(rec); $('#save-notes').value = ''; setSaveStatus(`Saved ${label}. See the Saved tab.`); }
    catch (e) { setSaveStatus(e && e.code === 'invalid_argument' ? 'Saving is read-only for you on this dashboard.' : `Couldn't save (${(e && e.code) || 'error'}).`); }
    $('#save-btn').disabled = !WL.col;
  });
  const openSaved = (rec) => {
    const i = restore(rec.inputs || {});
    $('#in-postcode').value = i.postcode || ''; state.addrKey = null; state.epc = null; fillAddresses();
    if (i.epc && i.epc.address) { const k = state.epcOptions.findIndex((r) => r.address === i.epc.address); if (k >= 0) $('#in-address').value = String(k); }
    state.epc = i.epc || null; state.sapManual = !!i.sapManual;
    const setv = (s, v) => { $(s).value = v == null || (typeof v === 'number' && !isFinite(v)) ? '' : String(v); };
    setv('#in-type', i.type); setv('#in-tenure', i.tenure); setv('#in-beds', i.beds); setv('#in-condition', i.condition); setv('#in-area', i.area); setv('#in-rooms', i.rooms);
    setv('#in-form', i.form); setv('#in-age', i.age); setv('#in-prev-price', i.prevPrice); setv('#in-prev-month', i.prevMonth); setv('#in-asking', i.asking); setv('#in-plot', i.plot); setv('#in-ctband', i.ctband);
    if (isFinite(i.sap)) $('#in-rating').value = SAP_TO_SELECT(i.sap);
    $('#in-bungalow').checked = !!i.bungalow; $('#in-new').checked = !!i.newBuild;
    freshDeal(); state.listingOwned = {}; state.listingRent = null;
    if (isFinite(rec.rent)) { state.listingRent = rec.rent; }
    showTab('value');
  };
  const renderSaved = () => {
    const tb = $('#saved-table tbody'), st = $('#saved-status');
    if (!WL.col) { tb.replaceChildren(); st.textContent = WL.off ? 'Saving needs you to be signed in with at least Contributor access to this dashboard.' : (WL.err ? `Your saved list couldn't be read (${WL.err}).` : 'Loading your saved list…'); return; }
    const items = WL.items.slice().sort((a, b) => String(b.savedAt).localeCompare(String(a.savedAt)));
    st.textContent = items.length ? `${items.length} saved` : 'Nothing saved yet. Use "Save this property" on the value tab.';
    tb.replaceChildren();
    items.forEach((r) => {
      const tr = document.createElement('tr'), cond = (getCond() || []).find((c) => c.key === (r.inputs && r.inputs.condition)) || { adj: 0 };
      const ri = r.inputs ? restore(r.inputs) : null, now = ri ? value(ri) : { status: 'none' }, estNow = now.status === 'ok' ? now.est * (1 + condFor(cond, ri).adj / 100) : NaN;
      cell(tr, r.label || '—'); cell(tr, r.savedAt ? d3.utcFormat('%-d %b %Y')(new Date(r.savedAt)) : '—'); cell(tr, isFinite(r.asking) && r.asking ? gbp(r.asking) : '—', 'r');
      cell(tr, gbp(r.estimate), 'r'); cell(tr, gbp(estNow), 'r');
      const gapc = cell(tr, isFinite(r.asking) && r.asking && isFinite(estNow) ? sgn((r.asking / estNow - 1) * 100, 0) : '—', 'r'); if (isFinite(r.asking) && r.asking > estNow * 1.1) gapc.classList.add('warnc');
      cell(tr, r.rent ? gbp(r.rent) : '—', 'r'); cell(tr, isFinite(r.gross) ? pct(r.gross, 1) : '—', 'r');
      const cc = cell(tr, isFinite(r.cash) ? gbp(r.cash) : '—', 'r'); if (r.cash < 0) cc.classList.add('badc');
      cell(tr, r.notes || '');
      const td = document.createElement('td'), o = document.createElement('button'), del = document.createElement('button');
      o.className = 'btn'; o.textContent = 'Open'; o.addEventListener('click', () => openSaved(r));
      del.className = 'btn'; del.textContent = 'Delete'; del.style.marginLeft = '4px';
      del.addEventListener('click', async () => { if (del.dataset.armed !== '1') { del.dataset.armed = '1'; del.textContent = 'Confirm'; return; }
        try { await WL.col.doc(r.id).delete(); } catch (e) { st.textContent = `Couldn't delete (${(e && e.code) || 'error'}).`; } });
      td.append(o, del); tr.appendChild(td); tb.appendChild(tr);
    });
  };

  // ================= BUY-TO-LET =================
  const sdlt = (price, A) => {
    if (price < 40000) return 0; // additional homes under £40k pay no surcharge, and fall in the 0% band
    const bands = [0, A.sdlt_band_1.v, A.sdlt_band_2.v, A.sdlt_band_3.v, A.sdlt_band_4.v, Infinity];
    const rates = [A.sdlt_rate_1.v, A.sdlt_rate_2.v, A.sdlt_rate_3.v, A.sdlt_rate_4.v, A.sdlt_rate_5.v].map((r) => (r + A.sdlt_surcharge.v) / 100);
    let tax = 0; for (let i = 0; i < 5; i++) tax += Math.max(0, Math.min(price, bands[i + 1]) - bands[i]) * rates[i];
    return tax;
  };
  const DEFAULTS = [['#b-deposit', 'deposit'], ['#b-rate', 'mortgage_rate'], ['#b-term', 'mortgage_term'], ['#b-fee', 'product_fee'], ['#b-letting', 'letting_fee'], ['#b-maint', 'maintenance'],
    ['#b-voids', 'voids'], ['#b-ins', 'insurance'], ['#b-comp', 'compliance'], ['#b-legal', 'buying_costs'], ['#p-rent', 'rent_growth'], ['#p-price', 'price_growth'], ['#p-cost', 'cost_inflation'], ['#b-income', 'cgt_other_income']];
  const syncDefaults = () => {
    const A = getAss(); if (!A) return;
    DEFAULTS.forEach(([s, k]) => { if ($(s).value === '' && A[k]) $(s).value = String(A[k].v); });
    if ($('#b-works').value === '') $('#b-works').value = '0';
    const L = state.last;
    if (L && !state.touched.price) $('#b-price').value = String(Math.round((isFinite(L.inp.asking) && L.inp.asking > 0 ? L.inp.asking : L.adj) / 1000) * 1000);
    if (!state.touched.rent) {
      const R = rentEstimate(), r = state.listingRent || (R ? R.est : null) || (L ? (latestRent({ 1: '1 bed', 2: '2 bed', 3: '3 bed', 4: '4+ bed' }[L.inp.beds]) || {}).v : null);
      if (r) $('#b-rent').value = String(r);
    }
    if (!state.touched.epcCost) {
      const price = num(val('#b-price')), sap = L ? L.inp.sap : NaN;
      const cap = isFinite(price) && price < 100000 ? price * 0.1 : A.epc_cost_cap.v;
      $('#b-epc').value = String(isFinite(sap) && sap < 69 ? Math.round(Math.min(A.epc_upgrade_avg.v, cap)) : 0);
    }
    if (!state.touched.gPrice) { const H = homeReturn(); if (H && isFinite(H.g)) $('#p-price').value = String(Math.round(H.g * 100) / 100); }
    if ($('#f-area').value === '' || !state.touched.farea) $('#f-area').value = String(L && isFinite(L.inp.area) ? Math.round(L.inp.area) : A.floor_area.v);
  };
  [['#b-price', 'price'], ['#b-rent', 'rent'], ['#b-epc', 'epcCost'], ['#f-area', 'farea'], ['#p-price', 'gPrice']].forEach(([s, k]) => $(s).addEventListener('input', () => { state.touched[k] = true; renderInvest(); }));
  ['#b-deposit', '#b-rate', '#b-term', '#b-fee', '#b-letting', '#b-maint', '#b-voids', '#b-ins', '#b-comp', '#b-legal', '#b-works', '#b-improve', '#b-income', '#p-rent', '#p-cost', '#f-baths', '#f-quote', '#f-cont', '#f-months', '#f-fin', '#f-ltv']
    .forEach((s) => $(s).addEventListener('input', () => renderInvest()));
  ['#b-owner', '#b-taxyear', '#b-mtype'].forEach((s) => $(s).addEventListener('change', () => renderInvest()));
  ['#f-scope', '#f-finish', '#f-vat'].forEach((s) => $(s).addEventListener('change', () => renderInvest()));

  const readDeal = () => ({
    price: num(val('#b-price')), rent: num(val('#b-rent')), owner: val('#b-owner'), taxYear: val('#b-taxyear'), dep: num(val('#b-deposit')) / 100, rate: num(val('#b-rate')) / 100,
    mtype: val('#b-mtype'), term: num(val('#b-term')), fee: num(val('#b-fee')) || 0, letting: num(val('#b-letting')) / 100, maint: num(val('#b-maint')) / 100, voids: num(val('#b-voids')),
    ins: num(val('#b-ins')) || 0, comp: num(val('#b-comp')) || 0, legal: num(val('#b-legal')) || 0, works: num(val('#b-works')) || 0, epc: num(val('#b-epc')) || 0,
    improve: num(val('#b-improve')) || 0, income: num(val('#b-income')),
    gRent: num(val('#p-rent')) / 100, gPrice: num(val('#p-price')) / 100, gCost: num(val('#p-cost')) / 100
  });
  const taxRates = (A, owner, year2027) => {
    if (owner === 'company') return { company: true, rate: A.corp_tax_small.v / 100, credit: 0 };
    const rate = owner === 'higher' ? (year2027 ? A.tax_higher_2027.v : A.tax_higher.v) : (year2027 ? A.tax_basic_2027.v : A.tax_basic.v);
    return { company: false, rate: rate / 100, credit: (year2027 ? A.finance_credit_2027.v : A.finance_credit.v) / 100 };
  };
  // corporation tax with marginal relief (HMRC rates for FY2025 and FY2026): 19% on profits up to £50,000, 25% above
  // £250,000, and in between 25% less 3/200 of (£250,000 - profit). Associated companies and short accounting periods,
  // which lower both limits, aren't modelled. A company letting to unconnected tenants qualifies for the small profits rate.
  const corpTax = (profit, A) => {
    const v = (k, dflt) => (A[k] ? A[k].v : dflt), sm = v('corp_tax_small', 19) / 100, mn = v('corp_tax_main', 25) / 100, lo = v('corp_tax_lower', 50000), hi = v('corp_tax_upper', 250000), fr = v('corp_tax_fraction', 0.015);
    if (!(profit > 0)) return 0; if (profit <= lo) return profit * sm; if (profit >= hi) return profit * mn; return profit * mn - fr * (hi - profit);
  };
  // tax on the gain when the home is sold (gov.uk, 2026/27): an individual pays 18% (basic rate) or 24% (higher rate) on
  // the gain above the £3,000 annual exempt amount; a company pays corporation tax on it, on top of that year's profit, with
  // no exempt amount. Gain = sale price less selling costs, less the price, stamp duty, legal costs, works and EPC upgrade.
  // A basic-rate owner pays 24% on any part of the gain above their unused basic-rate band; that isn't modelled.
  // A basic-rate owner pays 18% only on the part of the taxable gain that fits in what's left of the basic-rate band
  // (£37,700) after their other taxable income and that year's rental profit, and 24% on the rest (gov.uk's example:
  // £20,000 income and a £52,600 gain pay £10,842). Returns the tax and how much fell at each rate.
  const gainsTaxDetail = (d, A, gain, profitThatYear = 0) => {
    const v = (k, dflt) => (A[k] ? A[k].v : dflt), none = { tax: 0, low: 0, high: 0, taxable: 0 };
    if (!(gain > 0)) return none;
    if (d.owner === 'company') return { ...none, tax: corpTax(Math.max(0, profitThatYear) + gain, A) - corpTax(Math.max(0, profitThatYear), A), taxable: gain };
    const taxable = Math.max(0, gain - v('cgt_aea', 3000)), hi = v('cgt_higher', 24) / 100, lo = v('cgt_basic', 18) / 100;
    if (d.owner === 'higher') return { tax: taxable * hi, low: 0, high: taxable, taxable };
    const income = isFinite(d.income) ? d.income : v('cgt_other_income', 20000), left = Math.max(0, v('basic_rate_band', 37700) - income - Math.max(0, profitThatYear));
    const low = Math.min(taxable, left), high = taxable - low;
    return { tax: low * lo + high * hi, low, high, taxable };
  };
  const gainsTax = (d, A, gain, profitThatYear = 0) => gainsTaxDetail(d, A, gain, profitThatYear).tax;
  // one year of the deal; balance = loan at start of year
  // carry = { fin, loss } brought forward from earlier years (none in a single-year view)
  // oneOff: a deduction from that year's taxable profit only (repairs in the works, in year 1 of the projection); it
  // changes the tax, not the cash flow, since the works are already in the cash put in
  const yearCalc = (d, A, { rent, costMult, balance, year2027, rateAdj = 0, voids = d.voids, maintMult = 1, carry = { fin: 0, loss: 0 }, oneOff = 0 }) => {
    const r = d.rate + rateAdj, annualRent = rent * 12, collected = annualRent * (52 - voids) / 52;
    const opex = collected * (d.letting + d.maint * maintMult) + (d.ins + d.comp) * costMult;
    let interest = 0, principal = 0;
    if (d.mtype === 'io') interest = balance * r;
    else {
      const mr = r / 12, n = d.term * 12, pay = mr > 0 ? (d.price * (1 - d.dep)) * mr / (1 - (1 + mr) ** -n) : (d.price * (1 - d.dep)) / n;
      let b = balance; for (let i = 0; i < 12 && b > 0; i++) { const it = b * mr, pr = Math.min(b, pay - it); interest += it; principal += pr; b -= pr; }
    }
    const tr = taxRates(A, d.owner, year2027);
    let tax, relieved = 0, finCF = 0, lossCF = 0, taxable;
    if (tr.company) {
      // a company deducts interest; a loss is carried forward against later profits
      taxable = collected - opex - interest - carry.loss - oneOff; if (taxable < 0) { lossCF = -taxable; taxable = 0; }
      tax = corpTax(taxable, A);
    } else {
      // individuals: interest isn't deducted; the tax credit is the basic rate on the lowest of the finance costs (with any
      // brought forward) and the property profits (after losses brought forward). HMRC's third limit, adjusted total income
      // above the personal allowance, is assumed not to bind (other income covers the allowance). Unused costs carry forward.
      taxable = collected - opex - carry.loss - oneOff; if (taxable < 0) { lossCF = -taxable; taxable = 0; }
      const fin = interest + carry.fin; relieved = Math.min(fin, taxable); finCF = fin - relieved;
      tax = taxable * tr.rate - relieved * tr.credit;
    }
    const pre = collected - opex - interest - principal;
    return { annualRent, collected, opex, interest, principal, tax, pre, post: pre - tax, endBalance: balance - principal, tr, taxable, relieved, carry: { fin: finCF, loss: lossCF } };
  };
  // every rate between -99% and +10,000% a year at which the NPV is zero. The NPV is a polynomial in x = 1/(1+r), and
  // between two neighbouring turning points a polynomial is monotone, so it crosses zero at most once there. polyRoots
  // finds the turning points (the roots of the derivative, by the same method, down to a straight line), bisects every
  // stretch whose ends differ in sign, and counts a turning point where the value is zero to rounding as a repeated root
  // (-100, 220, -121 touches zero at 10% without crossing). Tested on cash flows built from known rates: pairs 0.01
  // points apart are always separated, pairs 0.001 points apart almost always; near a repeated rate a penny's change in
  // one cash flow moves the rates further than that. Cash flows that change sign more than once can have several rates
  // (-100, 230, -132: 10% and 20%)
  const IRR_LO = -0.99, IRR_HI = 100;
  const polyRoots = (coef, a, b) => {
    let n = coef.length - 1; while (n > 0 && coef[n] === 0) n -= 1;
    if (n < 1) return [];
    const c = coef.slice(0, n + 1);
    const p = (x) => { let v = 0; for (let t = n; t >= 0; t--) v = v * x + c[t]; return v; };
    const size = (x) => { let v = 0; const ax = Math.abs(x); for (let t = n; t >= 0; t--) v = v * ax + Math.abs(c[t]); return v; };
    const isZero = (x) => Math.abs(p(x)) <= 1e-13 * size(x);
    const turns = n > 1 ? polyRoots(c.slice(1).map((v, t) => v * (t + 1)), a, b).filter((x) => x > a && x < b) : [];
    const knots = [a, ...turns, b], roots = [];
    knots.forEach((x) => { if (isZero(x)) roots.push(x); });
    for (let i = 0; i + 1 < knots.length; i++) {
      let lo = knots[i], hi = knots[i + 1], flo = p(lo); const fhi = p(hi);
      if (isZero(lo) || isZero(hi) || flo * fhi > 0) continue;
      for (let k = 0; k < 200 && hi - lo > 1e-16 * Math.max(1, Math.abs(lo)); k++) { const m = (lo + hi) / 2, fm = p(m); if (flo * fm <= 0) hi = m; else { lo = m; flo = fm; } }
      roots.push((lo + hi) / 2);
    }
    return roots.sort((u, v) => u - v).filter((x, k, arr) => k === 0 || x - arr[k - 1] > 1e-12 * Math.max(1, Math.abs(x)));
  };
  const irrRoots = (cfs) => {
    if (!cfs.length || !cfs.every(isFinite) || !cfs.some((c) => c !== 0)) return [];
    return polyRoots(cfs, 1 / (1 + IRR_HI), 1 / (1 + IRR_LO)).map((x) => 1 / x - 1).sort((u, v) => u - v);
  };
  const irr = (cfs) => { const R = irrRoots(cfs); return R.length === 1 ? R[0] : NaN; };
  // more than one change of sign in the cash flows means more than one rate can give a zero NPV
  const signChanges = (cfs) => { let n = 0, prev = 0; cfs.forEach((c) => { const g = Math.sign(c); if (g) { if (prev && g !== prev) n += 1; prev = g; } }); return n; };
  const kv = (el, items) => {
    el.replaceChildren();
    items.forEach((it) => {
      if (it === 'sep') { const d = document.createElement('div'); d.className = 'sep'; el.appendChild(d); return; }
      const dt = document.createElement('dt'); dt.textContent = it[0]; const dd = document.createElement('dd'); dd.textContent = it[1]; if (it[2]) dd.className = it[2]; el.append(dt, dd);
    });
  };
  // every deal input and its allowed range. Each panel checks only the inputs it uses: the whole deal for the mortgage
  // analysis, CASH_KEYS for the cash-purchase scorecard, COST_KEYS for rent markers worked out from the price
  const DEAL_CHECKS = { price: [1000, 20000000, 'Purchase price (£1,000 to £20 million)'], rent: [0, 100000, 'Monthly rent (£0 to £100,000)'], dep: [0, 1, 'Deposit (0% to 100%)'], rate: [0, 0.25, 'Mortgage rate (0% to 25%)'],
    term: [1, 40, 'Mortgage term (1 to 40 years)'], letting: [0, 1, 'Letting fee (0% to 100%)'], maint: [0, 1, 'Maintenance (0% to 100%)'], voids: [0, 52, 'Void weeks (0 to 52)'],
    fee: [0, 1e6, 'Arrangement fee (£0 to £1 million)'], ins: [0, 1e6, 'Insurance (£0 to £1 million a year)'], comp: [0, 1e6, 'Safety checks (£0 to £1 million a year)'], legal: [0, 1e6, 'Legal and survey (£0 to £1 million)'], works: [0, 1e7, 'Works (£0 to £10 million)'], epc: [0, 1e6, 'EPC upgrade (£0 to £1 million)'],
    improve: [0, 1e7, 'Improvements (£0 to £10 million)'], income: [0, 1e7, 'Other taxable income (£0 to £10 million)'] };
  const DEAL_KEYS = Object.keys(DEAL_CHECKS), COST_KEYS = ['price', 'letting', 'maint', 'voids', 'ins', 'comp', 'legal', 'works', 'epc'], CASH_KEYS = [...COST_KEYS, 'rent'];
  const MORTGAGE_KEYS = DEAL_KEYS.filter((k) => !['rent', 'improve', 'income'].includes(k));      // the yearly figures: no sale-time inputs
  const dealProblem = (d, keys = DEAL_KEYS) => {
    for (const k of keys) {
      const [lo, hi, name] = DEAL_CHECKS[k], v = d[k];
      if (!isFinite(v)) { if (k === 'income') continue; return `${name.split(' (')[0]} is missing.`; }      // blank income: the default (cgt_other_income)
      if (v < lo || v > hi) return `${name} is out of range.`;
    }
    if (keys === DEAL_KEYS) for (const [v, name] of [[d.gRent, 'Rent growth'], [d.gPrice, 'Price growth'], [d.gCost, 'Cost inflation']]) if (isFinite(v) && (v < -0.5 || v > 0.5)) return `${name} must be between -50% and 50% a year.`;
    if (keys.includes('letting') && keys.includes('maint') && d.letting + d.maint > 1) return 'Letting and maintenance together can\'t be more than the rent.';
    if (keys.includes('improve') && d.improve > d.works + d.epc + 0.5) return 'Improvements can\'t be more than the works and EPC upgrade together.';
    return '';
  };
  // the deal over 10 years in one place, so the projection, the past-decades fan and the sensitivity tornado agree.
  // values: the home's value at the end of each year 1-10 (default: the price growing at the projection's price growth).
  // Year 1 uses the chosen tax year, later years April-2027 rates; the sale in year 10 pays tax on the gain
  const projectDeal = (d, A, values) => {
    const loan = d.price * (1 - d.dep), tax = sdlt(d.price, A), cashIn = d.price * d.dep + tax + d.legal + d.fee + d.works + d.epc;
    const gR = isFinite(d.gRent) ? d.gRent : 0, gP = isFinite(d.gPrice) ? d.gPrice : 0, gC = isFinite(d.gCost) ? d.gCost : 0;
    // works split: improvements come off the gain when sold; the rest are repairs, set against year 1's rental profit
    const repairs = Math.max(0, d.works + d.epc - d.improve), sell = A.selling_costs.v / 100;
    let bal = loan, carry = { fin: 0, loss: 0 }, y10 = null, cum = 0; const proj = [], cfs = [-cashIn];
    for (let t = 1; t <= 10; t++) {
      const y = yearCalc(d, A, { rent: d.rent * (1 + gR) ** (t - 1), costMult: (1 + gC) ** (t - 1), balance: bal, year2027: t > 1 || d.taxYear === '2027', carry, oneOff: t === 1 ? repairs : 0 });
      bal = y.endBalance; cum += y.post; carry = y.carry; if (t === 10) y10 = y;
      const value = values ? values[t - 1] : d.price * (1 + gP) ** t;
      proj.push({ t, rent: y.annualRent, post: y.post, value, loan: bal, equity: value - bal, cum });
      cfs.push(y.post + (t === 10 ? value * (1 - sell) - bal : 0));
    }
    const gain = proj[9].value * (1 - sell) - (d.price + tax + d.legal + d.improve), gt = gainsTaxDetail(d, A, gain, y10 ? y10.taxable : 0);
    const cfsT = cfs.slice(); cfsT[10] -= gt.tax;
    const roots = irrRoots(cfsT);
    return { loan, tax, cashIn, proj, cfs, cfsT, gain, gt, cgt: gt.tax, roots, irr: roots.length === 1 ? roots[0] : NaN, profit: cfsT.reduce((a, b) => a + b, 0) };
  };
  const clearDeal = (msg) => {
    ['#r-gross', '#r-cash', '#r-coc', '#r-irr'].forEach((s) => { $(s).textContent = '—'; $(s).className = 'big'; });
    ['#r-gross-note', '#r-cash-note', '#r-irr-note', '#r-stress'].forEach((s) => ($(s).textContent = ''));
    kv($('#r-detail'), []); ['#stress-table tbody', '#proj-table tbody'].forEach((s) => $(s).replaceChildren()); fresh($('#proj-chart')); dealCharts.clear();
    $('#b-notes').textContent = msg; $('#b-notes').className = 'note warnc';
  };
  const renderDeal = () => {
    syncDefaults();
    const A = getAss(); if (!A) return;
    const d = readDeal(), problem = dealProblem(d);
    if (problem) { clearDeal(problem + ' The results are cleared until it is fixed.'); renderFlip(A); return; }
    $('#b-notes').className = 'note';
    const iw = $('#b-income-wrap'); if (iw) iw.hidden = d.owner !== 'basic';       // only a basic-rate owner's band matters for the gain
    const P = projectDeal(d, A), { loan, tax, cashIn } = P;
    const y1 = yearCalc(d, A, { rent: d.rent, costMult: 1, balance: loan, year2027: d.taxYear === '2027' });
    $('#r-gross').textContent = pct(y1.annualRent / d.price * 100, 1);
    $('#r-gross-note').textContent = `Net of running costs: ${pct((y1.collected - y1.opex) / (d.price + tax + d.legal + d.works + d.epc) * 100, 1)}`;
    const cf = $('#r-cash'); cf.textContent = gbp(y1.post / 12); cf.className = 'big ' + (y1.post < 0 ? 'badc' : '');
    $('#r-cash-note').textContent = `${gbp(y1.pre / 12)} before tax`;
    $('#r-coc').textContent = pct(y1.post / cashIn * 100, 1);
    kv($('#r-detail'), [['Rent, full year', gbp(y1.annualRent)], [`Rent after ${d.voids} void weeks`, gbp(y1.collected)], ['Letting and maintenance', gbp(-(y1.collected * (d.letting + d.maint)))],
      ['Insurance, safety checks, licences', gbp(-(d.ins + d.comp))], [`Mortgage interest (${pct(d.rate * 100, 2)})`, gbp(-y1.interest)],
      ...(!y1.tr.company && y1.relieved < y1.interest - 0.5 ? [[`Interest relieved this year (capped at the property profit; ${gbp(y1.interest - y1.relieved)} carried forward)`, gbp(y1.relieved)]] : []), ...(d.mtype === 'rep' ? [['Mortgage capital repaid', gbp(-y1.principal)]] : []),
      ['Cash flow before tax', gbp(y1.pre), y1.pre < 0 ? 'badc' : ''], [y1.tr.company ? `Corporation tax (${y1.taxable > 0 ? pct(y1.tax / y1.taxable * 100, 1) : pct(y1.tr.rate * 100, 0)} with marginal relief)` : `Income tax (${pct(y1.tr.rate * 100, 0)}, less ${pct(y1.tr.credit * 100, 0)} interest credit)`, gbp(-y1.tax)],
      ['Cash flow after tax', gbp(y1.post), y1.post < 0 ? 'badc' : 'good'], 'sep',
      ['Deposit', gbp(d.price * d.dep)], ['Stamp duty incl. 5% surcharge', gbp(tax)], ['Legal, survey, arrangement fee', gbp(d.legal + d.fee)], ['Works and EPC upgrade', gbp(d.works + d.epc)], ['Cash invested', gbp(cashIn)]]);
    $('#pl-note').textContent = y1.tr.company ? 'Limited company: interest is a deductible cost and losses are carried forward; corporation tax is 19% on profits up to £50,000, rising to 25% at £250,000 (marginal relief in between). Taking money out (dividends) is taxed again and not modelled.' : 'Personal ownership: mortgage interest isn\'t deductible; you get a basic-rate tax credit instead (Section 24), on the interest or the property profit, whichever is lower. Interest above the profit, and any loss, is carried forward to later years in the projection. Assumes your other income uses your personal allowance and nothing is brought forward into year 1.';
    const rep_ = Math.max(0, d.works + d.epc - d.improve);
    if (d.works + d.epc > 0) $('#pl-note').textContent += ` Of the works and EPC upgrade, ${gbp(d.improve)} counts as improvements, taken off the gain when sold; the other ${gbp(rep_)} counts as repairs, set against year 1's rental profit in the projection (not in the yearly figures above, which show a typical year).`;
    const icr = (d.owner === 'higher' ? A.icr_higher.v : A.icr_basic.v) / 100, sr = Math.max(A.stress_rate.v / 100, d.rate + 0.02), need = loan * sr * icr / 12, pass = d.rent >= need;
    const s = $('#r-stress');
    s.textContent = `Lender stress test (assumption): rent must cover ${pct(icr * 100, 0)} of interest at ${pct(sr * 100, 2)}, so at least ${gbp(need)} a month. This rent ${pass ? 'passes' : `fails; the largest loan this rent supports is about ${gbp(d.rent * 12 / (sr * icr))}`}.`;
    s.className = 'note ' + (pass ? '' : 'warnc');
    const notes = [];
    const lr = state.last && latestRent({ 1: '1 bed', 2: '2 bed', 3: '3 bed', 4: '4+ bed' }[state.last.inp.beds]);
    const Rn = rentEstimate();
    if (state.listingRent) notes.push(`Rent from the pasted listing (${gbp(state.listingRent)} pcm).`); else if (Rn) notes.push(`Rent default: the estimate above (${gbp(Rn.est)}).`); else if (lr) notes.push(`Rent default: ONS Doncaster average ${state.last.inp.beds === '4' ? '4+' : state.last.inp.beds}-bed rent, ${monthLabel(lr.month)}.`);
    const lha = rows('lha').find((r) => state.last && r.bedrooms === state.last.inp.beds); if (lha) notes.push(`Housing benefit (LHA) cap for this size: ${gbp(num(lha.monthly_rate))} a month.`);
    notes.push(`Mortgage rate default: ${A.mortgage_rate.src}.`);
    const HG = homeReturn(); if (!state.touched.gPrice && HG && isFinite(HG.g)) notes.push(`Price growth default: ${HG.nbName}'s ${HG.o.basis}-year growth (${pct(HG.g, 2)} a year), the figure the scorecard uses.`);
    const exF = state.last && getExtras() ? getExtras().get(state.last.pc.postcode) : null;
    if (exF && num(exF.flood_hm) > 0) notes.push(`Flood risk: ${pct(num(exF.flood_hm) * 100, 0)} of homes at this postcode are at high or medium risk from rivers or the sea, so insurance can cost more and some lenders ask questions. Check the exact address with the Environment Agency.`);
    if (d.epc > 0) notes.push('EPC upgrade allowance added because the energy rating is below C (all rentals must reach C by October 2030).');
    $('#b-notes').textContent = notes.join(' ');
    // stress tests
    const base = y1.post / 12, scen = [['Base case', {}], ['Interest rate +2 points', { rateAdj: 0.02 }], ['Rent 10% lower', { rent: d.rent * 0.9 }], ['8 void weeks', { voids: 8 }], ['Maintenance doubled', { maintMult: 2 }],
      ['All of the above', { rateAdj: 0.02, rent: d.rent * 0.9, voids: 8, maintMult: 2 }]];
    const tb = $('#stress-table tbody'); tb.replaceChildren();
    scen.forEach(([name, o]) => {
      const y = yearCalc(d, A, { rent: d.rent, costMult: 1, balance: loan, year2027: d.taxYear === '2027', ...o }), mth = y.post / 12, tr = document.createElement('tr');
      cell(tr, name); const c = cell(tr, gbp(mth), 'r'); if (mth < 0) c.classList.add('badc'); cell(tr, name === 'Base case' ? '—' : gbp(mth - base), 'r'); tb.appendChild(tr);
    });
    // 10-year projection, and the IRR after tax on the gain
    const { proj, cfs, cfsT, gain, gt, cgt, roots, irr: r10, profit } = P, before = irrRoots(cfs);
    const og = A.opp_gilt_10y ? A.opp_gilt_10y.v / 100 : NaN, npvG = cfsT.reduce((s_, c, t) => s_ + c / (1 + og) ** t, 0);
    const npvTxt = isFinite(og) ? ` Judge it by NPV instead: ${gbp(npvG)} at the 10-year gilt (${pct(og * 100, 2)}).` : '';
    $('#r-irr').textContent = roots.length === 1 ? pct(r10 * 100, 1) : '—';
    const split = d.owner === 'basic' && gt.low > 0 && gt.high > 0 ? ` (18% on ${gbp(gt.low)} within the basic-rate band, 24% on ${gbp(gt.high)})` : d.owner === 'basic' && gt.high > 0 ? ' (all at 24%: the basic-rate band is used up)' : '';
    const cgtTxt = cgt > 0 ? `${gbp(cgt)} ${d.owner === 'company' ? 'corporation tax' : 'capital gains tax'} on a ${gbp(gain)} gain${split}` : gain > 0 ? `no tax on the ${gbp(gain)} gain (within the £3,000 exemption)` : 'no gain to tax';
    // one change of sign (money in, then money back) means exactly one rate (Descartes' rule of signs); more than one, and
    // the IRR can mislead even when a single rate is found, so the NPV is shown alongside it
    const flips = signChanges(cfsT);
    $('#r-irr-note').textContent = roots.length === 1 ? `After tax, including ${cgtTxt} when sold${before.length === 1 && cgt > 0 ? ` (${pct(before[0] * 100, 1)} before it)` : ''}. Total profit ${gbp(profit)} on ${gbp(cashIn)} invested.${flips > 1 ? ` The cash flows change sign ${flips} times, so the IRR can mislead (a higher rate isn't always a better deal).${npvTxt}` : ''}`
      : roots.length > 1 ? `More than one rate fits (${roots.map((r) => pct(r * 100, 1)).join(' and ')}), so the IRR is ambiguous.${npvTxt}`
        : flips === 0 ? 'No rate fits: the cash flows never change sign.' : `No rate between −99% and 10,000% a year fits.${npvTxt}`;
    const ptb = $('#proj-table tbody'); ptb.replaceChildren();
    proj.forEach((p) => { const tr = document.createElement('tr'); cell(tr, String(p.t)); cell(tr, gbp(p.rent), 'r'); const c = cell(tr, gbp(p.post), 'r'); if (p.post < 0) c.classList.add('badc'); cell(tr, gbp(p.value), 'r'); cell(tr, gbp(p.loan), 'r'); cell(tr, gbp(p.equity), 'r'); ptb.appendChild(tr); });
    drawProjection(proj, cashIn);
    dealCharts.draw(d, A, P, y1);
    renderFlip(A);
    renderRules();
  };
  const renderInvest = () => { safe('the deal analyser', renderDeal); safe('the rent estimate', renderRent); safe('the investment scorecard', renderScore); };
  const drawProjection = (proj, cashIn) => {
    const box = $('#proj-chart'); fresh(box);
    const start = getModel() ? +getModel().valMonth.slice(0, 4) : 2026;
    const series = [
      { name: 'Equity', color: dash.colors[0], values: [{ date: new Date(Date.UTC(start, 0, 1)), v: proj[0].value / (1 + (num(val('#p-price')) / 100 || 0)) - num(val('#b-price')) * (1 - num(val('#b-deposit')) / 100) }, ...proj.map((p) => ({ date: new Date(Date.UTC(start + p.t, 0, 1)), v: p.equity }))] },
      { name: 'Cash taken', color: dash.colors[1], values: [{ date: new Date(Date.UTC(start, 0, 1)), v: 0 }, ...proj.map((p) => ({ date: new Date(Date.UTC(start + p.t, 0, 1)), v: p.cum }))] }
    ];
    lineChart(box, series, { label: 'Equity and cumulative cash flow over 10 years', yFmt: gbpK, tipFmt: gbp, endLabels: true, endFmt: gbpK, height: 240, yZero: true, xFmt: (dt) => 'Year ' + (dt.getUTCFullYear() - start) });
  };
  // the flip's own inputs; the quote and floor area may be left blank (the guide price and the home's size are used)
  const FLIP_CHECKS = [['#f-months', 1, 60, 'Months held (1 to 60)'], ['#f-fin', 0, 25, 'Loan rate (0% to 25% a year)'], ['#f-ltv', 0, 100, 'Loan (0% to 100% of the price)'], ['#f-baths', 0, 5, 'Bathrooms to refit (0 to 5)'],
    ['#f-cont', 0, 50, 'Contingency (0% to 50%)'], ['#f-quote', 0, 1e7, 'Your quote (£0 to £10 million)', true], ['#f-area', 10, 1500, 'Floor area (10 to 1,500 m²)', true]];
  const flipProblem = () => {
    for (const [s, lo, hi, name, optional] of FLIP_CHECKS) {
      const raw = val(s), v = num(raw); if (optional && String(raw).trim() === '') continue;
      if (!isFinite(v)) return `${name.split(' (')[0]} is missing.`; if (v < lo || v > hi) return `${name} is out of range.`;
    }
    return '';
  };
  const renderFlip = (A) => {
    const cond = getCond(), L = state.last;
    if (!cond || !L) { kv($('#f-detail'), []); $('#f-works-note').textContent = ''; return; }
    if ($('#f-cont').value === '') $('#f-cont').value = String(A.rf_contingency.v);
    const fp = flipProblem(), wn = $('#f-works-note');
    if (fp) { kv($('#f-detail'), []); wn.textContent = fp + ' The appraisal is cleared until it is fixed.'; wn.className = 'note warnc'; return; }
    wn.className = 'note';
    const a0 = num(val('#f-area')), area = isFinite(a0) && a0 > 0 ? a0 : A.floor_area.v;
    const R = refurbCost(A, val('#f-scope'), area, val('#f-finish'), num(val('#f-baths')), num(val('#f-vat')), L.est, num(val('#f-cont')));
    if (!R) { kv($('#f-detail'), []); $('#f-works-note').textContent = ''; return; }
    $('#f-quote').placeholder = 'Guide ' + gbp(Math.round(R.total / 100) * 100);
    // every input has three states: blank = the default, invalid = the appraisal is cleared and says why, valid = used
    // as given, £0 included (a £0 quote means no works, not the guide price)
    const own = String(val('#f-quote')).trim() !== '', q = num(val('#f-quote'));
    const needs = cond.find((c) => c.key === R.from), refurb = cond.find((c) => c.key === R.to), aNeeds = condFor(needs, L.inp).adj, aRefurb = condFor(refurb, L.inp).adj;
    // your price when you've given one (typed in the deal, or the asking price); left blank, the model's value in the
    // condition the works put right; a price the deal refuses clears the flip rather than being swapped for the model's
    const d = readDeal(), modelBuy = L.est * (1 + aNeeds / 100), given = (state.touched.price || (isFinite(L.inp.asking) && L.inp.asking > 0)) && String(val('#b-price')).trim() !== '';
    const pp = given ? dealProblem(d, ['price']) : '';
    if (pp) { kv($('#f-detail'), []); wn.textContent = pp + ' The appraisal is cleared until it is fixed.'; wn.className = 'note warnc'; return; }
    const yours = given, buy = yours ? d.price : modelBuy, sell = L.est * (1 + aRefurb / 100), months = num(val('#f-months')), fin = num(val('#f-fin')) / 100, ltv = num(val('#f-ltv')) / 100;
    const works = own ? q : R.total, feePct = A.flip_fee ? A.flip_fee.v / 100 : 0.02, sellCosts = sell * A.selling_costs.v / 100, holding = (A.insurance.v / 12) * months;
    // profit at a purchase price: the loan is a share of the price; interest and the fee are costs; the rest is your cash
    const at = (b) => { const tax = sdlt(b, A), loan = b * ltv, finance = loan * fin * months / 12 + loan * feePct;
      return { tax, loan, finance, cash: b - loan + tax + A.buying_costs.v + works, profit: sell - (b + tax + A.buying_costs.v + works + finance + holding + sellCosts) }; };
    const x = at(buy), margin = A.flip_margin ? A.flip_margin.v / 100 : 0.15;
    const offer = (target) => { let lo = 0, hi = sell * 1.5; if (at(lo).profit < target) return NaN; for (let k = 0; k < 60; k++) { const m = (lo + hi) / 2; if (at(m).profit >= target) lo = m; else hi = m; } return Math.floor(lo / 500) * 500; };
    kv($('#f-detail'), [[yours ? 'Buy (your price)' : `Buy (model value, ${needs.label.toLowerCase()}, ${sgn(aNeeds)})`, gbp(buy)],
      ...(yours ? [[`Model value, ${needs.label.toLowerCase()}`, gbp(Math.round(modelBuy / 1000) * 1000)]] : []), ['Stamp duty incl. surcharge', gbp(x.tax)], ['Legal and survey', gbp(A.buying_costs.v)],
      [own ? 'Works (your quote)' : `Works (guide, ${d3.format(',')(Math.round(area))} m²)`, gbp(works)],
      [ltv > 0 ? `Loan interest and ${pct(feePct * 100, 0)} fee (${pct(ltv * 100, 0)} loan, ${months} months)` : 'No loan', gbp(x.finance)], [`Insurance (${months} months)`, gbp(holding)],
      [`Sell (${refurb.label.toLowerCase()}, ${sgn(aRefurb)})`, gbp(sell)], ['Selling costs', gbp(sellCosts)], 'sep',
      ['Profit before tax', gbp(x.profit), x.profit < 0 ? 'badc' : 'good'], ['Your cash in', gbp(x.cash)], ['Return on your cash', pct(x.profit / x.cash * 100, 1), x.profit < 0 ? 'badc' : 'good'], 'sep',
      ['Highest price that breaks even', gbp(offer(0))], [`Highest price for a ${pct(margin * 100, 0)} margin on the sale price`, gbp(offer(margin * sell))]]);
    $('#f-works-note').textContent = (own ? `Using your quote. The guide for ${R.label.toLowerCase()} would be ${gbp(Math.round(R.total / 100) * 100)}: ` : `${R.label}, ${R.finish}: `) + refurbText(R)
      + `. Developers usually look for ${pct(margin * 100, 0)} to 20% of the sale price (planning viability guidance); the highest prices allow for stamp duty, finance and selling costs at that price.`;
  };
  const renderRules = () => {
    const box = $('#rules-list'); if (!ok('rules') || box.childElementCount) return;
    rows('rules').forEach((r) => {
      const a = document.createElement('article'), h = document.createElement('h3'), p = document.createElement('p'), m = document.createElement('p');
      h.textContent = r.topic; p.textContent = r.summary; m.className = 'muted';
      m.append(r.status + ' · ');
      if (/^https:\/\//.test(r.source_url)) { const l = document.createElement('a'); l.href = r.source_url; l.target = '_blank'; l.rel = 'noopener'; l.textContent = 'Source'; m.append(l); }
      a.append(h, p, m); box.appendChild(a);
    });
  };

  // ================= INVEST: one home as an investment =================
  // rent = Doncaster's ONS rent for the type x (value / Doncaster's UK HPI price for the type) ^ beta (rent_model dataset)
  const getRM = () => {
    if (!ok('rent_model')) return null;
    if (cache.rm) return cache.rm;
    return (cache.rm = { v: Object.fromEntries(rows('rent_model').map((r) => [r.key, num(r.value)])), row: Object.fromEntries(rows('rent_model').map((r) => [r.key, r])) });
  };
  const modelRent = (RM, t, value) => RM.v['rent_' + t] * (value / RM.v['ref_price_' + t]) ** RM.v.beta;
  const BED_KEY = (b) => (['1', '2', '3', '4'].includes(String(b)) ? String(b) : 'all');
  const BED_NAME = { 1: '1-bed', 2: '2-bed', 3: '3-bed', 4: '4+ bed', all: 'all' };
  const rentEstimate = () => {
    const RM = getRM(), L = state.last; if (!RM || !L || !L.inp) return null;
    const t = L.inp.type, V = L.adj; if (!TYPES.includes(t) || !isFinite(V) || V <= 0) return null;
    const base = RM.v['rent_' + t], ref = RM.v['ref_price_' + t], ratio = V / ref, raw = base * ratio ** RM.v.beta, k = BED_KEY(L.inp.beds);
    const est = Math.round(raw / 5) * 5;
    return { t, V, base, ref, ratio, est, lo: Math.round(raw * RM.v['rq_lq_' + k] / 5) * 5, hi: Math.round(raw * RM.v['rq_uq_' + k] / 5) * 5, k, RM };
  };
  const getDist = () => {
    if (!ok('nb_dist')) return null;
    if (cache.dist) return cache.dist;
    const m = new Map();
    rows('nb_dist').forEach((r) => m.set(`${r.msoa21}|${r.type}|${r.metric}`, { n: num(r.n), mean: num(r.mean), sd: num(r.sd), q: [5, 10, 25, 50, 75, 90, 95].map((p) => [p, num(r['p' + p])]) }));
    return (cache.dist = m);
  };
  // the closest comparison group with 30+ sales: this type here, all types here, then this type across Doncaster
  const distFor = (ms, t, metric) => {
    const G = getDist(); if (!G) return null;
    for (const [m, tt, scope] of [[ms, t, 'here'], [ms, 'A', 'all types here'], [LA_CODE, t, 'Doncaster']]) { const d = m && G.get(`${m}|${tt}|${metric}`); if (d && d.n >= 30) return { ...d, scope }; }
    return null;
  };
  const pctBelow = (d, x) => {                      // share of recent sales with a lower value than x
    const q = d.q; if (x <= q[0][1]) return { p: q[0][0], edge: -1 }; if (x >= q.at(-1)[1]) return { p: q.at(-1)[0], edge: 1 };
    for (let i = 1; i < q.length; i++) if (x <= q[i][1]) { const [p0, v0] = q[i - 1], [p1, v1] = q[i]; return { p: p0 + (p1 - p0) * (x - v0) / ((v1 - v0) || 1), edge: 0 }; }
    return { p: 50, edge: 0 };
  };
  const zTok = (beat) => `var(--cds-chart-diverging-${4 - Math.max(-3, Math.min(3, Math.round((beat - 50) / 15)))})`;   // blue beats most sales, red few
  const beatTxt = (b, edge) => (edge > 0 ? `Over ${Math.round(b)}%` : edge < 0 ? `Under ${Math.max(1, Math.round(b))}%` : `${Math.round(b)}%`);
  // cash purchase, buying and selling costs spread over the holding period (the Areas tab's method, with this deal's costs)
  const dealCosts = (A) => {
    const d = readDeal(), f = (x, dflt) => (isFinite(x) ? x : dflt);
    return { letting: f(d.letting, A.letting_fee.v / 100), maint: f(d.maint, A.maintenance.v / 100), voids: f(d.voids, A.voids.v), ins: f(d.ins, A.insurance.v), comp: f(d.comp, A.compliance.v),
      legal: f(d.legal, A.buying_costs.v), sell: A.selling_costs.v / 100, hold: A.hold_years.v, extra: (d.works || 0) + (d.epc || 0) };
  };
  const cashNet = (P, rent, c, A, extra = 0) => {
    const income = 12 * rent * (1 - c.voids / 52) * (1 - c.letting - c.maint) - c.ins - c.comp;
    return 100 * (income - (sdlt(P, A) + c.legal + extra + P * c.sell) / c.hold) / P;
  };
  // a horizontal spread of recent sales (5th to 95th percentile, middle half darker), better to the right, with this home's dot
  const drawStrip = (box, d, x, lowerBetter, fmt, beat) => {
    fresh(box);
    const W = Math.max(200, box.clientWidth), H = 46, m = 10, q = Object.fromEntries(d.q), lo = Math.min(q[5], x), hi = Math.max(q[95], x);
    const sx = d3.scaleLinear(lowerBetter ? [hi, lo] : [lo, hi], [m, W - m]), yc = 18;
    const svg = d3.select(box).append('svg').attr('width', '100%').attr('viewBox', `0 0 ${W} ${H}`).attr('role', 'img').attr('aria-label', `This home against recent sales: ${fmt(x)} against a typical ${fmt(q[50])}`);
    svg.append('line').attr('x1', sx(q[5])).attr('x2', sx(q[95])).attr('y1', yc).attr('y2', yc).attr('stroke', 'var(--cds-chart-muted)').attr('stroke-width', 2).attr('stroke-linecap', 'round');
    svg.append('rect').attr('x', Math.min(sx(q[25]), sx(q[75]))).attr('width', Math.abs(sx(q[75]) - sx(q[25]))).attr('y', yc - 5).attr('height', 10).attr('rx', 5).attr('fill', 'var(--cds-chart-muted)');
    svg.append('line').attr('x1', sx(q[50])).attr('x2', sx(q[50])).attr('y1', yc - 9).attr('y2', yc + 9).attr('stroke', 'var(--color-fg-muted)').attr('stroke-width', 2);
    const dot = svg.append('circle').attr('cx', sx(x)).attr('cy', yc).attr('r', 7).attr('fill', zTok(beat)).attr('stroke', 'var(--color-fg)').attr('stroke-width', 1.5);
    if (motionOK() && box._x != null && box._x !== x) dot.attr('cx', sx(box._x)).transition().duration(500).ease(d3.easeCubicInOut).attr('cx', sx(x)); box._x = x;
    const cap = (tx, xx, anchor) => svg.append('text').attr('x', xx).attr('y', H - 3).attr('text-anchor', anchor).attr('fill', 'var(--color-fg-muted)').style('font-size', 'var(--cds-font-size-caption)').text(tx);
    cap('Worse', m, 'start'); cap('Better', W - m, 'end'); cap(`Typical ${fmt(q[50])}`, Math.max(70, Math.min(W - 70, sx(q[50]))), 'middle');
  };
  // the home's total return a year as the scorecard counts it: cash net yield + its neighbourhood's price growth, less the
  // risk allowance when it's on. One function, so the scorecard, the rent markers and the projection's growth agree.
  const homeReturn = () => {
    const N = getNb(), o = nbOpts(), A = getAss(), L = state.last; if (!N || !o || !A || !L || !L.inp) return null;
    const ms = N.ofLsoa.get(L.pc && L.pc.lsoa21), nb = ms ? N.byId.get(ms) : null, R = nb || N.D, g = num(R[`growth_${o.basis}y`]);
    const c = dealCosts(A), exF = getExtras() && L.pc ? getExtras().get(L.pc.postcode) : null, flood = exF && isFinite(num(exF.flood_hm)) ? num(exF.flood_hm) : null;
    const total = (P, rent) => {
      const net = cashNet(P, rent, c, A, c.extra), rk = riskFor(R, P, rent, A, c.hold, { flood, noEpc: true });   // the deal already counts this home's EPC upgrade
      return { net, rk, total: net + g - (state.riskOn && rk ? rk.total : 0) };
    };
    return { N, o, A, L, ms, nb, R, g, c, total, nbName: nb ? nb.name : 'Doncaster' };
  };
  // nothing from an earlier home or deal may stay on the scorecard: stop the count-ups and blank every figure and row
  const clearScore = (title, why = '') => {
    $('#inv-title').textContent = title; $('#inv-rows').replaceChildren();
    ['#inv-z', '#inv-total', '#inv-above', '#inv-vs'].forEach((s) => { const el = $(s); if (el) { still(el); el.classList.remove('good', 'badc'); } });
    ['#inv-verdict', '#inv-total-n', '#inv-above-n', '#inv-vs-n', '#inv-note'].forEach((s) => { const el = $(s); if (el) el.textContent = ''; });
    const sub = $('#inv-sub'); sub.textContent = why; sub.className = why ? 'note warnc' : 'note';
    const rk = $('#inv-risks'); if (rk) rk.replaceChildren();
  };
  const renderScore = () => {
    const card = $('#inv-card'), N = getNb(), o = nbOpts(), A = getAss(), L = state.last, RM = getRM();
    if (failed($('#inv-rows'), ['nb_dist', 'rent_model', 'neighbourhoods'])) return;
    oppLabels();
    if (!N || !o || !A || !RM || !getDist()) return;
    if (!L || !L.inp) { clearScore('Pick a property on the first tab'); return; }
    const d = readDeal(), P = d.price, V = L.adj, t = L.inp.type, ms = N.ofLsoa.get(L.pc && L.pc.lsoa21), nb = ms ? N.byId.get(ms) : null, nbName = nb ? nb.name : 'Doncaster';
    const title = `${L.inp.beds ? BED_NAME[BED_KEY(L.inp.beds)] + ' ' : ''}${TYPE_NAME[t].toLowerCase()}${L.pc ? ' in ' + L.pc.postcode : ''}`;
    // the same checks as the deal analyser, on the inputs a cash purchase uses (price, rent and running costs; not the mortgage)
    const problem = dealProblem(d, CASH_KEYS) || (isFinite(V) && V > 0 ? '' : 'There is no estimated value for this home.');
    if (problem) { clearScore(title, `${problem} The scorecard is cleared until it is fixed.`); return; }
    $('#inv-title').textContent = title; $('#inv-sub').className = 'note';
    $('#inv-sub').textContent = `${nb ? nbName + ' · ' : ''}bought at ${gbp(P)} against an estimated value of ${gbp(V)} · change the home on the Value tab and the price or rent in the deal below`;
    const H = homeReturn(), c = H.c, rent = d.rent, g = H.g, { net, rk: rkP, total } = H.total(P, rent);
    // a typical home of this type here, valued at the local median and let at its modelled rent
    const R = nb || N.D, Pt = isFinite(num(R['median_' + t])) ? num(R['median_' + t]) : num(R.median_price), rt = modelRent(RM, t, Pt), netT = cashNet(Pt, rt, c, A), rkT = riskFor(R, Pt, rt, A, c.hold), totT = netT + g - (state.riskOn && rkT ? rkT.total : 0);
    countTo($('#inv-total'), total, (v) => pct(v, 1)); $('#inv-total-n').textContent = state.riskOn && rkP ? `Net yield ${pct(net, 1)} + growth ${pct(g, 1)} − risk ${d3.format('.1f')(rkP.total)} (tenants ${d3.format('.1f')(rkP.tenant)}, flood ${d3.format('.1f')(rkP.flood)}, downturn ${d3.format('.1f')(rkP.down)})` : `Net yield ${pct(net, 1)} + ${o.basis}-year growth ${pct(g, 1)}${rkP ? ` · risk allowance would take ${d3.format('.1f')(rkP.total)} pts` : ''}`;
    $('#inv-above-l').textContent = `Above ${o.oppName} (${pct(o.opp, 2)})`;
    const ab = $('#inv-above'); countTo(ab, total - o.opp, (v) => pts(v)); ab.classList.toggle('good', total > o.opp); ab.classList.toggle('badc', total < o.opp);
    $('#inv-above-n').textContent = `Against ${pct(o.opp, 2)}, for a cash purchase`;
    const vs = $('#inv-vs'); countTo(vs, total - totT, (v) => pts(v)); vs.classList.toggle('good', total > totT); vs.classList.toggle('badc', total < totT);
    $('#inv-vs-n').textContent = `Typical ${TYPE_SHORT[t].toLowerCase()} here: ${gbpK(Pt)}, rent ${gbp(Math.round(rt / 5) * 5)}, total ${pct(totT, 1)}`;
    // against the spread of recent sales here
    const rowsDef = [];
    const dd = distFor(ms, t, 'deal');
    const fmtDeal = (v) => { const q = (Math.exp(v) - 1) * 100; return Math.abs(q) < 0.5 ? '0%' : sgn(q, 0); };
    if (dd) { const x = Math.log(P / V), pb = pctBelow(dd, x); rowsDef.push({ key: 'deal', h: 'Price against estimated value', x, d: dd, lower: true, fmt: fmtDeal,
      v: Math.abs(P / V - 1) < 0.005 ? 'At its estimated value' : `${pct(Math.abs(P / V - 1) * 100, 1)} ${P < V ? 'below' : 'above'} its estimated value`, z: -(x - dd.mean) / dd.sd, beat: 100 - pb.p, edge: -pb.edge,
      t1: fmtDeal(dd.q[3][1]) === '0%' ? 'Recent sales here sold at about their estimates.' : `Recent sales here sold a typical ${fmtDeal(dd.q[3][1])} against their estimates.`, what: 'cheaper against value than' }); }
    const area = L.inp.area, dp = distFor(ms, t, 'ppsqm');
    if (dp && isFinite(area) && area > 0) { const x = Math.log(P / area), pb = pctBelow(dp, x); rowsDef.push({ key: 'ppsqm', h: 'Price per m²', x, d: dp, lower: true, fmt: (v) => gbp(Math.exp(v)),
      v: `${gbp(P / area)} per m² (${d3.format(',')(Math.round(area))} m²)`, z: -(x - dp.mean) / dp.sd, beat: 100 - pb.p, edge: -pb.edge, t1: `Typical ${gbp(Math.exp(dp.q[3][1]))} per m² for recent sales.`, what: 'cheaper per m² than' }); }
    const dy = distFor(ms, t, 'yield');
    if (dy && rent >= 0) { const y = 1200 * rent / P, x = y > 0 ? Math.log(y) : dy.q[0][1] - 0.15 * (dy.q[6][1] - dy.q[0][1]), pb = pctBelow(dy, x); rowsDef.push({ key: 'yield', h: 'Gross yield', x, d: dy, lower: false, fmt: (v) => pct(Math.exp(v), 1),
      v: `${pct(y, 1)} at ${gbp(rent)} a month`, z: (x - dy.mean) / dy.sd, beat: pb.p, edge: pb.edge, t1: `Typical ${pct(Math.exp(dy.q[3][1]), 1)} for recent sales, at their modelled rents.`, what: 'a higher yield than' }); }
    const box = $('#inv-rows');
    if (!(isFinite(area) && area > 0)) rowsDef.push({ key: 'hint' });
    const keep = new Map([...box.querySelectorAll('.inv-row')].map((el) => [el.dataset.k, el]));
    box.replaceChildren();
    rowsDef.forEach((r) => {
      if (r.key === 'hint') { const p = document.createElement('p'); p.className = 'muted inv-hint'; p.textContent = 'Add the floor area on the Value tab (or pick the address) to compare price per m² too.'; box.appendChild(p); return; }
      const el = keep.get(r.key) || document.createElement('div'); el.className = 'inv-row'; el.dataset.k = r.key; el.replaceChildren();
      const a = document.createElement('div'); a.className = 'inv-row-t';
      const s = (cls, tx) => { const e = document.createElement('span'); e.className = cls; e.textContent = tx; return e; };
      const scope = r.d.scope === 'here' ? `${TYPE_SHORT[t].toLowerCase()} sales in ${nbName}` : r.d.scope === 'all types here' ? `sales of all types in ${nbName}` : `${TYPE_SHORT[t].toLowerCase()} sales across Doncaster`;
      const beatTx = r.edge > 0 ? `over ${Math.round(r.beat)}%` : r.edge < 0 ? `under ${Math.max(1, Math.round(r.beat))}%` : `${Math.round(r.beat)}%`;
      a.append(s('h', r.h), s('v', r.v), s('muted', `${r.t1} This is ${r.what} ${beatTx} of ${d3.format(',')(r.d.n)} recent ${scope}.`));
      const st = el.querySelector('.inv-strip') || document.createElement('div'); st.className = 'inv-strip';
      const zc = document.createElement('div'); zc.className = 'inv-row-z'; zc.append(s('zv', `Beats ${beatTxt(r.beat, r.edge).toLowerCase()}`), s('muted', r.beat >= 40 && r.beat <= 60 ? 'about typical' : r.beat > 60 ? 'better than most' : 'worse than most'));
      el.append(a, st, zc); box.appendChild(el); drawStrip(st, r.d, r.x, r.lower, r.fmt, r.beat);
    });
    // tenant and area risks: anti-social behaviour here, and court claims across Doncaster
    const rk = $('#inv-risks'); rk.replaceChildren();
    const fact = (h, v, n) => { const e = document.createElement('div'), a1 = document.createElement('span'), a2 = document.createElement('span'), a3 = document.createElement('span');
      a1.className = 'h'; a1.textContent = h; a2.className = 'v'; a2.textContent = v; a3.className = 'muted'; a3.textContent = n; e.append(a1, a2, a3); rk.appendChild(e); };
    const asb = num((nb || N.D).asb_rate), asbD = num(N.D.asb_rate);
    if (isFinite(asb)) fact('Anti-social behaviour', `${d3.format('.1f')(asb)} reports a year per 1,000 residents${nb ? ' in ' + nbName : ''}`,
      `${asb > asbD * 1.25 ? 'Above' : asb < asbD * 0.8 ? 'Below' : 'Close to'} Doncaster's ${d3.format('.1f')(asbD)} (police.uk, ${monthLabel(N.D.asb_from)} to ${monthLabel(N.D.asb_to)})`);
    const P_ = getPoss();
    if (P_) { const d1 = P_.latest('Doncaster', 'standard'), e1 = P_.latest('England', 'standard');
      if (d1 && e1) fact('Landlord court claims', `${d3.format('.1f')(d1.rate)} a year per 1,000 rented homes in Doncaster`, `England ${d3.format('.1f')(e1.rate)}; standard claims, which include rent arrears (year to ${P_.label(d1.quarter)}). Borough-wide only.`); }
    // headline: price against value and income together
    const zs = rowsDef.filter((r) => r.key === 'deal' || r.key === 'yield'), zbar = zs.length ? d3.mean(zs, (r) => r.z) : NaN, beat = zs.length ? d3.mean(zs, (r) => r.beat) : NaN;
    const zb = $('#inv-z'); countTo(zb, beat, (v) => (isFinite(v) ? `${Math.round(v)}%` : '—'));
    $('#inv-verdict').textContent = !isFinite(beat) ? '—' : `${beat >= 40 && beat <= 60 ? 'About the same as' : beat > 60 ? 'Better than' : 'Worse than'} a typical recent sale in ${nbName}, on price against value and rental yield together. 50% is typical.`;
    const sig = isFinite(L.sigma) ? (Math.exp(L.sigma) - 1) * 100 : NaN;
    $('#inv-note').textContent = `Percentages are the share of recent sales of this type in the neighbourhood that this home beats: 50% is typical, 80% is better than four in five. A price well below the estimate often means condition or something the model can't see${isFinite(sig) ? `; this estimate's typical error is about ±${d3.format('.0f')(sig)}%` : ''}. Yields use modelled rents for the homes sold, and this home's rent from the deal. Total return is for a cash purchase with the deal's costs; the deal analyser below adds the mortgage and tax.`;
  };
  const renderRent = () => {
    const box = $('#rent-chart'); if (failed(box, ['rent_model', 'rents'])) return;
    const R = rentEstimate(), A = getAss(), L = state.last, o = nbOpts();
    if (!R || !A) { still($('#rent-est')); ['#rent-range', '#rent-note'].forEach((s) => ($(s).textContent = '')); kv($('#rent-build'), []); fresh(box); $('#rent-use').hidden = true; return; }
    const RM = R.RM, d = readDeal(), c = dealCosts(A), N = getNb(), rentOK = !dealProblem(d, ['rent']);
    countTo($('#rent-est'), R.est, (v) => gbp(v)); $('#rent-range').textContent = `Likely ${gbp(R.lo)} to ${gbp(R.hi)} a month: the middle half of Doncaster rents for ${R.k === 'all' ? 'all homes' : BED_NAME[R.k] + ' homes'}, around the estimate`;
    kv($('#rent-build'), [
      [`Doncaster average rent, ${TYPE_NAME[R.t].toLowerCase()} (ONS)`, gbp(R.base)],
      [`This home's value against Doncaster's average ${TYPE_SHORT[R.t].toLowerCase()} (${gbpK(R.ref)})`, `${d3.format('.2f')(R.ratio)}×`],
      [`Rents rise ${d3.format('.2f')(RM.v.beta)}% for each 1% of value`, `×${d3.format('.2f')(R.ratio ** RM.v.beta)}`],
      ['Estimated rent', gbp(R.est)], 'sep',
      [`Fitted across ${RM.v.n_areas} council areas; predicts an area's rents it hadn't seen to within`, `${d3.format('.1f')(RM.v.loo_error)}% (vs ${d3.format('.1f')(RM.v.loo_error_base)}% from the region alone)`],
      ['Inside Doncaster, rents across the four house types follow prices by', `${d3.format('.2f')(RM.v.slope_doncaster)}% per 1%`]]);
    // the rent ladder: estimate and range against the reference points
    const lr = latestRent({ 1: '1 bed', 2: '2 bed', 3: '3 bed', 4: '4+ bed' }[L.inp.beds]), lha = rows('lha').find((r) => r.bedrooms === String(L.inp.beds));
    const items = [];
    if (lr) items.push({ v: lr.v, t: `ONS ${BED_NAME[BED_KEY(L.inp.beds)]} average ${gbp(lr.v)}` });
    if (lha) items.push({ v: num(lha.monthly_rate), t: `Housing benefit cap ${gbp(num(lha.monthly_rate))}` });
    if (state.listingRent) items.push({ v: state.listingRent, t: `Listing ${gbp(state.listingRent)}` });
    if (rentOK && Math.abs(d.rent - R.est) >= 5) items.push({ v: d.rent, t: `In the deal ${gbp(d.rent)}` });
    const ms = N && L.pc ? N.ofLsoa.get(L.pc.lsoa21) : null, g = N && o ? num((ms ? N.byId.get(ms) : N.D)[`growth_${o.basis}y`]) : NaN;
    const HR = homeReturn();
    if (o && HR && isFinite(HR.g) && !dealProblem(d, COST_KEYS)) {
      // the rent at which the scorecard's total return equals the opportunity cost, with the risk allowance when it's on
      const f = (r) => HR.total(d.price, r).total - o.opp; let lo = 0, hi = 20000;
      if (f(lo) < 0 && f(hi) > 0) { for (let k = 0; k < 50; k++) { const m = (lo + hi) / 2; if (f(m) < 0) lo = m; else hi = m; } const need = Math.ceil(hi);
        items.push({ v: need, t: `Matches ${o.oppShort === 'gilt' ? 'the gilt' : o.oppName}${state.riskOn ? ' after risk' : ''} ${gbp(need)}`, kind: 'need' }); }
    }
    if (!dealProblem(d, MORTGAGE_KEYS)) {
      const loan = d.price * (1 - d.dep), cf = (r) => yearCalc(d, A, { rent: r, costMult: 1, balance: loan, year2027: d.taxYear === '2027' }).post;
      if (cf(0) < 0 && cf(6000) > 0) { let lo = 0, hi = 6000; for (let i = 0; i < 40; i++) { const m = (lo + hi) / 2; if (cf(m) < 0) lo = m; else hi = m; } items.push({ v: hi, t: `Breaks even with the mortgage ${gbp(hi)}`, kind: 'need' }); }
    }
    drawRentLadder(box, R, items);
    const src = RM.row['rq_lq_' + R.k] ? RM.row['rq_lq_' + R.k].source.replace('ONS private rental market statistics, Doncaster, ', '').replace(/ \((\d+) rents\)/, (m0, n) => `, from ${d3.format(',')(+n)} rents`) : '';
    const notes = [`The middle half comes from ONS private rental market statistics for Doncaster (${src}), the last year they gave quartiles.`,
      'The estimate assumes homes within Doncaster follow the same link between rent and value as council areas do; it hasn\'t been tested on individual lets, as no open data has them. Check it against local listings.'];
    $('#rent-note').textContent = notes.join(' ');
    const use = $('#rent-use'); use.hidden = rentOK && Math.abs(d.rent - R.est) < 5; use.textContent = `Use ${gbp(R.est)} in the deal`;
  };
  $('#rent-use').addEventListener('click', () => { const R = rentEstimate(); if (!R) return; $('#b-rent').value = String(R.est); state.touched.rent = true; renderInvest(); });
  const drawRentLadder = (box, R, items) => {
    fresh(box);
    const W = Math.max(280, box.clientWidth), H = 124, yc = 62, m = { l: 12, r: 12 };
    const vals = [R.lo, R.hi, R.est, ...items.map((i) => i.v)], x = d3.scaleLinear([d3.min(vals) * 0.94, d3.max(vals) * 1.04], [m.l, W - m.r]);
    const svg = d3.select(box).append('svg').attr('width', '100%').attr('viewBox', `0 0 ${W} ${H}`).attr('role', 'img').attr('aria-label', `Estimated rent ${gbp(R.est)} a month, likely ${gbp(R.lo)} to ${gbp(R.hi)}`);
    const gx = svg.append('g').attr('transform', `translate(0,${H - 18})`).call(d3.axisBottom(x).ticks(Math.max(3, Math.floor(W / 110))).tickFormat((v) => '£' + d3.format(',')(v)).tickSizeOuter(0)); cleanAxis(gx);
    svg.append('rect').attr('x', x(R.lo)).attr('width', x(R.hi) - x(R.lo)).attr('y', yc - 9).attr('height', 18).attr('rx', 9).attr('fill', dash.colors[0]).attr('fill-opacity', 0.18);
    // labels go in the first free row above or below the line, so none overlap
    const rowsY = [yc - 22, yc + 30, yc - 40, yc + 46], ends = rowsY.map(() => -Infinity);
    items.slice().sort((a, b) => a.v - b.v).forEach((it) => {
      const xx = x(it.v); svg.append('line').attr('x1', xx).attr('x2', xx).attr('y1', yc - 12).attr('y2', yc + 12).attr('stroke', it.kind === 'need' ? 'var(--color-fg)' : 'var(--cds-chart-reference)').attr('stroke-width', 1.5).attr('stroke-dasharray', it.kind === 'need' ? '3 2' : null);
      const tx = svg.append('text').attr('fill', 'var(--color-fg-muted)').style('font-size', 'var(--cds-font-size-caption)').text(it.t), w = tx.node().getComputedTextLength();
      let k = rowsY.findIndex((ry, i) => xx - w / 2 > ends[i] + 8); if (k < 0) k = rowsY.length - 1;
      const cx = Math.max(m.l + w / 2, Math.min(W - m.r - w / 2, xx)); tx.attr('x', cx).attr('y', rowsY[k]).attr('text-anchor', 'middle'); ends[k] = cx + w / 2;
    });
    const dot = svg.append('circle').attr('cx', x(R.est)).attr('cy', yc).attr('r', 8).attr('fill', dash.colors[0]).attr('stroke', 'var(--color-panel)').attr('stroke-width', 2.5);
    if (motionOK() && box._v != null && box._v !== R.est) dot.attr('cx', x(box._v)).transition().duration(500).ease(d3.easeCubicInOut).attr('cx', x(R.est)); box._v = R.est;
  };
  // the opportunity-cost buttons show each rate, and say where it comes from on hover
  const oppLabels = () => {
    const A = getAss(); if (!A || !A.opp_gilt_10y || !A.opp_bank_rate) return;
    const tips = { gilt: `10-year gilt yield ${pct(A.opp_gilt_10y.v, 2)}: what a 10-year UK government bond pays (${A.opp_gilt_10y.src})`,
      bank: `Bank Rate ${pct(A.opp_bank_rate.v, 2)}: the Bank of England's rate, a guide to what cash savings earn (${A.opp_bank_rate.src})`,
      custom: 'Your own rate: what you think the money would earn elsewhere, for example in savings or shares' };
    ['#nb-opp', '#inv-opp'].forEach((g) => document.querySelectorAll(g + ' button').forEach((b) => { b.title = tips[b.dataset.o]; }));
    document.querySelectorAll('[data-where="key=opp_gilt_10y"]').forEach((el) => (el.textContent = d3.format('.2f')(A.opp_gilt_10y.v)));
    document.querySelectorAll('[data-where="key=opp_bank_rate"]').forEach((el) => (el.textContent = d3.format('.2f')(A.opp_bank_rate.v)));
  };
  // the opportunity cost is shared with the Areas tab
  const setOpp = (v) => {
    state.nbOpp = v;
    ['#nb-opp', '#inv-opp'].forEach((g) => document.querySelectorAll(g + ' button').forEach((x) => x.setAttribute('aria-pressed', String(x.dataset.o === v))));
    $('#nb-custom-wrap').hidden = v !== 'custom'; $('#inv-custom-wrap').hidden = v !== 'custom';
    render();
  };
  ['#nb-opp', '#inv-opp'].forEach((g) => document.querySelectorAll(g + ' button').forEach((b) => b.addEventListener('click', () => { setOpp(b.dataset.o); if (b.dataset.o === 'custom') setTimeout(() => $(g === '#nb-opp' ? '#nb-opp-custom' : '#inv-opp-custom').focus(), 0); })));
  [['#nb-opp-custom', '#inv-opp-custom'], ['#inv-opp-custom', '#nb-opp-custom']].forEach(([a, b]) => $(a).addEventListener('input', () => { $(b).value = $(a).value; render(); }));

  // ================= AREAS AND RENTS =================
  // Neighbourhoods (MSOAs): prices, growth and stock from the neighbourhoods dataset; returns worked out here from the
  // assumptions, so the property type, growth period and opportunity cost can change without new data.
  const LA_CODE = 'E08000017';
  const TYPE_PLURAL = { D: 'detached houses', S: 'semi-detached houses', T: 'terraced houses', F: 'flats and maisonettes' };
  const pts = (v, d = 1) => { if (v == null || !isFinite(v)) return '—'; const r = fix0(v, d); return (r > 0 ? '+' : r < 0 ? '−' : '') + d3.format(`.${d}f`)(Math.abs(r)) + ' pts'; };
  const ordinal = (n) => n + (n % 100 >= 11 && n % 100 <= 13 ? 'th' : ['th', 'st', 'nd', 'rd'][n % 10] || 'th');
  Object.assign(state, { nbType: 'A', nbBasis: 10, nbOpp: 'gilt', nb: null, nbPicked: false, btlSort: { k: 'above', dir: -1 } });

  // ---------- motion helpers ----------
  const motionOK = () => !(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);
  // count a number up or down to its new value (only when it changes, and never with reduced motion)
  const countTo = (el, to, fmt, ms = 650) => {
    if (!el) return;
    const from = el._v; el._v = to;
    if (el._raf) { cancelAnimationFrame(el._raf); el._raf = null; }
    if (!isFinite(to) || !isFinite(from) || from === to || !motionOK()) { el.textContent = fmt(to); return; }
    const t0 = performance.now(), ip = d3.interpolateNumber(from, to);
    const step = (now) => { const k = Math.min(1, (now - t0) / ms); el.textContent = fmt(ip(d3.easeCubicInOut(k))); el._raf = k < 1 ? requestAnimationFrame(step) : null; };
    el._raf = requestAnimationFrame(step);
  };
  // show a fixed text and stop any count-up still running on the element, so a pending frame can't write an old figure
  // back; forgetting the last value means the next figure appears directly instead of counting from a stale one
  const still = (el, text = '—') => { if (!el) return; if (el._raf) cancelAnimationFrame(el._raf); el._raf = null; el._v = NaN; el.textContent = text; };
  // run f once, the first time el is at least `ratio` on screen
  const onFirstView = (el, f, ratio = 0.35) => {
    if (!el || !('IntersectionObserver' in window)) return;
    const io = new IntersectionObserver((es) => es.forEach((e) => { if (e.isIntersecting && e.intersectionRatio >= ratio) { io.disconnect(); f(); } }), { threshold: [ratio] });
    io.observe(el);
  };
  const fitText = (node, maxW) => {        // trim an SVG label with an ellipsis until it fits
    const full = node.textContent; if (node.getComputedTextLength() <= maxW) return;
    let s = full; while (s.length > 3 && node.getComputedTextLength() > maxW) { s = s.slice(0, -1); node.textContent = s.trimEnd() + '…'; }
  };


  const getNb = () => {
    if (!ok('neighbourhoods') || !ok('nbhd_index')) return null;
    if (cache.nb) return cache.nb;
    const k = Math.cos(53.52 * Math.PI / 180), pr = ([x, y]) => [x * k, y];
    const all = rows('neighbourhoods').map((r) => ({ ...r, geometry: r.geom ? { type: 'MultiPolygon', coordinates: JSON.parse(r.geom).map((poly) => poly.map((ring) => ring.map(pr))) } : null }));
    const D = all.find((r) => r.msoa21 === LA_CODE), list = all.filter((r) => r.msoa21 !== LA_CODE).sort((a, b) => a.name.localeCompare(b.name));
    const byId = new Map(all.map((r) => [r.msoa21, r])), ofLsoa = new Map();
    list.forEach((r) => String(r.lsoas || '').split(' ').filter(Boolean).forEach((l) => ofLsoa.set(l, r.msoa21)));
    const idx = new Map();
    rows('nbhd_index').forEach((r) => { if (!idx.has(r.msoa21)) idx.set(r.msoa21, []); idx.get(r.msoa21).push({ year: num(r.year), v: num(r.index) }); });
    idx.forEach((a) => a.sort((x, y) => x.year - y.year));
    return (cache.nb = { all, list, D, byId, ofLsoa, idx, k });
  };
  const nbOpts = () => {
    const A = getAss(); if (!A || !A.opp_gilt_10y || !A.opp_bank_rate || !A.hold_years) return null;
    const custom = num(val('#nb-opp-custom')), useCustom = state.nbOpp === 'custom' && isFinite(custom) && custom >= OPP_LIMITS[0] && custom <= OPP_LIMITS[1];
    const opp = state.nbOpp === 'bank' ? A.opp_bank_rate.v : useCustom ? custom : A.opp_gilt_10y.v;
    const oppName = state.nbOpp === 'bank' ? 'Bank Rate' : useCustom ? 'your rate' : 'the 10-year gilt';
    const oppShort = state.nbOpp === 'bank' ? 'Bank Rate' : useCustom ? 'your rate' : 'gilt';
    return { A, type: state.nbType, basis: state.nbBasis, opp, oppName, oppShort, hold: A.hold_years.v };
  };
  // a cash purchase at the local median price, let at the borough's ONS rent for the type; buying and selling costs
  // spread over the holding period; total = net yield + past price growth a year
  // ---------- risk allowance: points a year off the return ----------
  // tenants  rent x the typical-area rate (rent guarantee insurance pricing) x Doncaster's court claims against England's
  //          x this area's risk index (anti-social behaviour and deprivation against Doncaster's, kept within 0.4 to 3)
  // flood    the share of homes at flood risk x the extra insurance a landlord pays there
  // EPC      the share of homes below C x the average cost to reach C (capped as the rules do), spread over the hold
  // downturn this area's 2008 fall, once in every so many years
  state.riskOn = true;   // on from the start; the switch turns it off
  const RISK_CHECKS = [['#rk-tenant', 0, 30, 'Arrears, voids and damage (0% to 30% of rent)', 'risk_tenant_pct'], ['#rk-flood', 0, 5000, 'Extra flood insurance (£0 to £5,000 a year)', 'risk_flood_extra'],
    ['#rk-years', 5, 200, 'One downturn every (5 to 200 years)', 'risk_downturn_years']];
  const OPP_LIMITS = [0, 30];
  const riskSet = (A) => {
    const f = (sel, k, lo, hi) => { const v = num(val(sel)); return isFinite(v) && v >= lo && v <= hi ? v : (A[k] ? A[k].v : NaN); };
    const [t, fl, y] = RISK_CHECKS.map(([sel, lo, hi, , k]) => f(sel, k, lo, hi));
    return { tenant: t, flood: fl, years: Math.max(1, y) };
  };
  // a setting outside its range isn't used: the default is, and this says so next to the settings
  const settingsProblem = () => {
    const A = getAss(); if (!A) return '';
    for (const [sel, lo, hi, name, k] of RISK_CHECKS) { const raw = val(sel), v = num(raw); if (String(raw).trim() !== '' && !(isFinite(v) && v >= lo && v <= hi)) return `${name} is out of range, so the default (${A[k] ? A[k].v : '—'}) is used until it is fixed.`; }
    const c = num(val('#nb-opp-custom'));
    if (state.nbOpp === 'custom' && String(val('#nb-opp-custom')).trim() !== '' && !(isFinite(c) && c >= OPP_LIMITS[0] && c <= OPP_LIMITS[1])) return `Your rate must be between ${OPP_LIMITS[0]}% and ${OPP_LIMITS[1]}%, so the 10-year gilt is used until it is fixed.`;
    return '';
  };
  const showSettingsProblem = () => { const m = settingsProblem(); ['#risk-err', '#inv-risk-err'].forEach((sel) => { const el = $(sel); if (el) { el.textContent = m; el.hidden = !m; } }); };
  const courtRatio = () => {
    const P = typeof getPoss === 'function' ? getPoss() : null; if (!P) return 1;
    const d = P.latest('Doncaster', 'standard'), e = P.latest('England', 'standard'); return d && e && e.rate > 0 ? d.rate / e.rate : 1;
  };
  const riskIndex = (r) => {
    const N = getNb(); if (!N) return 1;
    const a = num(r.asb_rate) / num(N.D.asb_rate), b = num(r.imd_score) / num(N.D.imd_score), v = [a, b].filter(isFinite);
    return v.length ? Math.max(0.4, Math.min(3, d3.mean(v))) : 1;
  };
  // P: price; rent: monthly; opts.flood: this home's flood share (else the area's); opts.noEpc: the deal already counts it
  const riskFor = (r, P, rent, A, hold, opts = {}) => {
    if (!r || !A || !A.risk_tenant_pct || !isFinite(P) || P <= 0) return null;
    const S = riskSet(A), idx = riskIndex(r), cr = courtRatio();
    const tenant = 100 * 12 * rent * (S.tenant / 100) * cr * idx / P;
    const fs = opts.flood != null ? opts.flood : num(r.flood_pct) / 100, flood = 100 * (isFinite(fs) ? fs : 0) * S.flood / P;
    const es = num(r.epc_below_c_pct) / 100, epc = opts.noEpc || !isFinite(es) ? 0 : 100 * es * Math.min(A.epc_upgrade_avg.v, P < 100000 ? 0.1 * P : A.epc_cost_cap.v) / hold / P;
    const down = isFinite(num(r.peak_fall_pct)) ? Math.abs(num(r.peak_fall_pct)) / S.years : 0;
    return { tenant, flood, epc, down, income: tenant + flood + epc, total: tenant + flood + epc + down, idx, cr };
  };
  const nbReturn = (r, o) => {
    if (!r || !o) return null;
    const A = o.A, g = num(r[`growth_${o.basis}y`]);
    const part = (t) => {
      const P = num(r['median_' + t]), rent = num(r['rent_' + t]); if (!isFinite(P) || !isFinite(rent) || P <= 0) return null;
      const R = 12 * rent, income = R * (1 - A.voids.v / 52) * (1 - (A.letting_fee.v + A.maintenance.v) / 100) - A.insurance.v - A.compliance.v;
      const oneOff = (sdlt(P, A) + A.buying_costs.v + P * A.selling_costs.v / 100) / o.hold;
      return { P, n: num(r['n_' + t]) || 1, gross: 100 * R / P, net: 100 * (income - oneOff) / P, rk: riskFor(r, P, rent, A, o.hold) };
    };
    const parts = (o.type === 'A' ? TYPES : [o.type]).map(part).filter(Boolean);
    if (!parts.length || !isFinite(g)) return null;
    const w = d3.sum(parts, (p) => p.n), avg = (f) => d3.sum(parts, (p) => f(p) * p.n) / w, net = avg((p) => p.net);
    const rk = parts.every((p) => p.rk) ? { tenant: avg((p) => p.rk.tenant), flood: avg((p) => p.rk.flood), epc: avg((p) => p.rk.epc), down: parts[0].rk.down, idx: parts[0].rk.idx, cr: parts[0].rk.cr } : null;
    if (rk) { rk.income = rk.tenant + rk.flood + rk.epc; rk.total = rk.income + rk.down; }
    const on = state.riskOn && rk, total = net + g - (on ? rk.total : 0);
    return { price: o.type === 'A' ? num(r.median_price) : parts[0].P, n: o.type === 'A' ? num(r.sales_3y) : parts[0].n, gross: avg((p) => p.gross), net,
      growth: g, glo: num(r[`growth_${o.basis}y_lo`]), ghi: num(r[`growth_${o.basis}y_hi`]), total, above: total - o.opp,
      risk: rk ? rk.total : NaN, rk, px: g - (on ? rk.down : 0), py: net - (on ? rk.income : 0) };
  };
  const nbRanked = (N, o) => {
    const d = N.list.map((r) => ({ r, x: nbReturn(r, o) })).filter((e) => e.x).sort((a, b) => b.x.above - a.x.above);
    d.forEach((e, i) => (e.rank = i + 1)); return d;
  };
  const propertyNb = (N) => (state.last && state.last.pc ? N.ofLsoa.get(state.last.pc.lsoa21) || null : null);
  const selectNb = (ms, scroll) => {
    const N = getNb(); if (!N || !N.byId.has(ms)) return;
    state.nb = ms; state.nbPicked = true; renderAreas();
    if (scroll) $('#nb-card').scrollIntoView({ behavior: 'smooth', block: 'start' });
  };

  // ---------- controls ----------
  const syncRisk = () => document.querySelectorAll('.risk-toggle').forEach((b) => b.setAttribute('aria-pressed', String(state.riskOn)));
  document.querySelectorAll('.risk-toggle').forEach((b) => b.addEventListener('click', () => { state.riskOn = !state.riskOn; syncRisk(); render(); }));
  ['#rk-tenant', '#rk-flood', '#rk-years'].forEach((s) => $(s).addEventListener('input', () => render()));
  const renderRiskHow = (A) => {
    const N = getNb(); if (!A || !A.risk_tenant_pct || !N) return;
    [['#rk-tenant', 'risk_tenant_pct'], ['#rk-flood', 'risk_flood_extra'], ['#rk-years', 'risk_downturn_years']].forEach(([s, k]) => { if ($(s).value === '') $(s).value = String(A[k].v); });
    const S = riskSet(A), cr = courtRatio(), P = getPoss ? getPoss() : null, dC = P && P.latest('Doncaster', 'standard'), eC = P && P.latest('England', 'standard');
    const li = (tx) => { const e = document.createElement('li'); e.textContent = tx; return e; };
    $('#risk-how').replaceChildren(
      li(`Tenants: ${pct(S.tenant, 2)} of rent a year in a typical area. ${A.risk_tenant_pct.src.split(':')[0]}. This is × ${d3.format('.2f')(cr)} for Doncaster, because Doncaster's landlord court claims run at ${dC ? d3.format('.1f')(dC.rate) : '—'} per 1,000 rented homes against England's ${eC ? d3.format('.1f')(eC.rate) : '—'}, × the area's risk index: its anti-social behaviour and deprivation against Doncaster's, averaged and kept between 0.4 and 3.`),
      li(`Flood: the share of homes at flood risk × ${gbp(S.flood)} a year of extra insurance, a scenario rather than a price: get a landlord insurance quote. A typical let falls outside Flood Re, whose cover needs the policyholder or their family to live in the home (or it to be empty), so its premium is set on the open market.`),
      li(`EPC: the share of homes below C × the average ${gbp(A.epc_upgrade_avg.v)} to reach C (capped at ${gbp(A.epc_cost_cap.v)}, or 10% of the value under £100k), spread over ${A.hold_years.v} years. Lettings need C by October 2030.`),
      li(`Downturn: the area's own fall after the 2008 peak, once every ${S.years} years. ${A.risk_downturn_years.src.split(';')[0]}.`),
      li('These are allowances, not measured losses: no open data gives arrears or voids by area. Change the settings to test your own view.'));
  };
  const segPick = (sel, attr, set) => document.querySelectorAll(sel + ' button').forEach((b) => b.addEventListener('click', () => {
    set(b.dataset[attr]); document.querySelectorAll(sel + ' button').forEach((x) => x.setAttribute('aria-pressed', String(x === b))); renderAreas();
  }));
  segPick('#nb-type', 't', (v) => (state.nbType = v));
  segPick('#nb-basis', 'b', (v) => (state.nbBasis = Number(v)));
  ['#btl-min', '#btl-max', '#btl-flood'].forEach((s) => $(s).addEventListener('input', () => safe('the buy-to-let ranking', renderBtl)));
  $('#map-metric').addEventListener('change', () => ($('#map-metric').value === 'above' ? safe('the hurdle rate', runSweep) : safe('the neighbourhood map', renderMap)));
  document.querySelectorAll('#btl-table th button').forEach((b) => b.addEventListener('click', () => {
    const k = b.dataset.k, S = state.btlSort; S.dir = S.k === k ? -S.dir : (k === 'name' || k === 'price' || k === 'imd_score' || k === 'asb_rate' || k === 'risk' || k === 'flood_pct' || k === 'epc_below_c_pct' ? 1 : -1); S.k = k;
    safe('the buy-to-let ranking', renderBtl);
  }));

  // ---------- search: neighbourhood names, towns and villages, wards, postcode sectors and full postcodes ----------
  const normText = (s) => String(s || '').toLowerCase().replace(/&/g, 'and').replace(/[^a-z0-9 ]+/g, ' ').replace(/\s+/g, ' ').trim();
  const normCode = (s) => String(s || '').toUpperCase().replace(/[^A-Z0-9]/g, '');
  const searchIndex = (N) => {
    if (cache.nbSearch) return cache.nbSearch;
    const items = [];
    N.list.forEach((r) => {
      items.push({ key: normText(r.name), ms: r.msoa21, sub: (r.places ? r.places.split('; ').join(', ') + ' · ' : '') + r.wards.split('; ')[0] + ' ward', rank: 0 });
      String(r.places || '').split('; ').filter(Boolean).forEach((p) => items.push({ key: normText(p), ms: r.msoa21, sub: 'Takes in ' + p, rank: 1 }));
      String(r.wards || '').split('; ').filter(Boolean).forEach((w) => items.push({ key: normText(w), ms: r.msoa21, sub: 'In ' + w + ' ward', rank: 2 }));
      String(r.sectors || '').split('; ').filter(Boolean).forEach((s) => items.push({ code: normCode(s), ms: r.msoa21, sub: 'Covers part of postcode sector ' + s, rank: 3 }));
    });
    return (cache.nbSearch = items);
  };
  const findNb = (q) => {
    const N = getNb(); if (!N) return [];
    const items = searchIndex(N), t = normText(q), c = normCode(q), out = new Map();
    const add = (ms, sub, score) => { const e = out.get(ms); if (!e || score < e.score) out.set(ms, { ms, sub, score }); };
    if (!t) return [];
    if (/^[A-Z]{1,2}\d/.test(c)) {                                   // a postcode, sector or district
      if (c.length >= 5) {
        const pcs = getPcs(), p = pcs && pcs.get(normPc(q));
        if (p) { const ms = N.ofLsoa.get(p.lsoa21); if (ms) add(ms, 'Postcode ' + p.postcode, -1); else return [{ none: `${p.postcode} is outside Doncaster's neighbourhoods` }]; }
      }
      // "DN11" written without a space is the district DN11, not the sector DN1 1 (which needs its space): when the
      // characters spell a real district, the district's sectors come first
      const isDistrict = items.some((it) => it.code && it.code.slice(0, -1) === c), spaced = /\s\d$/.test(String(q).trim());
      const exact = isDistrict && !spaced ? 3.5 : 3, inDistrict = isDistrict && !spaced ? 3 : 3.5;
      items.forEach((it) => {                                        // sector exactly, a district, or a part postcode inside a sector
        if (!it.code) return;
        if (it.code === c) add(it.ms, it.sub, exact); else if (it.code.slice(0, -1) === c) add(it.ms, it.sub, inDistrict); else if (c.length > it.code.length && c.startsWith(it.code)) add(it.ms, it.sub, 3.2);
      });
    }
    items.forEach((it) => {
      if (!it.key) return;
      const i = it.key.indexOf(t); if (i < 0) return;
      add(it.ms, it.sub, it.rank + (i === 0 ? 0 : (it.key[i - 1] === ' ' ? 0.3 : 0.6)));
    });
    return [...out.values()].sort((a, b) => a.score - b.score || N.byId.get(a.ms).name.localeCompare(N.byId.get(b.ms).name)).slice(0, 8);
  };
  const nbQ = $('#nb-q'), nbList = $('#nb-results'); let nbActive = -1, nbHits = [];
  const closeResults = () => { nbList.hidden = true; nbQ.setAttribute('aria-expanded', 'false'); nbQ.removeAttribute('aria-activedescendant'); nbActive = -1; };
  const showResults = () => {
    const N = getNb(); nbHits = findNb(nbQ.value); nbList.replaceChildren(); nbActive = -1;
    if (!nbQ.value.trim() || !N) { closeResults(); return; }
    if (!nbHits.length || nbHits[0].none) {
      const li = document.createElement('li'); li.className = 'none'; li.setAttribute('role', 'option'); li.setAttribute('aria-disabled', 'true');
      li.textContent = nbHits[0] && nbHits[0].none ? nbHits[0].none : 'No neighbourhood matches. Try a town, ward or postcode.'; nbList.appendChild(li); nbHits = [];
    } else nbHits.forEach((h, i) => {
      const li = document.createElement('li'), a = document.createElement('span'), b = document.createElement('span');
      li.id = 'nb-opt-' + i; li.setAttribute('role', 'option'); li.setAttribute('aria-selected', 'false');
      a.className = 'r1'; a.textContent = N.byId.get(h.ms).name; b.className = 'r2'; b.textContent = h.sub; li.append(a, b);
      li.addEventListener('mousedown', (e) => { e.preventDefault(); pickHit(i); }); nbList.appendChild(li);
    });
    nbList.hidden = false; nbQ.setAttribute('aria-expanded', 'true');
  };
  const markActive = () => nbList.querySelectorAll('li[id]').forEach((li, i) => { li.setAttribute('aria-selected', String(i === nbActive)); if (i === nbActive) { nbQ.setAttribute('aria-activedescendant', li.id); li.scrollIntoView({ block: 'nearest' }); } });
  const pickHit = (i) => { const h = nbHits[i]; if (!h) return; const N = getNb(); nbQ.value = N.byId.get(h.ms).name; closeResults(); selectNb(h.ms, true); };
  nbQ.addEventListener('input', showResults);
  nbQ.addEventListener('focus', () => { if (nbQ.value.trim()) showResults(); });
  nbQ.addEventListener('blur', () => setTimeout(closeResults, 120));
  nbQ.addEventListener('keydown', (e) => {
    if (e.key === 'ArrowDown' && nbHits.length) { e.preventDefault(); if (nbList.hidden) showResults(); nbActive = Math.min(nbHits.length - 1, nbActive + 1); markActive(); }
    else if (e.key === 'ArrowUp' && nbHits.length) { e.preventDefault(); nbActive = Math.max(0, nbActive - 1); markActive(); }
    else if (e.key === 'Enter') { e.preventDefault(); if (!nbList.hidden || nbQ.value.trim()) { if (nbList.hidden) showResults(); pickHit(nbActive >= 0 ? nbActive : 0); } }
    else if (e.key === 'Escape') { closeResults(); }
  });

  // ---------- the whole tab ----------
  const renderAreas = () => {
    const A = getAss(), rs = rentSeries(), N = getNb(), o = nbOpts();
    if (rs) {
      const all = rs.get('all') || [], lastR = all[all.length - 1], yAgo = all[all.length - 13];
      if (lastR) { $('#t-rent').textContent = gbp(lastR.v); $('#t-rent-note').textContent = 'A month, ' + monthLabel(lastR.month) + ' (ONS)'; }
      if (lastR && yAgo) $('#t-rent-yoy').textContent = sgn((lastR.v / yAgo.v - 1) * 100);
    }
    if (A) { $('#t-rent-10').textContent = pct(A.rent_growth.v, 1); $('#t-rent-5').textContent = `${pct(A.rent_growth_5y.v, 1)} a year over 5 years`; }
    if (N) { $('#t-price-10').textContent = pct(num(N.D.growth_10y), 1); $('#t-price-10-n').textContent = `Repeat-sales index · ${pct(num(N.D.growth_5y), 1)} a year over 5 years`; }
    oppLabels();
    safe('the risk allowance settings', () => renderRiskHow(A)); syncRisk();
    if (N && o) {
      if (!state.nbPicked || !N.byId.has(state.nb)) state.nb = propertyNb(N) || (nbRanked(N, o)[0] || {}).r?.msoa21 || N.list[0].msoa21;
      const tn = o.type === 'A' ? 'each type of home' : TYPE_PLURAL[o.type];
      $('#nb-ctl-note').textContent = `Returns are for a cash purchase at the local median price, let at Doncaster's ONS average rent for ${tn}. Net yield takes off letting and management (${pct(o.A.letting_fee.v, 0)} of rent), maintenance (${pct(o.A.maintenance.v, 0)}), ${o.A.voids.v} void weeks, insurance and safety checks, and spreads stamp duty (with the ${pct(o.A.sdlt_surcharge.v, 0)} surcharge), legal and selling costs over ${o.hold} years. Price growth is the average of the past ${o.basis} years, not a forecast. The opportunity cost is what the same cash could earn instead: ${o.oppName} at ${pct(o.opp, 2)}.${state.riskOn ? ' Risk allowance on: returns are after allowances for tenant risk, flood insurance, EPC upgrades and a future downturn.' : ''}`;
    }
    safe('the neighbourhood profile', renderNb);
    safe('the time-lapse', renderLapse);
    safe('the neighbourhood map', renderMap);
    safe('the buy-to-let ranking', renderBtl);
    // rent by bedrooms
    if (rs && !failed($('#rentbeds-chart'), ['rents'])) {
      const names = ['1 bed', '2 bed', '3 bed', '4+ bed'];
      const series = names.map((n, i) => ({ name: n, color: dash.colors[i], values: (rs.get(n) || []).map((p) => ({ date: parseMonth(p.month), v: p.v })) }));
      const lg = $('#rentbeds-legend'); lg.replaceChildren();
      series.forEach((s) => { const sp = document.createElement('span'), ic = document.createElement('i'); ic.style.background = s.color; sp.append(ic, s.name); lg.appendChild(sp); });
      lineChart($('#rentbeds-chart'), series, { label: 'Average rent by bedrooms in Doncaster', yFmt: (v) => '£' + d3.format(',')(v), tipFmt: (v) => gbp(v) + ' a month', endLabels: true, endFmt: gbp, height: 240 });
      const tb = $('#lha-table tbody'); tb.replaceChildren();
      [['1', '1 bed'], ['2', '2 bed'], ['3', '3 bed'], ['4', '4+ bed']].forEach(([b, n]) => {
        const lr = latestRent(n), l = rows('lha').find((x) => x.bedrooms === b); if (!lr || !l) return;
        const tr = document.createElement('tr'); cell(tr, b === '4' ? '4+' : b); cell(tr, gbp(lr.v), 'r'); cell(tr, gbp(num(l.monthly_rate)), 'r'); cell(tr, gbp(lr.v - num(l.monthly_rate)), 'r'); tb.appendChild(tr);
      });
    }
  };

  // ---------- one neighbourhood ----------
  const pill = (box, text, cls) => { const s = document.createElement('span'); s.className = 'pill' + (cls ? ' ' + cls : ''); s.textContent = text; box.appendChild(s); return s; };
  const renderNb = () => {
    const card = $('#nb-card'); if (failed($('#nb-hist'), ['neighbourhoods', 'nbhd_index'])) return;
    const N = getNb(), o = nbOpts(); if (!N || !o) return;
    const r = N.byId.get(state.nb); if (!r) return;
    const D = N.D, x = nbReturn(r, o), xd = nbReturn(D, o), ranked = nbRanked(N, o), me = ranked.find((e) => e.r.msoa21 === r.msoa21), mine = propertyNb(N);
    card.dataset.key = r.msoa21;
    $('#nb-name').textContent = r.name;
    const wards = r.wards.split('; ');
    $('#nb-sub').textContent = `${wards.length > 1 ? 'Wards' : 'Ward'}: ${wards.join(', ')} · postcode sectors ${String(r.sectors || '').split('; ').filter(Boolean).join(', ') || '—'} · ${d3.format(',')(num(r.homes))} homes`;
    const bd = $('#nb-badges'); bd.replaceChildren();
    if (me) pill(bd, `${ordinal(me.rank)} of ${ranked.length} for return above ${o.oppShort === 'gilt' ? 'the gilt' : o.oppName}`, 'strong');
    if (mine === r.msoa21) pill(bd, 'Your property is here');
    else if (mine) { const b = document.createElement('button'); b.className = 'pill linkish'; b.type = 'button'; b.textContent = 'Go to your property\'s neighbourhood'; b.addEventListener('click', () => selectNb(mine, false)); bd.appendChild(b); }
    if (r.licensing) pill(bd, 'Selective licensing (part)');
    if (num(r.sales_3y) < 180) pill(bd, 'Fewer sales: figures less certain');
    if (num(r.flood_pct) >= 25) pill(bd, `${pct(num(r.flood_pct), 0)} of homes at flood risk`);
    const tl = o.type === 'A' ? 'Typical price' : 'Typical ' + TYPE_SHORT[o.type].toLowerCase();
    $('#nb-t-price-l').textContent = tl;
    countTo($('#nb-t-price'), x ? x.price : NaN, gbpK);
    $('#nb-t-price-n').textContent = x ? `${d3.format(',')(x.n)} sales in 3 years · Doncaster ${gbpK(xd && xd.price)}` : `Too few ${TYPE_SHORT[o.type] ? TYPE_SHORT[o.type].toLowerCase() : ''} sales here`;
    countTo($('#nb-t-gross'), x ? x.gross : NaN, (v) => pct(v, 1));
    countTo($('#nb-t-net'), x ? x.net : NaN, (v) => pct(v, 1));
    $('#nb-t-growth-l').textContent = `Price growth a year, ${o.basis} years`;
    countTo($('#nb-t-growth'), x ? x.growth : num(r[`growth_${o.basis}y`]), (v) => pct(v, 1));
    $('#nb-t-growth-r').textContent = `80% range ${pct(num(r[`growth_${o.basis}y_lo`]), 1)} to ${pct(num(r[`growth_${o.basis}y_hi`]), 1)}`;
    countTo($('#nb-t-total'), x ? x.total : NaN, (v) => pct(v, 1));
    $('#nb-t-above-l').textContent = `Above ${o.oppName} (${pct(o.opp, 2)})`;
    const tn_ = $('#nb-t-total').nextElementSibling; if (tn_) tn_.textContent = x && state.riskOn && x.rk ? `Net yield + growth − ${d3.format('.1f')(x.rk.total)} pts risk allowance` : 'Net yield + price growth';
    const ab = $('#nb-t-above'); countTo(ab, x ? x.above : NaN, (v) => pts(v)); ab.classList.toggle('good', !!x && x.above > 0); ab.classList.toggle('badc', !!x && x.above < 0);
    $('#nb-t-above-n').textContent = x ? `Total ${pct(x.total, 1)} vs ${pct(o.opp, 2)} · Doncaster ${pts(xd && xd.above)}` : '—';
    // history: today's typical price moved back along the neighbourhood's index
    const box = $('#nb-hist'), useType = o.type !== 'A' && isFinite(num(r['median_' + o.type])) && isFinite(num(D['median_' + o.type]));
    const base = useType ? num(r['median_' + o.type]) : num(r.median_price), baseD = useType ? num(D['median_' + o.type]) : num(D.median_price);
    const ser = (ms, b) => (N.idx.get(ms) || []).map((p) => ({ date: new Date(Date.UTC(p.year, 7, 1)), v: b * p.v / 100 }));
    const series = [{ name: r.name, color: dash.colors[0], values: ser(r.msoa21, base) }, { name: 'Doncaster', color: 'var(--cds-chart-reference)', values: ser(LA_CODE, baseD) }];
    const y0 = (N.idx.get(r.msoa21) || [{}])[0].year, y1 = (N.idx.get(r.msoa21) || []).at(-1)?.year;
    $('#nb-hist-title').textContent = `Value of a typical ${useType ? TYPE_SHORT[o.type].toLowerCase() : 'home'} here, ${y0} to ${y1}`;
    const lg = $('#nb-hist-legend'); lg.replaceChildren();
    series.forEach((s) => { const sp = document.createElement('span'), ic = document.createElement('i'); ic.style.background = s.color; sp.append(ic, s.name); lg.appendChild(sp); });
    const hk = `${r.msoa21}|${useType ? o.type : 'A'}`, animate = state.nbHistKey !== hk; state.nbHistKey = hk;
    lineChart(box, series, { label: `Value of a typical home in ${r.name} and in Doncaster, ${y0} to ${y1}`, yFmt: (v) => gbpK(v), tipFmt: (v) => gbp(v), xFmt: d3.utcFormat('%Y'),
      tipX: (d) => `Year to August ${d.getUTCFullYear()}`, endLabels: true, endFmt: gbpK, height: 260, animate });
    const rec = num(r.recovered_year);
    $('#nb-hist-note').textContent = `Today's typical price moved back along a repeat-sales index (${d3.format(',')(num(r.pairs))} homes sold twice since ${y0}), so changes in the mix of homes sold don't move it. ` +
      `After the ${r.peak_year} peak, values fell ${pct(-num(r.peak_fall_pct), 0)} to ${r.trough_year}` + (isFinite(rec) ? ` and were back to the peak by ${rec}.` : ' and have not yet regained the peak.') +
      ` Doncaster fell ${pct(-num(D.peak_fall_pct), 0)}.`;
    // facts
    const tb = $('#nb-facts tbody'); tb.replaceChildren();
    const group = (t) => { const tr = document.createElement('tr'), th = document.createElement('th'); th.scope = 'rowgroup'; th.colSpan = 3; th.textContent = t; tr.appendChild(th); tb.appendChild(tr); };
    const line = (label, f) => { const tr = document.createElement('tr'); cell(tr, label); cell(tr, f(r), 'r'); cell(tr, f(D), 'r'); tb.appendChild(tr); };
    const n0 = (v) => (isFinite(v) ? d3.format(',.0f')(v) : '—');
    group('Prices, last 3 years');
    line('Typical price, all types', (z) => gbpK(num(z.median_price)));
    TYPES.forEach((t) => line(`${TYPE_SHORT[t]} (sales)`, (z) => (isFinite(num(z['median_' + t])) ? `${gbpK(num(z['median_' + t]))} (${n0(num(z['n_' + t]))})` : `— (${n0(num(z['n_' + t]))})`)));
    line('Price per m²', (z) => gbp(num(z.price_per_m2)));
    line('Typical floor area', (z) => (isFinite(num(z.floor_area)) ? num(z.floor_area) + ' m²' : '—'));
    group('Market');
    line('Sales a year', (z) => n0(num(z.sales_per_year)));
    line('Homes sold a year', (z) => pct(num(z.turnover_pct), 1));
    line('New builds among sales', (z) => pct(num(z.new_build_pct), 0));
    group('Price growth (repeat sales)');
    line('Last 12 months', (z) => sgn(num(z.growth_1y), 1));
    line('A year, last 5 years', (z) => pct(num(z.growth_5y), 1));
    line('A year, last 10 years', (z) => pct(num(z.growth_10y), 1));
    line('A year, last 20 years', (z) => pct(num(z.growth_20y), 1));
    line('Fall after the 2008 peak', (z) => `${sgn(num(z.peak_fall_pct), 0)} (${z.peak_year}–${z.trough_year})`);
    line('Back to that peak', (z) => (isFinite(num(z.recovered_year)) ? String(z.recovered_year) : 'Not yet'));
    group(`Renting${o.type === 'A' ? '' : ', ' + TYPE_SHORT[o.type].toLowerCase()}`);
    line('Gross yield', (z) => { const q = nbReturn(z, o); return q ? pct(q.gross, 1) : '—'; });
    line('Net yield', (z) => { const q = nbReturn(z, o); return q ? pct(q.net, 1) : '—'; });
    line('Private renters (Census 2021)', (z) => pct(num(z.private_rented_pct), 0));
    line('Social renters', (z) => pct(num(z.social_rented_pct), 0));
    line('Owned outright', (z) => pct(num(z.owned_outright_pct), 0));
    group(`Risk allowance, points a year${state.riskOn ? ' (taken off the return)' : ' (switch on to take off)'}`);
    const rkOf = (z) => { const q = nbReturn(z, o); return q && q.rk ? q.rk : null; }, f2 = (v) => (!isFinite(v) ? '—' : v < 0.005 ? '0.00' : `−${d3.format('.2f')(v)}`);
    line('Tenants: arrears, voids, damage', (z) => { const k = rkOf(z); return k ? `${f2(k.tenant)} (index ${d3.format('.2f')(k.idx)})` : '—'; });
    line('Flood insurance', (z) => { const k = rkOf(z); return k ? f2(k.flood) : '—'; });
    line('EPC upgrades to C', (z) => { const k = rkOf(z); return k ? f2(k.epc) : '—'; });
    line('Downturn', (z) => { const k = rkOf(z); return k ? f2(k.down) : '—'; });
    line('Total risk allowance', (z) => { const k = rkOf(z); return k ? f2(k.total) : '—'; });
    group('Risks and housing stock');
    line('Homes at flood risk', (z) => pct(num(z.flood_pct), 0));
    line('Homes with EPC below C', (z) => pct(num(z.epc_below_c_pct), 0));
    line('Deprivation score', (z) => (isFinite(num(z.imd_score)) ? d3.format('.1f')(num(z.imd_score)) : '—'));
    line('Crime score', (z) => (isFinite(num(z.crime_score)) ? d3.format('.2f')(num(z.crime_score)) : '—'));
    line('Council tax band A', (z) => pct(num(z.band_a_pct), 0));
    line('Homes', (z) => n0(num(z.homes)));
    line('Anti-social behaviour, reports a year per 1,000 residents', (z) => (isFinite(num(z.asb_rate)) ? d3.format('.1f')(num(z.asb_rate)) : '—'));
    line('Distance to a station', (z) => (isFinite(num(z.dist_rail_km)) ? d3.format('.1f')(num(z.dist_rail_km)) + ' km' : '—'));
  };

  // ---------- the map ----------
  // div: blue better, red worse, grey within one step of the midpoint (Doncaster, or zero for the opportunity cost)
  const NB_MAP = {
    above: { lvl: 'nb', kind: 'div', better: 1, zero: true, get: (r, o) => nbReturn(r, o)?.above, fmt: (v) => pts(v),
      note: (o) => `Total return a year minus ${o.oppName} (${pct(o.opp, 2)}). Blue beats it, red falls short.` },
    total: { lvl: 'nb', kind: 'div', better: 1, get: (r, o) => nbReturn(r, o)?.total, fmt: (v) => pct(v, 1), note: () => 'Net yield plus the average price growth a year, for a cash purchase.' },
    net: { lvl: 'nb', kind: 'div', better: 1, get: (r, o) => nbReturn(r, o)?.net, fmt: (v) => pct(v, 1), note: () => 'Rent after running costs, with buying and selling costs spread over the holding period, as a share of the price.' },
    gross: { lvl: 'nb', kind: 'div', better: 1, get: (r, o) => nbReturn(r, o)?.gross, fmt: (v) => pct(v, 1), note: () => "A year's rent at Doncaster's ONS average for the type, over the local median price. Rents are borough-wide, so this mostly reflects local prices." },
    growth: { lvl: 'nb', kind: 'div', better: 1, get: (r, o) => num(r[`growth_${o.basis}y`]), fmt: (v) => pct(v, 1), note: (o) => `Average price growth a year over the last ${o.basis} years, from a repeat-sales index.` },
    risk: { lvl: 'nb', kind: 'div', better: -1, floor: 0, get: (r, o) => nbReturn(r, o)?.risk, fmt: (v) => d3.format('.1f')(v) + ' pts',
      note: () => 'Points a year the risk allowance takes off: tenant risk, flood insurance, EPC upgrades and a downturn. Red needs a bigger allowance than Doncaster overall.' },
    growth_1y: { lvl: 'nb', kind: 'div', better: 1, get: (r) => num(r.growth_1y), fmt: (v) => sgn(v, 1), note: () => 'Change in the repeat-sales index, year to August, against the year before. One year is noisy.' },
    peak_fall_pct: { lvl: 'nb', kind: 'div', better: 1, get: (r) => num(r.peak_fall_pct), fmt: (v) => sgn(v, 0), note: () => 'How far values fell from the 2008 peak to the low a few years later: a guide to how hard a downturn hits.' },
    turnover_pct: { lvl: 'nb', kind: 'div', better: 1, floor: 0, get: (r) => num(r.turnover_pct), fmt: (v) => pct(v, 1), note: () => 'Sales a year as a share of all homes (VOA council tax list): how easily homes change hands.' },
    private_rented_pct: { lvl: 'nb', kind: 'seq', get: (r) => num(r.private_rented_pct), fmt: (v) => pct(v, 1), note: () => 'Households renting privately, Census 2021: darker where the rental market is bigger.' },
    price_per_m2: { lvl: 'lsoa', kind: 'seq', get: (r) => num(r.price_per_m2), fmt: (v) => gbp(v), note: () => 'Median sale price per m² of floor area, last 3 years (sales with an EPC). Darker is dearer. Blank where fewer than 10 sales.' },
    median_price: { lvl: 'lsoa', kind: 'seq', get: (r) => num(r.median_price), fmt: (v) => gbpK(v), note: () => 'Median sale price, all types, last 3 years. Darker is dearer; reflects the mix of homes as well as location.' },
    flood_pct: { lvl: 'lsoa', kind: 'flood', get: (r) => num(r.flood_pct), fmt: (v) => pct(v, 0), note: () => 'Estimated share of homes at high or medium risk of flooding from rivers or the sea (Environment Agency, NaFRA2).' },
    imd_score: { lvl: 'lsoa', kind: 'div', better: -1, floor: 0, get: (r) => num(r.imd_score), fmt: (v) => d3.format('.1f')(v), note: () => 'Index of Multiple Deprivation 2025 score: red is more deprived than Doncaster overall, blue less.' },
    asb_rate: { lvl: 'lsoa', kind: 'div', better: -1, floor: 0, get: (r) => num(r.asb_rate), fmt: (v) => d3.format('.1f')(v),
      note: () => { const N = getNb(); return `Anti-social behaviour reported to the police, ${N ? monthLabel(N.D.asb_from) + ' to ' + monthLabel(N.D.asb_to) : 'last 12 months'} (police.uk), per 1,000 residents: red is more than Doncaster overall, blue less. Town-centre areas with few residents score high.`; } },
    epc_below_c_pct: { lvl: 'lsoa', kind: 'div', better: -1, floor: 0, get: (r) => num(r.epc_below_c_pct), fmt: (v) => pct(v, 0), note: () => 'Share of homes whose latest EPC is D or worse: lettings need C by October 2030. Red means more upgrades.' }
  };
  const mapClasses = (M, vals, mid) => {
    const tok = (i) => `var(--cds-chart-${M.kind === 'seq' ? 'sequential' : 'diverging'}-${i})`;
    if (M.kind === 'seq') {
      const q = d3.scaleQuantile(vals, [1, 2, 3, 4, 5, 6, 7]), th = q.quantiles(), e = [d3.min(vals), ...th, d3.max(vals)];
      return { color: (v) => tok(q(v)), legend: [1, 2, 3, 4, 5, 6, 7].map((i) => ({ c: tok(i), t: `${M.fmt(e[i - 1])} to ${M.fmt(e[i])}` })).filter((l, i) => e[i] < e[i + 1]) };
    }
    if (M.kind === 'flood') {
      const br = [0.05, 10, 25], lab = ['None', 'Under 10%', '10% to 25%', '25% or more'];
      return { color: (v) => tok(4 + d3.bisectRight(br, v)), legend: lab.map((t, i) => ({ c: tok(4 + i), t })) };
    }
    const dev = vals.map((v) => Math.abs(v - mid)).sort(d3.ascending), S = d3.quantile(dev, 0.95) || d3.max(dev) || 1, w = S / 3;
    const k = (v) => Math.max(-3, Math.min(3, Math.round(M.better * (v - mid) / w)));
    // a measure that can't go below zero (a rate or a share) drops steps that would only hold negative values
    const legend = [-3, -2, -1, 0, 1, 2, 3].map((j) => {
      let a = mid + (j - 0.5) * w * M.better, b = mid + (j + 0.5) * w * M.better; if (a > b) [a, b] = [b, a];
      let lowEnd = (j === -3 && M.better > 0) || (j === 3 && M.better < 0); const highEnd = (j === 3 && M.better > 0) || (j === -3 && M.better < 0);
      if (M.floor != null && b <= M.floor) return null;
      if (M.floor != null && a < M.floor) lowEnd = true;
      return { c: tok(4 - j), t: lowEnd ? `Under ${M.fmt(b)}` : highEnd ? `Over ${M.fmt(a)}` : `${M.fmt(a)} to ${M.fmt(b)}` };
    }).filter(Boolean);
    return { color: (v) => tok(4 - k(v)), legend, step: w };
  };
  const renderMap = () => {
    const box = $('#lsoa-map'); if (failed(box, ['lsoa_map', 'neighbourhoods'])) return;
    const L = getLsoa(), N = getNb(), o = nbOpts(); if (!L || !N || !o) return; fresh(box);
    if (sweepRaf) { cancelAnimationFrame(sweepRaf); sweepRaf = null; $('#map-sweep').disabled = false; }
    const key = $('#map-metric').value, M = NB_MAP[key] || NB_MAP.total;
    const W = Math.max(300, box.clientWidth), H = Math.round(Math.min(600, Math.max(320, W * 0.78)));
    const proj = fitShapes(L.rows, W, H, 8), path = (g) => shapePath(proj, g);
    const shapes = M.lvl === 'nb'
      ? N.list.filter((r) => r.geometry).map((r) => ({ ms: r.msoa21, geometry: r.geometry, v: M.get(r, o), r, nb: r }))
      : L.rows.map((r) => ({ ms: N.ofLsoa.get(r.lsoa21), geometry: r.geometry, v: M.get(r, o), r, nb: N.byId.get(N.ofLsoa.get(r.lsoa21)) }));
    const vals = shapes.map((s) => s.v).filter((v) => v != null && isFinite(v));
    if (!vals.length) return;
    const mid = M.kind === 'div' ? (M.zero ? 0 : M.get(N.D, o)) : null, C = mapClasses(M, vals, mid);
    const svg = d3.select(box).append('svg').attr('width', '100%').attr('viewBox', `0 0 ${W} ${H}`).attr('role', 'img')
      .attr('aria-label', `Map of Doncaster neighbourhoods by ${$('#map-metric').selectedOptions[0].textContent.toLowerCase()}`);
    const t = tip(box), fin = (v) => v != null && isFinite(v);
    const pathsSel = svg.append('g').selectAll('path').data(shapes).join('path').attr('d', (s) => path(s.geometry)).attr('fill-rule', 'evenodd')
      .attr('fill', (s) => (fin(s.v) ? C.color(s.v) : 'var(--cds-chart-muted)')).attr('fill-opacity', (s) => (fin(s.v) ? 1 : 0.35))
      .attr('stroke', 'var(--color-panel)').attr('stroke-width', M.lvl === 'nb' ? 1.25 : 0.6).style('cursor', 'pointer')
      .on('mousemove', function (e, s) {
        d3.select(this).attr('stroke', 'var(--color-fg)').attr('stroke-width', 1.75).raise();
        const [x, y] = d3.pointer(e, box), q = nbReturn(s.nb, o), lines = [['t', s.nb ? s.nb.name + (M.lvl === 'lsoa' ? ` · ${s.r.lsoa21}` : '') : s.r.lsoa21]];
        lines.push(['', `${$('#map-metric').selectedOptions[0].textContent}: ${fin(s.v) ? M.fmt(s.v) : '—'}`]);
        if (q) { lines.push(['', `Total return ${pct(q.total, 1)} (net yield ${pct(q.net, 1)} + growth ${pct(q.growth, 1)})`]); lines.push(['', `Typical ${gbpK(q.price)} · ${pts(q.above)} vs ${o.oppShort} (${pct(o.opp, 2)})`]); }
        lines.push(['', 'Click for its figures']); t.show(lines, x, y);
      })
      .on('mouseleave', function () { d3.select(this).attr('stroke', 'var(--color-panel)').attr('stroke-width', M.lvl === 'nb' ? 1.25 : 0.6); t.hide(); })
      .on('click', (e, s) => { if (s.ms) selectNb(s.ms, true); });
    cache.mapRef = { key, paths: pathsSel, shapes, C };
    const badge = $('#map-badge');
    if (key === 'above') {
      const n = vals.filter((v) => v > 0).length; badge.replaceChildren(); const b = document.createElement('b'); b.textContent = pct(o.opp, 2);
      badge.append(`${o.oppName[0].toUpperCase() + o.oppName.slice(1)} `, b, document.createElement('br'), `${n} of ${vals.length} neighbourhoods beat it`); badge.hidden = false;
    } else badge.hidden = true;
    if (M.lvl === 'lsoa') svg.append('g').style('pointer-events', 'none').selectAll('path').data(N.list.filter((r) => r.geometry)).join('path').attr('d', (r) => path(r.geometry))
      .attr('fill', 'none').attr('stroke', 'var(--color-fg-muted)').attr('stroke-width', 0.9).attr('stroke-opacity', 0.6);
    const sel = N.byId.get(state.nb);
    if (sel && sel.geometry) {
      svg.append('path').attr('d', path(sel.geometry)).attr('fill', 'none').attr('stroke', 'var(--color-fg)').attr('stroke-width', 2.5).style('pointer-events', 'none');
      const [lx, ly] = proj([num(sel.lon) * N.k, num(sel.lat)]);
      svg.append('text').attr('x', Math.max(4, Math.min(W - 4, lx))).attr('y', ly - 14).attr('text-anchor', lx < 90 ? 'start' : lx > W - 90 ? 'end' : 'middle')
        .attr('fill', 'var(--color-fg)').attr('stroke', 'var(--color-panel)').attr('stroke-width', 3).attr('paint-order', 'stroke').attr('stroke-linejoin', 'round')
        .style('font-size', 'var(--cds-font-size-caption)').style('font-weight', 'var(--cds-font-weight-medium)').style('pointer-events', 'none').text(sel.name);
    }
    const P = getPlaces();
    if (P && P.station) {
      const inside = (pt) => L.rows.some((r) => r.geometry.coordinates.some((poly) => ringContains(poly[0], pt)));
      const st = P.station.filter((s) => inside([s.lonN * L.k, s.latN])).map((s) => ({ ...s, xy: proj([s.lonN * L.k, s.latN]) }));
      svg.append('g').selectAll('rect').data(st).join('rect').attr('x', (s) => s.xy[0] - 4).attr('y', (s) => s.xy[1] - 4).attr('width', 8).attr('height', 8).attr('rx', 1.5)
        .attr('fill', 'var(--color-fg)').attr('stroke', 'var(--color-panel)').attr('stroke-width', 1.5)
        .on('mousemove', (e, s) => { const [x, y] = d3.pointer(e, box); t.show([['t', s.name + ' station']], x, y); }).on('mouseleave', () => t.hide());
    }
    if (state.last) { const [x, y] = proj([state.last.lon * L.k, state.last.lat]); svg.append('circle').attr('cx', x).attr('cy', y).attr('r', 8).attr('fill', 'none').attr('stroke', 'var(--color-fg)').attr('stroke-width', 2.5).style('pointer-events', 'none'); }
    const lg = $('#map-legend'); lg.replaceChildren();
    C.legend.forEach((l) => { const sp = document.createElement('span'), ic = document.createElement('i'); ic.style.background = l.c; sp.append(ic, l.t); lg.appendChild(sp); });
    const na = shapes.length - vals.length;
    if (na) { const sp = document.createElement('span'), ic = document.createElement('i'); ic.style.background = 'var(--cds-chart-muted)'; ic.style.opacity = '0.4'; sp.append(ic, `No figure (${na})`); lg.appendChild(sp); }
    let note = M.note(o);
    if (M.kind === 'div') {
      const isPct = /%$/.test(M.fmt(1)), half = isPct ? `${d3.format('.1f')(C.step / 2)} points` : M.fmt(C.step / 2).replace('+', '');
      note += M.zero ? ` Grey is within ${half} of zero.` : ` Grey is within ${half} of Doncaster's ${M.fmt(mid)}.`;
    }
    $('#map-note').textContent = note;
  };

  // ---------- best buy-to-let ----------
  state.btlIntro = 'waiting';
  onFirstView($('#btl-card'), () => { if (motionOK() && state.btlIntro === 'waiting' && !$('#areas').hidden) { state.btlIntro = 'pending'; safe('the buy-to-let ranking', renderBtl); } }, 0.25);
  const renderBtl = () => {
    const N = getNb(), o = nbOpts(); if (failed($('#btl-chart'), ['neighbourhoods', 'assumptions']) || !N || !o) return;
    const mx = num(val('#btl-max')), mn = num(val('#btl-min')), skipFlood = $('#btl-flood').checked, ranked = nbRanked(N, o);
    const data = ranked.filter((d) => (!isFinite(mx) || d.x.price <= mx) && (!isFinite(mn) || d.x.price >= mn) && (!skipFlood || !(num(d.r.flood_pct) >= 25)));
    const tn = o.type === 'A' ? 'all types of home' : TYPE_PLURAL[o.type];
    $('#btl-sub').textContent = `Ranked by total return${state.riskOn ? ' after the risk allowance' : ''} above ${o.oppName} (${pct(o.opp, 2)}), for ${tn}, with ${o.basis}-year price growth.${state.riskOn ? '' : ' Switch on the risk allowance to allow for tenant risk, flood, EPC upgrades and a downturn.'} ${data.length} of ${N.list.length} neighbourhoods shown. Past growth isn't a forecast, and a mortgage changes the picture: use the Investing tab for one property.`;
    // top five
    const top = $('#btl-top'); top.replaceChildren();
    const intro = state.btlIntro === 'pending' && motionOK();
    data.slice(0, 5).forEach((d, k) => {
      const li = document.createElement('li'), b = document.createElement('button');
      if (intro) { li.className = 'enter'; li.style.animationDelay = `${120 + k * 110}ms`; } b.type = 'button'; b.setAttribute('aria-current', String(d.r.msoa21 === state.nb));
      const s = (cls, text) => { const e = document.createElement('span'); e.className = cls; e.textContent = text; b.appendChild(e); return e; };
      s('rk', `${ordinal(d.rank)} of ${ranked.length}`); s('nm', d.r.name); const bv = s('bigv', pts(intro ? 0 : d.x.above)); s('muted', `above ${o.oppName}`);
      if (intro) { bv._v = 0; setTimeout(() => countTo(bv, d.x.above, (v) => pts(v), 900), 200 + k * 110); }
      s('ln', state.riskOn && d.x.rk ? `Total ${pct(d.x.total, 1)} = net yield ${pct(d.x.net, 1)} + growth ${pct(d.x.growth, 1)} − risk ${d3.format('.1f')(d.x.rk.total)}` : `Total ${pct(d.x.total, 1)} = net yield ${pct(d.x.net, 1)} + growth ${pct(d.x.growth, 1)}`);
      s('muted', `Typical ${gbpK(d.x.price)} · ${d3.format(',.0f')(num(d.r.sales_per_year))} sales a year`);
      const pl = document.createElement('span'); pl.className = 'pills';
      if (num(d.r.sales_3y) < 180) pill(pl, 'Fewer sales');
      if (num(d.r.flood_pct) >= 25) pill(pl, `Flood risk ${pct(num(d.r.flood_pct), 0)}`);
      if (num(d.r.epc_below_c_pct) >= 65) pill(pl, `EPC below C ${pct(num(d.r.epc_below_c_pct), 0)}`);
      if (d.r.licensing) pill(pl, 'Selective licensing');
      if (num(d.r.asb_rate) > 1.5 * num(N.D.asb_rate)) pill(pl, 'High anti-social behaviour');
      if (pl.childElementCount) b.appendChild(pl);
      b.addEventListener('click', () => selectNb(d.r.msoa21, true)); li.appendChild(b); top.appendChild(li);
    });
    if (!data.length) { const li = document.createElement('li'); li.className = 'muted'; li.textContent = 'No neighbourhood fits these filters.'; top.appendChild(li); }
    drawBtlChart(data, o, N, intro);
    if (intro) state.btlIntro = 'done';
    // table
    const S = state.btlSort, getv = (d, k) => (k === 'name' ? d.r.name : k in d.x ? d.x[k] : num(d.r[k]));
    const sorted = data.slice().sort((a, b) => { const x = getv(a, S.k), y = getv(b, S.k); if (typeof x === 'string') return S.dir * x.localeCompare(y); return S.dir * ((isFinite(x) ? x : -Infinity) - (isFinite(y) ? y : -Infinity)); });
    const table = $('#btl-table');
    $('#btl-th-price').dataset.field = o.type === 'A' ? 'median_price' : 'median_' + o.type; $('#btl-th-growth').dataset.field = `growth_${o.basis}y`;
    $('#btl-th-growth').querySelector('button').textContent = `Growth a year (${o.basis} yrs)`; $('#btl-th-above').textContent = `vs ${o.oppShort}`; $('#btl-th-above').title = `Total return minus ${o.oppName} (${pct(o.opp, 2)})`;
    table.querySelectorAll('th').forEach((th) => { const btn = th.querySelector('button'); if (btn) th.setAttribute('aria-sort', btn.dataset.k === S.k ? (S.dir > 0 ? 'ascending' : 'descending') : 'none'); });
    const tb = table.querySelector('tbody'); tb.replaceChildren();
    sorted.forEach((d) => {
      const tr = document.createElement('tr'), r = d.r; tr.dataset.key = r.msoa21; tr.setAttribute('aria-current', String(r.msoa21 === state.nb)); tr.tabIndex = 0;
      cell(tr, r.name); cell(tr, gbpK(d.x.price), 'r'); cell(tr, pct(d.x.gross, 1), 'r'); cell(tr, pct(d.x.net, 1), 'r'); cell(tr, pct(d.x.growth, 1), 'r'); cell(tr, pct(d.x.total, 1), 'r');
      cell(tr, pts(d.x.above), 'r'); cell(tr, isFinite(d.x.risk) ? `−${d3.format('.1f')(d.x.risk)}` : '—', 'r' + (state.riskOn ? '' : ' muted-cell')); cell(tr, sgn(num(r.peak_fall_pct), 0), 'r'); cell(tr, d3.format(',.0f')(num(r.sales_per_year)), 'r'); cell(tr, pct(num(r.private_rented_pct), 0), 'r');
      cell(tr, pct(num(r.epc_below_c_pct), 0), 'r'); cell(tr, pct(num(r.flood_pct), 0), 'r'); cell(tr, d3.format('.1f')(num(r.imd_score)), 'r'); cell(tr, d3.format('.1f')(num(r.asb_rate)), 'r');
      tr.addEventListener('click', () => selectNb(r.msoa21, true)); tr.addEventListener('keydown', (e) => { if (e.key === 'Enter') selectNb(r.msoa21, true); });
      if (intro && tb.childElementCount < 16) { tr.className = 'enter-fade'; tr.style.animationDelay = `${600 + tb.childElementCount * 35}ms`; }
      tb.appendChild(tr);
    });
    const xd = nbReturn(N.D, o);
    $('#btl-foot').textContent = `Doncaster overall: net yield ${pct(xd && xd.net, 1)}, growth ${pct(xd && xd.growth, 1)} a year, total ${pct(xd && xd.total, 1)} (${pts(xd && xd.above)} vs ${o.oppShort}). ` +
      'Rents are Doncaster-wide ONS averages, as no open source gives rents for smaller areas, so cheaper areas get higher yields and real local rents may differ. ' +
      'Growth figures carry an 80% range of about ±0.3 points a year (see each neighbourhood), so close ranks are a tie. Private renters are from Census 2021; EPC, flood and deprivation figures are homes-weighted from the smaller areas.';
  };
  const drawBtlChart = (data, o, N, intro) => {
    const box = $('#btl-chart'); fresh(box); if (!data.length) { $('#btl-legend').replaceChildren(); return; }
    const W = Math.max(300, box.clientWidth), H = 350, m = { t: 30, r: 16, b: 40, l: 48 };   // the y label sits above the plot
    const xd = nbReturn(N.D, o), all = data.concat(xd ? [{ x: xd }] : []);
    const x = d3.scaleLinear(d3.extent(all, (d) => d.x.px), [m.l, W - m.r]).nice(), y = d3.scaleLinear(d3.extent(all, (d) => d.x.py), [H - m.b, m.t]).nice();
    const rr = d3.scaleSqrt([0, d3.max(data, (d) => num(d.r.sales_per_year))], [3, 13]);
    const svg = d3.select(box).append('svg').attr('width', '100%').attr('viewBox', `0 0 ${W} ${H}`).attr('role', 'img').attr('aria-label', 'Net yield against price growth by neighbourhood');
    const gx = svg.append('g').attr('transform', `translate(0,${H - m.b})`).call(d3.axisBottom(x).ticks(Math.max(3, Math.floor((W - m.l - m.r) / 70))).tickFormat((v) => d3.format('.1f')(v) + '%').tickSize(-(H - m.t - m.b))); cleanAxis(gx); gx.select('.domain').remove();
    const gy = svg.append('g').attr('transform', `translate(${m.l},0)`).call(d3.axisLeft(y).ticks(5).tickFormat((v) => d3.format('.1f')(v) + '%').tickSize(-(W - m.l - m.r))); cleanAxis(gy); gy.select('.domain').remove();
    svg.append('text').attr('x', W - m.r).attr('y', H - 6).attr('text-anchor', 'end').attr('fill', 'var(--color-fg-muted)').style('font-size', 'var(--cds-font-size-caption)').text(W < 480 ? `Growth a year, ${o.basis} yrs${state.riskOn ? ', less downturn' : ''} →` : `Price growth a year, last ${o.basis} years${state.riskOn ? ', less the downturn allowance' : ''} →`);
    svg.append('text').attr('x', m.l - 40).attr('y', 14).attr('fill', 'var(--color-fg-muted)').style('font-size', 'var(--cds-font-size-caption)').text(state.riskOn ? '↑ Net yield, less tenant, flood and EPC allowances' : '↑ Net yield');
    // where net yield + growth = the opportunity cost, and = Doncaster's total
    const clipId = 'btl-clip-' + Math.random().toString(36).slice(2, 8);
    svg.append('clipPath').attr('id', clipId).append('rect').attr('x', m.l).attr('y', m.t).attr('width', W - m.l - m.r).attr('height', H - m.t - m.b);
    // lines of equal total return (net yield + growth): the opportunity cost, and Doncaster's; is each in view?
    const iso = (tot, dash_) => {
      const [x0, x1] = x.domain(), [ya, yb] = y.domain(), lo = Math.max(x0, tot - yb), hi = Math.min(x1, tot - ya);
      if (!(hi > lo + (x1 - x0) * 0.08)) return false;
      const seg = svg.append('g').attr('clip-path', `url(#${clipId})`);
      seg.append('line').attr('x1', x(x0)).attr('y1', y(tot - x0)).attr('x2', x(x1)).attr('y2', y(tot - x1)).attr('stroke', 'var(--cds-chart-reference)').attr('stroke-width', 1.5).attr('stroke-dasharray', dash_);
      return true;
    };
    const oppSeen = iso(o.opp, '6 4'), dSeen = xd ? iso(xd.total, '2 3') : false;
    const C = mapClasses(NB_MAP.above, data.map((d) => d.x.above), 0), tp = tip(box), sel = state.nb;
    // circles start where they were (or, the first time, at Doncaster) and glide to their places
    const prev = cache.btlW === W ? cache.btlPos || new Map() : new Map(), home = xd ? [x(xd.px), y(xd.py)] : [(m.l + W - m.r) / 2, (m.t + H - m.b) / 2];
    const glide = motionOK() && (intro || prev.size > 0);
    const circ = svg.append('g').selectAll('circle').data(data.slice().sort((a, b) => num(b.r.sales_per_year) - num(a.r.sales_per_year))).join('circle')
      .attr('cx', (d) => (intro ? home[0] : (prev.get(d.r.msoa21) || [x(d.x.px)])[0])).attr('cy', (d) => (intro ? home[1] : (prev.get(d.r.msoa21) || [0, y(d.x.py)])[1]))
      .attr('r', (d) => (intro ? 0 : rr(num(d.r.sales_per_year))))
      .attr('fill', (d) => C.color(d.x.above)).attr('stroke', (d) => (d.r.msoa21 === sel ? 'var(--color-fg)' : 'var(--color-panel)')).attr('stroke-width', (d) => (d.r.msoa21 === sel ? 2.5 : 1.5)).style('cursor', 'pointer')
      .on('mousemove', (e, d) => { const [px, py] = d3.pointer(e, box); tp.show([['t', `${ordinal(d.rank)} · ${d.r.name}`], ['', state.riskOn && d.x.rk ? `Net yield ${pct(d.x.net, 1)} + growth ${pct(d.x.growth, 1)} − risk ${d3.format('.1f')(d.x.rk.total)} = ${pct(d.x.total, 1)}` : `Net yield ${pct(d.x.net, 1)} + growth ${pct(d.x.growth, 1)} = ${pct(d.x.total, 1)}`], ['', `${pts(d.x.above)} vs ${o.oppShort} (${pct(o.opp, 2)}) · typical ${gbpK(d.x.price)}`], ['', `${d3.format(',.0f')(num(d.r.sales_per_year))} sales a year`]], px, py); })
      .on('mouseleave', () => tp.hide()).on('click', (e, d) => selectNb(d.r.msoa21, true));
    const end = (s) => s.attr('cx', (d) => x(d.x.px)).attr('cy', (d) => y(d.x.py)).attr('r', (d) => rr(num(d.r.sales_per_year)));
    if (glide) end(circ.transition().delay((d) => (intro ? 250 + d.rank * 30 : 0)).duration(intro ? 800 : 650).ease(d3.easeCubicInOut)); else end(circ);
    cache.btlW = W; cache.btlPos = new Map(data.map((d) => [d.r.msoa21, [x(d.x.px), y(d.x.py)]]));
    if (xd) svg.append('circle').attr('cx', x(xd.px)).attr('cy', y(xd.py)).attr('r', 6).attr('fill', 'none').attr('stroke', 'var(--color-fg)').attr('stroke-width', 2).style('pointer-events', 'none');
    // labels: the top three and the selected one, nudged apart
    const lab = data.slice(0, 3).concat(data.filter((d) => d.r.msoa21 === sel && d.rank > 3));
    if (xd) lab.push({ r: { name: 'Doncaster' }, x: xd, ring: true });
    const placed = [];
    lab.forEach((d) => {
      const cx = x(d.x.px), cy = y(d.x.py), off = d.ring ? 9 : rr(num(d.r.sales_per_year)) + 4; let ly = cy;
      placed.forEach((p) => { if (Math.abs(p - ly) < 13) ly = p + 13; }); placed.push(ly);
      const right = cx < W - 150;
      const lt = svg.append('text').attr('x', right ? cx + off : cx - off).attr('y', ly).attr('dy', '0.35em').attr('text-anchor', right ? 'start' : 'end')
        .attr('fill', 'var(--color-fg)').attr('stroke', 'var(--color-panel)').attr('stroke-width', 3).attr('paint-order', 'stroke').attr('stroke-linejoin', 'round')
        .style('font-size', 'var(--cds-font-size-caption)').style('pointer-events', 'none').text(d.r.name);
      if (glide) lt.attr('opacity', 0).transition().delay(intro ? 1500 : 500).duration(350).attr('opacity', 1);
    });
    const allAbove = data.every((d) => d.x.above > 0), allBelow = data.every((d) => d.x.above < 0);
    $('#btl-chart-note').textContent = `Each circle is a neighbourhood, sized by sales a year and coloured by its return above ${o.oppName}. Up and to the right is better. Along a line, net yield plus growth is the same.` +
      (allAbove ? ` Every neighbourhood shown beats ${o.oppName}${oppSeen ? '' : ', so its line is below the chart'}.` : allBelow ? ` None of these beats ${o.oppName}${oppSeen ? '' : ', so its line is above the chart'}.` : '');
    const lg = $('#btl-legend'); lg.replaceChildren();
    const lineKey = (dashes, text) => { const sp = document.createElement('span'), sv = document.createElementNS('http://www.w3.org/2000/svg', 'svg'); sv.setAttribute('width', '22'); sv.setAttribute('height', '10');
      const ln = document.createElementNS('http://www.w3.org/2000/svg', 'line'); [['x1', 0], ['y1', 5], ['x2', 22], ['y2', 5], ['stroke', 'var(--cds-chart-reference)'], ['stroke-width', 1.5], ['stroke-dasharray', dashes]].forEach(([k, v]) => ln.setAttribute(k, v));
      sv.appendChild(ln); sp.append(sv, text); lg.appendChild(sp); };
    if (oppSeen) lineKey('6 4', `Total return = ${o.oppName} (${pct(o.opp, 2)})`);
    if (dSeen) lineKey('2 3', `Total return = Doncaster (${pct(xd.total, 1)})`);
    const used = new Set(data.map((d) => C.color(d.x.above)));
    C.legend.filter((l) => used.has(l.c)).forEach((l) => { const sp = document.createElement('span'), ic = document.createElement('i'); ic.style.background = l.c; sp.append(ic, l.t); lg.appendChild(sp); });
    const ring = document.createElement('span'), ri = document.createElement('i'); ri.style.cssText = 'background:none;border:2px solid var(--color-fg);border-radius:50%'; ring.append(ri, 'Doncaster'); lg.appendChild(ring);
  };

  // ---------- Prices since 1995: a time-lapse over a chosen period ----------
  // the map shows each neighbourhood's growth over the period against Doncaster's (or its change in each year); the bars race
  // growth since the period's start; Doncaster's line draws itself, and dragging across it picks the period
  const LAPSE_BR = [-8, -3, -1, 1, 5, 15];
  const LAPSE_LAB = ['Fell over 8%', 'Fell 3% to 8%', 'Fell 1% to 3%', 'Within 1%', 'Rose 1% to 5%', 'Rose 5% to 15%', 'Rose over 15%'];
  const LAPSE_ROWS = 10, LAPSE_RH = 24;
  const lapse = { t: null, playing: false, raf: null, last: 0, settle: 0, built: null, autoplayed: false, from: null, to: null, mode: 'growth' };
  const binTok = (br, c) => (isFinite(c) ? `var(--cds-chart-diverging-${7 - d3.bisectRight(br, c)})` : 'var(--cds-chart-muted)');
  const lapseTok = (c) => binTok(LAPSE_BR, c);
  // seven bins centred on Doncaster's growth, spaced by how much the neighbourhoods differ
  const growthBins = (vals, c) => {
    const sd = Math.max(0.5, d3.deviation(vals) || 0), d = sd < 4 ? 1 : 0, k = Math.pow(10, d);
    const br = [-1.5, -0.75, -0.25, 0.25, 0.75, 1.5].map((m) => Math.round((c + m * sd) * k) / k);
    for (let j = 1; j < br.length; j++) if (br[j] <= br[j - 1]) br[j] = br[j - 1] + 1 / k;
    const f = (x) => sgn(x, d), lab = [`Under ${f(br[0])}`, ...br.slice(0, -1).map((v, j) => `${f(v)} to ${f(br[j + 1])}`), `Over ${f(br[5])}`];
    lab[3] += ' (like Doncaster)';
    return { br, lab };
  };
  const lapseLegend = (labels, title) => {
    const lg = $('#lapse-legend'); lg.replaceChildren();
    if (title) { const h = document.createElement('span'); h.textContent = title; lg.appendChild(h); }
    labels.forEach((x, k) => { const sp = document.createElement('span'), ic = document.createElement('i'); ic.style.background = `var(--cds-chart-diverging-${7 - k})`; sp.append(ic, x); lg.appendChild(sp); });
  };
  const getLapse = (N) => {
    if (cache.lapse) return cache.lapse;
    const years = (N.idx.get(LA_CODE) || []).map((p) => p.year), series = new Map();
    [...N.list, N.D].forEach((r) => {
      const by = new Map((N.idx.get(r.msoa21) || []).map((p) => [p.year, p.v])), v = years.map((y) => by.get(y));
      series.set(r.msoa21, { r, v, chg: v.map((x, i) => (i ? 100 * (x / v[i - 1] - 1) : NaN)) });
    });
    return (cache.lapse = { years, y0: years[0], y1: years.at(-1), series });
  };
  // growth from the period's start (index iF) to index i plus a fraction f of the next year
  const lapseGrow = (s, iF, i, f) => { const n = s.v.length, v = s.v[i] + (f ? (s.v[Math.min(i + 1, n - 1)] - s.v[i]) * f : 0); return 100 * (v / s.v[iF] - 1); };
  const buildLapse = () => {
    const N = getNb(), L = getLsoa(); if (!N || !L) return null;
    const Z = getLapse(N); if (Z.years.length < 3) return null;
    if (lapse.from == null || lapse.from < Z.y0 || lapse.to > Z.y1) { lapse.from = Z.y0; lapse.to = Z.y1; }
    const mapBox = $('#lapse-map'), raceBox = $('#lapse-race'), lineBox = $('#lapse-line');
    const W = Math.max(280, mapBox.clientWidth), RW = Math.max(240, raceBox.clientWidth), LW = Math.max(280, lineBox.clientWidth), key = `${W}|${RW}|${LW}|${isDark()}`;   // rebuilt for a new width or theme
    if (lapse.built && lapse.built.key === key && lapse.built.N === N) return lapse.built;
    [mapBox, raceBox, lineBox].forEach(fresh);
    const B = { key, N, Z, lastY: null, ry: new Map(), xmax: null };
    // map
    const H = Math.round(Math.min(440, Math.max(260, W * 0.8)));
    B.proj = fitShapes(L.rows, W, H, 6);
    const msvg = d3.select(mapBox).append('svg').attr('width', '100%').attr('viewBox', `0 0 ${W} ${H}`).attr('role', 'img').attr('aria-label', 'Map of price growth by neighbourhood');
    const mt = tip(mapBox);
    B.paths = msvg.append('g').selectAll('path').data(N.list.filter((r) => r.geometry)).join('path').attr('d', (r) => shapePath(B.proj, r.geometry)).attr('fill-rule', 'evenodd')
      .attr('fill', 'var(--cds-chart-diverging-4)').attr('stroke', 'var(--color-panel)').attr('stroke-width', 1).style('cursor', 'pointer')
      .on('mousemove', function (e, r) {
        d3.select(this).attr('stroke', 'var(--color-fg)').attr('stroke-width', 1.75).raise(); B.selPath.raise();
        const s = Z.series.get(r.msoa21), i = B.i ?? Z.years.length - 1, iF = lapse.from - Z.y0, [x, y] = d3.pointer(e, mapBox);
        mt.show([['t', r.name], ['', `${lapse.from} to ${Z.years[i]}: ${sgn(lapseGrow(s, iF, i, 0), 0)}`], ['', `Year to August ${Z.years[i]}: ${sgn(s.chg[i], 1)}`], ['', `Today's typical home was worth ${gbpK(num(r.median_price) * s.v[i] / 100)}`]], x, y);
      })
      .on('mouseleave', function () { d3.select(this).attr('stroke', 'var(--color-panel)').attr('stroke-width', 1); mt.hide(); })
      .on('click', (e, r) => selectNb(r.msoa21, false));
    B.selPath = msvg.append('path').attr('fill', 'none').attr('stroke', 'var(--color-fg)').attr('stroke-width', 2.25).style('pointer-events', 'none');
    // race
    const RT = 2, RH_ = LAPSE_ROWS * LAPSE_RH + RT + 20;
    B.RW = RW; B.LBL = Math.round(Math.min(178, RW * 0.44));
    const rsvg = d3.select(raceBox).append('svg').attr('width', '100%').attr('viewBox', `0 0 ${RW} ${RH_}`).attr('role', 'img').attr('aria-label', 'Neighbourhoods ranked by price growth over the period');
    const clipId = 'lapse-clip-' + Math.random().toString(36).slice(2, 8);
    rsvg.append('clipPath').attr('id', clipId).append('rect').attr('x', 0).attr('y', 0).attr('width', RW).attr('height', LAPSE_ROWS * LAPSE_RH + RT);
    const rg = rsvg.append('g').attr('clip-path', `url(#${clipId})`);
    B.bars = rg.selectAll('g').data(N.list).join('g').attr('transform', `translate(0,${RH_})`);
    B.bars.append('rect').attr('class', 'b').attr('y', 3).attr('height', LAPSE_RH - 7).attr('rx', 3);
    B.bars.append('text').attr('class', 'n').attr('x', B.LBL - 8).attr('y', LAPSE_RH / 2 + 1).attr('dy', '0.32em').attr('text-anchor', 'end')
      .attr('fill', 'var(--color-fg)').style('font-size', 'var(--cds-font-size-caption)').text((r) => r.name).each(function () { fitText(this, B.LBL - 12); });
    B.bars.append('text').attr('class', 'v').attr('y', LAPSE_RH / 2 + 1).attr('dy', '0.32em').attr('fill', 'var(--color-fg-muted)').style('font-size', 'var(--cds-font-size-caption)').style('font-variant-numeric', 'tabular-nums');
    B.donRule = rsvg.append('line').attr('y1', 0).attr('y2', LAPSE_ROWS * LAPSE_RH + RT).attr('stroke', 'var(--cds-chart-reference)').attr('stroke-width', 1.25).attr('stroke-dasharray', '3 3');
    B.donLab = rsvg.append('text').attr('y', RH_ - 4).attr('text-anchor', 'middle').attr('fill', 'var(--color-fg-muted)').style('font-size', 'var(--cds-font-size-caption)');
    // Doncaster's line
    const LH = 136, lm = { t: 26, r: 14, b: 22, l: 46 }, D = N.D, ds = Z.series.get(LA_CODE), base = num(D.median_price);
    B.dv = ds.v.map((v) => base * v / 100);
    B.lx = d3.scaleLinear([Z.y0, Z.y1], [lm.l, LW - lm.r]); B.ly = d3.scaleLinear([0, d3.max(B.dv) * 1.12], [LH - lm.b, lm.t]);
    const lsvg = d3.select(lineBox).append('svg').attr('width', '100%').attr('viewBox', `0 0 ${LW} ${LH}`).attr('role', 'img').attr('aria-label', "Value of Doncaster's typical home since 1995; drag across it to choose a period");
    const gx = lsvg.append('g').attr('transform', `translate(0,${LH - lm.b})`).call(d3.axisBottom(B.lx).ticks(Math.max(3, Math.min(8, Math.floor(LW / 90)))).tickFormat(d3.format('d')).tickSizeOuter(0)); cleanAxis(gx);
    const gy = lsvg.append('g').attr('transform', `translate(${lm.l},0)`).call(d3.axisLeft(B.ly).ticks(3).tickFormat((v) => gbpK(v)).tickSize(-(LW - lm.l - lm.r))); cleanAxis(gy); gy.select('.domain').remove();
    const lclip = 'lapse-lclip-' + Math.random().toString(36).slice(2, 8);
    B.lclip = lsvg.append('clipPath').attr('id', lclip).append('rect').attr('x', 0).attr('y', 0).attr('height', LH).attr('width', LW);
    const pts = Z.years.map((y, i) => [B.lx(y), B.ly(B.dv[i])]);
    lsvg.append('path').attr('clip-path', `url(#${lclip})`).attr('d', d3.area().x((p) => p[0]).y0(B.ly(0)).y1((p) => p[1])(pts)).attr('fill', dash.colors[0]).attr('fill-opacity', 0.12);
    lsvg.append('path').attr('clip-path', `url(#${lclip})`).attr('d', d3.line()(pts)).attr('fill', 'none').attr('stroke', dash.colors[0]).attr('stroke-width', 2).attr('stroke-linejoin', 'round').attr('stroke-linecap', 'round');
    B.ltitle = lsvg.append('text').attr('x', lm.l + 2).attr('y', 12).attr('fill', 'var(--color-fg-muted)').style('font-size', 'var(--cds-font-size-caption)');
    // moments, from the data: the boom year, the 2008 peak, the low and the recovery
    const iBoom = d3.maxIndex(ds.chg), mk = [];
    if (iBoom > 0) mk.push({ y: Z.years[iBoom], t: `${Z.years[iBoom]} boom: ${sgn(ds.chg[iBoom], 0)} in a year`, up: true });
    if (isFinite(num(D.peak_year))) mk.push({ y: num(D.peak_year), t: `${D.peak_year} peak`, up: true });
    if (isFinite(num(D.trough_year))) mk.push({ y: num(D.trough_year), t: `${D.trough_year} low, ${sgn(num(D.peak_fall_pct), 0)}`, up: false });
    if (isFinite(num(D.recovered_year))) mk.push({ y: num(D.recovered_year), t: `Back to the peak by ${D.recovered_year}`, up: false });
    B.marks = lsvg.append('g').selectAll('g').data(mk).join('g').style('pointer-events', 'none');
    B.marks.append('circle').attr('cx', (d) => B.lx(d.y)).attr('cy', (d) => B.ly(B.dv[Z.years.indexOf(d.y)])).attr('r', 3.5).attr('fill', 'var(--color-fg)').attr('stroke', 'var(--color-panel)').attr('stroke-width', 1.5);
    B.marks.append('text').attr('x', (d) => B.lx(d.y)).attr('y', (d) => B.ly(B.dv[Z.years.indexOf(d.y)]) + (d.up ? -9 : 15)).attr('text-anchor', (d) => (B.lx(d.y) > LW - 150 ? 'end' : B.lx(d.y) < lm.l + 60 ? 'start' : 'middle'))
      .attr('fill', 'var(--color-fg)').attr('stroke', 'var(--color-panel)').attr('stroke-width', 3).attr('paint-order', 'stroke').style('font-size', 'var(--cds-font-size-caption)').text((d) => d.t);
    B.rule = lsvg.append('line').attr('y1', lm.t).attr('y2', LH - lm.b).attr('stroke', 'var(--color-fg)').attr('stroke-width', 1).style('pointer-events', 'none');
    B.dot = lsvg.append('circle').attr('r', 4.5).attr('fill', dash.colors[0]).attr('stroke', 'var(--color-panel)').attr('stroke-width', 2).style('pointer-events', 'none');
    // drag across the line to choose the period; a click picks a year
    B.brush = d3.brushX().extent([[lm.l, lm.t - 4], [LW - lm.r, LH - lm.b]]).touchable(() => false).on('end', (e) => {
      if (!e.sourceEvent) return;
      const pick = () => { const [px] = d3.pointer(e.sourceEvent, lsvg.node()); if (isFinite(px)) { lapsePause(); lapseFrame(Math.round(B.lx.invert(px))); setLapseBtn(); } syncBrush(); };
      if (!e.selection) return pick();                                  // a click, not a drag: pick that year
      const a = Math.max(Z.y0, Math.min(Z.y1 - 1, Math.round(B.lx.invert(e.selection[0])))), b = Math.max(a + 1, Math.min(Z.y1, Math.round(B.lx.invert(e.selection[1]))));
      if (a === lapse.from && b === lapse.to) return pick();             // a click inside the period
      setLapseWindow(a, b);
    });
    B.gBrush = lsvg.append('g').attr('class', 'lapse-brush').call(B.brush);
    // the year pickers
    ['#lapse-from', '#lapse-to'].forEach((sl) => { $(sl).min = String(Z.y0); $(sl).max = String(Z.y1); });
    const pre = $('#lapse-presets'); pre.replaceChildren();
    [[`Since ${Z.y0}`, Z.y0, Z.y1], ['Since 2000', 2000, Z.y1], ['20 years', Z.y1 - 20, Z.y1], ['10 years', Z.y1 - 10, Z.y1], ['5 years', Z.y1 - 5, Z.y1], ['2007 to 2013', 2007, 2013]]
      .filter(([, a, b]) => a >= Z.y0 && b <= Z.y1 && a < b).forEach(([label, a, b]) => {
        const btn = document.createElement('button'); btn.type = 'button'; btn.textContent = label; btn.dataset.a = String(a); btn.dataset.b = String(b);
        btn.addEventListener('click', () => setLapseWindow(a, b)); pre.appendChild(btn);
      });
    $('#lapse-note').textContent = `Today's typical price in each neighbourhood moved back along its repeat-sales index, so a change in the mix of homes sold doesn't move it. Years run September to August; ${Z.y0} is January to August. The shaded box on the line is the period; on a computer you can also drag across the line to set it.`;
    lapse.built = B; syncWindowUI(); return B;
  };
  const syncBrush = () => { const B = lapse.built; if (!B) return; const full = lapse.from === B.Z.y0 && lapse.to === B.Z.y1; B.gBrush.call(B.brush.move, full ? null : [B.lx(lapse.from), B.lx(lapse.to)]); };
  const syncWindowUI = () => {
    const B = lapse.built; if (!B) return;
    const { Z } = B, a = lapse.from, b = lapse.to, full = a === Z.y0 && b === Z.y1, g = 100 * (B.dv[b - Z.y0] / B.dv[a - Z.y0] - 1);
    $('#lapse-from').value = String(a); $('#lapse-to').value = String(b); $('#lapse-from').style.zIndex = a > Z.y1 - 3 ? '3' : '1';
    $('#lapse-from').setAttribute('aria-valuetext', `From ${a}`); $('#lapse-to').setAttribute('aria-valuetext', `To ${b}`);
    const span = Z.y1 - Z.y0, fl = $('#lapse-fill'); fl.style.left = `calc(11px + (100% - 22px) * ${(a - Z.y0) / span})`; fl.style.width = `calc((100% - 22px) * ${(b - a) / span})`;
    $('#lapse-period-t').textContent = `${a} to ${b}`;
    document.querySelectorAll('#lapse-presets button').forEach((x) => x.setAttribute('aria-pressed', String(Number(x.dataset.a) === a && Number(x.dataset.b) === b)));
    $('#lapse-y').min = String(a + 1); $('#lapse-y').max = String(b);
    $('#lapse-race-h').textContent = `Growth ${a} to ${b}, top 10`;
    $('#lapse-y').closest('label').hidden = lapse.mode !== 'year';
    B.ltitle.text(`Doncaster: value of today's typical home${full ? '' : ` · ${a} to ${b}: ${sgn(g, 0)}`}`);
    syncBrush(); setLapseBtn();
  };
  const setLapseWindow = (a, b) => {
    const B = lapse.built; if (!B) return;
    lapse.from = a; lapse.to = b; lapsePause(); B.ry.clear(); B.xmax = null; B.lastY = null;
    syncWindowUI(); lapseFrame(b); setLapseBtn();
  };
  const lapseFrame = (t) => {
    const B = lapse.built; if (!B) return;
    const { Z, N } = B, n = Z.years.length, a = lapse.from, bEnd = lapse.to, iF = a - Z.y0;
    t = Math.max(a + 1, Math.min(bEnd, t)); lapse.t = t;
    const i = Math.min(n - 1, Math.floor(t - Z.y0)), f = i < n - 1 && t < bEnd ? t - Z.y0 - i : 0, Y = Z.years[i]; B.i = i;
    const ds = Z.series.get(LA_CODE), smooth = lapse.playing && motionOK();
    if (B.lastY !== Y) {
      B.lastY = Y;
      $('#lapse-big').textContent = String(Y);
      $('#lapse-y').value = String(Y); $('#lapse-y').setAttribute('aria-valuetext', `Year to August ${Y}`);
      if (lapse.mode === 'year') {
        B.paths.attr('fill', (r) => lapseTok(Z.series.get(r.msoa21).chg[i]));
        lapseLegend(LAPSE_LAB, `Year to August ${Y}:`);
        const up = N.list.filter((r) => Z.series.get(r.msoa21).chg[i] > 0).length;
        $('#lapse-don').textContent = `Year to August ${Y}: Doncaster ${sgn(ds.chg[i], 1)}. Today's typical home would have been worth ${gbpK(B.dv[i])}, ${sgn(lapseGrow(ds, iF, i, 0), 0)} on ${a}.`;
        $('#lapse-count').textContent = up === N.list.length ? `Prices rose in all ${up} neighbourhoods.` : up === 0 ? `Prices fell in all ${N.list.length} neighbourhoods.` : `Prices rose in ${up} of ${N.list.length} neighbourhoods and fell in ${N.list.length - up}.`;
      } else {
        const gr = N.list.map((r) => ({ r, g: lapseGrow(Z.series.get(r.msoa21), iF, i, 0) })).filter((d) => isFinite(d.g)), byG = new Map(gr.map((d) => [d.r.msoa21, d.g]));
        const gD = lapseGrow(ds, iF, i, 0), G = growthBins(gr.map((d) => d.g), gD);
        B.paths.attr('fill', (r) => binTok(G.br, byG.get(r.msoa21)));
        lapseLegend(G.lab, `Growth ${a} to ${Y}:`);
        const hi = d3.greatest(gr, (d) => d.g), lo = d3.least(gr, (d) => d.g), up = gr.filter((d) => d.g > 0).length;
        $('#lapse-don').textContent = `${a} to ${Y}: Doncaster ${sgn(gD, 0)}, today's typical home going from ${gbpK(B.dv[iF])} to ${gbpK(B.dv[i])}. Year to August ${Y}: ${sgn(ds.chg[i], 1)}.`;
        $('#lapse-count').textContent = `${up === gr.length ? `Prices rose in all ${up} neighbourhoods` : up === 0 ? `Prices fell in all ${gr.length} neighbourhoods` : `Prices rose in ${up} of ${gr.length} neighbourhoods`} over the period. Strongest: ${hi.r.name} (${sgn(hi.g, 0)}); weakest: ${lo.r.name} (${sgn(lo.g, 0)}).`;
      }
    }
    // race: growth since the period's start, between years when playing
    const vals = N.list.map((r) => ({ r, v: lapseGrow(Z.series.get(r.msoa21), iF, i, f) })).filter((d) => isFinite(d.v)).sort((p, q) => q.v - p.v), dv = lapseGrow(ds, iF, i, f);
    const target = Math.max(dv, vals[0].v, 1) * 1.08;
    B.xmax = smooth && B.xmax != null ? B.xmax + (target - B.xmax) * 0.12 : target;
    const xs = d3.scaleLinear([Math.min(0, d3.min(vals, (d) => d.v), dv), B.xmax], [B.LBL, B.RW - 54]), x0 = xs(0);
    vals.forEach((d, k) => { const tgt = k < LAPSE_ROWS + 1 ? 2 + k * LAPSE_RH : 2 + (LAPSE_ROWS + 1) * LAPSE_RH; const p = B.ry.get(d.r.msoa21); B.ry.set(d.r.msoa21, smooth && p != null ? p + (tgt - p) * 0.16 : tgt); d.y = B.ry.get(d.r.msoa21); });
    const byMs = new Map(vals.map((d) => [d.r.msoa21, d])), sel = state.nb, yOf = (r) => (byMs.get(r.msoa21) || { y: 2 + (LAPSE_ROWS + 1) * LAPSE_RH, v: 0 });
    B.bars.attr('transform', (r) => `translate(0,${yOf(r).y})`);
    B.bars.select('rect.b').attr('x', (r) => Math.min(x0, xs(yOf(r).v))).attr('width', (r) => Math.max(1, Math.abs(xs(yOf(r).v) - x0)))
      .attr('fill', (r) => (r.msoa21 === sel ? 'var(--color-fg)' : dash.colors[0]));
    B.bars.select('text.n').style('font-weight', (r) => (r.msoa21 === sel ? 'var(--cds-font-weight-medium)' : null));
    B.bars.select('text.v').attr('x', (r) => Math.max(x0, xs(yOf(r).v)) + 5).text((r) => sgn(yOf(r).v, 0));
    B.donRule.attr('x1', xs(dv)).attr('x2', xs(dv)); B.donLab.attr('x', Math.max(B.LBL + 40, Math.min(B.RW - 60, xs(dv)))).text(`Doncaster ${sgn(dv, 0)}`);
    // Doncaster's line, drawn up to now
    const xt = B.lx(Z.y0 + i + f), vt = B.dv[i] + ((B.dv[Math.min(i + 1, n - 1)] - B.dv[i]) * f);
    B.rule.attr('x1', xt).attr('x2', xt); B.dot.attr('cx', xt).attr('cy', B.ly(vt));
  };
  const setLapseBtn = () => {
    const b = $('#lapse-play'), B = lapse.built, atEnd = B && lapse.t >= lapse.to, span = B ? `${lapse.from} to ${lapse.to}` : '1995 to 2026';
    b.setAttribute('aria-pressed', String(lapse.playing));
    $('#lapse-play-t').textContent = lapse.playing ? 'Pause' : atEnd ? (lapse.played ? `Replay ${span}` : `Play ${span}`) : 'Play';
  };
  const lapsePause = () => { lapse.playing = false; if (lapse.raf) cancelAnimationFrame(lapse.raf); lapse.raf = null; setLapseBtn(); };
  const lapsePlay = () => {
    const B = lapse.built || buildLapse(); if (!B) return;
    if (lapse.t == null || lapse.t >= lapse.to) { lapse.t = lapse.from + 1; B.ry.clear(); B.xmax = null; lapse.playing = false; lapseFrame(lapse.t); }
    lapse.playing = true; lapse.played = true; lapse.settle = 0; lapse.last = performance.now(); setLapseBtn();
    const step = (now) => {
      if (!lapse.playing) return;
      if ($('#areas').hidden) { lapsePause(); lapseFrame(lapse.to); setLapseBtn(); return; }   // left the tab: finish at the last year
      const dt = Math.min(0.1, (now - lapse.last) / 1000); lapse.last = now;
      const speed = lapse.t > 2007.5 && lapse.t < 2010 ? 0.6 : 1.3;          // slower through the crash
      if (lapse.t < lapse.to) lapseFrame(Math.min(lapse.to, lapse.t + dt * speed)); else { lapse.settle += 1; lapseFrame(lapse.to); }
      if (lapse.settle > 45) { lapse.playing = false; lapseFrame(lapse.to); setLapseBtn(); return; }
      lapse.raf = requestAnimationFrame(step);
    };
    lapse.raf = requestAnimationFrame(step);
  };
  $('#lapse-play').addEventListener('click', () => (lapse.playing ? lapsePause() : lapsePlay()));
  $('#lapse-y').addEventListener('input', (e) => { lapsePause(); lapseFrame(Number(e.target.value)); setLapseBtn(); });
  // the two handles of the period slider: each keeps at least a year from the other
  $('#lapse-from').addEventListener('input', (e) => { const B = lapse.built; if (!B) return; let a = Number(e.target.value); if (a > B.Z.y1 - 1) a = B.Z.y1 - 1; const b = Math.max(lapse.to, a + 1); if (a !== lapse.from || b !== lapse.to) setLapseWindow(a, b); else syncWindowUI(); });
  $('#lapse-to').addEventListener('input', (e) => { const B = lapse.built; if (!B) return; let b = Number(e.target.value); if (b < B.Z.y0 + 1) b = B.Z.y0 + 1; const a = Math.min(lapse.from, b - 1); if (a !== lapse.from || b !== lapse.to) setLapseWindow(a, b); else syncWindowUI(); });
  document.querySelectorAll('#lapse-mode button').forEach((btn) => btn.addEventListener('click', () => {
    lapse.mode = btn.dataset.m; document.querySelectorAll('#lapse-mode button').forEach((x) => x.setAttribute('aria-pressed', String(x === btn)));
    if (lapse.built) { lapsePause(); lapse.built.lastY = null; syncWindowUI(); lapseFrame(lapse.mode === 'growth' ? lapse.to : (lapse.t ?? lapse.to)); }
  }));
  const renderLapse = () => {
    if (failed($('#lapse-map'), ['neighbourhoods', 'nbhd_index', 'lsoa_map'])) return;
    const N = getNb(); if (!N || !getLsoa()) return;
    const B = buildLapse(); if (!B) return;
    if (lapse.t == null) lapse.t = lapse.to;
    const sel = N.byId.get(state.nb); B.selPath.attr('d', sel && sel.geometry ? shapePath(B.proj, sel.geometry) : null);
    if (!lapse.playing) { B.lastY = null; lapseFrame(lapse.t); setLapseBtn(); }
  };

  // ---------- the map's hurdle rate: neighbourhoods turn from red to blue as the rate elsewhere falls ----------
  let sweepRaf = null;
  const runSweep = () => {
    const N = getNb(), o = nbOpts(); if (!N || !o) return;
    $('#map-metric').value = 'above'; renderMap();
    const ref = cache.mapRef; if (!ref || ref.key !== 'above') return;
    const tot = ref.shapes.map((s) => { const q = nbReturn(s.nb, o); return q ? q.total : NaN; }), ok_ = tot.filter(isFinite);
    const hi = Math.ceil(d3.max(ok_) + 1), lo = o.opp, w = ref.C.step, badge = $('#map-badge');
    const paint = (h) => {
      ref.paths.attr('fill', (s, i) => (isFinite(tot[i]) ? `var(--cds-chart-diverging-${4 - Math.max(-3, Math.min(3, Math.round((tot[i] - h) / w)))})` : 'var(--cds-chart-muted)'));
      const n = ok_.filter((v) => v > h).length; badge.replaceChildren();
      const b = document.createElement('b'); b.textContent = pct(h, 2); badge.append('Rate elsewhere ', b, document.createElement('br'), `${n} of ${ok_.length} neighbourhoods beat it`); badge.hidden = false;
    };
    if (sweepRaf) cancelAnimationFrame(sweepRaf);
    if (!motionOK() || !(hi > lo)) { paint(lo); return; }
    const dur = 5200, t0 = performance.now(); $('#map-sweep').disabled = true; paint(hi);
    const step = (now) => {
      const k = Math.min(1, (now - t0) / dur); paint(hi + (lo - hi) * d3.easeCubicInOut(k));
      if (k < 1) sweepRaf = requestAnimationFrame(step); else { sweepRaf = null; $('#map-sweep').disabled = false; renderMap(); }
    };
    sweepRaf = requestAnimationFrame(step);
  };
  $('#map-sweep').addEventListener('click', () => safe('the hurdle rate', runSweep));

  const getLsoa = () => {
    if (!ok('lsoa_map')) return null;
    if (cache.lsoa) return cache.lsoa;
    const k = Math.cos(53.52 * Math.PI / 180), pr = ([x, y]) => [x * k, y];
    return (cache.lsoa = { k, rows: rows('lsoa_map').map((r) => ({ ...r, type: 'Feature', geometry: { type: 'MultiPolygon', coordinates: JSON.parse(r.geom).map((poly) => poly.map((ring) => ring.map(pr))) } })) });
  };
  // The dashboard's built-in d3 has no geo or polygon modules, so the map fits, projects and draws its own shapes
  // (what geoIdentity().reflectY(true).fitExtent and geoPath would do; the stand-alone copy had full d3 and hid this)
  const fitShapes = (rows, W, H, pad) => {
    let x0 = Infinity, x1 = -Infinity, y0 = Infinity, y1 = -Infinity;
    rows.forEach((r) => r.geometry.coordinates.forEach((poly) => poly.forEach((ring) => ring.forEach(([x, y]) => {
      if (x < x0) x0 = x; if (x > x1) x1 = x; if (y < y0) y0 = y; if (y > y1) y1 = y; }))));
    const s = Math.min((W - 2 * pad) / (x1 - x0), (H - 2 * pad) / (y1 - y0)), ox = (W - (x1 - x0) * s) / 2, oy = (H - (y1 - y0) * s) / 2;
    return ([x, y]) => [ox + (x - x0) * s, oy + (y1 - y) * s];
  };
  const shapePath = (proj, geom) => geom.coordinates.map((poly) => poly.map((ring) => 'M' + ring.map((pt) => proj(pt).map((v) => v.toFixed(1)).join(',')).join('L') + 'Z').join('')).join('');
  const ringContains = (ring, [x, y]) => {           // ray casting, as polygonContains would
    let inside = false;
    for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
      const [xi, yi] = ring[i], [xj, yj] = ring[j];
      if ((yi > y) !== (yj > y) && x < (xj - xi) * (y - yi) / (yj - yi) + xi) inside = !inside;
    }
    return inside;
  };

  // ================= MARKET =================
  const lineChart = (box, series, opts) => {
    fresh(box);
    const all = series.flatMap((s) => s.values).filter((d) => isFinite(d.v)); if (!all.length) return;
    const W = Math.max(280, box.clientWidth), H = opts.height || 260, m = { t: 12, r: 16, b: 26, l: 10 };
    const x = d3.scaleUtc(d3.extent(all, (d) => d.date), [0, 1]);
    const ymin = opts.yZero ? Math.min(0, d3.min(all, (d) => d.v)) : (opts.yMin != null ? opts.yMin : d3.min(all, (d) => d.v) * 0.95);
    const y = d3.scaleLinear([ymin, d3.max(all, (d) => d.v) * 1.04], [H - m.b, m.t]).nice();
    const svg = d3.select(box).append('svg').attr('width', '100%').attr('viewBox', `0 0 ${W} ${H}`).attr('role', 'img').attr('aria-label', opts.label);
    // end labels name each line; where the names won't fit in 40% of the width, they show the value only (the legend names them)
    let endText = (s, v) => `${s.name} ${opts.endFmt(v)}`;
    if (opts.endLabels) {
      const width = (f) => { let ew = 0; series.forEach((s) => { const l = s.values.filter((d) => isFinite(d.v)).at(-1); if (!l) return; const tx = svg.append('text').text(f(s, l.v)).style('font-size', 'var(--cds-font-size-caption)'); ew = Math.max(ew, tx.node().getComputedTextLength()); tx.remove(); }); return ew; };
      let ew = width(endText); if (ew + 12 > W * 0.4) { endText = (s, v) => opts.endFmt(v); ew = width(endText); }
      m.r = Math.min(ew + 12, W * 0.4);
    }
    const ga = svg.append('g'); ga.call(d3.axisLeft(y).ticks(5).tickFormat(opts.yFmt)); cleanAxis(ga);
    let wl = 0; ga.selectAll('text').each(function () { wl = Math.max(wl, this.getComputedTextLength()); }); ga.remove();
    m.l = wl + 12; x.range([m.l, W - m.r]);
    const gy = svg.append('g').attr('transform', `translate(${m.l},0)`).call(d3.axisLeft(y).ticks(5).tickFormat(opts.yFmt).tickSize(-(W - m.l - m.r))); cleanAxis(gy); gy.select('.domain').remove();
    const xa = d3.axisBottom(x).ticks(Math.max(2, Math.min(10, Math.floor((W - m.l - m.r) / 80)))).tickSizeOuter(0); if (opts.xFmt) xa.tickFormat(opts.xFmt);
    const gx = svg.append('g').attr('transform', `translate(0,${H - m.b})`).call(xa); cleanAxis(gx);
    const line = d3.line().x((d) => x(d.date)).y((d) => y(d.v)).defined((d) => isFinite(d.v));
    const drawn = series.map((s) => svg.append('path').datum(s.values).attr('fill', 'none').attr('stroke', s.color).attr('stroke-width', 2).attr('stroke-linejoin', 'round').attr('stroke-linecap', 'round').attr('d', line));
    const anim = opts.animate && motionOK();
    if (anim) drawn.forEach((p, k) => { const len = p.node().getTotalLength(); p.attr('stroke-dasharray', `${len} ${len}`).attr('stroke-dashoffset', len)
      .transition().delay(k * 150).duration(1300).ease(d3.easeCubicInOut).attr('stroke-dashoffset', 0).on('end', function () { d3.select(this).attr('stroke-dasharray', null).attr('stroke-dashoffset', null); }); });
    if (opts.endLabels) {
      const ends = series.map((s) => { const l = s.values.filter((d) => isFinite(d.v)).at(-1); return l ? { y: y(l.v), text: endText(s, l.v) } : null; }).filter(Boolean).sort((a, b) => a.y - b.y);
      for (let i = 1; i < ends.length; i++) if (ends[i].y - ends[i - 1].y < 14) ends[i].y = ends[i - 1].y + 14;
      ends.forEach((e) => { const tx = svg.append('text').attr('x', W - m.r + 6).attr('y', e.y).attr('dy', '0.35em').attr('fill', 'var(--color-fg)').style('font-size', 'var(--cds-font-size-caption)').text(e.text);
        if (anim) tx.attr('opacity', 0).transition().delay(1200).duration(400).attr('opacity', 1); });
    }
    const t = tip(box), rule = svg.append('line').attr('stroke', 'var(--cds-chart-reference)').attr('y1', m.t).attr('y2', H - m.b).attr('opacity', 0);
    const dots = series.map((s) => svg.append('circle').attr('r', 4).attr('fill', s.color).attr('stroke', 'var(--color-panel)').attr('stroke-width', 2).attr('opacity', 0));
    const dates = series[0].values.map((d) => d.date), bis = d3.bisector((d) => d).center;
    svg.append('rect').attr('x', m.l).attr('y', m.t).attr('width', W - m.l - m.r).attr('height', H - m.t - m.b).attr('fill', 'transparent')
      .on('mousemove', (e) => {
        const [px] = d3.pointer(e), dt = dates[bis(dates, x.invert(px))]; if (!dt) return;
        rule.attr('x1', x(dt)).attr('x2', x(dt)).attr('opacity', 1);
        const lines = [['t', opts.tipX ? opts.tipX(dt) : opts.xFmt ? opts.xFmt(dt) : d3.utcFormat('%B %Y')(dt)]];
        series.forEach((s, k) => { const pt = s.values.find((d) => +d.date === +dt); if (pt && isFinite(pt.v)) { dots[k].attr('cx', x(dt)).attr('cy', y(pt.v)).attr('opacity', 1); lines.push(['', (series.length > 1 ? s.name + ': ' : '') + opts.tipFmt(pt.v)]); } else dots[k].attr('opacity', 0); });
        const [bx, by] = d3.pointer(e, box); t.show(lines, bx, by);
      })
      .on('mouseleave', () => { rule.attr('opacity', 0); dots.forEach((d) => d.attr('opacity', 0)); t.hide(); });
  };
  const getPoss = () => {
    if (!ok('possession')) return null;
    if (cache.poss) return cache.poss;
    const R = rows('possession').map((r) => ({ ...r, rate: num(r.rate), count: num(r.count) })), Q = { Q1: 3, Q2: 6, Q3: 9, Q4: 12 };
    const date = (q) => new Date(Date.UTC(+q.slice(0, 4), Q[q.slice(5)] - 1, 1));
    const label = (q) => d3.utcFormat('%B %Y')(date(q));
    const series = (area, m) => R.filter((r) => r.area === area && r.metric === m).sort((a, b) => (a.quarter < b.quarter ? -1 : 1));
    return (cache.poss = { R, date, label, series, latest: (area, m) => series(area, m).at(-1) || null });
  };

  // ================= ACCURACY =================
  const FEAT = { lvl_sector_type: 'Recent prices, sector and type', lvl_lsoa: 'Recent prices, neighbourhood', property_type: 'Property type', lat: 'Latitude', lon: 'Longitude', dist_centre_km: 'Distance to town centre',
    new_build: 'New build', tenure: 'Tenure', n_sector_type: 'Recent sales count', imd_score: 'Deprivation (overall)', imd_income: 'Income deprivation', imd_employment: 'Employment deprivation',
    imd_education: 'Education deprivation', imd_health: 'Health deprivation', imd_crime: 'Crime', imd_barriers: 'Barriers to housing', imd_living_env: 'Living environment', floor_area: 'Floor area',
    rooms: 'Bedrooms + living rooms', age_year: 'Build age', bungalow: 'Bungalow', built_form_code: 'Built form', extensions: 'Extensions', sap_current: 'Energy rating', sap_potential: 'Potential energy rating',
    sap_gap: 'Energy improvement gap', mains_gas: 'Mains gas', knn_lvl: '10 nearest sales, same type', knn_dist: 'Distance to nearest sales', knn_ppsqm: '£/m² of 15 nearest sales',
    prev_defl: 'Last sale price, index-adjusted', years_since_prev: 'Years since last sale', prev_nb: 'Last sale was new build',
    plot_m2: 'Plot size', plot_epc_homes: 'Homes on the same title', plot_uprns: 'Addresses on the same title', plot_m2_per_home: 'Plot per home',
    lvl_street_type: 'Recent prices, same street and type', n_street_type: 'Recent sales on the street', lvl_postcode: 'Recent prices, same postcode', n_postcode: 'Recent sales in the postcode',
    wall_type: 'Wall construction', ceiling_m: 'Ceiling height', floor_level_n: 'Floor level (flats)', top_floor: 'Top-floor flat', heated_rooms: 'Heated rooms', glazed_area_n: 'Window area',
    fireplaces: 'Open fireplaces', wall_insulated: 'Wall insulation', loft_mm: 'Loft insulation', glazing: 'Glazing', elec_heating: 'Electric heating', heat_pump: 'Heat pump',
    woodburner: 'Wood burner or stove', low_energy_light: 'Low-energy lighting', solar_pv: 'Solar panels',
    epc_reason: 'Why the latest certificate was done', epc_tenure_n: 'Tenure on the latest certificate', epc_rental_5y: 'Certificate for a let in the last 5 years',
    epc_age_y: 'Age of the latest certificate', epc_n: 'Certificates on record', sap_jump: 'Energy score change since the previous certificate' };
  const bars = (box, d, o) => {
    fresh(box); if (!d.length) return;
    const W = Math.max(280, box.clientWidth), bh = 18, gap = 6;
    const probe = d3.select(box).append('svg').attr('width', W).attr('height', 1);
    let maxw = 0; d.forEach((r) => { const tx = probe.append('text').text(r.label).style('font-size', 'var(--cds-font-size-caption)'); maxw = Math.max(maxw, tx.node().getComputedTextLength()); tx.remove(); });
    probe.remove();
    // labels that don't fit beside the bars (a phone) go above them instead of running off the left edge
    const stacked = maxw + 10 > W * 0.6, lh = stacked ? 16 : 0, row = bh + gap + lh, H = d.length * row;
    box.style.minHeight = H + 'px';
    const svg = d3.select(box).append('svg').attr('width', '100%').attr('viewBox', `0 0 ${W} ${H}`).attr('role', 'img').attr('aria-label', o.label);
    const left = stacked ? 0 : maxw + 10, x = d3.scaleLinear([0, d3.max(d, (r) => r.v)], [left, W - (o.right || 48)]);
    d.forEach((r, i) => {
      const yy = i * row + lh, accent = r.accent != null ? r.accent : (o.accentLast && i === d.length - 1) || (o.accentTop && i < o.accentTop);
      if (stacked) svg.append('text').attr('x', 0).attr('y', yy - 4).attr('fill', 'var(--color-fg-muted)').style('font-size', 'var(--cds-font-size-caption)').text(r.label);
      else svg.append('text').attr('x', left - 8).attr('y', yy + bh / 2).attr('dy', '0.35em').attr('text-anchor', 'end').attr('fill', 'var(--color-fg-muted)').style('font-size', 'var(--cds-font-size-caption)').text(r.label);
      svg.append('rect').attr('x', left).attr('y', yy).attr('height', bh).attr('width', Math.max(2, x(r.v) - left)).attr('rx', 4).attr('fill', accent ? dash.colors[0] : 'var(--cds-chart-muted)');
      svg.append('text').attr('x', x(r.v) + 6).attr('y', yy + bh / 2).attr('dy', '0.35em').attr('fill', 'var(--color-fg)').style('font-size', 'var(--cds-font-size-caption)').style('font-variant-numeric', 'tabular-nums').text(o.fmt(r.v));
      if (r.tip) svg.append('rect').attr('x', 0).attr('y', yy - gap / 2).attr('width', W).attr('height', bh + gap).attr('fill', 'transparent').append('title').text(r.tip);
    });
  };

  // ================= light / dark =================
  // the dashboard follows the reader's system or app theme; this button pins light or dark for this visit
  const themeBtn = $('#theme-toggle');
  const isDark = () => { const m = document.documentElement.getAttribute('data-mode'); return m === 'dark' ? true : m === 'light' ? false : !!(window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches); };
  const syncTheme = () => themeBtn.setAttribute('aria-pressed', String(isDark()));
  themeBtn.addEventListener('click', () => { document.documentElement.setAttribute('data-mode', isDark() ? 'light' : 'dark'); syncTheme(); render(); });
  syncTheme();
  if (window.MutationObserver) new MutationObserver(syncTheme).observe(document.documentElement, { attributes: true, attributeFilter: ['data-mode'] });
  if (window.matchMedia) window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', syncTheme);

  // ================= version and changelog =================
  // one row per change; the newest version number is the dashboard's version
  const getChanges = () => {
    if (!ok('changelog')) return null;
    if (cache.changes) return cache.changes;
    const by = d3.group(rows('changelog').map((r) => ({ ...r, v: num(r.version), m: num(r.model_version) })), (r) => r.v);
    const list = [...by.entries()].sort((a, b) => b[0] - a[0]).map(([v, rs]) => ({ v, date: rs[0].date, headline: rs[0].headline, model: rs[0].m, items: rs.map((r) => r.change) }));
    return (cache.changes = list);
  };
  const dayLabel = (d) => d3.utcFormat('%-d %b %Y')(new Date(d + 'T00:00:00Z'));
  const renderVersion = () => {
    const L = getChanges(); if (!L || !L.length) return;
    const b = $('#head-version'); b.textContent = `Version ${L[0].v} · ${dayLabel(L[0].date)}`;
    b.setAttribute('aria-label', `Version ${L[0].v}, released ${dayLabel(L[0].date)}: open the changelog`);
  };
  const renderChanges = () => {
    const box = $('#changelog'); if (failed(box, ['changelog'])) return;
    const L = getChanges(); if (!L) return;
    const mNow = L[0].model, mFrom = L.filter((x) => x.model === mNow).at(-1);
    $('#changes-sub').textContent = `Every version of the dashboard, newest first: ${L.length} so far. The valuation model itself is version ${mNow}, unchanged since dashboard version ${mFrom.v} on ${dayLabel(mFrom.date)}.`;
    if (box.dataset.n === String(L.length)) return;
    box.replaceChildren(); box.dataset.n = String(L.length);
    L.forEach((x, k) => {
      const li = document.createElement('li'), head = document.createElement('div'), v = document.createElement('div'), d = document.createElement('span'), body = document.createElement('div'), h = document.createElement('h3'), ul = document.createElement('ul');
      v.className = 'cl-v'; v.textContent = `Version ${x.v}`; d.className = 'cl-d'; d.textContent = dayLabel(x.date) + (x.model !== (L.at(k + 1) || {}).model ? ` · valuation model ${x.model}` : '');
      if (k === 0) { const now = document.createElement('span'); now.className = 'pill strong cl-now'; now.textContent = 'Current'; v.appendChild(now); }
      head.append(v, d); h.textContent = x.headline;
      x.items.forEach((t) => { const i = document.createElement('li'); i.textContent = t; ul.appendChild(i); });
      body.append(h, ul); li.append(head, body); box.appendChild(li);
    });
  };
  $('#head-version').addEventListener('click', () => showTab('changes'));

  // ================= Market and Accuracy tabs (market_accuracy.js) =================
  // in a file of their own, loaded first: one page file can't exceed 256 KB. They get the helpers they use from here
  const missingTabs = (name) => () => { throw new Error(`market_accuracy.js didn't load, so ${name} can't be drawn`); };
  const tabs2 = window.DPM_TABS ? window.DPM_TABS({ $, FEAT, TYPES, TYPE_NAME, TYPE_SHORT, bars, cell, cleanAxis, failed, fix0, fresh, gbp, gbpK, getConf, getIndex, getPoss, kv, lineChart, median, num, ok, parseMonth, pill, pts, rows, safe, sgn, state, tip, typed }) : {};
  const renderMarket = tabs2.renderMarket || missingTabs('the Market tab'), renderAccuracy = tabs2.renderAccuracy || missingTabs('the Accuracy tab');
  // the mortgage-rate, sensitivity and past-decades charts on the Investing tab (deal_charts.js, loaded first as well)
  const dealCharts = window.DPM_DEAL ? window.DPM_DEAL({ $, gbp, gbpK, pct, fix0, num, fresh, tip, cleanAxis, motionOK, onFirstView, state, yearCalc, projectDeal, DEAL_CHECKS, getNb, homeReturn, LA_CODE, renderInvest, failed })
    : { draw() { throw new Error("deal_charts.js didn't load"); }, clear() {} };

  // ================= header and render loop =================
  const renderHeader = () => {
    if (!ok('accuracy') || !ok('model_meta')) return;
    const g = (mt) => num((rows('accuracy').find((x) => x.model === 'dashboard' && x.split === 'test_2025_26' && x.metric === mt) || {}).value);
    const meta = Object.fromEntries(rows('model_meta').map((r) => [r.key, r.value]));
    $('#lede').textContent = `What a Doncaster home would sell for today, from ${d3.format(',')(num(meta.n_sales_model))} Land Registry sales matched to energy certificates. On 2025–26 sales it hadn't seen, half of its estimates were within ${d3.format('.1%')(g('mdape'))} of the price paid and ${d3.format('.0%')(g('within10'))} within 10%.`;
    $('#head-meta').textContent = `Prices to ${monthLabel(meta.index_latest_month)} · built from open data: HM Land Registry, energy certificates, ONS, OS`;
  };
  // each section draws on its own, so one that fails (or whose data is still loading) can't leave the rest of a tab blank
  function render() {
    safe('the header', renderHeader);
    safe('the settings check', showSettingsProblem);
    safe('the version', renderVersion);
    const t = state.tab;
    if (t === 'value' || t === 'invest' || t === 'areas' || t === 'saved') safe('the estimate', renderValue);
    if (t === 'invest') safe('buy-to-let', renderInvest);
    if (t === 'areas') safe('areas and rents', renderAreas);
    if (t === 'market') safe('the market charts', renderMarket);
    if (t === 'accuracy') safe('model accuracy', renderAccuracy);
    if (t === 'saved') safe('the saved list', renderSaved);
    if (t === 'changes') safe('the changelog', renderChanges);
  }
  const applyLimits = () => {
    const set = (sel, lo, hi) => { const el = $(sel); if (!el) return; if (isFinite(lo)) el.min = String(lo); else el.removeAttribute('min'); if (isFinite(hi)) el.max = String(hi); else el.removeAttribute('max'); };
    [['#in-area', 'area'], ['#in-rooms', 'rooms'], ['#in-plot', 'plot'], ['#in-prev-price', 'prevPrice'], ['#in-asking', 'asking']].forEach(([sel, k]) => set(sel, LIMITS[k][0], LIMITS[k][1]));
    const pctKeys = { dep: 100, rate: 100, letting: 100, maint: 100 };
    [['#b-price', 'price'], ['#b-rent', 'rent'], ['#b-deposit', 'dep'], ['#b-rate', 'rate'], ['#b-term', 'term'], ['#b-letting', 'letting'], ['#b-maint', 'maint'], ['#b-voids', 'voids'],
      ['#b-fee', 'fee'], ['#b-ins', 'ins'], ['#b-comp', 'comp'], ['#b-legal', 'legal'], ['#b-works', 'works'], ['#b-epc', 'epc'], ['#b-improve', 'improve'], ['#b-income', 'income']].forEach(([sel, k]) => { const [lo, hi] = DEAL_CHECKS[k], m = pctKeys[k] || 1; set(sel, lo * m, hi * m); });
    ['#p-rent', '#p-price', '#p-cost'].forEach((sel) => set(sel, -50, 50));
    FLIP_CHECKS.forEach(([sel, lo, hi]) => set(sel, lo, hi)); RISK_CHECKS.forEach(([sel, lo, hi]) => set(sel, lo, hi));
    ['#nb-opp-custom', '#inv-opp-custom'].forEach((sel) => set(sel, OPP_LIMITS[0], OPP_LIMITS[1]));
    WI_CHECKS.forEach(([sel, lo, hi]) => set(sel, lo, hi));
  };
  safe('the input limits', applyLimits);
  dash.onData(render);
  let named = ''; try { named = location.hash.slice(1); } catch (e) { /* no address to read */ }
  if (TABS.includes(named)) showTab(named, false);
})();
