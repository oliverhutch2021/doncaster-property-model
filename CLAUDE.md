# CLAUDE.md

## Checking your work

After any change, run the tests that cover it and fix anything that fails. Don't skip a failing test or loosen it to make it pass.

| Changed | Run |
|---|---|
| `dashboard/` (any page source or script), `config/assumptions.csv` | `python src/build_page.py`, then `node tests/test_units.js`, `python tests/test_ui.py`, `python tests/test_build.py` |
| `src/build_standalone.py`, anything that ends up in `public/` | `python tests/test_build.py`, `python tests/test_privacy.py` |
| `src/predict.py`, `src/features.py`, feature or training scripts | `python tests/test_parity.py` |
| Deal, tax, IRR or listing-parser logic | `node tests/test_units.js` |

If you're unsure which tests apply, run all five.

After changing the dashboard, take screenshots at desktop width (1366 × 900, the same as `test_ui.py`) and phone width (390 × 844) with Playwright, and look at them. Check the tabs and panels you changed for overlapping or cut-off text, horizontal scrolling on the phone, and charts that are empty or misdrawn. Check light and dark themes if you touched colours. Save the screenshots in a scratch folder, not in the repo.

Never say a task is done until these checks pass. When you report back, say which tests you ran and what they reported (for example "test_units.js: all 101 passed"), and which screenshots you looked at. If a check couldn't be run, say so and why; don't count it as passed.

### Environment notes

- Node.js isn't on PATH on this machine. RStudio's bundled Node works: `& "C:\Program Files\RStudio\resources\app\bin\node\node.exe" tests/test_units.js`.
- `test_ui.py` and the screenshots need Playwright with Chromium, and `test_ui.py` also needs pandas. All three were installed on 13 Oct 2026 (`pip install playwright pandas`, then `python -m playwright install chromium`).
- Screenshot `public/index.html`, the self-contained page; `dashboard/index.html` is only the page source. The Saved tab is hidden in the public copy. Block `fonts.g*` requests as `test_ui.py` does; the one failed request this leaves in the console is that font, not a page error.
- `test_parity.py` and some `test_ui.py` cases need the private address lookup (see the README); without it, those cases can't run.
