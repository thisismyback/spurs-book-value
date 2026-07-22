#!/usr/bin/env python3
"""
Tottenham Hotspur squad book-value / amortization engine.

Reads players.csv (the source of truth) and computes, for each player:
  - Net Book Value (NBV): the un-amortized remainder of the transfer fee
  - Book profit/loss if sold today at Transfermarkt market value

Accounting model (Premier League / UEFA):
  annual_amortization = fee / amortization_period
  amortization_period = contract length in years, CAPPED at 5 (60 months)
  accumulated_amort   = annual_amortization * years_elapsed (clamped to fee)
  NBV                 = fee - accumulated_amort
  book_profit         = market_value - NBV

Notes / limitations:
  - Loan players hold no capitalized asset -> no NBV, excluded from book P/L.
  - Academy/free players have fee 0 -> NBV 0 -> entire market value is pure profit.
  - Contract EXTENSIONS reset the amortization schedule (remaining NBV re-spread
    over the new term). This v1 amortizes from the signing date over the original
    capped term and does NOT model resets - see the 'note' column in players.csv.
  - Market values are Transfermarkt euros converted to GBP at EUR_GBP below; FX
    adds noise. Edit fees/values in players.csv and re-run; nothing here is stored.

Usage:  py -3 book_value.py
"""
import csv
import json
import os
from datetime import date, datetime, timedelta

CSV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "players.csv")
OUT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "book_value_output.csv")
PSR_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "psr.json")

EUR_GBP = 0.86          # EUR -> GBP conversion for Transfermarkt market values
AMORT_CAP_YEARS = 5.0   # PL/UEFA cap on amortization period
TODAY = date.today()


def parse_date(s):
    return datetime.strptime(s.strip(), "%Y-%m-%d").date()


def years_between(a, b):
    return (b - a).days / 365.25


def compute(row):
    status = row["status"].strip().lower()
    mv_eur = float(row["market_value_eur_m"] or 0)
    mv_gbp = mv_eur * EUR_GBP

    sale_raw = (row.get("sale_price_gbp_m") or "").strip()
    sale = float(sale_raw) if sale_raw else None
    # Proceeds = agreed/actual sale price if entered, else Transfermarkt market value.
    proceeds = sale if sale is not None else mv_gbp

    out = {
        "player": row["player"],
        "position": row["position"],
        "status": status,
        "market_value_gbp_m": round(mv_gbp, 1),
        "sale_price_gbp_m": round(sale, 1) if sale is not None else "",
        "sold": sale is not None,
        "confidence": row["confidence"],
        "on_loan_at": (row.get("on_loan_at") or "").strip(),
        # Transfer-window bucket: 'in' = new signing, 'out' = confirmed departure,
        # '' = existing squad. Drives the Incomings/Outgoings sections in the app.
        "window_move": (row.get("window_move") or "").strip().lower(),
    }

    if status == "loan":
        out.update(fee_gbp_m="", amort_period_yrs="", years_elapsed="",
                   nbv_gbp_m="", book_profit_gbp_m="", pct_amortized="", extended="")
        return out

    fee = float(row["fee_gbp_m"] or 0)
    signed = parse_date(row["signed_date"])
    expiry = parse_date(row["contract_expiry"])
    ext_date = row.get("extension_date", "").strip()

    def remaining_fraction(start, end, asof):
        """Fraction of a fee still un-amortized at `asof`, over start->end capped at 5y."""
        period = min(years_between(start, end), AMORT_CAP_YEARS)
        if period <= 0:
            return 0.0, period
        elapsed = max(0.0, years_between(start, asof))
        return max(0.0, (period - elapsed) / period), period

    if ext_date:
        # Extension resets the schedule: amortize original fee up to the extension
        # date, then re-spread the remaining NBV over the new (capped) term.
        orig_expiry = parse_date(row["orig_expiry"])
        ext = parse_date(ext_date)
        frac_at_ext, _ = remaining_fraction(signed, orig_expiry, ext)
        nbv_at_ext = fee * frac_at_ext
        frac_now, period = remaining_fraction(ext, expiry, TODAY)
        nbv = nbv_at_ext * frac_now
        elapsed = max(0.0, years_between(ext, TODAY))
    else:
        frac_now, period = remaining_fraction(signed, expiry, TODAY)
        nbv = fee * frac_now
        elapsed = max(0.0, years_between(signed, TODAY))

    book_profit = proceeds - nbv
    pct_amortized = (1 - nbv / fee) * 100 if fee > 0 else 100.0

    out.update(
        fee_gbp_m=round(fee, 1),
        amort_period_yrs=round(period, 1),
        years_elapsed=round(elapsed, 1),
        nbv_gbp_m=round(nbv, 1),
        book_profit_gbp_m=round(book_profit, 1),
        pct_amortized=round(pct_amortized, 0),
        extended="Y" if ext_date else "",
    )
    return out


def load_players():
    """Return all players computed, sorted by book profit (owned first, biggest on top)."""
    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        raw = list(csv.DictReader(f))
    # Guard: a comma inside an unquoted field (usually the 'note') shifts columns.
    # csv stashes the overflow under the None key — fail loudly rather than corrupt.
    for r in raw:
        if r.get(None):
            raise ValueError(
                f"Row for '{r.get('player')}' has too many fields — a stray comma in "
                f"players.csv (commas aren't allowed in note/values; use ';')."
            )
    rows = [compute(r) for r in raw]

    def sort_key(r):
        bp = r["book_profit_gbp_m"]
        return (0, -bp) if isinstance(bp, (int, float)) else (1, 0)
    rows.sort(key=sort_key)
    return rows


def partition(rows):
    """Split computed rows into the three display buckets used by the dashboard:
    incomings (window_move 'in'), the current squad (everything else, incl. loans),
    and outgoings (window_move 'out')."""
    incomings = [r for r in rows if r.get("window_move") == "in"]
    outgoings = [r for r in rows if r.get("window_move") == "out"]
    squad = [r for r in rows if r.get("window_move") not in ("in", "out")]
    return {"incomings": incomings, "squad": squad, "outgoings": outgoings}


def compute_totals(rows):
    """Sum the owned/academy rows (loans excluded), split by transfer-window bucket.

    Go-forward squad = current squad + incomings (window_move != 'out'): its fee,
    NBV, market value and (unrealized) book profit feed the summary cards.
    Confirmed outgoings (window_move == 'out') are off the books -> their book
    profit is the *realized* gain; their proceeds/NBV feed the window summary.
    """
    t = {"fee": 0.0, "nbv": 0.0, "mv": 0.0, "bp": 0.0, "realized": 0.0, "unrealized": 0.0,
         # window-activity tallies
         "in_fee": 0.0, "in_nbv": 0.0, "in_count": 0,
         "out_proceeds": 0.0, "out_nbv": 0.0, "out_count": 0, "loan_out_count": 0}
    for r in rows:
        move = r.get("window_move", "")
        if r["status"] == "loan":
            # Loaned-in players hold no asset. Flagging one 'out' = the loan ended
            # (they returned to their parent club): a departure, but no sale
            # proceeds, NBV or book profit — so it touches no financial totals.
            if move == "out":
                t["loan_out_count"] += 1
            continue
        if move == "out":
            proceeds = r["sale_price_gbp_m"] if r.get("sold") else r["market_value_gbp_m"]
            t["out_proceeds"] += proceeds
            t["out_nbv"] += r["nbv_gbp_m"]
            t["out_count"] += 1
            t["realized"] += r["book_profit_gbp_m"]
            continue
        # go-forward squad (existing + incomings)
        t["fee"] += r["fee_gbp_m"]
        t["nbv"] += r["nbv_gbp_m"]
        t["mv"] += r["market_value_gbp_m"]
        t["unrealized"] += r["book_profit_gbp_m"]
        if move == "in":
            t["in_fee"] += r["fee_gbp_m"]
            t["in_nbv"] += r["nbv_gbp_m"]
            t["in_count"] += 1
    t["bp"] = t["unrealized"] + t["realized"]
    t["amortized"] = t["fee"] - t["nbv"]
    t["net_spend"] = t["in_fee"] - t["out_proceeds"]
    return {k: round(v, 1) if isinstance(v, float) else v for k, v in t.items()}


def load_psr():
    """Load the financial-reporting inputs (psr.json) used by the PSR/UEFA model."""
    with open(PSR_PATH, encoding="utf-8") as f:
        return json.load(f)


def incomings_amortisation(rows):
    """Total annual P&L amortisation charge of the confirmed incomings (fee / capped
    term). This is the *only* way an incoming transfer fee hits PSR each year — the
    fee itself is capitalised, not expensed. Loans contribute nothing."""
    total = 0.0
    for r in rows:
        if r.get("window_move") != "in" or r["status"] == "loan":
            continue
        period = r.get("amort_period_yrs") or 0
        if period:
            total += r["fee_gbp_m"] / period
    return round(total, 1)


def compute_psr(rows, cfg=None):
    """Build the PSR / UEFA compliance picture from psr.json + live transfer activity.

    Premier League PSR: a club may lose at most £105m over a rolling 3 seasons, but
    on an ADJUSTED basis — reported losses are softened by big allowable deductions
    (stadium/infrastructure depreciation, COVID, women's, academy, community). We sum
    the window's reported pre-tax P&L and deductions to get the adjusted result, then
    overlay what this tool knows about the current window: confirmed player-sale book
    profit (helps) and new-signing amortisation (a recurring annual charge that hurts).

    UEFA adds two tests: the Football Earnings Rule (its PSR equivalent, a €60m/€90m
    loss limit, here reduced to Spurs' equity-extended €47m) and Squad Cost Control
    (player wages + amortisation + agent fees capped at 70% of revenue + sale profit).
    """
    cfg = cfg or load_psr()
    by_season = {s["season"]: s for s in cfg["seasons"]}
    window = [by_season[s] for s in cfg["window_seasons"] if s in by_season]

    reported = sum(s["pretax_pnl_gbp_m"] for s in window)          # negative = loss
    deductions = sum(s["allowable_deductions_gbp_m"] for s in window)
    adjusted = reported + deductions                               # +ve = PSR profit
    limit = cfg["psr_limit_gbp_m"]
    headroom = limit + adjusted                                    # room before breach

    # --- live transfer overlay (this window's dealing, per the squad tool) ---
    realized = round(sum(
        (r["sale_price_gbp_m"] if r.get("sold") else r["market_value_gbp_m"]) - r["nbv_gbp_m"]
        for r in rows if r.get("window_move") == "out" and r["status"] != "loan"), 1)
    new_amort = incomings_amortisation(rows)
    net_first_yr = round(realized - new_amort, 1)
    proj_adjusted = round(adjusted + net_first_yr, 1)
    proj_headroom = round(limit + proj_adjusted, 1)

    # --- UEFA Football Earnings Rule (work in EUR) ---
    u = cfg["uefa"]
    eur = u["eur_gbp"]
    adj_eur = round(adjusted / eur, 1)
    allow_eur = u["equity_extended_allowable_loss_eur_m"]
    uefa_margin = round(adj_eur + allow_eur, 1)                    # +ve = below threshold

    # --- UEFA Squad Cost Control (anchor = newest window season) ---
    anchor = window[-1]
    player_wages = anchor["wages_gbp_m"] * u["player_wage_share_of_total_pct"] / 100.0
    squad_cost = player_wages + anchor["amortisation_gbp_m"] + u["agent_fees_gbp_m"]
    scr_base = anchor["revenue_gbp_m"] + anchor["player_sale_profit_gbp_m"]
    scr = round(squad_cost / scr_base * 100, 1) if scr_base else 0.0
    # projected ratio if this window's incomings amortisation + sale profit are layered on
    proj_squad_cost = squad_cost + new_amort
    proj_scr_base = scr_base + realized
    proj_scr = round(proj_squad_cost / proj_scr_base * 100, 1) if proj_scr_base else 0.0

    def clamp(v):
        return round(max(0.0, min(100.0, v)), 1)

    return {
        "limit": limit,
        "window": [s["season"] for s in window],
        "seasons": window,
        "reported_loss": round(-reported, 1),                     # positive magnitude
        "deductions": round(deductions, 1),
        "adjusted": round(adjusted, 1),
        "headroom": round(headroom, 1),
        "within": adjusted >= -limit,
        "used_pct": clamp(-adjusted / limit * 100) if limit else 0.0,
        # live overlay
        "realized": realized,
        "new_amort": new_amort,
        "net_first_yr": net_first_yr,
        "proj_adjusted": proj_adjusted,
        "proj_headroom": proj_headroom,
        "proj_used_pct": clamp(-proj_adjusted / limit * 100) if limit else 0.0,
        # UEFA football earnings
        "uefa_adj_eur": adj_eur,
        "uefa_allow_eur": allow_eur,
        "uefa_base_eur": u["football_earnings_base_limit_eur_m"],
        "uefa_ext_eur": u["football_earnings_equity_extended_limit_eur_m"],
        "uefa_equity_eur": u["equity_contribution_eur_m"],
        "uefa_margin": uefa_margin,
        "uefa_within": adj_eur >= -allow_eur,
        "uefa_used_pct": clamp(-adj_eur / allow_eur * 100) if allow_eur else 0.0,
        # UEFA squad cost control
        "scr": scr,
        "scr_cap": u["squad_cost_ratio_cap_pct"],
        "scr_pct": clamp(scr / u["squad_cost_ratio_cap_pct"] * 100) if u["squad_cost_ratio_cap_pct"] else 0.0,
        "proj_scr_pct": clamp(proj_scr / u["squad_cost_ratio_cap_pct"] * 100) if u["squad_cost_ratio_cap_pct"] else 0.0,
        "scr_anchor": anchor["season"],
        "scr_player_wages": round(player_wages, 1),
        "scr_amort": round(anchor["amortisation_gbp_m"], 1),
        "scr_agent": round(u["agent_fees_gbp_m"], 1),
        "scr_revenue": round(anchor["revenue_gbp_m"], 1),
        "scr_sale_profit": round(anchor["player_sale_profit_gbp_m"], 1),
        "proj_scr": proj_scr,
        "scr_within": scr <= u["squad_cost_ratio_cap_pct"],
        "reference": cfg.get("reference", {}),
    }


def set_sale_price(player, price):
    """Write a sale price (GBP m, or '' to clear) for one player back to players.csv.
    Preserves all other columns and the unquoted format (no field contains a comma)."""
    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        rows = list(reader)
    if any(r.get(None) for r in rows):
        raise ValueError("players.csv has a mis-columned row (stray comma) — fix before editing.")
    matches = [r for r in rows if r["player"] == player]
    if not matches:
        raise KeyError(player)
    matches[0]["sale_price_gbp_m"] = price
    with open(CSV_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def add_player(player, position, fee_gbp_m, contract_years, market_value_eur_m,
               status="owned", signed_date=None, confidence="med", note="",
               window_move="in"):
    """Append a new player to players.csv.

    The caller supplies the CONTRACT LENGTH in years; we derive contract_expiry
    from it (signed_date + length) so the amortization engine gets a real end date.
    Contract length itself is never stored as a column — only the resulting expiry.
    Returns the written row dict. Raises ValueError on bad/duplicate input.
    """
    player = (player or "").strip()
    note = (note or "").strip()
    position = (position or "").strip()
    if not player:
        raise ValueError("Player name is required.")
    # Unquoted CSV: a comma in a text field would shift every column.
    if "," in player or "," in note or "," in position:
        raise ValueError("No commas allowed in name/position/note (use ';').")

    status = (status or "owned").strip().lower()
    if status not in ("owned", "academy", "loan"):
        raise ValueError("Status must be owned, academy or loan.")
    window_move = (window_move or "").strip().lower()
    if window_move not in ("", "in", "out"):
        raise ValueError("window_move must be 'in', 'out' or '' (squad).")

    signed = parse_date(signed_date) if signed_date else TODAY
    try:
        yrs = float(contract_years)
    except (TypeError, ValueError):
        raise ValueError("Contract length (years) must be a number.")
    if yrs <= 0:
        raise ValueError("Contract length must be greater than 0 years.")
    # Day-based so it round-trips with the engine's years_between (days / 365.25).
    expiry = signed + timedelta(days=round(365.25 * yrs))

    try:
        mv = float(market_value_eur_m or 0)
    except (TypeError, ValueError):
        raise ValueError("Market value (€m) must be a number.")
    if status == "loan":
        fee = ""  # loaned-in: no asset capitalized
    else:
        try:
            fee = float(fee_gbp_m or 0)
        except (TypeError, ValueError):
            raise ValueError("Fee (£m) must be a number.")
        if fee < 0:
            raise ValueError("Fee cannot be negative.")

    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        rows = list(reader)
    if any(r.get(None) for r in rows):
        raise ValueError("players.csv has a mis-columned row (stray comma) — fix before adding.")
    if any((r["player"] or "").strip().lower() == player.lower() for r in rows):
        raise ValueError(f"'{player}' is already in the squad.")

    newrow = {k: "" for k in fieldnames}
    newrow.update(
        player=player, position=position, status=status,
        fee_gbp_m=fee, signed_date=signed.isoformat(),
        contract_expiry=expiry.isoformat(), market_value_eur_m=mv,
        confidence=(confidence or "med").strip().lower(), note=note,
        window_move=window_move,
    )
    with open(CSV_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
        writer.writerow(newrow)
    return newrow


def read_raw():
    """Return the raw CSV rows (unquoted, no compute) for edit pre-fill. Guards commas."""
    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        if r.get(None):
            raise ValueError(f"Row for '{r.get('player')}' has a stray comma — fix players.csv.")
    return rows


def update_player(player, position=None, status=None, fee_gbp_m=None,
                  contract_years=None, market_value_eur_m=None, window_move=None):
    """Edit an existing player in players.csv. Only the fields passed (not None) are
    changed. contract_years, when given, re-derives contract_expiry from signed_date
    (same length->expiry rule as add_player). window_move is left untouched unless
    passed, so the Deal dropdown remains the bucket control. Raises KeyError if the
    player isn't found, ValueError on bad input."""
    player = (player or "").strip()
    if not player:
        raise ValueError("Player name is required.")
    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        rows = list(reader)
    if any(r.get(None) for r in rows):
        raise ValueError("players.csv has a mis-columned row (stray comma) — fix before editing.")
    matches = [r for r in rows if (r["player"] or "").strip() == player]
    if not matches:
        raise KeyError(player)
    row = matches[0]

    if status is not None:
        status = (status or "").strip().lower()
        if status not in ("owned", "academy", "loan"):
            raise ValueError("Status must be owned, academy or loan.")
        row["status"] = status
    cur_status = (row["status"] or "").strip().lower()

    if position is not None:
        position = (position or "").strip()
        if "," in position:
            raise ValueError("No commas allowed in position (use ';').")
        row["position"] = position

    if fee_gbp_m is not None:
        if cur_status == "loan":
            row["fee_gbp_m"] = ""  # loaned-in: no asset capitalized
        else:
            try:
                fee = float(fee_gbp_m or 0)
            except (TypeError, ValueError):
                raise ValueError("Fee (£m) must be a number.")
            if fee < 0:
                raise ValueError("Fee cannot be negative.")
            row["fee_gbp_m"] = fee

    if market_value_eur_m is not None:
        try:
            row["market_value_eur_m"] = float(market_value_eur_m or 0)
        except (TypeError, ValueError):
            raise ValueError("Market value (€m) must be a number.")

    if contract_years is not None and str(contract_years).strip() != "":
        try:
            yrs = float(contract_years)
        except (TypeError, ValueError):
            raise ValueError("Contract length (years) must be a number.")
        if yrs <= 0:
            raise ValueError("Contract length must be greater than 0 years.")
        signed = parse_date(row["signed_date"]) if row["signed_date"] else TODAY
        row["contract_expiry"] = (signed + timedelta(days=round(365.25 * yrs))).isoformat()

    if window_move is not None:
        window_move = (window_move or "").strip().lower()
        if window_move not in ("", "in", "out"):
            raise ValueError("window_move must be 'in', 'out' or '' (squad).")
        row["window_move"] = window_move

    with open(CSV_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return row


def set_window_move(player, move):
    """Set the transfer-window bucket ('in', 'out', or '' for squad) for one player.
    Preserves all other columns and the unquoted format."""
    move = (move or "").strip().lower()
    if move not in ("", "in", "out"):
        raise ValueError("window_move must be 'in', 'out', or '' (squad).")
    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        rows = list(reader)
    if any(r.get(None) for r in rows):
        raise ValueError("players.csv has a mis-columned row (stray comma) — fix before editing.")
    matches = [r for r in rows if r["player"] == player]
    if not matches:
        raise KeyError(player)
    matches[0]["window_move"] = move
    with open(CSV_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main():
    rows = load_players()

    # --- console table ---
    hdr = f"{'Player':<22}{'Pos':<5}{'Fee':>7}{'NBV':>8}{'MktVal':>9}{'BookP/L':>9}{'%Amort':>8}"
    print("\nTOTTENHAM HOTSPUR - SQUAD BOOK VALUE (as of {})".format(TODAY))
    print("All figures in GBP millions. Market values = Transfermarkt EUR x {:.2f}.".format(EUR_GBP))
    print("* = contract extension modelled (amortization schedule reset at extension date).")
    print("=" * len(hdr))
    print(hdr)
    print("-" * len(hdr))

    for r in rows:
        if r["status"] == "loan":
            print(f"{r['player']:<22}{r['position']:<5}{'loan':>7}{'-':>8}"
                  f"{r['market_value_gbp_m']:>9}{'-':>9}{'-':>8}")
            continue
        name = r["player"] + (" *" if r.get("extended") else "")
        print(f"{name:<22}{r['position']:<5}{r['fee_gbp_m']:>7}{r['nbv_gbp_m']:>8}"
              f"{r['market_value_gbp_m']:>9}{r['book_profit_gbp_m']:>9}{r['pct_amortized']:>7}%")

    t = compute_totals(rows)
    print("-" * len(hdr))
    print(f"{'TOTAL (owned + academy)':<27}{t['fee']:>7.1f}{t['nbv']:>8.1f}"
          f"{t['mv']:>9.1f}{t['bp']:>9.1f}")
    print("=" * len(hdr))
    print(f"\nSquad acquisition cost : GBP {t['fee']:,.1f}m")
    print(f"Remaining book value   : GBP {t['nbv']:,.1f}m   (already amortized: GBP {t['amortized']:,.1f}m)")
    print(f"Squad market value     : GBP {t['mv']:,.1f}m")
    print(f"Book profit on sale    : GBP {t['bp']:,.1f}m  <- PSR/FFP profit at market value (agreed price where known)\n")

    # --- write output csv ---
    fields = ["player", "position", "status", "confidence", "extended", "on_loan_at",
              "window_move", "fee_gbp_m", "amort_period_yrs", "years_elapsed",
              "pct_amortized", "nbv_gbp_m", "market_value_gbp_m", "sale_price_gbp_m",
              "book_profit_gbp_m"]
    with open(OUT_PATH, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fields})
    print(f"Wrote {OUT_PATH}")


if __name__ == "__main__":
    main()
