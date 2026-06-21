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
import os
from datetime import date, datetime

CSV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "players.csv")
OUT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "book_value_output.csv")

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


def compute_totals(rows):
    """Sum the owned/academy rows (loans excluded). Splits book profit into
    realized (players with a sale price entered) vs unrealized (at market value)."""
    t = {"fee": 0.0, "nbv": 0.0, "mv": 0.0, "bp": 0.0, "realized": 0.0, "unrealized": 0.0}
    for r in rows:
        if r["status"] == "loan":
            continue
        t["fee"] += r["fee_gbp_m"]
        t["nbv"] += r["nbv_gbp_m"]
        t["mv"] += r["market_value_gbp_m"]
        t["bp"] += r["book_profit_gbp_m"]
        if r.get("sold"):
            t["realized"] += r["book_profit_gbp_m"]
        else:
            t["unrealized"] += r["book_profit_gbp_m"]
    t["amortized"] = t["fee"] - t["nbv"]
    return {k: round(v, 1) for k, v in t.items()}


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
              "fee_gbp_m", "amort_period_yrs", "years_elapsed", "pct_amortized",
              "nbv_gbp_m", "market_value_gbp_m", "sale_price_gbp_m", "book_profit_gbp_m"]
    with open(OUT_PATH, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fields})
    print(f"Wrote {OUT_PATH}")


if __name__ == "__main__":
    main()
