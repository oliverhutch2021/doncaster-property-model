// The Value tab's source tags, its Census 2021 card and the one-page printable report (dashboard version 32). They sit in
// their own file because the Claude dashboard refuses any one page file over 256 KB; index.html loads this before
// app.js, and app.js calls window.DPM_VALUE once its own helpers exist, passing the ones used here.
window.DPM_VALUE = (h) => {
  const { $, state, monthLabel, num, gbp, gbpK, pct, parseSales, kv, cell, TYPE_NAME, getModel, rentEstimate, ok, rows } = h;
  // where each detail the model uses came from, and how many of the six that matter most came from official records
  const SRC_OFFICIAL = new Set(['cert', 'lr']);
  const detailSources = (inp) => {
    const e = state.epc, cert = e && e.lodged ? `energy certificate, ${monthLabel(String(e.lodged).slice(0, 7))}` : 'energy certificate';
    const has = (sel) => $(sel).value !== '';
    const shown = (sel) => { const el = $(sel); return el.tagName === 'SELECT' ? (el.options[el.selectedIndex] || {}).text : el.value; };
    const typed = (sel) => (state.listingOwned[sel] ? ['listing', 'from the listing'] : ['you', 'you entered']);
    const field = (sel) => (state.epcAuto[sel] && e ? ['cert', cert] : has(sel) ? typed(sel) : ['none', 'not given, so valued without it']);
    const out = [];
    const push = (name, [kind, src], value, key = true) => out.push({ name, kind, src, value, key });
    const tCert = e ? (e.epc_type === 'Flat' || e.epc_type === 'Maisonette' ? 'F' : { 0: 'D', 1: 'S', 2: 'T', 3: 'T', 4: 'T', 5: 'T' }[String(e.built_form_code)]) : null;
    push('Property type', tCert && tCert === inp.type ? ['cert', cert] : state.listingOwned['#in-type'] ? ['listing', 'from the listing'] : ['you', 'you chose'], shown('#in-type'), false);
    push('Floor area', field('#in-area'), has('#in-area') ? shown('#in-area') + ' m²' : '—');
    push('Bedrooms and living rooms', field('#in-rooms'), has('#in-rooms') ? shown('#in-rooms') : '—');
    push('Built', field('#in-age'), has('#in-age') ? shown('#in-age') : '—');
    const sapCert = e && !state.sapManual && isFinite(num(e.sap_current));
    push('Energy rating', sapCert ? ['cert', cert] : state.sapFromListing ? ['listing', 'from the listing'] : has('#in-rating') ? ['you', 'you entered'] : ['none', 'not given, so valued without it'],
      sapCert ? `${e.rating || shown('#in-rating')} (score ${num(e.sap_current)})` : has('#in-rating') ? shown('#in-rating') : '—');
    const plotLR = e && isFinite(num(e.plot_m2)) && num(e.plot_m2) > 0;
    push('Plot size', has('#in-plot') ? typed('#in-plot') : plotLR ? ['lr', 'HM Land Registry title plan'] : ['none', 'not given, so valued without it'],
      has('#in-plot') ? shown('#in-plot') + ' m²' : plotLR ? `${d3.format(',')(Math.round(num(e.plot_m2)))} m²` : '—');
    const noSale = e && !state.prevAuto && !has('#in-prev-price') && parseSales(e.sales).length === 0;
    push('Last sale', state.prevAuto ? ['lr', `HM Land Registry, ${monthLabel(inp.prevMonth)}`] : has('#in-prev-price') ? ['you', 'you entered'] : noSale ? ['lr', 'HM Land Registry: none since 1995'] : ['none', 'not given, so valued without it'],
      state.prevAuto || has('#in-prev-price') ? gbp(inp.prevPrice) : noSale ? 'None on record' : '—');
    return out;
  };
  const renderSources = (inp) => {
    const sum = $('#v-src-sum'), list = $('#v-src-list'); if (!sum || !list) return;
    const d = detailSources(inp), key = d.filter((x) => x.key), off = key.filter((x) => SRC_OFFICIAL.has(x.kind)).length, none = key.filter((x) => x.kind === 'none').length;
    sum.textContent = `Where the details come from: ${off} of ${key.length} from official records` + (none ? `, ${none} not given` : '');
    kv(list, d.map((x) => [x.name, `${x.value} · ${x.src}`, SRC_OFFICIAL.has(x.kind) ? 'src-off' : x.kind === 'none' ? 'src-none' : '']));
  };
  // Census 2021 for the home's neighbourhood (LSOA), against Doncaster and England (census dataset, src/census_profile.py)
  let censusMap = null;
  const getCensus = () => (ok('census') ? (censusMap || (censusMap = new Map(rows('census').map((r) => [r.geo, r])))) : null);
  const CENSUS_ROWS = [['private_rented_pct', 'Households renting privately', '%'], ['owned_pct', 'Owner-occupied', '%'], ['social_rented_pct', 'Renting from a council or housing association', '%'],
    ['degree_pct', 'Adults with a degree or higher', '%'], ['no_qual_pct', 'Adults with no qualifications', '%'], ['students_pct', 'Schoolchildren and full-time students', '%'],
    ['mean_age', 'Average age', 'y'], ['age65_pct', 'Aged 65 or over', '%'], ['cars_per_household', 'Cars or vans per household', 'n'], ['no_car_pct', 'Households with no car', '%']];
  const renderCensus = (v) => {
    const tb = $('#census-table tbody'); if (!tb) return; tb.replaceChildren();
    const C = getCensus(), here = C && v.pc ? C.get(v.pc.lsoa21) : null, la = C ? C.get('E08000017') : null, en = C ? C.get('E92000001') : null;
    $('#census-card').hidden = !here;
    if (!here) return;
    $('#census-where').textContent = `${here.name} (about ${d3.format(',')(Math.round(num(here.households) / 10) * 10)} households), the Census neighbourhood this postcode is in.`;
    const f = (r, k, u) => { const x = num(r[k]); return !isFinite(x) ? '—' : u === '%' ? pct(x, 0) : u === 'y' ? d3.format('.0f')(x) : d3.format('.1f')(x); };
    CENSUS_ROWS.forEach(([k, name, u]) => { const tr = document.createElement('tr'); cell(tr, name); cell(tr, f(here, k, u), 'r'); cell(tr, la ? f(la, k, u) : '—', 'r'); cell(tr, en ? f(en, k, u) : '—', 'r'); tb.appendChild(tr); });
  };
  // ================= one-page report =================
  // built from what the Value tab shows; the print stylesheet hides everything else, so the browser's print (or Save as PDF) gives one A4 page
  const buildReport = () => {
    const box = $('#report'); if (!box) return false;
    box.replaceChildren();
    const L = state.last;
    const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };
    if (!L) { box.append(el('p', null, 'Value a home on the Value tab first, then print.')); return false; }
    const inp = L.inp, model = getModel(), e = state.epc;
    const where = e && e.address ? `${e.address}, ${inp.postcode}` : `${inp.postcode}${L.street ? ', ' + L.street.replace(/\w\S*/g, (w) => w[0] + w.slice(1).toLowerCase()) : ''}`;
    box.append(el('h1', null, 'Valuation report'), el('p', 'r-meta', `${where} · ${TYPE_NAME[inp.type]} · ${model ? `prices at ${monthLabel(model.valMonth)}` : ''} · printed ${new Date().toLocaleDateString('en-GB', { day: 'numeric', month: 'long', year: 'numeric' })}`));
    const hero = el('div', 'r-hero'), a = el('div'), cond = L.cond && L.cond.adj ? `, ${L.cond.label.toLowerCase()}` : ', average condition';
    a.append(el('span', 'r-l', 'Estimated value today'), el('b', 'r-big', gbp(Math.round(L.adj / 1000) * 1000)),
      el('span', null, `80% range ${gbpK(L.lo * (1 + (L.cond ? L.cond.adj : 0) / 100))} to ${gbpK(L.hi * (1 + (L.cond ? L.cond.adj : 0) / 100))}${cond}`), el('span', null, $('#v-conf').innerText));
    hero.append(a);
    const R = rentEstimate();
    if (R) { const b = el('div'); b.append(el('span', 'r-l', R.N ? 'Rent for a new tenancy (provisional)' : 'Estimated rent'), el('b', 'r-big', gbp(R.est) + ' a month'),
      el('span', null, `Likely ${gbp(R.lo)} to ${gbp(R.hi)}${R.N ? `; rents being paid on homes like it about ${gbp(R.paid)}` : ''}`), el('span', null, `Gross yield at the estimate ${pct(1200 * R.est / L.adj, 1)}`)); hero.append(b); }
    box.append(hero);
    const two = (ps) => { const out = []; for (let i = 0; i < ps.length; i += 2) out.push([ps[i][0], ps[i][1], ps[i + 1] ? ps[i + 1][0] : '', ps[i + 1] ? ps[i + 1][1] : '']); return out; };
    const grid = (rs) => { const tb = el('table', 'r-kv'); rs.forEach((r) => { const tr = el('tr'); r.forEach((c, i) => tr.append(el('td', i % 2 ? null : 'r-k', c))); tb.append(tr); }); return tb; };
    const table = (head, rowsIn, cls) => { const tb = el('table', cls), th = el('tr'); head.forEach((h, i) => th.append(el('th', i ? 'r' : null, h))); tb.append(th); rowsIn.forEach((r) => { const tr = el('tr'); r.forEach((c, i) => tr.append(el('td', i ? 'r' : null, c))); tb.append(tr); }); return tb; };
    const d = detailSources(inp), key = d.filter((x) => x.key), off = key.filter((x) => SRC_OFFICIAL.has(x.kind)).length;
    box.append(el('h2', null, `The home: ${off} of ${key.length} key details from official records`), grid(two(d.map((x) => [x.name, `${x.value} · ${x.src}`]))));
    const comps = [...$('#comps-table tbody').rows].slice(0, 6).map((tr) => { const c = tr.cells; const addr = c[0].firstChild ? c[0].firstChild.textContent : ''; const why = c[0].querySelector('.comp-why'); return [addr, c[1].textContent, c[2].textContent, c[4].textContent, why ? why.textContent : '']; });
    if (comps.length) box.append(el('h2', null, 'Nearest comparable sales, adjusted to this home'), table(['Address', 'Sold', 'Price', 'Like this home', 'Why it differs'], comps.map((r) => [r[0], r[1], r[2], r[3], r[4]]), 'r-comps'), el('p', 'r-note', $('#comps-note').textContent));
    const pairs = []; [...$('#around-risk').children, ...$('#around-amen').children].forEach((n) => { if (n.tagName === 'DT') { if (n.textContent.trim() || !pairs.length) pairs.push([n.textContent, []]); } else if (pairs.length && n.textContent) pairs.at(-1)[1].push(n.textContent); });
    if (pairs.length) box.append(el('h2', null, 'Around this home'), grid(two(pairs.map(([k, v]) => [k, v.join(' · ')]))));
    const C = getCensus(), here = C && L.pc ? C.get(L.pc.lsoa21) : null, la = C ? C.get('E08000017') : null;
    if (here) box.append(el('h2', null, `Who lives nearby (Census 2021, ${here.name})`), table(['', 'Here', 'Doncaster'], CENSUS_ROWS.filter(([k]) => ['private_rented_pct', 'owned_pct', 'degree_pct', 'mean_age', 'cars_per_household'].includes(k))
      .map(([k, name, u]) => { const f = (r) => { const x = num(r[k]); return u === '%' ? pct(x, 0) : u === 'y' ? d3.format('.0f')(x) : d3.format('.1f')(x); }; return [name, f(here), la ? f(la) : '—']; }), 'r-census'));
    box.append(el('p', 'r-foot', `Doncaster Property Model: a statistical estimate from public data (HM Land Registry, energy certificates, ONS, Census 2021, OS, Environment Agency, DfE), not a survey, mortgage valuation, or financial advice. Median error on 5,995 test sales: 8.1%. oliverhutch2021.github.io/doncaster-property-model`));
    return true;
  };
  $('#print-btn').addEventListener('click', () => { buildReport(); window.print(); });
  window.addEventListener('beforeprint', () => { if (!$('#report').childElementCount) buildReport(); });
  window.addEventListener('afterprint', () => $('#report').replaceChildren());
  return { detailSources, renderSources, renderCensus, buildReport };
};
