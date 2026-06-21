#!/usr/bin/env python3
"""
Build a self-contained, shareable static snapshot of the dashboard.

Reuses the exact same template as the live app (app.PAGE) in `static=True` mode:
the page is fully interactive client-side (sort, Sell XI simulator, PSR panel) but
sale prices are read-only and the data is baked in — no Python/Flask needed to view.

Output: dist/index.html  (a single file you can host anywhere or open directly).

Run:  py -3 build_static.py
"""
import os
from jinja2 import Template

import book_value as bv
from app import PAGE

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs")
OUT_FILE = os.path.join(OUT_DIR, "index.html")


def main():
    rows = bv.load_players()
    totals = bv.compute_totals(rows)
    html = Template(PAGE).render(
        rows=rows, t=totals, today=bv.TODAY, rate=bv.EUR_GBP, static=True
    )
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Wrote {OUT_FILE} ({len(html):,} bytes, {len(rows)} players)")
    print("Open it directly, or host the dist/ folder (GitHub Pages, Netlify, etc.).")


if __name__ == "__main__":
    main()
