// Unit tests for the dashboard's money and validation functions, run on the page script itself (no browser needed).
//   node tests/test_units.js            (finds dashboard/app.js or outputs/dash2/app.js)
//   node tests/test_units.js path/to/app.js
// Each function is cut out of app.js by its name, so the tests always run the shipped code.
const fs = require('fs'), path = require('path');
const root = path.resolve(__dirname, '..');
const appPath = process.argv[2] || ['dashboard/app.js', 'outputs/dash2/app.js'].map((p) => path.join(root, p)).find((p) => fs.existsSync(p));
const d3Path = ['dashboard/vendor/d3.min.js', 'outputs/dash2/vendor/d3.min.js'].map((p) => path.join(root, p)).find((p) => fs.existsSync(p));
const src = fs.readFileSync(appPath, 'utf8'), d3 = require(d3Path);
const cut = (a, b) => { const i = src.indexOf(a), j = src.indexOf(b, i); if (i < 0 || j < 0) throw new Error(`can't find ${a}`); return src.slice(i, j); };
const helpers = cut('const gbp = ', 'const num = ') + cut('const num = ', 'const TYPE_NAME');
const fns = new Function('d3', 'getModel', 'parseMonth', helpers + cut('const sdlt = ', 'const DEFAULTS') + cut('const lastSaleMonths', 'const rentSeries') + cut('const LIMITS', 'const value = ') + cut('const taxRates', 'const kv = ') + cut('const DEAL_CHECKS', 'const clearDeal')
  + cut('const normPc', 'const hav = ') + cut('const WORD_NUM', 'const readListing')
  + '; return { badInput, taxRates, yearCalc, irrRoots, irr, signChanges, dealProblem, CASH_KEYS, COST_KEYS, MORTGAGE_KEYS, corpTax, gainsTax, listingType, listingPostcode, fix0, pct, sgn, gainsTaxDetail, condFor, projectDeal, sdlt };')(d3, () => ({ valMonth: '2026-09' }), (s) => new Date(Date.UTC(+s.slice(0, 4), +s.slice(5, 7) - 1, 1)));
const { badInput, yearCalc, irrRoots, irr, signChanges, dealProblem, CASH_KEYS, COST_KEYS, MORTGAGE_KEYS, corpTax, gainsTax, listingType, listingPostcode, pct, sgn, gainsTaxDetail, condFor, projectDeal, sdlt } = fns;

let fails = 0, n = 0;
const near = (got, want, tol) => (Number.isNaN(want) ? Number.isNaN(got) : Math.abs(got - want) <= tol);
const eq = (name, got, want, tol = 0.01) => { n++; const ok = near(got, want, tol); if (!ok) fails++; console.log(ok ? 'PASS' : 'FAIL', name, '|', got, 'want', want); };
const truthy = (name, v) => { n++; if (!v) fails++; console.log(v ? 'PASS' : 'FAIL', name); };

// ---------- Section 24 (HMRC: the credit is on the lowest of finance costs and property profits) ----------
const A = { corp_tax_small: { v: 19 }, tax_higher: { v: 40 }, tax_basic: { v: 20 }, tax_higher_2027: { v: 42 }, tax_basic_2027: { v: 22 }, finance_credit: { v: 20 }, finance_credit_2027: { v: 22 } };
const d = { rate: 0.05, mtype: 'io', term: 25, price: 400000, dep: 0.25, letting: 0, maint: 0, voids: 0, ins: 0, comp: 0, owner: 'higher' };
const rentFor = (profit) => profit / 12;
const y1 = yearCalc(d, A, { rent: rentFor(10000), costMult: 1, balance: 300000, year2027: false });
eq('interest on £300k at 5%', y1.interest, 15000); eq('higher-rate tax, relief capped at profit', y1.tax, 2000);
eq('cash flow after tax', y1.post, -7000); eq('finance costs carried forward', y1.carry.fin, 5000);
const y2 = yearCalc(d, A, { rent: rentFor(10000), costMult: 1, balance: 300000, year2027: false, carry: y1.carry });
eq('year 2 tax', y2.tax, 2000); eq('year 2 carried forward', y2.carry.fin, 10000);
const y3 = yearCalc(d, A, { rent: rentFor(30000), costMult: 1, balance: 300000, year2027: false, carry: y2.carry });
eq('year 3 uses brought-forward costs', y3.tax, 30000 * 0.4 - 25000 * 0.2); eq('year 3 nothing left', y3.carry.fin, 0);
eq('basic rate, interest above profit', yearCalc({ ...d, owner: 'basic' }, A, { rent: rentFor(10000), costMult: 1, balance: 300000, year2027: false }).tax, 0);
const yl = yearCalc({ ...d, ins: 12000 }, A, { rent: rentFor(10000), costMult: 1, balance: 300000, year2027: false });
eq('property loss carried forward', yl.carry.loss, 2000); eq('no tax on a loss', yl.tax, 0);
const yc = yearCalc({ ...d, owner: 'company' }, A, { rent: rentFor(10000), costMult: 1, balance: 300000, year2027: false });
eq('company: no tax on a loss', yc.tax, 0); eq('company: loss carried forward', yc.carry.loss, 5000);

// ---------- IRR ----------
eq('irr(-100, 300) = 200%', irr([-100, 300]), 2, 1e-6);
eq('irr(-50000, 55000) = 10%', irr([-50000, 55000]), 0.1, 1e-9);
eq('irr(-1, 11) = 1,000%', irr([-1, 11]), 10, 1e-6);
eq('all-zero cash flows: undefined', irr([0, 0, 0]), NaN); eq('no change of sign: undefined', irr([100, 100]), NaN);
const amb = irrRoots([-100, 230, -132]);
eq('ambiguous: two rates found', amb.length, 2, 0); eq('ambiguous: 10%', amb[0], 0.1, 1e-6); eq('ambiguous: 20%', amb[1], 0.2, 1e-6);
eq('ambiguous: irr() refuses to pick one', irr([-100, 230, -132]), NaN);
eq('sign changes, three', signChanges([-100, 50, -20, 200]), 3, 0); eq('sign changes, zeros skipped', signChanges([-100, 0, 10, 10]), 1, 0);
// a repeated rate: the NPV touches zero at 10% without crossing (the third review's first example)
const dbl = irrRoots([-100, 220, -121]);
eq('repeated rate: one found', dbl.length, 1, 0); eq('repeated rate: 10%', dbl[0], 0.1, 1e-9);
// three rates, two of them 0.01 points apart (the third review's second example)
const close3 = irrRoots([-100, 370.01, -451.026, 181.5165]);
eq('close rates: three found', close3.length, 3, 0); eq('close rates: 10%', close3[0], 0.1, 1e-8); eq('close rates: 10.01%', close3[1], 0.1001, 1e-8); eq('close rates: 50%', close3[2], 0.5, 1e-9);
eq('close rates: irr() refuses to pick one', irr([-100, 370.01, -451.026, 181.5165]), NaN);
// cash flows built from known rates: -100 x prod(1 - (1 + r) x), x = 1 / (1 + r). Every rate must come back, and nothing else
const fromRates = (rs) => rs.reduce((c, r) => { const o = new Array(c.length + 1).fill(0); c.forEach((v, t) => { o[t] += v; o[t + 1] -= v * (1 + r); }); return o; }, [-100]);
eq('triple rate at 10%', irrRoots(fromRates([0.1, 0.1, 0.1])).length, 1, 0); eq('triple rate value', irrRoots(fromRates([0.1, 0.1, 0.1]))[0], 0.1, 1e-4);
eq('double rate plus a single one', irrRoots(fromRates([0.05, 0.05, 0.3])).length, 2, 0);
let seed = 20261010; const rnd = () => ((seed = (seed * 1103515245 + 12345) % 2147483648) / 2147483648);
let built = 0, builtOk = 0, worst = 0;
for (let k = 0; k < 2000; k++) {
  const m = 1 + Math.floor(rnd() * 5), rs = [];
  while (rs.length < m) { const r = -0.5 + rnd() * 3.5; if (rs.every((q) => Math.abs(Math.log((1 + q) / (1 + r))) > 0.002)) rs.push(r); }
  rs.sort((u, v) => u - v); const got = irrRoots(fromRates(rs)); built++;
  const okk = got.length === rs.length && got.every((g, i) => Math.abs(g - rs[i]) < 1e-6);
  if (okk) builtOk++; else if (built - builtOk <= 3) console.log('  missed', rs, got);
  if (got.length === rs.length) worst = Math.max(worst, ...got.map((g, i) => Math.abs(g - rs[i])));
}
eq(`2,000 cash flows built from 1 to 5 known rates (at least 0.2% apart): all rates found, none extra (worst error ${worst.toExponential(1)})`, builtOk, built, 0);
// close pairs (0.01% apart in 1 + r, about 0.01 points) and repeated rates hidden among up to seven others
let pairs = 0, dbls = 0;
for (let k = 0; k < 1000; k++) {
  const b = -0.3 + rnd() * 2, rs = [b, (1 + b) * Math.exp(1e-4) - 1].sort((u, v) => u - v), g = irrRoots(fromRates(rs));
  if (g.length === 2 && g.every((x, i) => Math.abs(x - rs[i]) < 2e-5)) pairs++;
  const d2 = -0.3 + rnd() * 2, ds = [d2, d2]; const m = Math.floor(rnd() * 5);
  while (ds.length < 2 + m) { const r = -0.5 + rnd() * 3.5; if (ds.every((q) => Math.abs(Math.log((1 + q) / (1 + r))) > 0.01)) ds.push(r); }
  const want = [...new Set(ds)].sort((u, v) => u - v), h = irrRoots(fromRates(ds));
  if (h.length === want.length && h.every((x, i) => Math.abs(x - want[i]) < 1e-5)) dbls++;
}
eq('1,000 pairs of rates 0.01 points apart: both found', pairs, 1000, 0);
eq('1,000 repeated rates among up to four others: all found once', dbls, 1000, 0);
// ten-year deals with a year or two below zero: every rate a very fine scan sees is found, and each found rate gives a zero NPV
const npv = (cfs, r) => cfs.reduce((a, c, t) => a + c / (1 + r) ** t, 0);
let deals = 0, dealsOk = 0;
for (let k = 0; k < 300; k++) {
  const cf = [-(20000 + rnd() * 60000)]; for (let t = 1; t <= 10; t++) cf.push((rnd() - 0.45) * 4000); cf[10] += (rnd() - 0.2) * 150000;
  const got = irrRoots(cf), scan = [];
  for (let i = 0, G = 200000, a = Math.log(0.01), b = Math.log(101), f0 = npv(cf, 0.01 - 1); i < G; i++) {
    const r1 = Math.exp(a + (b - a) * (i + 1) / G) - 1, f1 = npv(cf, r1); if (f0 * f1 < 0) scan.push(r1); f0 = f1;
  }
  deals++;
  const sees = scan.every((r) => got.some((g) => Math.abs(g - r) < 1e-3)), zero = got.every((g) => Math.abs(npv(cf, g)) < 1e-6 * cf.reduce((a, c) => a + Math.abs(c), 0));
  if (sees && zero && got.length >= scan.length) dealsOk++; else console.log('  deal mismatch', cf.map(Math.round), got, scan);
}
eq('300 random ten-year deals: matches a 200,000-point scan and every rate found zeroes the NPV', dealsOk, deals, 0);

// ---------- input checks ----------
truthy('negative floor area refused', badInput({ area: -85 }));
truthy('floor area of 85 m² accepted', !badInput({ area: 85 }));
truthy('fractional rooms refused', badInput({ rooms: 2.5 }));
truthy('last sale price without a month refused', badInput({ prevPrice: 90000, prevMonth: '' }));
truthy('last sale with a month accepted', !badInput({ prevPrice: 90000, prevMonth: '2016-05' }));
const deal = { price: 150000, rent: 800, dep: 0.25, rate: 0.05, term: 25, letting: 0.12, maint: 0.08, voids: 2, fee: 0, ins: 300, comp: 250, legal: 1500, works: 0, epc: 0, improve: 0, income: NaN };
truthy('a normal deal accepted', !dealProblem(deal));
truthy('150% deposit refused', dealProblem({ ...deal, dep: 1.5 }));
truthy('negative rent refused', dealProblem({ ...deal, rent: -10 }));
truthy('missing price refused', dealProblem({ ...deal, price: NaN }));
// each panel checks only what it uses: the cash scorecard ignores the mortgage, the price markers ignore the rent
truthy('scorecard: impossible deposit ignored (cash purchase)', !dealProblem({ ...deal, dep: 1.5 }, CASH_KEYS));
truthy('scorecard: price of £500 refused', dealProblem({ ...deal, price: 500 }, CASH_KEYS));
truthy('scorecard: negative rent refused', dealProblem({ ...deal, rent: -10 }, CASH_KEYS));
truthy('scorecard: letting fee of 150% refused', dealProblem({ ...deal, letting: 1.5 }, CASH_KEYS));
truthy('price markers: missing rent ignored', !dealProblem({ ...deal, rent: NaN }, COST_KEYS));
truthy('break-even: impossible deposit refused', dealProblem({ ...deal, dep: 1.5 }, MORTGAGE_KEYS));
truthy('growth checked only for the full deal', dealProblem({ ...deal, gRent: 0.9 }) && !dealProblem({ ...deal, gRent: 0.9 }, CASH_KEYS));

// ---------- corporation tax with marginal relief, and tax on the gain (fourth review) ----------
const AT = { corp_tax_small: { v: 19 }, corp_tax_main: { v: 25 }, corp_tax_lower: { v: 50000 }, corp_tax_upper: { v: 250000 }, corp_tax_fraction: { v: 0.015 }, cgt_basic: { v: 18 }, cgt_higher: { v: 24 }, cgt_aea: { v: 3000 } };
eq('corporation tax at £40k: 19%', corpTax(40000, AT), 7600); eq('at £50k: 19%', corpTax(50000, AT), 9500);
eq('at £100k: 25% less 3/200 of £150k', corpTax(100000, AT), 22750); eq('at £300k: 25%', corpTax(300000, AT), 75000); eq('no tax on a loss', corpTax(-5000, AT), 0);
eq('marginal relief joins up at £250k', corpTax(250000, AT), 62500); eq('and at £50k', corpTax(50000.01, AT), 9500, 0.05);
eq('higher-rate CGT: 24% above £3,000', gainsTax({ owner: 'higher' }, AT, 103000), 24000); eq('basic-rate CGT: 18%', gainsTax({ owner: 'basic' }, AT, 13000), 1800);
eq('gain inside the exemption: no CGT', gainsTax({ owner: 'basic' }, AT, 2500), 0); eq('a loss: no CGT', gainsTax({ owner: 'higher' }, AT, -20000), 0);
eq('company: corporation tax on the gain on top of the year', gainsTax({ owner: 'company' }, AT, 60000, 20000), corpTax(80000, AT) - corpTax(20000, AT));
// the basic-rate band (fifth review): gov.uk's worked example, £20,000 income and a £52,600 gain, pays £10,842
eq("gov.uk example: £20,000 income, £52,600 gain", gainsTax({ owner: 'basic', income: 20000 }, AT, 52600), 10842);
const hm = gainsTaxDetail({ owner: 'basic', income: 20000 }, AT, 52600);
eq('  of which at 18%', hm.low, 17700); eq('  and at 24%', hm.high, 31900);
eq('band used up by other income: all 24%', gainsTax({ owner: 'basic', income: 40000 }, AT, 13000), 2400);
eq("that year's rental profit uses the band too", gainsTax({ owner: 'basic', income: 20000 }, AT, 52600, 10000), 7700 * 0.18 + 41900 * 0.24);
eq('a year 1 repair deduction cuts that year\'s tax', yearCalc({ ...d, owner: 'basic' }, A, { rent: rentFor(30000), costMult: 1, balance: 0, year2027: false, oneOff: 10000 }).taxable, 20000);
truthy('improvements above the works and EPC upgrade refused', dealProblem({ ...{ price: 150000, rent: 800, dep: 0.25, rate: 0.05, term: 25, letting: 0.12, maint: 0.08, voids: 2, fee: 0, ins: 300, comp: 250, legal: 1500, works: 5000, epc: 0, improve: 9000, income: 20000 } }));
// condition by what the model knows (fifth review)
const NEEDS = { adj: -8.9, adjPrev: -6.9 }, REF = { adj: 6.2, adjPrev: 0.6 };
eq('refurbished, no last sale: the no-last-sale premium', condFor(REF, {}).adj, 6.2);
eq('refurbished, last sale 8 months ago: the full model knows most of it', condFor(REF, { prevPrice: 90000, prevMonth: '2026-01' }).adj, 0.6);
eq('refurbished, last sale years ago: not measured, keeps the premium', condFor(REF, { prevPrice: 90000, prevMonth: '2015-05' }).adj, 6.2);
eq('needs renovation, last sale known: the full model\'s discount', condFor(NEEDS, { prevPrice: 90000, prevMonth: '2015-05' }).adj, -6.9);
eq('needs renovation, no last sale', condFor(NEEDS, { prevPrice: NaN }).adj, -8.9);
// ---------- listing parser (fourth review) ----------
eq("'detached ... flat roof' is detached", listingType('detached house with a flat roof garage extension') === 'D' ? 1 : 0, 1, 0);
eq("'apartment with roof terrace' is a flat", listingType('two bedroom apartment with roof terrace') === 'F' ? 1 : 0, 1, 0);
eq("'terraced ... detached garage' is terraced", listingType('3 bed terraced house with detached garage') === 'T' ? 1 : 0, 1, 0);
eq("'semi-detached bungalow' is semi", listingType('semi-detached bungalow for sale') === 'S' ? 1 : 0, 1, 0);
eq("a street called Terrace isn't a type", listingType('detached house, bass terrace, doncaster') === 'D' ? 1 : 0, 1, 0);
eq("'granny flat' isn't a flat", listingType('detached house with a granny flat') === 'D' ? 1 : 0, 1, 0);
eq("the type named first wins", listingType('ground floor flat in a converted detached house') === 'F' ? 1 : 0, 1, 0);
const PCS = new Map([['DN4 0AH', { in_doncaster: '1' }], ['DN1 2UA', { in_doncaster: '1' }], ['OX5 3AT', { in_doncaster: '0' }]]);
const lp = (txt) => listingPostcode(txt, txt.toLowerCase(), PCS);
eq("agent's postcode in another district is ignored", lp('Hexthorpe Road, Doncaster, DN4. Marketed by X, Doncaster DN1 2UA').pc === null ? 1 : 0, 1, 0);
eq("the home's own postcode is used", lp('Hexthorpe Road, Doncaster DN4 0AH. Marketed by X, Doncaster DN1 2UA').pc === 'DN4 0AH' ? 1 : 0, 1, 0);
eq("a postcode in the agent's details is ignored", lp('Lovely home. Contact us: X Estates, Doncaster DN1 2UA').pc === null ? 1 : 0, 1, 0);
eq('a postcode outside Doncaster is ignored', lp('Home for sale OX5 3AT').pc === null ? 1 : 0, 1, 0);
// ---------- the 10-year projection shared by the deal, the past-decades fan and the tornado ----------
const AP = { ...A, selling_costs: { v: 1.8 }, cgt_aea: { v: 3000 }, cgt_basic: { v: 18 }, cgt_higher: { v: 24 }, basic_rate_band: { v: 37700 }, cgt_other_income: { v: 20000 },
  corp_tax_main: { v: 25 }, corp_tax_lower: { v: 50000 }, corp_tax_upper: { v: 250000 }, corp_tax_fraction: { v: 0.015 },
  sdlt_band_1: { v: 125000 }, sdlt_band_2: { v: 250000 }, sdlt_band_3: { v: 925000 }, sdlt_band_4: { v: 1500000 }, sdlt_rate_1: { v: 0 }, sdlt_rate_2: { v: 2 }, sdlt_rate_3: { v: 5 }, sdlt_rate_4: { v: 10 }, sdlt_rate_5: { v: 12 }, sdlt_surcharge: { v: 5 } };
const DD = { price: 150000, rent: 850, dep: 0.25, rate: 0.0529, mtype: 'io', term: 25, fee: 0, letting: 0.12, maint: 0.08, voids: 2, ins: 300, comp: 250, legal: 1500, works: 0, epc: 0, improve: 0, income: NaN, owner: 'basic', taxYear: '2026', gRent: 0.03, gPrice: 0.04, gCost: 0.03 };
eq('stamp duty with the 5% surcharge on £150,000', sdlt(150000, AP), 125000 * 0.05 + 25000 * 0.07);
const PD = projectDeal(DD, AP), PDv = projectDeal(DD, AP, PD.proj.map((p) => p.value));
eq('a value path equal to the growth figure gives the same IRR', PDv.irr, PD.irr, 1e-12);
eq('cash in: deposit, stamp duty, legal', PD.cashIn, 37500 + sdlt(150000, AP) + 1500);
eq('equity is value less the loan', PD.proj[4].equity, PD.proj[4].value - PD.proj[4].loan, 1e-6);
eq('the IRR solves the after-tax cash flows', PD.cfsT.reduce((s_, c, t) => s_ + c / (1 + PD.irr) ** t, 0), 0, 1e-6);
const flat = projectDeal(DD, AP, new Array(10).fill(150000)), fall = projectDeal(DD, AP, d3.range(1, 11).map((t) => 150000 * 0.99 ** t));
truthy('prices flat then falling: lower IRRs, in order', fall.irr < flat.irr && flat.irr < PD.irr);
eq('no gain, no capital gains tax', fall.cgt, 0);
// a deep fall leaves the sale below the loan: money in, money back each year, money in again at the end, so two rates fit
const deep = projectDeal(DD, AP, d3.range(1, 11).map((t) => 150000 * 0.97 ** t));
eq('a sale below the loan: two rates, so no single IRR', deep.roots.length, 2, 0); eq('  and irr is left undefined', deep.irr, NaN);

// ---------- no negative zero (fourth review) ----------
eq("pct(-0.04) reads 0.0%", pct(-0.04) === '0.0%' ? 1 : 0, 1, 0); eq("sgn(-0.04) has no sign", sgn(-0.04) === '0.0%' ? 1 : 0, 1, 0); eq("sgn(-0.06) keeps it", sgn(-0.06) === '−0.1%' ? 1 : 0, 1, 0);

console.log(fails ? `${fails} of ${n} FAILED` : `all ${n} passed`); process.exit(fails ? 1 : 0);
