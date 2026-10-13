"""Browser regression tests for the dashboard's state changes (Playwright + Chromium).

  python tests/test_ui.py

With the address lookup built (outputs/dash2/epc_*.csv, a full checkout) it builds a PRIVATE test copy that includes it
(DPM_TEST_BUILD, written to tests/.private/, never published or shared) and runs every case. From the zip alone it
runs the cases that don't need addresses against public/index.html and skips the rest.

Cases
  A1  picking an address whose certificate has no size blanks the size left by the previous address
  A2  a size typed by hand survives clearing the address
  A3  a pasted listing with the same size, rating and bungalow as the selected certificate keeps them
  B   an impossible floor area clears the estimate and everything that came from it, including the asking-price advice
  C   an impossible deposit clears the deal results; a valid one brings them back
  D   with no valid estimate, the Investing scorecard and rent estimate don't show the last home's figures
These change inputs while the page is still counting or typing, not only on settled screens:
  E   an impossible price or rent clears the scorecard and the rent markers worked out from it; fixing it restores them
  F   an impossible price typed while the scorecard is counting up leaves it blank
  G   an impossible floor area typed while the rent estimate is counting up leaves it blank
  G2  the 'Use £… in the deal' button goes with the rent estimate
  H   a price typed key by key (1, 16, 165 ... refused on the way) ends on the same figures as one entered at once
  I   an impossible deposit keeps the cash-purchase scorecard but drops the mortgage break-even marker
  J   impossible flip inputs (months, finance rate, bathrooms) clear the flip appraisal; valid ones restore it
  N1  the Market and Accuracy tabs (market_accuracy.js, a file of their own) draw every chart without an error
  N2  the mortgage-rate slider and a drag across its chart set the deal's rate; a typed rate moves the slider; at the
      break-even rate it reports, the deal's monthly cash flow after tax is £0; dragging to the end of the scale keeps the
      scale still until the drag ends, then grows it
  N3  each end of a tornado bar is the deal's own figure with that input changed (rent raised 10%, rate lowered 1 point)
  N4  the past-decades fan: 22 stretches, its "your growth figure" IRR is the deal's, and an invalid deposit clears all three
      new charts until it is fixed"""
import glob, os, pathlib, subprocess, sys
import pandas as pd
from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parents[1]; D = ROOT / "outputs/dash2"
FULL = any(D.glob("epc_*.csv"))            # your own address lookup is built (never in the shared zip)
if FULL:
    page_file = ROOT / "tests/.private/dashboard_test.html"; page_file.parent.mkdir(parents=True, exist_ok=True)
    (page_file.parent / ".gitignore").write_text("*\n")
    subprocess.run([sys.executable, str(ROOT / "src/build_standalone.py")], check=True, env={**os.environ, "DPM_TEST_BUILD": str(page_file)}, capture_output=True)
else:
    page_file = ROOT / "public/index.html"
results = []
def check(name, ok, detail=""):
    ok = bool(ok); results.append(ok); print("PASS" if ok else "FAIL", name, ("| " + str(detail)) if detail else "")

def epc_cases():
    e = pd.concat([pd.read_csv(f, usecols=["postcode", "address", "epc_type", "floor_area", "rooms", "rating"]) for f in sorted(glob.glob(str(D / "epc_*.csv")))])
    g = e.groupby("postcode")
    miss = next(pc for pc, x in g if x.floor_area.isna().any() and x.floor_area.notna().sum() >= 2 and len(x) <= 40)
    bung = e[(e.epc_type == "Bungalow") & (e.floor_area.round() == 85) & (e.rating == "D")].iloc[0]
    return miss, bung

with sync_playwright() as p:
    b = p.chromium.launch(); pg = b.new_page(viewport={"width": 1366, "height": 900}); errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.on("console", lambda m: errs.append(m.text) if m.type == "error" and "Couldn't draw" in m.text else None)
    pg.route("**/fonts.g*/**", lambda r: r.abort())
    pg.goto(page_file.as_uri()); pg.wait_for_timeout(6000)
    v = lambda s: pg.input_value(s)
    txt = lambda s: pg.evaluate("(s) => { const e = document.querySelector(s); return e ? e.innerText.trim() : null; }", s)
    def options():
        return pg.eval_on_selector_all("#in-address option", "els => els.map(e => [e.value, e.textContent])")
    def set_postcode(pc):
        pg.fill("#in-postcode", pc); pg.dispatch_event("#in-postcode", "input"); pg.wait_for_timeout(2500)
    if FULL:
        miss_pc, bung = epc_cases()
        set_postcode(miss_pc); o = options()
        sized = [x for x in o if x[0] and "m²" in x[1]]; bare = next(x for x in o if x[0] and "m²" not in x[1].split("·")[2])
        pg.select_option("#in-address", sized[0][0]); pg.wait_for_timeout(600); before = v("#in-area")
        pg.select_option("#in-address", bare[0]); pg.wait_for_timeout(600)
        check("A1 certificate with no size blanks the previous size", before != "" and v("#in-area") == "", f"{before} -> {v('#in-area')!r}")
        pg.select_option("#in-address", sized[1][0]); pg.wait_for_timeout(400); pg.fill("#in-area", "90"); pg.select_option("#in-address", ""); pg.wait_for_timeout(600)
        check("A2 typed size survives clearing the address", v("#in-area") == "90", v("#in-area"))
        set_postcode(bung.postcode); o = options()
        pick = next(x for x in o if x[0] and bung.address.lower() in x[1].lower())
        pg.select_option("#in-address", pick[0]); pg.wait_for_timeout(700)
        area0, rating0, bung0 = v("#in-area"), v("#in-rating"), pg.is_checked("#in-bungalow")
        pg.evaluate("() => { const d = document.querySelector('#listing-text').closest('details'); if (d) d.open = true; }")
        pg.fill("#listing-text", f"Detached bungalow for sale, {bung.address}, Doncaster {bung.postcode}. 2 bedrooms, 85 sq m. EPC rating D. Offers over £150,000")
        pg.click("#listing-read"); pg.wait_for_timeout(1500)
        check("A3 listing with the same details keeps them", (v("#in-area"), v("#in-rating"), pg.is_checked("#in-bungalow")) == (area0, rating0, bung0) and area0 == "85" and bung0,
              f"before {(area0, rating0, bung0)} after {(v('#in-area'), v('#in-rating'), pg.is_checked('#in-bungalow'))}; parser said: {txt('#listing-found')}")
        pg.select_option("#in-address", "")
    else:
        print("SKIP A1-A3: no address data in this copy (run from a full checkout)")
    # B: impossible size clears everything that came from the estimate
    set_postcode("DN4 7HA"); pg.select_option("#in-type", "S"); pg.fill("#in-area", "85")
    pg.evaluate("() => document.querySelectorAll('details').forEach((d) => { if (d.querySelector('#in-asking')) d.open = true; })")
    pg.fill("#in-asking", "40000"); pg.wait_for_timeout(1200)
    cheap = txt("#v-ask-note") or ""; comps0 = pg.eval_on_selector_all("#comps-table tbody tr", "e => e.length")
    pg.fill("#in-area", "-85"); pg.wait_for_timeout(900)
    after = dict(base=txt("#v-base"), note=txt("#v-ask-note"), comps=pg.eval_on_selector_all("#comps-table tbody tr", "e => e.length"),
                 why=pg.eval_on_selector_all("#why-chart svg", "e => e.length"), whatif=pg.eval_on_selector_all("#wi-kv dt", "e => e.length"), err=txt("#pc-err"))
    check("B impossible size clears the estimate and its advice", "cheap" in cheap.lower() and comps0 > 0 and after["base"] == "—" and not after["note"] and after["comps"] == 0
          and after["why"] == 0 and after["whatif"] == 0 and "between" in (after["err"] or ""), after)
    # D: other tabs don't keep the last home's figures
    pg.click("#tab-invest"); pg.wait_for_timeout(1200)
    check("D Investing shows no figures from the cleared estimate", txt("#inv-title") == "Pick a property on the first tab" and txt("#rent-est") == "—" and not txt("#rent-range"),
          (txt("#inv-title"), txt("#rent-est"), txt("#rent-range")))
    pg.click("#tab-value"); pg.fill("#in-area", "85"); pg.fill("#in-asking", ""); pg.wait_for_timeout(900)
    check("B2 a valid size brings the estimate back", txt("#v-base") not in ("—", None) and not txt("#pc-err"), txt("#v-base"))
    # C: impossible deposit
    pg.click("#tab-invest"); pg.wait_for_timeout(1200); ok_cash = txt("#r-cash")
    pg.fill("#b-deposit", "150"); pg.wait_for_timeout(600)
    cleared = (txt("#r-cash"), txt("#r-irr"), pg.eval_on_selector_all("#r-detail dt", "e => e.length"), pg.eval_on_selector_all("#proj-table tbody tr", "e => e.length"))
    pg.fill("#b-deposit", "25"); pg.wait_for_timeout(600)
    check("C impossible deposit clears the deal, a valid one restores it", ok_cash != "—" and cleared[:2] == ("—", "—") and cleared[2:] == (0, 0) and txt("#r-cash") != "—", (ok_cash, cleared, txt("#r-cash")))

    # ---- the cases below change inputs while the page is still drawing or counting, not only on settled screens ----
    tc = lambda s: pg.evaluate("(s) => { const e = document.querySelector(s); return e ? e.textContent : ''; }", s)
    SCORE = ["#inv-z", "#inv-total", "#inv-above", "#inv-vs"]
    def score():
        return dict(figs=[txt(s) for s in SCORE], verdict=txt("#inv-verdict"), rows=pg.eval_on_selector_all("#inv-rows .inv-row", "e => e.length"))
    blank = lambda s: s["figs"] == ["—"] * 4 and not s["verdict"] and s["rows"] == 0
    # change a field and then another inside the page, two animation frames apart, so the second edit lands mid count-up
    MID = """async ([s1, v1, s2, v2]) => {
      const set = (s, v) => { const e = document.querySelector(s); e.value = v; e.dispatchEvent(new Event('input', { bubbles: true })); };
      set(s1, v1); await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
      const during = document.querySelector('#inv-total').textContent; set(s2, v2); return during; }"""
    pg.wait_for_timeout(900); price0, rent0 = v("#b-price"), v("#b-rent"); s0 = score(); ladder0 = tc("#rent-chart")
    # E: a price or rent the deal refuses clears the scorecard and the rent markers worked out from the price; fixing it brings them back
    seen = []
    for sel, bad in (("#b-price", "-5"), ("#b-price", "500"), ("#b-price", ""), ("#b-rent", "-10")):
        pg.fill(sel, bad); pg.wait_for_timeout(900); seen.append((sel, bad, score(), tc("#rent-chart"), pg.is_visible("#rent-use")))
        pg.fill(sel, price0 if sel == "#b-price" else rent0); pg.wait_for_timeout(900)
    s1 = score()
    # the price-based markers go with a refused price; with a refused rent only the deal's own rent marker goes, and the button offers the estimate
    okE = all(blank(x[2]) and ("Matches" not in x[3] and "Breaks even" not in x[3] if x[0] == "#b-price" else "In the deal" not in x[3] and x[4]) for x in seen)
    check("E impossible price or rent clears the scorecard and price-based rent markers; a valid one restores them",
          s0["figs"][1] != "—" and s0["rows"] > 0 and "Matches" in ladder0 and okE and s1 == s0, (s0, [(x[0], x[1], x[2], "Matches" in x[3], "In the deal" in x[3], x[4]) for x in seen], s1))
    # F: an impossible price typed while the scorecard is still counting up to the last one
    during = pg.evaluate(MID, ["#b-price", str(int(int(price0) * 1.25)), "#b-price", "-5"]); pg.wait_for_timeout(1200); sF = score()
    check("F impossible price mid count-up leaves the scorecard blank", blank(sF), (during, sF))
    pg.fill("#b-price", price0); pg.wait_for_timeout(900)
    # G: an impossible size typed while the rent estimate is still counting up
    pg.click("#tab-value"); pg.fill("#in-area", "120"); pg.wait_for_timeout(900)
    rent_during = pg.evaluate("""async () => { const $ = (s) => document.querySelector(s); $('#tab-invest').click();
        await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
        const during = $('#rent-est').textContent; $('#tab-value').click();
        const a = $('#in-area'); a.value = '-85'; a.dispatchEvent(new Event('input', { bubbles: true })); $('#tab-invest').click(); return during; }""")
    pg.wait_for_timeout(1200)
    check("G impossible size mid count-up leaves the rent estimate blank", txt("#rent-est") == "—" and not txt("#rent-range"), (rent_during, txt("#rent-est")))
    # G2: the 'Use £… in the deal' button goes with the estimate it offers
    pg.click("#tab-value"); pg.fill("#in-area", "85"); pg.wait_for_timeout(900); pg.click("#tab-invest"); pg.wait_for_timeout(900)
    pg.fill("#b-rent", "500"); pg.wait_for_timeout(700); btn0 = pg.is_visible("#rent-use")
    pg.click("#tab-value"); pg.fill("#in-area", "-85"); pg.wait_for_timeout(700); pg.click("#tab-invest"); pg.wait_for_timeout(900)
    check("G2 with no rent estimate the 'use this rent' button is hidden", btn0 and txt("#rent-est") == "—" and not pg.is_visible("#rent-use"), (btn0, txt("#rent-est"), pg.is_visible("#rent-use"), txt("#rent-use")))
    pg.click("#tab-value"); pg.fill("#in-area", "85"); pg.wait_for_timeout(900); pg.click("#tab-invest"); pg.wait_for_timeout(900)
    # H: typing a price key by key (1, 16, 165 ... are refused on the way) ends on the same screen as entering it at once
    shot = lambda: (txt("#inv-total"), txt("#inv-z"), txt("#r-cash"), txt("#r-irr"), txt("#rent-est"), pg.eval_on_selector_all("#proj-table tbody tr", "e => e.length"))
    pg.fill("#b-price", ""); pg.click("#b-price"); pg.keyboard.type("165000", delay=0); pg.wait_for_timeout(1300); rapid = shot()
    pg.fill("#b-price", "1"); pg.wait_for_timeout(400); pg.fill("#b-price", "165000"); pg.wait_for_timeout(1300); slow = shot()
    check("H a price typed key by key ends on the same figures as one entered at once", rapid == slow and rapid[0] != "—" and rapid[2] != "—", (rapid, slow))
    pg.fill("#b-price", price0); pg.wait_for_timeout(900)
    # I: the scorecard is a cash purchase, so an impossible deposit leaves it alone but removes the mortgage break-even marker
    sI0, ladI0 = score(), tc("#rent-chart")
    pg.fill("#b-deposit", "150"); pg.wait_for_timeout(900); sI, ladI = score(), tc("#rent-chart")
    pg.fill("#b-deposit", "25"); pg.wait_for_timeout(900)
    check("I impossible deposit keeps the cash scorecard but drops the mortgage break-even", sI == sI0 and sI0["figs"][1] != "—" and "Breaks even" in ladI0 and "Breaks even" not in ladI and "Breaks even" in tc("#rent-chart"), (sI0["figs"], sI["figs"], "Breaks even" in ladI))
    # J: the flip appraisal refuses impossible months or finance rates instead of working them in
    flips = []
    for sel, bad, good in (("#f-months", "-6", "6"), ("#f-fin", "", "9"), ("#f-baths", "40", "1")):
        pg.fill(sel, bad); pg.wait_for_timeout(700); flips.append((sel, pg.eval_on_selector_all("#f-detail dt", "e => e.length"), txt("#f-works-note")))
        pg.fill(sel, good); pg.wait_for_timeout(700)
    check("J impossible flip inputs clear the flip appraisal; valid ones restore it", all(x[1] == 0 and x[2] for x in flips) and pg.eval_on_selector_all("#f-detail dt", "e => e.length") > 0, flips)
    # ---- fourth review ----
    import re as _re
    PC_RE = _re.compile(r"^[A-Z]{1,2}\d[A-Z\d]? \d[A-Z]{2}$")
    def paste(text):
        pg.click("#tab-value"); pg.evaluate("() => { const d = document.querySelector('#listing-text').closest('details'); if (d) d.open = true; }")
        pg.fill("#listing-text", text); pg.click("#listing-read"); pg.wait_for_timeout(1300)
        return dict(found=txt("#listing-found"), chips=pg.eval_on_selector_all("#listing-pcs button", "e => e.map(x => x.textContent)"), pc=v("#in-postcode"), type=v("#in-type"),
                    beds=v("#in-beds"), bung=pg.is_checked("#in-bungalow"), ct=v("#in-ctband"), area=v("#in-area"), ask=v("#in-asking"), base=txt("#v-base"), err=txt("#pc-err"))
    k1 = paste("3 bedroom semi-detached house for sale, Apley Road, Doncaster. Guide price £185,000.")
    pcchips = lambda ch: [c for c in ch if not c.startswith("Keep ")]
    check("K1 a street's chips are whole postcodes", pcchips(k1["chips"]) and all(PC_RE.match(c) for c in pcchips(k1["chips"])) and "DN1 2AX" in k1["chips"], k1["chips"][:4])
    k2 = [paste(t_)["type"] for t_ in ("Detached house for sale, 4 bedrooms, with a flat roof garage extension, Doncaster DN4 7HA. £350,000",
                                       "Two bedroom apartment with roof terrace for sale, Doncaster DN4 7HA. £120,000",
                                       "3 bedroom terraced house with a detached garage, Doncaster DN4 7HA. £150,000")]
    check("K2 type isn't taken from 'flat roof', 'roof terrace' or 'detached garage'", k2 == ["D", "F", "T"], k2)
    k2c = paste("Two bedroom apartment for sale, Doncaster DN4 7HA. £120,000")
    check("K2b bedrooms written as a word are read", k2c["beds"] == "2", k2c["beds"])
    agent = pg.evaluate("() => { const r = dash.data('postcodes').data.find((x) => x.postcode.startsWith('DN1 ') && x.in_doncaster === '1'); return r ? r.postcode : null; }")
    k3 = paste(f"3 bedroom terraced house for sale. Hexthorpe Road, Doncaster, DN4. Guide price £95,000. Marketed by Example Estates, 1 Hall Gate, Doncaster {agent}. Call 01302 000000")
    check("K3 the agent's postcode isn't used for the home", agent and k3["pc"] != agent and (not k3["pc"] or k3["pc"].startswith("DN4")) and all(c.startswith("DN4") for c in pcchips(k3["chips"])), (agent, k3["pc"], k3["chips"][:3], k3["found"]))
    pg.fill("#in-postcode", "DN4 7HA"); pg.dispatch_event("#in-postcode", "input"); pg.wait_for_timeout(1200)
    k4 = paste("2 bedroom terraced house for sale, £80,000")
    check("K4 a listing with no location doesn't value the last postcode", k4["pc"] == "" and k4["base"] == "—" and "postcode" in (k4["err"] or "").lower(), (k4["pc"], k4["base"], k4["err"]))
    paste("Detached bungalow, 2 bedrooms, 85 sq m, council tax band D, £150,000, £700 pcm, Doncaster DN4 7HA")
    k5 = paste("3 bedroom semi-detached house for sale, Doncaster DN4 7HA")
    pg.click("#tab-invest"); pg.wait_for_timeout(1000); rentnote = txt("#b-notes") or ""
    check("K5 a new paste doesn't keep the last listing's details", (k5["bung"], k5["ct"], k5["area"], k5["ask"]) == (False, "", "", "") and "pasted listing" not in rentnote, (k5, rentnote[:80]))
    pg.click("#tab-value"); pg.fill("#in-area", "85"); pg.wait_for_timeout(900)
    # K6: your deal figures survive edits to the same home, and reset for a different home
    pg.click("#tab-invest"); pg.wait_for_timeout(900); pg.fill("#b-price", "123000"); pg.fill("#b-rent", "777"); pg.wait_for_timeout(600)
    pg.click("#tab-value"); pg.select_option("#in-ctband", "C"); pg.select_option("#in-condition", "dated"); pg.fill("#in-area", "90"); pg.wait_for_timeout(900)
    pg.click("#tab-invest"); pg.wait_for_timeout(900); kept = (v("#b-price"), v("#b-rent"))
    pg.click("#tab-value"); pg.select_option("#in-condition", "average"); pg.fill("#in-postcode", "DN4 0AH"); pg.dispatch_event("#in-postcode", "input"); pg.select_option("#in-type", "T"); pg.wait_for_timeout(1500)
    pg.click("#tab-invest"); pg.wait_for_timeout(900); reset = (v("#b-price"), v("#b-rent"))
    check("K6 typed deal figures survive edits to the home and reset for a new one", kept == ("123000", "777") and reset[0] != "123000" and reset[1] != "777", (kept, reset))
    pg.click("#tab-value"); pg.fill("#in-postcode", "DN4 7HA"); pg.dispatch_event("#in-postcode", "input"); pg.select_option("#in-type", "S"); pg.fill("#in-area", "85"); pg.wait_for_timeout(1500)
    # K7: district searches
    pg.click("#tab-areas"); pg.wait_for_timeout(1500); first = {}
    for q in ("DN11", "DN12", "DN1 1"):
        pg.fill("#nb-q", q); pg.wait_for_timeout(400); first[q] = (pg.eval_on_selector_all("#nb-results li", "e => e.map(x => x.innerText)") or [""])[0]
    pg.fill("#nb-q", ""); pg.keyboard.press("Escape")
    check("K7 DN11 and DN12 find those districts; DN1 1 still finds the sector", "DN11 " in first["DN11"] and "DN12 " in first["DN12"] and "DN1 1" in first["DN1 1"], first)
    NEG0 = r"(s) => (document.querySelector(s).innerText.match(/[−-]0\.0(?:0)?\s?(?:pts|%)/g) || []).length"
    neg0 = pg.evaluate(NEG0, "#areas")
    pg.click("#tab-invest"); pg.wait_for_timeout(900); neg0 += pg.evaluate(NEG0, "#invest")
    check("K8 no '−0.0' figures on the Areas and Investing tabs", neg0 == 0, neg0)
    # K9: a postcode outside Doncaster
    pg.click("#tab-value"); pg.fill("#in-postcode", "OX5 3AT"); pg.dispatch_event("#in-postcode", "input"); pg.wait_for_timeout(1200)
    k9 = (txt("#v-base"), txt("#pc-err")); pg.fill("#in-postcode", "DN4 7HA"); pg.dispatch_event("#in-postcode", "input"); pg.wait_for_timeout(1200)
    check("K9 a postcode outside Doncaster is refused", k9[0] == "—" and "outside Doncaster" in (k9[1] or ""), k9)
    # K10: risk settings out of range are refused, with a message, and the default used
    pg.click("#tab-areas"); pg.wait_for_timeout(1200); top0 = txt("#btl-top")
    pg.evaluate("() => { const d = document.querySelector('#risk-set'); if (d) d.open = true; }"); pg.fill("#rk-tenant", "-5"); pg.wait_for_timeout(900)
    k10 = (pg.is_visible("#risk-err"), txt("#risk-err"), txt("#btl-top") == top0); pg.fill("#rk-tenant", ""); pg.wait_for_timeout(600)
    check("K10 a negative risk setting is refused and says so", k10[0] and "out of range" in (k10[1] or "") and k10[2], k10[:2])
    # K11: the page's own input limits are the script's
    lim = pg.evaluate("() => ['#in-area', '#in-rooms', '#b-term', '#b-deposit', '#f-months', '#rk-tenant'].map((s) => [s, document.querySelector(s).min, document.querySelector(s).max])")
    check("K11 input limits match the checks", lim == [["#in-area", "10", "1500"], ["#in-rooms", "1", "30"], ["#b-term", "1", "40"], ["#b-deposit", "0", "100"], ["#f-months", "1", "60"], ["#rk-tenant", "0", "30"]], lim)
    # K12-K14, K17, K18: investing
    pg.click("#tab-invest"); pg.wait_for_timeout(1000)
    pg.fill("#b-price", "100000"); pg.wait_for_timeout(900)
    fl = pg.eval_on_selector_all("#f-detail dt, #f-detail dd", "e => e.map(x => x.textContent)")
    check("K12 the flip buys at your price and gives a highest offer", len(fl) > 3 and fl[0] == "Buy (your price)" and fl[1] == "£100,000" and "Highest price that breaks even" in fl, fl[:2] + fl[-4:])
    pg.fill("#b-price", (txt("#v-base") or "200000").replace("£", "").replace(",", "")); pg.wait_for_timeout(900)
    z_real = txt("#inv-z"); pg.fill("#b-rent", "0"); pg.wait_for_timeout(900); z_zero = txt("#inv-z"); rows0 = pg.eval_on_selector_all("#inv-rows .inv-row", "e => e.map(x => x.dataset.k)")
    check("K13 a £0 rent scores no better than a real one, and keeps its yield row", "yield" in rows0 and float(z_zero.rstrip("%")) <= float(z_real.rstrip("%")), (z_real, z_zero, rows0))
    pg.fill("#b-rent", ""); pg.wait_for_timeout(300); lad = tc("#rent-chart"); m = _re.search(r"Matches the gilt(?: after risk)? £([\d,]+)", lad)
    if m: pg.fill("#b-rent", m.group(1).replace(",", "")); pg.wait_for_timeout(900)
    above = txt("#inv-above") or ""
    check("K14 the 'matches the gilt' rent really matches it, risk allowance included", bool(m) and not above.startswith("−"), (m.group(0) if m else lad[:120], above))
    tn = txt("#inv-total-n") or ""; gm = _re.search(r"growth ([\d.]+)%", tn)
    check("K17 the projection's price growth is the scorecard's", bool(gm) and abs(float(v("#p-price")) - float(gm.group(1))) < 0.06, (v("#p-price"), tn[:80]))
    irrn = txt("#r-irr-note") or ""
    check("K18 the IRR is after tax on the gain", "after tax" in irrn.lower() and ("capital gains tax" in irrn or "no gain" in irrn or "no tax on the" in irrn), irrn[:120])
    # K15: decorating a home that needs a full renovation doesn't make it 'good'
    pg.click("#tab-value"); pg.select_option("#in-condition", "needs_full_renovation"); pg.wait_for_timeout(700)
    pg.evaluate("() => document.querySelectorAll('details').forEach((d) => { if (d.querySelector('#wi-refurb')) d.open = true; })")
    pg.select_option("#wi-refurb", "cosmetic"); pg.dispatch_event("#wi-refurb", "input"); pg.wait_for_timeout(900)
    wi = pg.eval_on_selector_all("#wi-kv dt, #wi-kv dd", "e => e.map(x => x.textContent)"); wn = txt("#wi-note") or ""
    added = wi[wi.index("Value added") + 1] if "Value added" in wi else ""
    small = added.startswith(("£", "−£")) and abs(int(added.replace("£", "").replace(",", "").replace("−", "-"))) < 3000
    check("K15 light works on a home needing a full renovation add no condition value", small and "needs more than" in wn, (added, wn[wn.find("A home"):][:110]))
    pg.select_option("#wi-refurb", ""); pg.dispatch_event("#wi-refurb", "input"); pg.select_option("#in-condition", "average"); pg.wait_for_timeout(700)
    # K16: typing doesn't redraw on every key
    cost = pg.evaluate("""() => { const e = document.querySelector('#in-area'), t0 = performance.now();
        for (const x of ['9', '91', '92', '93', '94', '95']) { e.value = x; e.dispatchEvent(new Event('input', { bubbles: true })); } return performance.now() - t0; }""")
    pg.wait_for_timeout(1200); after16 = txt("#v-base"); pg.fill("#in-area", "85"); pg.wait_for_timeout(900)
    check("K16 six keystrokes cost one redraw, after the pause", cost < 150 and after16 not in ("—", None), (round(cost), after16))
    # ---- fifth review ----
    pg.click("#tab-value"); pg.fill("#in-postcode", "DN4 7HA"); pg.dispatch_event("#in-postcode", "input"); pg.select_option("#in-type", "S"); pg.fill("#in-area", "85"); pg.wait_for_timeout(1200)
    m1 = paste("4 bedroom detached house for sale, Doncaster DN4. Guide price £320,000")
    keep = [c for c in m1["chips"] if c.startswith("Keep ")]
    if keep: pg.click("#listing-pcs button.keep"); pg.wait_for_timeout(1200)
    check("M1 a listing naming only the district clears the last postcode, and keeping it is your choice", m1["pc"] == "" and m1["base"] == "—" and keep == ["Keep DN4 7HA"] and v("#in-postcode") == "DN4 7HA" and txt("#v-base") != "—",
          (m1["pc"], m1["base"], m1["chips"], v("#in-postcode"), txt("#v-base")))
    pg.click("#tab-invest"); pg.wait_for_timeout(1200)
    flip = lambda: pg.eval_on_selector_all("#f-detail dt, #f-detail dd", "e => e.map(x => x.textContent)")
    pg.fill("#b-price", "-1"); pg.wait_for_timeout(800); f_bad = (flip(), txt("#f-works-note") or "")
    pg.fill("#b-price", ""); pg.wait_for_timeout(800); f_blank = flip()
    pg.fill("#b-price", "150000"); pg.fill("#f-quote", "0"); pg.wait_for_timeout(800); f_zero = flip()
    wi_ = [i for i, x in enumerate(f_zero) if x.startswith("Works")]
    check("M2 the flip: an invalid price clears it, a blank one uses the model, a £0 quote is £0", f_bad[0] == [] and "Purchase price" in f_bad[1] and f_blank[:1] and f_blank[0].startswith("Buy (model value")
          and f_zero[0] == "Buy (your price)" and wi_ and f_zero[wi_[0]] == "Works (your quote)" and f_zero[wi_[0] + 1] == "£0", (f_bad[1][:60], f_blank[:1], f_zero[wi_[0]:wi_[0] + 2] if wi_ else f_zero[:4]))
    pg.fill("#f-quote", ""); pg.wait_for_timeout(500)
    # M3: capital gains tax within the basic-rate band; improvements no bigger than the works
    pg.select_option("#b-owner", "basic"); pg.fill("#b-income", "0"); pg.fill("#p-price", "6"); pg.wait_for_timeout(900); n_basic = txt("#r-irr-note") or ""
    shown = pg.is_visible("#b-income")
    pg.select_option("#b-owner", "higher"); pg.wait_for_timeout(800); n_high = txt("#r-irr-note") or ""; hidden = not pg.is_visible("#b-income")
    pg.select_option("#b-owner", "basic"); pg.fill("#b-income", ""); pg.fill("#b-works", "5000"); pg.fill("#b-improve", "9000"); pg.wait_for_timeout(800); n_bad = txt("#b-notes") or ""
    pg.fill("#b-improve", "0"); pg.fill("#b-works", "0"); pg.wait_for_timeout(600)
    check("M3 a basic-rate owner's gain is split across the band; improvements can't exceed the works", "18% on" in n_basic and "24% on" in n_basic and shown and hidden and "18% on" not in n_high
          and "Improvements can't be more" in n_bad, (n_basic[:150], n_high[:80], n_bad[:60]))
    # M4: condition by what the model knows
    pg.click("#tab-value"); pg.select_option("#in-condition", "recently_refurbished"); pg.fill("#in-prev-price", ""); pg.fill("#in-prev-month", ""); pg.wait_for_timeout(900); c_none = txt("#v-cond-note") or ""
    pg.fill("#in-prev-price", "200000"); pg.fill("#in-prev-month", "2026-03"); pg.wait_for_timeout(900); c_recent = txt("#v-cond-note") or ""
    pg.fill("#in-prev-month", "2014-03"); pg.wait_for_timeout(900); c_old = txt("#v-cond-note") or ""
    pg.fill("#in-prev-price", ""); pg.fill("#in-prev-month", ""); pg.select_option("#in-condition", "average"); pg.wait_for_timeout(700)
    check("M4 the refurbished premium depends on whether the model already knows a recent last sale", c_none.startswith("+6.2%") and c_recent.startswith("+0.6%") and "recent" in c_recent and c_old.startswith("+6.2%") and "older last sale" in c_old,
          (c_none[:40], c_recent[:60], c_old[:60]))
    # N1: the two tabs drawn by market_accuracy.js
    drawn = {}
    for tab, ids in (("market", ["index-chart", "tier-chart", "type-chart", "volume-chart", "poss-chart"]), ("accuracy", ["compare-chart", "backtest-chart", "confidence-chart", "ratio-chart", "scatter"])):
        pg.click(f"#tab-{tab}"); pg.wait_for_timeout(2500)
        if tab == "market": pg.click("#poss-metric button[aria-pressed=false] >> nth=0"); pg.wait_for_timeout(800)   # its own listener, also moved
        drawn.update({i: pg.evaluate("(i) => !!document.querySelector('#' + i + ' svg')", i) for i in ids})
    check("N1 the Market and Accuracy tabs draw every chart", all(drawn.values()), [k for k, x in drawn.items() if not x] or len(drawn))
    # N2-N4: the deal charts (deal_charts.js)
    money = lambda t: float(t.replace("£", "").replace(",", "").replace("−", "-").split()[0])
    pg.click("#tab-invest"); pg.wait_for_timeout(1500)
    pg.eval_on_selector("#b-rate-slider", "e => { e.value = '6.5'; e.dispatchEvent(new Event('input', { bubbles: true })); }"); pg.wait_for_timeout(500)
    slid = (v("#b-rate"), txt("#b-rate-out"))
    bb = pg.locator("#rate-chart svg").bounding_box(); pg.locator("#rate-card").scroll_into_view_if_needed(); bb = pg.locator("#rate-chart svg").bounding_box()
    pg.mouse.move(bb["x"] + bb["width"] * 0.5, bb["y"] + bb["height"] * 0.5); pg.mouse.down(); pg.mouse.move(bb["x"] + bb["width"] * 0.3, bb["y"] + bb["height"] * 0.5, steps=6); pg.mouse.up(); pg.wait_for_timeout(500)
    dragged = v("#b-rate")
    # a drag towards the top of the scale keeps the scale still until it ends (the reviewer's run-away rate), then grows it
    bb = pg.locator("#rate-chart svg").bounding_box(); pg.mouse.move(bb["x"] + bb["width"] * 0.5, bb["y"] + bb["height"] * 0.5); pg.mouse.down()
    pg.mouse.move(bb["x"] + bb["width"] * 0.985, bb["y"] + bb["height"] * 0.5, steps=12); pg.wait_for_timeout(200); far = v("#b-rate"); pg.mouse.up(); pg.wait_for_timeout(500)
    far_max = pg.get_attribute("#b-rate-slider", "max")
    pg.fill("#b-rate", "5.25"); pg.wait_for_timeout(500); typed_ = v("#b-rate-slider")
    import re as _re
    be = _re.search(r"breaks even at ([\d.]+)%", txt("#rate-note") or "")
    cash_be = None
    if be: pg.fill("#b-rate", be.group(1)); pg.wait_for_timeout(500); cash_be = money(txt("#r-cash"))
    check("N2 the rate slider and a drag set the deal's rate; at the break-even rate the cash flow is £0", slid == ("6.5", "6.50%") and dragged not in ("6.5", "") and float(dragged) < 6.5 and typed_ == "5.25" and cash_be is not None and abs(cash_be) <= 1
          and float(far) > 11 and int(far_max) == min(25, -(-int(float(far) * 100 + 300) // 100)), (slid, dragged, typed_, be.group(1) if be else None, cash_be, far, far_max))
    pg.fill("#b-rate", "5.25"); pg.wait_for_timeout(500)
    tor = lambda: {r[0]: r[1:] for r in pg.eval_on_selector_all("#tor-chart g.row", "gs => gs.map(g => [g.querySelector('.nm').textContent, g.querySelector('.vlo').textContent, g.querySelector('.vhi').textContent])")}
    T = tor(); rent0 = float(v("#b-rent")); rent_hi = (T.get("Rent ±10%") or [None, None])[1]; rate_lo = (T.get("Mortgage rate ±1 pt") or [None, None])[0]
    pg.fill("#b-rent", str(rent0 * 1.1)); pg.wait_for_timeout(500); irr_rent = txt("#r-irr"); pg.fill("#b-rent", str(rent0)); pg.wait_for_timeout(300)
    pg.fill("#b-rate", "4.25"); pg.wait_for_timeout(500); irr_rate = txt("#r-irr"); pg.fill("#b-rate", "5.25"); pg.wait_for_timeout(500)
    base_ = float(_re.search(r"([−\d.]+)%", pg.evaluate("() => document.querySelector('#tor-chart g.base text').textContent")).group(1).replace("−", "-"))
    order = [max(abs(float(a.rstrip("%").replace("−", "-")) - base_), abs(float(b.rstrip("%").replace("−", "-")) - base_)) for a, b in tor().values()]
    check("N3 each end of a tornado bar is the deal's own figure with that input changed", rent_hi == irr_rent and rate_lo == irr_rate and order == sorted(order, reverse=True), (rent_hi, irr_rent, rate_lo, irr_rate))
    fan_note = txt("#fan-note") or ""; yours = _re.search(r"your growth figure gives ([−\d.]+%)", fan_note)
    n_dec = len(pg.query_selector_all("#fan-irr circle")); stretches = _re.search(r"\((\d+) overlapping stretches", txt("#fan-sub") or "")
    pg.fill("#b-deposit", "150"); pg.wait_for_timeout(500)
    gone = [pg.evaluate(f"() => !!document.querySelector('{s_} svg')") for s_ in ("#rate-chart", "#tor-chart", "#fan-chart", "#fan-irr")] + [bool(txt("#rate-note")), bool(txt("#tor-note")), bool(txt("#fan-note"))]
    pg.fill("#b-deposit", "25"); pg.wait_for_timeout(600)
    back = [pg.evaluate(f"() => !!document.querySelector('{s_} svg')") for s_ in ("#rate-chart", "#tor-chart", "#fan-chart", "#fan-irr")]
    check("N4 the past-decades fan matches the deal, and an invalid deposit clears all three charts", stretches and stretches.group(1) == "22" and n_dec == 22 and yours and yours.group(1) == txt("#r-irr") and not any(gone) and all(back),
          (stretches.group(1) if stretches else None, n_dec, yours.group(1) if yours else None, txt("#r-irr"), gone, back))
    pg.click("#tab-value"); pg.wait_for_timeout(500)
    check("no page errors", not errs, errs[:3])
    b.close()
print(f"{sum(results)} of {len(results)} passed"); sys.exit(0 if all(results) else 1)
