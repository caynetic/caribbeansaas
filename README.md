# CaribbeanSaaS

**Discover software built in or serving the Caribbean.**

CaribbeanSaaS is a curated directory of SaaS products, AI tools, and digital
platforms with a Caribbean connection. Browse by country or category, search
for a product, and follow its official website.

[Explore the directory](https://caribbeansaas.com/#directory) ·
[Open data](https://caribbeansaas.com/open-data.html) ·
[Listing policy](https://caribbeansaas.com/curation.html) ·
[Get listed](https://caribbeansaas.com/#submit) · [Run locally](#run-it-locally)

[![CaribbeanSaaS illustration of software search, category and region filters, and product discovery](readme-assets/caribbeansaas-illustration.webp)](https://caribbeansaas.com/)

*Project illustration from [Caynetic.com](https://caynetic.com/#products).*

## Explore the directory

- Search products and filter by category or Caribbean region.
- Share a search, filter, or results page through its URL.
- Browse country pages such as [The Bahamas](https://caribbeansaas.com/bahamas)
  and [Jamaica](https://caribbeansaas.com/jamaica).
- Read, copy, or download the complete public catalog on the
  [Open Data page](https://caribbeansaas.com/open-data.html).

Listings receive basic identity, official-link, and Caribbean-connection
checks. Inclusion is not an endorsement or an assessment of product quality,
security, or performance. See the [listing policy](https://caribbeansaas.com/curation.html).

## Run it locally

Requirements: Node.js with npm, and Python 3.

```bash
npm ci
python3 scripts/build_public_site.py
python3 -m http.server 8000 --directory dist
```

Open `http://127.0.0.1:8000`. The build refreshes the generated country pages
and sitemap, compiles the pinned Tailwind stylesheet, and copies the explicit
public allowlist into `dist/`. To rebuild only the stylesheet, run
`npm run build:css`.

## How it is built

The site is static and prebuilt. It uses HTML, JavaScript, compiled Tailwind
CSS, and a single public JSON catalog, with Cloudflare Pages serving the
generated bundle.

| Path | Purpose |
| --- | --- |
| [`data/products.json`](data/products.json) | Public catalog records, metadata, and available hosted logo URLs |
| [`index.html`](index.html) | Searchable directory with six matching records per page |
| [`open-data.html`](open-data.html) | Complete catalog as formatted JSON, with copy and download controls |
| [`scripts/build_public_site.py`](scripts/build_public_site.py) | Generate pages, compile CSS, and assemble `dist/` |
| [`scripts/generate_seo_pages.py`](scripts/generate_seo_pages.py) | Generate country pages and the sitemap from the catalog |
| [`styles/tailwind.css`](styles/tailwind.css) | Source for the compiled utility stylesheet |
| [`assets/`](assets/) | Public artwork, scripts, styles, and locally served fonts |

Primary countries represented in the catalog receive root files such as
`bahamas.html`, served canonically by Cloudflare Pages at `/bahamas`. Fonts are
served locally with their OFL licenses in `assets/fonts/`; the hero uses
responsive WebP variants of the existing brand artwork.

## Public deployment boundary

Cloudflare Pages deploys **`dist/`, not the repository root**. The public bundle
contains only website pages, public assets, and catalog data. Operating
records, research, audits, agent configuration, optional discovery material,
and credentials stay outside it. The README illustrations in `readme-assets/`
are excluded from the website bundle.

## Suggest a product or correction

Use the [Get listed section](https://caribbeansaas.com/#submit) for the current
submission instructions. Include the product name, official website, country
or Caribbean connection, category, and a short summary. For listing errors,
contact [hello@caribbeansaas.com](mailto:hello@caribbeansaas.com).

Maintained by [Caynetic Ltd.](https://caynetic.com/).
