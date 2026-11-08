// A portfolio of homes (versions 34-35): copies of the deal analyser's home, or your saved homes with this one, owned by you
// or by a limited company. Year 1 and the whole holding period with the sale, tax worked out on the whole portfolio (bands
// and corporation tax depend on the total), interest the company pays you on your loan, what taking its money out costs
// (dividends, or closing the company), and the lender's checks across everything. Rates and sources: config/assumptions.csv.
window.DPM_PORT = (h) => {
  const { $, gbp, pct, num, val, cell, readDeal, getAss, yearCalc, annuity, sdlt, corpTax, irrRoots, savedHomes } = h;

  // one person's income tax: other income at the main rates, then property profit at the property rates, then savings
  // income (interest), then dividends. The personal allowance goes against other income first (HMRC's order from April 2027:
  // employment, trading and pension income first), falls by £1 for every £2 of income over £100,000; the bands are on
  // taxable income. Taxed at 0% but still using their band: the starting rate for savings (£5,000, less taxable non-savings
  // income), the personal savings allowance (£1,000 basic rate, £500 higher, none additional) and the £500 dividend
  // allowance. Returns the tax on each kind of income.
  const personalTax = (A, other, prop, div, y27, sav = 0) => {
    const total = other + prop + sav + div, edges = [A.basic_rate_band.v, A.additional_threshold.v, Infinity];
    let pa = Math.max(0, A.personal_allowance.v - Math.max(0, total - A.pa_taper_start.v) / 2), used = 0;
    const all = Math.max(0, total - pa), psa = all > A.additional_threshold.v ? 0 : all > A.basic_rate_band.v ? A.psa_higher.v : A.psa_basic.v;
    const main = [A.tax_basic.v, A.tax_higher.v, A.tax_additional.v];          // 2026-27: property income is charged at the main rates
    const rates = { other: main, prop: y27 ? [A.tax_basic_2027.v, A.tax_higher_2027.v, A.tax_additional_2027.v] : main,
      sav: y27 ? [A.sav_basic_2027.v, A.sav_higher_2027.v, A.sav_additional_2027.v] : [A.sav_basic.v, A.sav_higher.v, A.sav_additional.v], div: [A.div_ordinary.v, A.div_upper.v, A.div_additional.v] };
    const tax = { other: 0, prop: 0, sav: 0, div: 0 };
    [['other', other], ['prop', prop], ['sav', sav], ['div', div]].forEach(([k, amt]) => {
      const off = Math.min(pa, Math.max(0, amt)); pa -= off;
      let free = k === 'div' ? A.div_allowance.v : k === 'sav' ? Math.max(0, A.sav_start_limit.v - used) + psa : 0;
      const start = used; used += Math.max(0, amt) - off;
      for (let i = 0, lo = 0; i < 3; lo = edges[i], i++) {
        const part = Math.max(0, Math.min(used, edges[i]) - Math.max(start, lo)), z = Math.min(part, free); free -= z;
        tax[k] += (part - z) * rates[k][i] / 100;
      }
    });
    tax.taxable = used; tax.total = tax.other + tax.prop + tax.sav + tax.div; return tax;
  };
  // the deal's "other taxable income" is after the personal allowance; back to the income before it
  const grossOf = (A, t) => {
    const pa = A.personal_allowance.v, s = A.pa_taper_start.v;
    if (!(t > 0)) return 0; if (t <= s - pa) return t + pa; const g = (t + pa + s / 2) / 1.5; return g >= s + 2 * pa ? t : g;
  };
  // capital gains tax for one person: the annual exempt amount, then 18% in what's left of the basic-rate band, 24% above
  const cgt = (A, gain, taxableIncome) => {
    const t = Math.max(0, gain - A.cgt_aea.v), lo = Math.min(t, Math.max(0, A.basic_rate_band.v - taxableIncome));
    return lo * A.cgt_basic.v / 100 + (t - lo) * A.cgt_higher.v / 100;
  };

  // the homes: copies of this deal, or your saved homes (each with its own price and rent) and this one
  const homesOf = (A, base, src, n) => {
    const me = { label: 'This home', d: base };
    if (src !== 'saved') return Array.from({ length: n }, () => me);
    const saved = (savedHomes() || []).filter((s) => s.price > 0 && s.rent > 0)
      .map((s) => ({ label: s.label || 'Saved home', d: { ...base, price: +s.price, rent: +s.rent, works: 0, epc: 0, improve: 0 } }));
    return [me, ...saved];
  };
  const forOwner = (d, owner, prem, coShare) => ({ ...d, owner: owner === 'company' ? 'company' : 'basic', prem: owner === 'company' ? prem : 0,
    co: owner === 'company' ? coShare : 0, rate: d.rate - (d.prem || 0) + (owner === 'company' ? prem : 0) });

  // the whole portfolio over the holding period, one owner. policy: 'pay' takes what the company can pay each year (your
  // loan first, then dividends) or 'keep' leaves it in the company until the end. When each home's fixed rate ends it is
  // remortgaged at o.refiRate (blank: the deal's rate) with a new arrangement fee, except in the sale year; a repayment
  // mortgage then restarts on its balance over the term left. o.refi: 'keep' the same loan, 'take' borrow back up to the
  // deposit's loan-to-value (as far as the rent covers the lender's test) and take the cash, or 'buy' put it (and, for a
  // company keeping its profit, that too) towards more homes like this one, each borrowing what its own rent passes the
  // lender's test for. Returns year 1, the totals and the cash flows to you for each way out.
  const project = (A, homes, owner, o) => {
    const company = owner === 'company', H = Math.max(1, Math.round(A.hold_years.v)), sell = A.selling_costs.v / 100;
    const ds = homes.map((x) => forOwner(x.d, owner, o.prem, 0)), base = ds[0];
    const gR = isFinite(base.gRent) ? base.gRent : 0, gP = isFinite(base.gPrice) ? base.gPrice : 0, gC = isFinite(base.gCost) ? base.gCost : 0;
    const costIn = (d) => d.price * d.dep + sdlt(d.price, A) + d.legal + d.fee + d.works + d.epc;     // as the deal's own cash in
    const cashIn = ds.reduce((s, d) => s + costIn(d), 0), repairs = ds.reduce((s, d) => s + Math.max(0, d.works + d.epc - d.improve), 0);
    const F = base.fix5 ? 5 : 2, rate0 = isFinite(o.refiRate) ? o.refiRate : base.rate - base.prem, refiRate = rate0 + (company ? o.prem : 0);
    // each home: when it was bought (0 = at the start), its loan, rate, and what it cost (for the gain and for what interest
    // a person can set against the rent: only on borrowing up to what the home cost, HMRC PIM2105), and its monthly repayment
    const P_ = ds.map((d) => { const bal = d.price * (1 - d.dep); return { d, s: 0, bal, rate: d.rate, pay: annuity(bal, d.rate, d.term), cost: d.price, sdlt: sdlt(d.price, A) }; });
    const T = { rent: 0, interest: 0, tax: 0, yourTax: 0, toYou: 0, dl: 0, ct: 0, fees: 0, released: 0, bought: 0 };
    let carryFin = 0, carryLoss = 0, ctLoss = 0, coCash = 0, pot = 0, loan = company && o.funding !== 'shares' ? cashIn : 0, y1 = null, band = 'basic';
    const capital = company && o.funding === 'shares' ? cashIn : 0;
    const cfs = [-cashIn], other = o.other, stress = (r) => (base.fix5 ? r : Math.max(A.stress_rate.v / 100, r + 0.02));
    // the most a lender will lend on a year's rent at the remortgage rate: 125% cover (company or basic rate) or 145%
    const lendOn = (rentY) => rentY / ((company || band === 'basic' ? A.icr_basic.v : A.icr_higher.v) / 100 * stress(refiRate));
    for (let t = 1; t <= H; t++) {
      const y27 = t > 1 || base.taxYear === '2027';
      // remortgage the homes whose fix has just ended (not in the sale year: they're sold at its end)
      let fees = 0, released = 0;
      P_.forEach((hm) => {
        const age = t - 1 - hm.s; if (t >= H || !(age > 0 && age % F === 0) || !(hm.bal > 0)) return;
        fees += hm.d.fee; hm.rate = refiRate;
        if (o.refi !== 'keep') {
          const most = Math.min((1 - hm.d.dep) * hm.cost * (1 + gP) ** age, lendOn(hm.d.rent * (1 + gR) ** (t - 1) * 12));
          if (most > hm.bal) { released += most - hm.bal; hm.bal = most; }
        }
        hm.pay = annuity(hm.bal, refiRate, hm.d.term - age);          // repayments restart on the balance over the term left
      });
      let coll = 0, opex = 0, int = 0, prin = 0, allowed = 0;
      P_.forEach((hm) => {
        if (hm.s >= t) return;
        const start = hm.bal, y = yearCalc({ ...hm.d, rate: hm.rate, co: 0 }, A, { rent: hm.d.rent * (1 + gR) ** (t - 1), costMult: (1 + gC) ** (t - 1), balance: hm.bal, year2027: y27, pay: hm.pay });
        coll += y.collected; opex += y.opex; int += y.interest; prin += y.principal; hm.bal = y.endBalance;
        allowed += start > 0 ? y.interest * Math.min(1, hm.cost / start) : 0;
      });
      const coC = company ? o.coCost * (1 + gC) ** (t - 1) : 0; opex += coC;
      const rep = t === 1 ? repairs : 0, row = { t, coll, opex, int, prin, fees, released };
      T.rent += coll; T.interest += int; T.fees += fees; T.released += released;
      if (!company) {
        // Section 24: the interest isn't deducted; a credit at the property basic rate on the lowest of the finance costs
        // (with any carried forward), the property profit (after losses brought forward) and the taxable income
        let prop = coll - opex - rep - carryLoss; carryLoss = Math.max(0, -prop); prop = Math.max(0, prop);
        const t0 = personalTax(A, other, 0, 0, y27), t1 = personalTax(A, other, prop, 0, y27), fin = allowed + fees + carryFin;
        const relieved = Math.max(0, Math.min(fin, prop, t1.taxable)); carryFin = fin - relieved;
        const tax = Math.max(0, t1.total - t0.total - relieved * (y27 ? A.finance_credit_2027.v : A.finance_credit.v) / 100);
        let cash = coll - opex - int - fees - prin - tax;
        if (o.refi === 'take') cash += released; else if (o.refi === 'buy') pot += released;
        band = t1.taxable > A.additional_threshold.v ? 'additional' : t1.taxable > A.basic_rate_band.v ? 'higher' : 'basic';
        Object.assign(row, { pre: coll - opex - int - fees, tax, cash, toYou: cash, taxable: t1.taxable, band });
        T.tax += tax; T.toYou += cash; cfs.push(cash);
      } else {
        const dl = loan * o.dlRate;                                   // interest the company pays you on your loan
        let profit = coll - opex - int - fees - dl - rep - ctLoss; ctLoss = Math.max(0, -profit);
        const ct = corpTax(Math.max(0, profit), A); coCash += coll - opex - int - fees - prin - dl - ct;
        if (o.refi === 'take') coCash += released; else if (o.refi === 'buy') pot += released;
        let repaid = 0, div = 0, lent = 0;
        if (coCash < 0) { lent = -coCash; loan += lent; coCash = 0; }   // a shortfall: you lend the company the difference
        else if (o.policy === 'pay') { repaid = Math.min(coCash, loan); loan -= repaid; div = coCash - repaid; coCash = 0; }
        const t0 = personalTax(A, other, 0, 0, y27), t1 = personalTax(A, other, 0, div, y27, dl), yt = t1.total - t0.total;
        const toYou = dl + repaid + div - lent - yt;
        Object.assign(row, { pre: coll - opex - int - fees - dl, ct, dl, repaid, div, lent, yourTax: yt, toYou, kept: coCash });
        T.ct += ct; T.dl += dl; T.yourTax += yt; T.toYou += toYou; T.tax += ct + yt; cfs.push(toYou);
      }
      // more homes like the first one, bought at the end of the year with what has built up (the pot first, then a company's
      // kept profit), each borrowing the deposit's loan-to-value or what next year's rent passes the lender's test for
      if (o.refi === 'buy' && t < H) {
        const price = base.price * (1 + gP) ** t, tax = sdlt(price, A), nd = { ...base, price, works: 0, epc: 0, improve: 0 };
        const borrow = Math.max(0, Math.min(price * (1 - base.dep), lendOn(base.rent * (1 + gR) ** t * 12))), need = price - borrow + tax + base.legal + base.fee;
        while (need > 0 && pot + (company ? coCash : 0) >= need) {
          const p = Math.min(pot, need); pot -= p; coCash -= need - p; T.bought += 1;
          P_.push({ d: nd, s: t, bal: borrow, rate: refiRate, pay: annuity(borrow, refiRate, base.term), cost: price, sdlt: tax });
        }
      }
      if (t === 1) y1 = row;
      if (t === H) T.last = row;
    }
    // the sale at the end of the holding period: every home sold, mortgages repaid
    const values = P_.map((hm) => hm.cost * (1 + gP) ** (H - hm.s)), net = values.reduce((s, v) => s + v * (1 - sell), 0), debt = P_.reduce((s, hm) => s + hm.bal, 0);
    const gain = P_.reduce((s, hm, i) => s + values[i] * (1 - sell) - (hm.cost + hm.sdlt + hm.d.legal + hm.d.improve), 0);
    const S = { sold: net, debt, gain, value: values.reduce((s, v) => s + v, 0), homes: P_.length };
    if (!company) {
      S.kept = pot; S.tax = cgt(A, gain, T.last.taxable); S.toYou = net - debt - S.tax + pot;
      const cf = cfs.slice(); cf[H] += S.toYou;
      return { company, cashIn, y1, T, S, refi: { F, rate: rate0 }, exits: { own: { tax: S.tax, toYou: S.toYou, cf } } };
    }
    // the company pays corporation tax on the gain on top of that year's profit (losses brought forward go against it too)
    coCash += pot; S.kept = coCash;
    const lastProfit = Math.max(0, T.last.pre - ctLoss);
    S.ct = corpTax(Math.max(0, lastProfit + gain), A) - corpTax(lastProfit, A);
    const left = coCash + net - debt - S.ct, repay = Math.min(Math.max(0, left), loan), rest = Math.max(0, left - repay);
    // way out 1: closing the company (a members' voluntary liquidation): the rest is a capital distribution, taxed as a gain
    // above what you paid for the shares
    const mvl = Math.min(rest, A.mvl_cost.v), dist = rest - mvl, close = cgt(A, Math.max(0, dist - capital), Math.max(0, other - A.personal_allowance.v));
    // way out 2: share capital handed back (a capital reduction, no income tax), the rest paid as dividends in one tax year
    const back = Math.min(rest, capital), d0 = personalTax(A, other, 0, 0, true), d1 = personalTax(A, other, 0, rest - back, true), divT = d1.total - d0.total;
    const mk = (tax, cost) => { const cf = cfs.slice(); cf[H] += repay + rest - cost - tax; return { tax, cost, toYou: repay + rest - cost - tax, cf }; };
    Object.assign(S, { coCash, repay, rest, loan });
    return { company, cashIn, y1, T, S, refi: { F, rate: rate0 }, exits: { close: mk(close, mvl), divs: mk(divT, 0) } };
  };

  // the lender's view of the whole portfolio: rent cover at the stress rate and borrowing against value (year 1)
  const lenderView = (A, homes, owner, prem, higher) => {
    const ds = homes.map((x) => forOwner(x.d, owner, prem, 0));
    const icr = owner === 'company' || !higher ? A.icr_basic.v : A.icr_higher.v;
    const rent = ds.reduce((s, d) => s + d.rent * 12, 0), stressed = ds.reduce((s, d) => s + d.price * (1 - d.dep) * (d.fix5 ? d.rate : Math.max(A.stress_rate.v / 100, d.rate + 0.02)), 0);
    const loans = ds.reduce((s, d) => s + d.price * (1 - d.dep), 0), value = ds.reduce((s, d) => s + d.price, 0);
    const worst = ds.map((d) => d.rent * 12 / (d.price * (1 - d.dep) * (d.fix5 ? d.rate : Math.max(A.stress_rate.v / 100, d.rate + 0.02))) * 100).filter(isFinite);
    return { icr, cover: stressed > 0 ? rent / stressed * 100 : Infinity, ltv: loans / value * 100, worst: worst.length ? Math.min(...worst) : Infinity };
  };

  const table = (sel, R) => {
    const tb = $(sel + ' tbody'); tb.replaceChildren();
    R.forEach(([label, a, b, c, strong]) => {
      const tr = document.createElement('tr'); if (strong) tr.className = 'strong';
      cell(tr, label); [a, b, c].forEach((x) => cell(tr, x, strong && /^−£/.test(x) ? 'r badc' : 'r'));
      tb.appendChild(tr);
    });
  };
  const clear = (msg) => { ['#port-table', '#port-10y'].forEach((s) => { const tb = $(s + ' tbody'); if (tb) tb.replaceChildren(); }); $('#port-note').textContent = msg || ''; $('#port-10y-note').textContent = ''; };

  const render = () => {
    const A = getAss(); if (!$('#port-table')) return;
    const need = ['ltd_homes', 'div_ordinary', 'personal_allowance', 'additional_threshold', 'tax_additional_2027', 'sav_basic_2027', 'mvl_cost', 'ltd_loan_rate'];
    if (!A || need.some((k) => !A[k])) { clear(); return; }
    const base = readDeal();
    if (![base.price, base.rent, base.dep, base.rate].every(isFinite) || base.price <= 0 || base.rent <= 0) { clear('Fill in the deal above to see a portfolio of homes like it.'); return; }
    const srcSel = $('#co-source'), savedN = (savedHomes() || []).filter((s) => s.price > 0 && s.rent > 0).length;
    if (srcSel) { const opt = srcSel.querySelector('option[value="saved"]'); opt.disabled = !savedN; opt.textContent = savedN ? `Your ${savedN} saved home${savedN > 1 ? 's' : ''} and this one` : 'Your saved homes and this one (none saved with a deal yet)'; if (!savedN) srcSel.value = 'copies'; }
    const src = srcSel ? srcSel.value : 'copies', n = Math.max(1, Math.round(num(val('#co-homes'))) || A.ltd_homes.v);
    const homes = homesOf(A, base, src, n), N = homes.length;
    const o = { prem: (num(val('#co-prem')) || 0) / 100, coCost: num(val('#co-cost')) || 0, dlRate: (num(val('#co-dlrate')) || 0) / 100, policy: val('#co-policy') || 'pay', funding: val('#co-funding') || 'loan', refi: val('#co-refi') || 'keep', refiRate: num(val('#co-refirate')) / 100 };
    const otherT = isFinite(base.income) ? base.income : A.cgt_other_income.v; o.other = grossOf(A, otherT);
    const rf = $('#co-refirate'); if (rf) rf.placeholder = ((base.rate - base.prem) * 100).toFixed(2);       // blank: the deal's rate
    const P = project(A, homes, 'basic', o), C = project(A, homes, 'company', o), p1 = P.y1, c1 = C.y1;
    const LP = lenderView(A, homes, 'basic', o.prem, p1.band !== 'basic'), LC = lenderView(A, homes, 'company', o.prem, false);
    const m = (v) => gbp(v / 12), per = (v) => gbp(v / 12 / N), bought = gbp(homes.reduce((s, x) => s + x.d.price, 0));
    const lender = (L) => `${L.cover >= L.icr - 0.05 ? 'Passes' : 'Fails'}: rent covers ${pct(Math.min(L.cover, 999), 0)} of stressed interest (needs ${pct(L.icr, 0)})`;
    const Ck = o.policy === 'keep' ? c1 : project(A, homes, 'company', { ...o, policy: 'keep' }).y1, Cp = o.policy === 'pay' ? c1 : project(A, homes, 'company', { ...o, policy: 'pay' }).y1;
    table('#port-table', [
      ['Homes', String(N), String(N), String(N)],
      ['Bought for', bought, bought, bought],
      ['Your cash in: deposits, stamp duty, fees, works', gbp(P.cashIn), gbp(C.cashIn), gbp(C.cashIn)],
      ['Mortgage rate', pct((base.rate - base.prem) * 100, 2), pct((base.rate - base.prem + o.prem) * 100, 2), pct((base.rate - base.prem + o.prem) * 100, 2)],
      ['Rent collected, after voids', gbp(p1.coll), gbp(c1.coll), gbp(c1.coll)],
      ['Letting, maintenance, insurance, safety checks, register' + (o.coCost ? ', company running costs' : ''), gbp(-p1.opex), gbp(-c1.opex), gbp(-c1.opex)],
      ['Mortgage interest', gbp(-p1.int), gbp(-c1.int), gbp(-c1.int)],
      ['Interest the company pays you on your loan', '—', gbp(-Ck.dl), gbp(-Cp.dl)],
      ['Profit before tax', gbp(p1.pre), gbp(Ck.pre), gbp(Cp.pre), true],
      ['Tax on the profit: income tax (less the interest credit) or corporation tax', gbp(-p1.tax), gbp(-Ck.ct), gbp(-Cp.ct)],
      ...(base.mtype === 'rep' ? [['Mortgage capital repaid', gbp(-p1.prin), gbp(-c1.prin), gbp(-c1.prin)]] : []),
      ['Paid to you: loan interest, then your loan back, then dividends', '—', gbp(Ck.dl), gbp(Cp.dl + Cp.repaid + Cp.div)],
      ['Your tax on what the company pays you', '—', gbp(-Ck.yourTax), gbp(-Cp.yourTax)],
      ...(Ck.lent || Cp.lent ? [['You lend the company its shortfall', '—', gbp(-Ck.lent), gbp(-Cp.lent)]] : []),
      ['Yours, a year', gbp(p1.toYou), gbp(Ck.toYou), gbp(Cp.toYou), true],
      ['Left in the company', '—', gbp(Ck.kept), gbp(Cp.kept)],
      ['A month', m(p1.toYou), m(Ck.toYou), m(Cp.toYou)],
      ['A month for each home', per(p1.toYou), per(Ck.toYou), per(Cp.toYou)],
      ['Year 1 return on your cash, to you', pct(p1.toYou / P.cashIn * 100, 1), pct(Ck.toYou / C.cashIn * 100, 1), pct(Cp.toYou / C.cashIn * 100, 1)],
      ["Lender's check, whole portfolio", lender(LP), lender(LC), lender(LC)],
      ['Borrowing against value, whole portfolio', pct(LP.ltv, 0), pct(LC.ltv, 0), pct(LC.ltv, 0)],
      ...(N > 1 && src === 'saved' ? [['Weakest home on its own: rent cover', pct(LP.worst, 0), pct(LC.worst, 0), pct(LC.worst, 0)]] : [])
    ]);
    const H = Math.round(A.hold_years.v), Ex = P.exits.own, Cl = C.exits.close, Dv = C.exits.divs;
    const irr = (cf) => { const r = irrRoots(cf); return r.length === 1 ? pct(r[0] * 100, 1) : '—'; };
    const sum = (cf) => cf.reduce((s, v) => s + v, 0);
    table('#port-10y', [
      ['Your cash in at the start', gbp(-P.cashIn), gbp(-C.cashIn), gbp(-C.cashIn)],
      [`Rent collected over ${H} years`, gbp(P.T.rent), gbp(C.T.rent), gbp(C.T.rent)],
      ['Mortgage interest', gbp(-P.T.interest), gbp(-C.T.interest), gbp(-C.T.interest)],
      ['Interest the company paid you on your loan', '—', gbp(C.T.dl), gbp(C.T.dl)],
      ['Remortgage fees', gbp(-P.T.fees), gbp(-C.T.fees), gbp(-C.T.fees)],
      ...(o.refi !== 'keep' ? [[o.refi === 'take' ? (o.policy === 'keep' ? 'Cash released by remortgaging: paid to you, or kept in the company until the sale' : 'Cash released by remortgaging, taken out') : 'Cash released by remortgaging, put into more homes', gbp(P.T.released), gbp(C.T.released), gbp(C.T.released)]] : []),
      ...(o.refi === 'buy' ? [['Homes bought with it (and, if the company keeps its profit, with that)', String(P.T.bought), String(C.T.bought), String(C.T.bought)]] : []),
      ['Income tax, or corporation tax, on the rent', gbp(-P.T.tax), gbp(-C.T.ct), gbp(-C.T.ct)],
      ['Your tax on interest and dividends paid each year', '—', gbp(-C.T.yourTax), gbp(-C.T.yourTax)],
      [`Cash to you during the ${H} years`, gbp(P.T.toYou), gbp(C.T.toYou), gbp(C.T.toYou), true],
      [`Homes sold in year ${H}, after selling costs`, `${gbp(P.S.sold)}${P.S.homes !== N ? ` (${P.S.homes} homes)` : ''}`, `${gbp(C.S.sold)}${C.S.homes !== N ? ` (${C.S.homes} homes)` : ''}`, `${gbp(C.S.sold)}${C.S.homes !== N ? ` (${C.S.homes} homes)` : ''}`],
      ['Mortgages repaid', gbp(-P.S.debt), gbp(-C.S.debt), gbp(-C.S.debt)],
      ['Tax on the gain: capital gains tax, or corporation tax', gbp(-P.S.tax), gbp(-C.S.ct), gbp(-C.S.ct)],
      ['Cash kept back: in the company, or remortgage money not yet spent', gbp(P.S.kept), gbp(C.S.kept), gbp(C.S.kept)],
      [o.funding === 'shares' ? 'Your shortfall loans repaid (tax-free)' : 'Your loan repaid (tax-free)', '—', gbp(C.S.repay), gbp(C.S.repay)],
      ['Closing the company (liquidator)', '—', gbp(-Cl.cost), '—'],
      ['Your tax on taking the rest out', '—', gbp(-Cl.tax), gbp(-Dv.tax)],
      ['Cash to you at the end', gbp(Ex.toYou), gbp(Cl.toYou), gbp(Dv.toYou), true],
      ['Total back to you, less your cash in', gbp(sum(Ex.cf)), gbp(sum(Cl.cf)), gbp(sum(Dv.cf)), true],
      [`${H}-year return (IRR), after every tax`, irr(Ex.cf), irr(Cl.cf), irr(Dv.cf), true],
      [`Or keep them: equity in year ${H}, before any tax on selling`, gbp(P.S.value - P.S.debt + P.S.kept), gbp(C.S.value - C.S.debt + C.S.coCash), gbp(C.S.value - C.S.debt + C.S.coCash)]
    ]);
    const y27 = base.taxYear === '2027';
    $('#port-note').textContent = `${otherT > 0 ? `With your other taxable income of ${gbp(otherT)}` : 'With no other income'}, owning them yourself puts the portfolio's profit in your ${p1.band}-rate band (${y27 ? 'property rates from April 2027' : '2026-27 rates'}). `
      + (src === 'saved' ? `${N} homes: this one and your saved homes, each at the price and rent saved with it, on this deal's deposit, mortgage and costs. ` : `${N} copies of this home, on this deal's rent, costs and mortgage. `)
      + (o.funding === 'shares' ? 'Your money went in as share capital, so what the company pays you is dividends. ' : 'Your money went in as a loan to the company, so it can pay it back to you tax-free before any dividends. ')
      + `Lenders test the whole portfolio: The Mortgage Works, for one, wants 125% rent cover for a company and 145% for a higher-rate taxpayer, and at most 75% borrowing across personally owned homes.`
      + (homes.some((x) => x.d.price > 500000) ? ' A company buying a home for over £500,000 can pay a flat 17% stamp duty instead (with reliefs for letting businesses), which this doesn\'t model.' : '');
    const refiTxt = `Each home is remortgaged when its ${P.refi.F}-year fix ends (except in year ${H}), at ${pct(P.refi.rate * 100, 2)}${o.prem ? ' (plus the company premium)' : ''} with a new ${gbp(base.fee)} fee${base.mtype === 'rep' ? ', repayments restarting over the term left' : ''}`
      + (o.refi === 'keep' ? ', keeping the same loan. ' : `, borrowing back up to ${pct((1 - base.dep) * 100, 0)} of its value as far as the rent passes the lender's test, and ${o.refi === 'take' ? (o.policy === 'keep' ? 'paying the cash out (a company keeping its profit keeps this too)' : 'paying the cash out') : "buying more homes like this one with it, each borrowing what its rent passes the lender's test for"}. Borrowing more than a home cost doesn't get the interest credit when you own it yourself (HMRC PIM2105). `);
    $('#port-10y-note').textContent = `Rents, costs and prices grow at the deal's projection rates; the tax bands stay frozen. ${refiTxt}Each year the company ${o.policy === 'pay' ? 'pays you what it can, your loan first and then dividends' : 'keeps its profit'}${o.dlRate ? ` and pays you ${pct(o.dlRate * 100, 2)} interest on your loan (it withholds 20% and pays it to HMRC quarterly on form CT61; your tax return settles the rest)` : ''}; when it's short of cash, you lend it the difference. `
      + `In year ${H} every home is sold. Closing the company through a members' voluntary liquidation (median fees ${gbp(A.mvl_cost.v)}) turns what's left into a capital gain at ${pct(A.cgt_basic.v, 0)}/${pct(A.cgt_higher.v, 0)}; letting isn't a trade, so Business Asset Disposal Relief doesn't apply, and if you carry on letting through another company within two years HMRC can tax it as a dividend instead. Paying it all as dividends in one tax year pushes most of it into the top rate.`;
  };
  return { render, personalTax, grossOf, cgt, project };
};
