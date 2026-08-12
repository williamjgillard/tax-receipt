#!/usr/bin/env python3
"""
Assembles the final tax-receipt.html from:
  - template_before.html  (everything up to the claims section; has
    {{CLAIM_CARDS}} and {{CLAIMS_FRESHNESS}} placeholders)
  - master_spending.json  (the ~5MB embedded spending dataset, checked
    into this repo as-is; only changes when a human re-runs pipeline.py
    in an interactive session and commits the result)
  - template_after.html   (the closing <script> block)
  - a claim-cards HTML fragment (existing claims + any new ones for this
    run, already rendered to the site's exact claim-card markup)
  - a one-line "claims freshness" string

Usage:
  python3 build.py --claims claim_cards.html --freshness "refreshed August 19, 2026 by automated routine, individually sourced" --out tax-receipt.html

Fails loudly (non-zero exit, no output file) if anything looks wrong,
rather than ever writing a half-broken page.
"""
import argparse
import json
import re
import sys


def fail(msg):
    print(f"BUILD FAILED: {msg}", file=sys.stderr)
    sys.exit(1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--claims", required=True, help="Path to an HTML file containing all <div class=\"claim-card\">...</div> blocks to show, in order.")
    ap.add_argument("--freshness", required=True, help="Text for the claims: segment of the freshness line, e.g. 'refreshed August 19, 2026 by automated routine, individually sourced'.")
    ap.add_argument("--out", default="tax-receipt.html")
    ap.add_argument("--template-before", default="template_before.html")
    ap.add_argument("--template-after", default="template_after.html")
    ap.add_argument("--spending-json", default="master_spending.json")
    args = ap.parse_args()

    with open(args.template_before, encoding="utf-8") as f:
        before = f.read()
    with open(args.template_after, encoding="utf-8") as f:
        after = f.read()
    with open(args.claims, encoding="utf-8") as f:
        claim_cards = f.read()
    with open(args.spending_json, encoding="utf-8") as f:
        spending_json_text = f.read()

    if "{{CLAIM_CARDS}}" not in before:
        fail("template_before.html is missing the {{CLAIM_CARDS}} placeholder")
    if "{{CLAIMS_FRESHNESS}}" not in before:
        fail("template_before.html is missing the {{CLAIMS_FRESHNESS}} placeholder")
    if claim_cards.count('<div class="claim-card">') < 1:
        fail("claims file has zero claim-card blocks — refusing to publish an empty Claim Check section")
    if "</script" in spending_json_text:
        fail("spending JSON contains a literal </script sequence — investigate before publishing")

    try:
        parsed = json.loads(spending_json_text)
        if not isinstance(parsed, list) or len(parsed) < 100:
            fail(f"spending JSON parsed but looks wrong (expected a list of 100+ orgs, got {type(parsed)} len {len(parsed) if hasattr(parsed, '__len__') else 'n/a'})")
    except json.JSONDecodeError as e:
        fail(f"spending JSON does not parse: {e}")

    before = before.replace("{{CLAIM_CARDS}}", claim_cards.strip())
    before = before.replace("{{CLAIMS_FRESHNESS}}", args.freshness)

    if "{{" in before:
        leftover = re.findall(r"\{\{[^}]*\}\}", before)
        fail(f"leftover unsubstituted placeholder(s) in template_before.html: {leftover}")

    full = (
        before
        + '\n<script type="application/json" id="spending-data">'
        + spending_json_text
        + "</script>\n"
        + after
    )

    with open(args.out, "w", encoding="utf-8") as f:
        f.write(full)

    card_count = claim_cards.count('<div class="claim-card">')
    print(f"Wrote {args.out} ({len(full)/1e6:.2f} MB), "
          f"{card_count} claim cards, "
          f"{len(parsed)} orgs in spending data.")


if __name__ == "__main__":
    main()
