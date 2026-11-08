// A portfolio of homes like this one (version 34): the deal analyser's home bought N times, owned by you or by a limited
// company, with tax worked out on the whole portfolio (bands and corporation tax depend on the total) and what taking the
// company's profit out costs. Rates and sources are in config/assumptions.csv.
window.DPM_PORT = (h) => {
  const { $, gbp, pct, num, val, cell, readDeal, getAss, yearCalc, corpTax, projectDeal } = h;

  // one person's income tax: other income at the main rates, then property profit at the property rates, then dividends.
  // The personal allowance goes against other income first (from April 2027 HMRC sets it against employment, trading and
  // pension income first), falls by £1 for every £2 of income over £100,000, and the bands are on taxable income. The
  // first £500 of dividends is taxed at 0% but still uses up its band. Returns the tax on each kind of income.
  const personalTax = (A, other, prop, div, y27) => {
    const total = other + prop + div, edges = [A.basic_rate_band.v, A.additional_threshold.v, Infinity];
    let pa = Math.max(0, A.personal_allowance.v - Math.max(0, total - A.pa_taper_start.v) / 2), used = 0;
    const main = [A.tax_basic.v, A.tax_higher.v, A.tax_additional.v];          // 2026-27: property income is charged at the main rates
    const rates = { other: main, prop: y27 ? [A.tax_basic_2027.v, A.tax_higher_2027.v, A.tax_additional_2027.v] : main, div: [A.div_ordinary.v, A.div_upper.v, A.div_additional.v] };
    const tax = { other: 0, prop: 0, div: 0, pa: 0 };
    [['other', other], ['prop', prop], ['div', div]].forEach(([k, amt]) => {
      const off = Math.min(pa, Math.max(0, amt)); pa -= off; tax.pa += off;
      const start = used; used += Math.max(0, amt) - off; let free = k === 'div' ? A.div_allowance.v : 0;
      for (let i = 0, lo = 0; i < 3; lo = edges[i], i++) {
        const part = Math.max(0, Math.min(used, edges[i]) - Math.max(start, lo)), z = Math.min(part, free); free -= z;
        tax[k] += (part - z) * rates[k][i] / 100;
      }
    });
    tax.taxable = used; return tax;
  };
  // the deal's "other taxable income" is after the personal allowance; back to the income before it
  const grossOf = (A, t) => {
    const pa = A.personal_allowance.v, s = A.pa_taper_start.v;
    if (!(t > 0)) return 0; if (t <= s - pa) return t + pa; const g = (t + pa + s / 2) / 1.5; return g >= s + 2 * pa ? t : g;
  };

  // the whole portfolio for one owner, year 1 of the deal's tax year
  const portfolio = (A, base, owner, n, prem, coCost, other) => {
    const company = owner === 'company', d = { ...base, owner, n: company ? n : 1, prem: company ? prem : 0, co: company ? coCost / n : 0, rate: base.rate - base.prem + (company ? prem : 0) };
    const y27 = d.taxYear === '2027', y = yearCalc(d, A, { rent: d.rent, costMult: 1, balance: d.price * (1 - d.dep), year2027: y27 });
    const N = (x) => x * n, opex = N(y.opex - d.co), co = company ? coCost : 0, interest = N(y.interest), principal = N(y.principal);
    const pre = N(y.collected) - opex - co - interest;                      // profit before tax
    const o = { d, n, price: N(d.price), cashIn: N(projectDeal(d, A).cashIn), rent: N(y.collected), opex, co, interest, principal, pre, loan: d.price * (1 - d.dep) };
    if (company) {
      o.tax = corpTax(pre, A);
      o.after = pre - o.tax - principal;                                     // cash after tax, in the company
      o.div = Math.max(0, o.after);                                          // paid out: profit after tax, less any capital repaid
      const t0 = personalTax(A, other, 0, 0, y27), t1 = personalTax(A, other, 0, o.div, y27);
      o.divTax = t1.other + t1.div - t0.other - t0.div;                      // includes allowance lost to the taper
      o.icr = A.icr_basic.v;
    } else {
      // interest isn't deducted: a credit at the property basic rate on the lowest of the interest, the property profit and
      // the income above the allowance (Section 24)
      const prop = pre + interest, t0 = personalTax(A, other, 0, 0, y27), t1 = personalTax(A, other, prop, 0, y27);
      const credit = (y27 ? A.finance_credit_2027.v : A.finance_credit.v) / 100 * Math.max(0, Math.min(interest, prop, t1.taxable));
      o.tax = Math.max(0, t1.other + t1.prop - t0.other - t0.prop - credit);
      o.after = pre - o.tax - principal;
      o.icr = t1.taxable > A.basic_rate_band.v ? A.icr_higher.v : A.icr_basic.v;   // lenders test higher-rate taxpayers harder
      o.band = t1.taxable > A.additional_threshold.v ? 'additional' : t1.taxable > A.basic_rate_band.v ? 'higher' : 'basic';
    }
    const sr = d.fix5 ? d.rate : Math.max(A.stress_rate.v / 100, d.rate + 0.02);          // as the deal's own stress test
    o.need = o.loan * sr * o.icr / 100 / 12; o.pass = d.rent >= o.need - 0.5;
    return o;
  };

  const render = () => {
    const A = getAss(), tb = $('#port-table tbody'), note = $('#port-note'); if (!tb) return;
    tb.replaceChildren(); note.textContent = '';
    const need = ['ltd_homes', 'div_ordinary', 'personal_allowance', 'additional_threshold', 'tax_additional_2027'];
    if (!A || need.some((k) => !A[k])) return;
    const base = readDeal();
    if (![base.price, base.rent, base.dep, base.rate].every(isFinite) || base.price <= 0 || base.rent <= 0) { note.textContent = 'Fill in the deal above to see a portfolio of homes like it.'; return; }
    const n = Math.max(1, Math.round(num(val('#co-homes'))) || A.ltd_homes.v), prem = (num(val('#co-prem')) || 0) / 100, coCost = num(val('#co-cost')) || 0;
    const otherT = isFinite(base.income) ? base.income : A.cgt_other_income.v, other = grossOf(A, otherT);
    const P = portfolio(A, base, 'basic', n, prem, coCost, other), C = portfolio(A, base, 'company', n, prem, coCost, other);   // 'basic': yearCalc's own tax isn't used
    const keep = C.after, div = C.after - C.divTax;
    const m = (v) => gbp(v / 12), per = (v) => gbp(v / 12 / n), check = (o) => `${o.pass ? 'Passes' : 'Fails'}: needs ${gbp(o.need)} a month (${pct(o.icr, 0)} cover)`;
    const R = [
      ['Homes', String(n), String(n), String(n)],
      ['Bought for', gbp(P.price), gbp(C.price), gbp(C.price)],
      ['Your cash in: deposits, stamp duty, fees, works', gbp(P.cashIn), gbp(C.cashIn), gbp(C.cashIn)],
      ['Mortgage rate', pct(P.d.rate * 100, 2), pct(C.d.rate * 100, 2), pct(C.d.rate * 100, 2)],
      ['Rent collected, after voids', gbp(P.rent), gbp(C.rent), gbp(C.rent)],
      ['Letting, maintenance, insurance, safety checks, register', gbp(-P.opex), gbp(-C.opex), gbp(-C.opex)],
      ['Company running costs: accounts, tax return, Companies House', '—', gbp(-C.co), gbp(-C.co)],
      ['Mortgage interest', gbp(-P.interest), gbp(-C.interest), gbp(-C.interest)],
      ['Profit before tax', gbp(P.pre), gbp(C.pre), gbp(C.pre), true],
      ['Tax on the profit: income tax (less the interest credit) or corporation tax', gbp(-P.tax), gbp(-C.tax), gbp(-C.tax)],
      ['Tax as a share of the profit', P.pre > 0 ? pct(P.tax / P.pre * 100, 1) : '—', C.pre > 0 ? pct(C.tax / C.pre * 100, 1) : '—', C.pre > 0 ? pct(C.tax / C.pre * 100, 1) : '—'],
      ...(base.mtype === 'rep' ? [['Mortgage capital repaid', gbp(-P.principal), gbp(-C.principal), gbp(-C.principal)]] : []),
      ['Cash after tax', gbp(P.after), gbp(C.after) + ' in the company', gbp(C.after) + ' in the company', true],
      ['Tax on taking it out', '—', '£0', gbp(-C.divTax)],
      ['Yours, a year', gbp(P.after), gbp(keep), gbp(div), true],
      ['A month', m(P.after), m(keep), m(div)],
      ['A month for each home', per(P.after), per(keep), per(div)],
      ['Year 1 return on your cash', pct(P.after / P.cashIn * 100, 1), pct(keep / C.cashIn * 100, 1), pct(div / C.cashIn * 100, 1)],
      ["Lender's rent check, each home", check(P), check(C), check(C)]
    ];
    R.forEach(([label, a, b, c, strong]) => {
      const tr = document.createElement('tr'); if (strong) tr.className = 'strong';
      cell(tr, label); [a, b, c].forEach((x) => cell(tr, x, strong && /^−£/.test(x) ? 'r badc' : 'r'));
      tb.appendChild(tr);
    });
    const y27 = base.taxYear === '2027', who = otherT > 0 ? `With your other taxable income of ${gbp(otherT)}` : 'With no other income';
    note.textContent = `${who}, the portfolio's profit is taxed at your ${P.band} rate if you own it yourself (${y27 ? 'property rates from April 2027' : '2026-27 rates'}). `
      + `Every home is taken to be like this one, with the deal's rent, costs and mortgage; corporation tax and your tax bands are worked out on the total. `
      + (base.mtype === 'rep' ? 'Dividends are paid from what is left after repaying mortgage capital. ' : '')
      + `Paying back money you lent the company costs no tax, so until your loan is repaid the middle column is what you can take; after that, dividends are taxed at ${pct(A.div_ordinary.v, 2)}, ${pct(A.div_upper.v, 2)} and ${pct(A.div_additional.v, 2)} above a ${gbp(A.div_allowance.v)} allowance.`
      + (base.price > 500000 ? ' A company buying a home for over £500,000 can pay a flat 17% stamp duty instead (with reliefs for letting businesses), which this doesn\'t model.' : '');
  };
  return { render, personalTax, grossOf };
};
