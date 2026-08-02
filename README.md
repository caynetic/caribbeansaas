# CaribbeanSaaS

CaribbeanSaaS is a curated directory of Caribbean-built software and digital
platforms.

## Public deployment

Cloudflare Pages deploys the generated `dist/` directory, not the repository
root. The build refreshes generated country pages and the sitemap before
copying the explicit public allowlist. Build it locally with:

```bash
python3 scripts/build_public_site.py
```

The public bundle contains only website pages, public assets, and catalog data.
Local operating records, research, audits, design-review artifacts, agent
configuration, optional discovery material, and credentials are deliberately
excluded.

The human-readable Open Data explorer at `open-data.html` visualizes every
public-safe catalog record, while `data/products.json` remains the raw data
endpoint and the homepage directory remains limited to `visibility: listed`.
The directory and explorer show six matching records per page with shareable
URL state. Listed primary countries also receive generated root pages such as
`bahamas.html`, served canonically by Cloudflare Pages at `/bahamas`.
