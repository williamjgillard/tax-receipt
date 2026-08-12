# Where Your Tax Dollar Goes — build pipeline

Source of truth for the [Where Your Tax Dollar Goes](https://claude.ai/code/artifact/793a3f4c-3b8c-4b7e-ab3e-a2edc7146ad7) artifact — a Canadian federal spending tracker and political fact-checker.

## Files

- **`pipeline.py`** — downloads and aggregates real Government of Canada open data (department spending by standard object, contracts ≥$10K, grants ≥$25K from open.canada.ca) into `master_spending.json`. **Only runnable from an environment with real internet access** — cloud routine sandboxes on this platform can't reach open.canada.ca (allowlisted to package registries only), so this is run manually in an interactive Claude Code session, not automated.
- **`master_spending.json`** — the ~5MB output of the last `pipeline.py` run. Checked in so the claims-refresh routine (which *can* run unattended) always has a complete, valid dataset to build from without touching the network for spending data.
- **`template_before.html`** / **`template_after.html`** — the site's HTML/CSS/JS, split around the embedded JSON data block. `template_before.html` has two placeholders: `{{CLAIM_CARDS}}` and `{{CLAIMS_FRESHNESS}}`.
- **`build.py`** — assembles the final page from the templates + `master_spending.json` + a claim-cards HTML fragment. Validates before writing (JSON parses, no leftover placeholders, at least one claim card) — refuses to produce a broken page.
- **`claim_cards_seed.html`** — the 5 original hand-checked claims, in the exact markup `build.py` expects. Useful as a reference for the expected claim-card format.

## Refresh cadence

| Data | How | Why |
|---|---|---|
| Department spending, contracts, grants | Manual: re-run `pipeline.py`, commit `master_spending.json` | Needs open.canada.ca access, which cloud routines can't reach |
| Tax brackets | Manual, annually (CRA publishes new brackets each fall) | Same |
| Claim Check | Automated weekly routine | Only needs WebSearch + the Artifact tool, both of which work fine in a cloud sandbox |

## How the Claim Check routine works

Each run: WebFetches the live artifact URL to extract the current claims (as structured text — it never touches WebFetch's saved file directly, since anything under a `tool-results` path triggers an unattended-unfriendly permission prompt), researches 1-2 new claims via WebSearch, reconstructs the full claim-card list, runs `build.py`, and publishes via the Artifact tool with `url=` pointing at the same artifact. The repo's `master_spending.json` is carried forward unchanged every time.

## Regenerating spending data manually

```
python3 pipeline.py            # downloads ~3GB, takes a few minutes, writes master_spending.json
python3 build.py --claims claim_cards_seed.html --freshness "verified $(date +'%B %-d, %Y')" --out tax-receipt.html
```

Then publish `tax-receipt.html` via the Artifact tool with `url=` set to the live artifact's URL, and commit the updated `master_spending.json`.
