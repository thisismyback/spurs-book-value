# Spurs Squad Book Value

Computes the **net book value (NBV)** and **unrealized book profit** of every
Tottenham Hotspur player: if we sold them today at their Transfermarkt market
value, what would the accounting return be after amortization?

## Files
- `players.csv` — **source of truth**. Edit this. One row per player.
- `book_value.py` — calculation engine + CLI. Reads the CSV, prints a table, writes output.
- `book_value_output.csv` — generated results (do not edit; regenerated each run).
- `app.py` — Flask web dashboard (imports the engine; no duplicate math).
- `start_dashboard.bat` — double-click to launch the dashboard + open the browser.

## Run
Console table / refresh the output CSV:
```
py -3 book_value.py
```
Web dashboard (sortable table, totals, colour-coded P/L):
```
py -3 app.py      # then open http://localhost:5200
```
or just double-click `start_dashboard.bat`. The dashboard reads `players.csv`
live on every request — edit the CSV and refresh the page to see changes.

## Shareable public sites
Two public URLs, both read-only/safe (no visitor can change your data):
- **Fly.io (server):** https://spurs-book-value.fly.dev/ — runs `app.py` with
  `PUBLIC_MODE=1` (shared mode + `/api/sale` disabled). Update with `fly deploy`
  after editing data (the CSV is baked into the image; redeploy to refresh).
- **GitHub Pages (static):** https://thisismyback.github.io/spurs-book-value/ —
  served from `docs/`, rebuilt with `build_static.py`.

GitHub Pages, repo `thisismyback/spurs-book-value`, served from `docs/`.

`build_static.py` renders the same dashboard as a single self-contained
`docs/index.html` in **shared mode**: data baked in, social/Twitter preview tags,
and sale-price edits handled in-browser only (viewers can run what-ifs without
touching `players.csv`). To update the public site after editing data:
```
py -3 build_static.py
git add -A && git commit -m "update data" && git push
```
GitHub Pages redeploys automatically (~1 min).

## The accounting model
A transfer fee is capitalized as an intangible asset and expensed evenly over the
contract ("amortization"). The un-expensed remainder is the **Net Book Value**.

```
amortization_period = contract length in years, capped at 5 (PL/UEFA rule)
annual_amortization = fee / amortization_period
NBV                 = fee - (annual_amortization * years_elapsed)   [floored at 0]
book_profit         = market_value - NBV
```

Any sale **above** NBV is pure profit for PSR/FFP purposes; below NBV is a loss.

### Special cases
- **Loaned IN** (status `loan`): no asset is capitalized → no NBV, excluded from
  totals, not sellable in the simulator (Palhinha, Kolo Muani).
- **Loaned OUT** (any owned/academy player with `on_loan_at` filled): still *our*
  asset, so it keeps its NBV and counts in totals (Vuskovic, Devine, Lankshear).
  The column is display-only — it does not change the accounting.
- **Academy / free** players (status `academy`, fee 0): NBV 0 → the *entire* market
  value is pure book profit. This is why selling homegrown talent is PSR gold.

### Agreed / actual sale price (editable in the dashboard)
The `sale_price_gbp_m` column (GBP millions) holds a real agreed/known fee. Book
P/L then uses that price instead of the Transfermarkt market value
(`book profit = sale price − NBV`), the player gets a green **SOLD £x** badge, and
the simulator's cash-in uses the agreed price too. Blank = fall back to market value.

You can **type the price straight into the Sale Price cell on the dashboard** — it
POSTs to `/api/sale`, writes back to `players.csv`, and live-updates the row, the
SOLD badge, the simulator, and the summary cards. Clear the cell to revert to
market value. Edits persist; non-numeric input is rejected. The column is **GBP**;
convert euro-quoted fees first. Example: Alejo Veliz `8` → +£2.3m (vs −£2.3m at €4m).

### Shareable scenarios (public sites)
On the public sites, visitors can type their own what-if sale prices and tick a
Sell XI, then hit **🔗 Share my scenario** — their edits (sale prices + selections)
are encoded into a `?s=` URL param (base64 JSON) and copied to the clipboard.
Opening that link replays the scenario via `applyScenario()`, entirely client-side
— no server writes, so no one can alter your canonical `players.csv`. A **Clear
sale prices** button resets every sale price back to market value (works on the
local app too, where it clears the saved values).

### Realized vs unrealized split
The summary cards break total book profit into **Realized** (sum of book P/L for
players with a sale price entered — locked in) and **Unrealized** (the rest, still
valued at Transfermarkt market value). As the window progresses and you enter real
fees, profit moves from the Unrealized card to the Realized card — a running PSR
tracker.

### PSR / FFP headroom tracker
A panel under the cards models the Premier League's **3-year rolling allowable
loss** (default £105m, editable). Enter your estimate of the club's 3-year
operating loss *before* player-sale profits, and it computes:

```
net headroom = allowable loss − assumed loss + realized sale profit
```

Realized sale profit (from SOLD entries) offsets losses £-for-£, so it shows a
claw-back bar (realized as a % of the limit) and flags `within limit` / `OVER
limit`. Updates live as you edit sale prices. Inputs are saved in your browser
(localStorage), not the CSV. **Simplified**: real PSR allows add-backs (academy,
infrastructure, women's football, community) that aren't modelled here.

### Sell XI simulator (dashboard)
Tick any sellable players and the bottom bar totals: **cash in** (sum of market
values), **book value wiped off** (sum of NBVs leaving the balance sheet), and
**PSR/FFP book profit** (sum of book P/L). Warns once you pass 11. Loaned-in
players have no checkbox.

## Contract extensions (modelled)
When a player re-signs, the schedule resets: the original fee is amortized from the
signing date up to the extension date, and the **remaining NBV** is then re-spread
over the new term (capped at 5 years from the extension). To model an extension,
fill the two optional columns in `players.csv`:
- `orig_expiry` — the end date of the contract that was in force *before* the extension
- `extension_date` — when the new deal was signed

(`contract_expiry` always holds the current/latest end date.) Leave both blank for
players who never extended. Extended players are flagged with `*` in the output.
Currently modelled: Romero, Udogie, Porro, Bentancur, Sarr. Note: van de Ven and
Kulusevski are on their *original* deals (no extension). Only one extension per
player is supported; a second re-sign would need the columns updated to the latest.

## Known limitations
- **Fees** are best-effort from public reporting; undisclosed add-ons and agent
  fees (also capitalized) aren't fully captured. See `confidence` column.
  `Souza` fee is a placeholder — needs verifying.
- **FX**: market values are Transfermarkt euros × `EUR_GBP` (0.86 in the script).
  Adjust the constant at the top of `book_value.py` as rates move.

## Updating
1. Refresh market values from Transfermarkt periodically (manual — they block scraping).
2. Add new signings / remove departures as rows in `players.csv`.
3. Re-run. Nothing is cached; the CSV fully drives the output.

**Do not use commas inside any field** (e.g. notes) — the CSV is unquoted, so a
stray comma shifts the columns. Use `;` instead. The engine now hard-errors on a
mis-columned row rather than silently corrupting it.

## Sources
- Squad, contracts, market values: Transfermarkt
- Transfer fees: Sky Sports, Transfermarkt, club announcements (per-row in `note`)
