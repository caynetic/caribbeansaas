# CaribbeanSaaS

CaribbeanSaaS is a discovery directory of software and digital platforms built in
or specifically serving the Caribbean.

## Public deployment

Cloudflare Pages deploys the generated `dist/` directory, not the repository
root. The build refreshes generated country pages and the sitemap before
compiling the stylesheet and copying the explicit public allowlist. Install the
locked CSS build dependencies with Node.js/npm, then build locally:

```bash
npm ci
python3 scripts/build_public_site.py
```

The public bundle contains only website pages, public assets, and catalog data.
Local operating records, research, audits, design-review artifacts, agent
configuration, optional discovery material, and credentials are deliberately
excluded.

The Open Data page at `open-data.html` displays every public catalog record as
formatted JSON, with copy and download controls. `data/products.json` remains
the raw source endpoint, including available hosted logo URLs and metadata.
The homepage directory remains limited to `visibility: listed`, with six
matching records per page and shareable URL state. Listed primary countries
also receive generated root pages such as `bahamas.html`, served canonically
by Cloudflare Pages at `/bahamas`.

Styles are compiled from `styles/tailwind.css` and `tailwind.config.cjs`; the
site does not generate Tailwind styles in visitors' browsers. Existing fonts
are served locally with their OFL licenses in `assets/fonts/`. The hero uses
responsive WebP variants of the existing brand image.
