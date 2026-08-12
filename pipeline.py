#!/usr/bin/env python3
"""
Rebuilds master_spending.json for "Where Your Tax Dollar Goes" from live
Government of Canada open data. Self-contained: downloads, aggregates,
matches, merges. Prints progress to stderr, writes master_spending.json.

Usage: python3 pipeline.py
Requires: curl on PATH, python3 stdlib only (csv, collections, re, json).
"""
import csv, collections, re, json, subprocess, sys, os

csv.field_size_limit(10_000_000)

def log(*a):
    print(*a, file=sys.stderr)

WORKDIR = os.environ.get("PIPELINE_DIR", ".")
os.makedirs(WORKDIR, exist_ok=True)

def dl(url, out):
    out = os.path.join(WORKDIR, out)
    if os.path.exists(out) and os.path.getsize(out) > 1000:
        log(f"  (reusing cached {out})")
        return out
    log(f"  downloading {url} -> {out}")
    r = subprocess.run(["curl", "-sL", url, "-o", out, "--max-time", "590",
                         "-w", "HTTP %{http_code} %{size_download} bytes"],
                        capture_output=True, text=True)
    log("  " + r.stdout)
    if r.returncode != 0:
        raise RuntimeError(f"download failed: {url}\n{r.stderr}")
    return out

# ---------------------------------------------------------------------------
# STEP 0: figure out the latest fully-tabled fiscal year available.
# Public Accounts of Canada (and this standard-object dataset) are tabled
# each FALL for the fiscal year ending the PRIOR March 31. So:
#   before ~November: latest available FY ends this year's March 31
#   after ~November: latest available FY may have just advanced one year
# Don't hardcode "2024-25" — detect it from the data itself (see STEP 1).
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# STEP 1: standard-object expenditures by department (ALL orgs, ALL years)
# Source: GC InfoBase / TBS, Public Accounts of Canada — Expenditures by
# Standard Object. Dataset a35cf382-690c-4221-a971-cf0fd189a46f, resource
# 27e54a33-3c39-42a9-8d58-46dd37c527e5. Columns: fy_ef, org_id, org_name,
# sobj_en, expenditures.
# ---------------------------------------------------------------------------
log("STEP 1: standard-object expenditures (department totals)")
eso_path = dl(
    "https://open.canada.ca/data/dataset/a35cf382-690c-4221-a971-cf0fd189a46f/resource/27e54a33-3c39-42a9-8d58-46dd37c527e5/download/eso_eac_en.csv",
    "eso_eac_en.csv",
)

years_seen = set()
with open(eso_path, encoding="utf-8-sig") as f:
    r = csv.DictReader(f)
    for row in r:
        years_seen.add(row["fy_ef"])
# pick the lexicographically-latest "YYYY-YY" fiscal year string present
FY = sorted(years_seen)[-1]
log(f"  latest fiscal year found in standard-object data: {FY}")

by_org = collections.defaultdict(lambda: collections.defaultdict(float))
with open(eso_path, encoding="utf-8-sig") as f:
    r = csv.DictReader(f)
    for row in r:
        if row["fy_ef"] != FY:
            continue
        by_org[row["org_name"]][row["sobj_en"]] += float(row["expenditures"] or 0)

all_orgs = []
for name, sobjs in by_org.items():
    total = sum(sobjs.values())
    all_orgs.append({
        "name": name, "total": round(total, 2),
        "standard_objects": [
            {"name": k, "amount": round(v, 2)}
            for k, v in sorted(sobjs.items(), key=lambda x: -x[1])
            if abs(v) > 1000
        ],
    })
TOTAL_SPEND = sum(o["total"] for o in all_orgs)
log(f"  {len(all_orgs)} organizations, total ${TOTAL_SPEND/1e9:.1f}B")

# ---------------------------------------------------------------------------
# STEP 2: contracts (Proactive Publication of Contracts, >=$10,000)
# Dataset d8f85d91-7dec-4fd1-8055-483b77225d8b, resource
# fac950c0-00d5-4ec1-a4d3-9cbebf98a305. ~600MB. Columns include:
# vendor_name, contract_value, reporting_period ("YYYY-YYYY-QN"),
# owner_org, owner_org_title, description_en, contract_date.
# Filter to the FOUR quarters matching FY (e.g. FY "2024-25" -> reporting
# periods "2024-2025-Q1".."Q4" — note FY uses 2-digit end year, reporting
# periods use 4-digit both years, so expand: "2024-25" -> "2024-2025").
# ---------------------------------------------------------------------------
log("STEP 2: contracts")
fy_start, fy_end2 = FY.split("-")
fy_end4 = fy_start[:2] + fy_end2  # e.g. "2024" + "25" -> "2025"
FY_QUARTERS = {f"{fy_start}-{fy_end4}-Q{q}" for q in (1, 2, 3, 4)}
log(f"  matching contract reporting periods: {sorted(FY_QUARTERS)}")

contracts_path = dl(
    "https://open.canada.ca/data/dataset/d8f85d91-7dec-4fd1-8055-483b77225d8b/resource/fac950c0-00d5-4ec1-a4d3-9cbebf98a305/download/contracts.csv",
    "contracts_full.csv",
)

c_by_org_total = collections.defaultdict(float)
c_by_org_count = collections.defaultdict(int)
c_vendors = collections.defaultdict(float)
c_big = []
with open(contracts_path, encoding="utf-8-sig", errors="replace") as f:
    r = csv.reader(f)
    header = next(r)
    idx = {h: i for i, h in enumerate(header)}
    vi, oi, pi, ni, di, dti = (idx["contract_value"], idx["owner_org_title"],
                                idx["reporting_period"], idx["vendor_name"],
                                idx["description_en"], idx["contract_date"])
    for row in r:
        if len(row) <= vi or row[pi] not in FY_QUARTERS:
            continue
        try:
            val = float(row[vi]) if row[vi] else 0.0
        except ValueError:
            continue
        org, vend = row[oi], row[ni]
        c_by_org_total[org] += val
        c_by_org_count[org] += 1
        c_vendors[(org, vend)] += val
        if val >= 500_000:
            c_big.append({"org": org, "vendor": vend, "value": round(val, 2), "desc": row[di][:180], "date": row[dti]})
log(f"  {sum(c_by_org_count.values())} contracts, ${sum(c_by_org_total.values())/1e9:.1f}B, {len(c_big)} >= $500K")

contract_orgs = []
for org, tot in sorted(c_by_org_total.items(), key=lambda x: -x[1]):
    top_v = sorted([(v[1], amt) for v, amt in c_vendors.items() if v[0] == org], key=lambda x: -x[1])[:12]
    contract_orgs.append({"org": org, "total": round(tot, 2), "count": c_by_org_count[org],
                           "top_vendors": [{"name": v, "amount": round(a, 2)} for v, a in top_v]})

# ---------------------------------------------------------------------------
# STEP 3: grants & contributions (Proactive Disclosure, >=$25,000)
# Dataset 432527ab-7aac-45b5-81d6-7597107a7013, resource
# 1d15a62f-5656-49ad-8c88-f40ce689d831. ~2.3GB. Columns include:
# recipient_legal_name, agreement_value, agreement_start_date (YYYY-MM-DD),
# owner_org, owner_org_title, agreement_title_en.
# Filter by agreement_start_date within the fiscal year window
# (Apr 1 fy_start -> Mar 31 fy_end4).
# ---------------------------------------------------------------------------
log("STEP 3: grants & contributions")
fy_lo = f"{fy_start}-04-01"
fy_hi = f"{fy_end4}-03-31"
log(f"  matching agreement_start_date in [{fy_lo}, {fy_hi}]")

grants_path = dl(
    "https://open.canada.ca/data/dataset/432527ab-7aac-45b5-81d6-7597107a7013/resource/1d15a62f-5656-49ad-8c88-f40ce689d831/download/grants.csv",
    "grants_full.csv",
)

g_by_org_total = collections.defaultdict(float)
g_by_org_count = collections.defaultdict(int)
g_recipients = collections.defaultdict(float)
g_big = []
with open(grants_path, encoding="utf-8-sig", errors="replace") as f:
    r = csv.reader(f)
    header = next(r)
    idx = {h: i for i, h in enumerate(header)}
    vi, oi, si, ri, ti = (idx["agreement_value"], idx["owner_org_title"],
                           idx["agreement_start_date"], idx["recipient_legal_name"],
                           idx["agreement_title_en"])
    for row in r:
        if len(row) <= vi:
            continue
        d = row[si]
        if not d or not (fy_lo <= d <= fy_hi):
            continue
        try:
            val = float(row[vi]) if row[vi] else 0.0
        except ValueError:
            continue
        org, rec = row[oi], row[ri]
        g_by_org_total[org] += val
        g_by_org_count[org] += 1
        g_recipients[(org, rec)] += val
        if val >= 250_000:
            g_big.append({"org": org, "recipient": rec, "value": round(val, 2), "title": row[ti][:180]})
log(f"  {sum(g_by_org_count.values())} grants, ${sum(g_by_org_total.values())/1e9:.1f}B, {len(g_big)} >= $250K")

grant_orgs = []
for org, tot in sorted(g_by_org_total.items(), key=lambda x: -x[1]):
    top_r = sorted([(v[1], amt) for v, amt in g_recipients.items() if v[0] == org], key=lambda x: -x[1])[:12]
    grant_orgs.append({"org": org, "total": round(tot, 2), "count": g_by_org_count[org],
                        "top_recipients": [{"name": v, "amount": round(a, 2)} for v, a in top_r]})

# ---------------------------------------------------------------------------
# STEP 4: fuzzy-match contract/grant org names ("X Canada" style) onto the
# canonical standard-object org names ("Department of X" style), by token
# overlap after stripping stopwords. Manual overrides for known mismatches.
# ---------------------------------------------------------------------------
log("STEP 4: reconciling organization names across datasets")
STOP = {"department", "of", "the", "canada", "agency", "board", "secretariat",
        "and", "for", "office", "service", "services", "commission", "offices"}

def tokens(s):
    s = s.split("|")[0]
    s = re.sub(r"[^a-zA-Z0-9]+", " ", s).lower()
    return set(w for w in s.split() if w not in STOP and len(w) > 2)

eso_tok = [(o["name"], tokens(o["name"])) for o in all_orgs]

MANUAL = {
    "Global Affairs Canada": "Department of Foreign Affairs, Trade and Development",
    "Elections Canada": "Office of the Chief Electoral Officer",
    "Office of the Privacy Commissioner of Canada": "Offices of the Information and Privacy Commissioners of Canada",
    "Office of the Information Commissioner of Canada": "Offices of the Information and Privacy Commissioners of Canada",
}

def best_match(raw_name):
    en = raw_name.split("|")[0].strip()
    for k, v in MANUAL.items():
        if en.startswith(k):
            return v
    t = tokens(raw_name)
    best, best_score = None, 0
    for eso_name, eso_t in eso_tok:
        if not t or not eso_t:
            continue
        score = len(t & eso_t) / max(1, min(len(t), len(eso_t)))
        if score > best_score:
            best_score, best = score, eso_name
    return best if best_score >= 0.6 else None

by_canon = {o["name"]: dict(o, contracts=None, grants=None) for o in all_orgs}
big_by_canon_c, big_by_canon_g = {}, {}

for c in contract_orgs:
    canon = best_match(c["org"])
    if canon and canon in by_canon:
        by_canon[canon]["contracts"] = {"total": c["total"], "count": c["count"], "top_vendors": c["top_vendors"], "raw_name": c["org"]}
    big_by_canon_c.setdefault(canon or c["org"], [])

for g in grant_orgs:
    canon = best_match(g["org"])
    if canon and canon in by_canon:
        by_canon[canon]["grants"] = {"total": g["total"], "count": g["count"], "top_recipients": g["top_recipients"], "raw_name": g["org"]}

for row in c_big:
    canon = best_match(row["org"]) or row["org"]
    big_by_canon_c.setdefault(canon, []).append(row)
for row in g_big:
    canon = best_match(row["org"]) or row["org"]
    big_by_canon_g.setdefault(canon, []).append(row)

for canon, entry in by_canon.items():
    if entry["contracts"]:
        entry["contracts"]["big"] = big_by_canon_c.get(canon, [])
    if entry["grants"]:
        entry["grants"]["big"] = big_by_canon_g.get(canon, [])

final = sorted(by_canon.values(), key=lambda x: -x["total"])
matched_c = sum(1 for o in final if o["contracts"])
matched_g = sum(1 for o in final if o["grants"])
log(f"  {matched_c} orgs matched to contract data, {matched_g} matched to grant data")

out_path = os.path.join(WORKDIR, "master_spending.json")
with open(out_path, "w") as f:
    json.dump(final, f, separators=(",", ":"))
log(f"DONE. Wrote {out_path} ({os.path.getsize(out_path)/1024:.0f} KB). "
    f"FY={FY}, total=${TOTAL_SPEND/1e9:.1f}B, orgs={len(final)}, "
    f"contracts>=500K={len(c_big)}, grants>=250K={len(g_big)}")
print(json.dumps({"FY": FY, "total": TOTAL_SPEND, "org_count": len(final),
                   "contracts_big": len(c_big), "grants_big": len(g_big)}))
