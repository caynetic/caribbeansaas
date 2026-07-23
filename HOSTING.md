# Hosting CaribbeanSaaS

CaribbeanSaaS is a static site hosted on Cloudflare Pages.

## Production setup

- **Git repository:** `caynetic/caribbeansaas`
- **Production branch:** `main`
- **Cloudflare Pages project:** `caribbeansaas`
- **Production domain:** `https://caribbeansaas.com/`
- **Source integration:** GitHub

Cloudflare Pages builds every production push to `main`. Its configured build
settings are:

```text
Root directory:   (repository root)
Build command:    python3 scripts/build_public_site.py
Build output:     dist
```

The build script generates `dist/` from an explicit allowlist. Pages uploads
that generated directory only; it does not publish the repository root.

## Public deployment contents

The generated bundle contains:

- Homepage and support pages (`index.html`, `404.html`, `privacy.html`, and
  `terms.html`).
- Public assets under `assets/`.
- The public catalog at `data/products.json`.
- Search and discovery files such as `robots.txt`, `sitemap.xml`, `llms.txt`,
  and `site.webmanifest`.

`data/products.json` is intentionally public. The directory displays only
records whose `visibility` is `listed`; the JSON can retain public-safe
`unlisted` records, but must never contain internal review notes, personal
contact details, or unpublished research. An unlisted record is not displayed
and does not communicate a rejection, availability conclusion, or endorsement.

## Deploying a change

1. Update the public source files or catalog data.
2. Run the local checks:

   ```bash
   python3 scripts/generate_seo_pages.py
   python3 tests/public_bundle_check.py
   python3 tests/page_structure_check.py
   python3 tests/seo_pages_check.py
   ```

3. Review the generated bundle if needed:

   ```bash
   python3 scripts/build_public_site.py
   find dist -type f | sort
   ```

4. Commit and push to `main`. Cloudflare Pages builds and deploys the commit
   automatically.

No public build-time environment variables are required. Keep credentials and
local operating records outside the public bundle and out of Git history.

## Verifying a deployment

After a deploy succeeds, confirm these endpoints are available:

```text
https://caribbeansaas.com/
https://caribbeansaas.com/privacy.html
https://caribbeansaas.com/terms.html
https://caribbeansaas.com/data/products.json
```

Source files and local records, such as `scripts/`, `tests/`, `docs/`, and
`PROJECT_BRAIN.md`, should return `404` from the public site.
