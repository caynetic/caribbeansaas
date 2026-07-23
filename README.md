# CaribbeanSaaS

CaribbeanSaaS is a curated directory of Caribbean-built software and digital
platforms.

## Public deployment

Cloudflare Pages deploys the generated `dist/` directory, not the repository
root. Build it locally with:

```bash
python3 scripts/build_public_site.py
```

The public bundle contains only website pages, public assets, catalog data, and
discovery files. Local operating records, research, audits, design-review
artifacts, and credentials are deliberately excluded.

The human-readable Open Data explorer at `open-data.html` visualizes every
public-safe catalog record, while `data/products.json` remains the raw data
endpoint and the homepage directory remains limited to `visibility: listed`.

For the production setup, deploy process, public-bundle boundaries, and live
verification steps, see [HOSTING.md](HOSTING.md).

## Automation

The local [weekly review skill](.agents/skills/caribbeansaas-weekly-review/SKILL.md)
runs every Monday at 9:00 AM Nassau time through a machine-local Codex
schedule. Private reviews and the schedule's machine-specific configuration
are ignored from Git and the public bundle. After a fully validated run, the
coordinator may automatically commit and push only append-only, public-safe
`visibility: unlisted` additions to `data/products.json`; GitHub-connected
Cloudflare Pages then deploys that public dataset. It never changes a record to
`listed`, so making an active homepage listing remains a manual decision. Its
guarded local ledger compares each discovery run against the full
public/private identity inventory, including aliases, canonical domains, and
official app-store IDs, and records a private publication receipt.

## Checks

```bash
python3 scripts/generate_seo_pages.py
python3 tests/review_ledger_check.py
python3 tests/public_bundle_check.py
python3 tests/page_structure_check.py
python3 tests/seo_pages_check.py
```
