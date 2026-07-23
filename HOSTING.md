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

The build script first regenerates and validates listed-only country pages and
the sitemap, then generates `dist/` from an explicit allowlist. Pages uploads
that generated directory only; it does not publish the repository root. A
generation failure occurs before the previous build directory is removed.

## Public deployment contents

The generated bundle contains:

- Homepage, generated listed-only country pages such as `bahamas.html`, and
  support pages (`404.html`, `curation.html`, `open-data.html`, `privacy.html`,
  and `terms.html`).
- Public assets under `assets/`.
- The public catalog at `data/products.json`.
- Search and discovery files such as `robots.txt`, `sitemap.xml`, `llms.txt`,
  and `site.webmanifest`.

`data/products.json` is intentionally public. The homepage directory and
product structured data include only records whose `visibility` is `listed`;
the dedicated Open Data explorer can visualize both `listed` and public-safe
`unlisted` records with explicit labels. The JSON must never contain internal
review notes, personal contact details, or unpublished research. An unlisted
record is not an active directory listing and does not communicate a rejection,
availability conclusion, or endorsement.

Country pages are generated only for explicitly mapped primary countries with
at least one listed record. Cloudflare Pages redirects an HTML filename to its
extensionless counterpart, so committed `bahamas.html` is linked and indexed
canonically as `https://caribbeansaas.com/bahamas`.

## Guarded weekly data publication

The machine-local weekly review may publish newly reviewed public-safe records
to the raw catalog as `visibility: unlisted`. This path is fail-closed:

- The run must start on a clean, aligned `main` checkout and pass every worker,
  evidence, deduplication, schema, and ledger gate.
- The publication plan must prove the catalog is the run-start snapshot plus
  only that run's sanitized unlisted additions. Existing records cannot change
  or move.
- The coordinator stages and commits only `data/products.json`, pushes without
  force to `origin/main`, and lets the GitHub-connected Pages project deploy.
- The live JSON and listed-only homepage boundary must be verified and recorded
  in the ignored private publication receipt.

A dirty, diverged, partial, or failed run remains private. No automated run may
set `visibility: listed`, edit an existing public record, resolve a Git
conflict, force-push, or use a separate direct-upload deployment.

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
https://caribbeansaas.com/bahamas
https://caribbeansaas.com/curation.html
https://caribbeansaas.com/open-data.html
https://caribbeansaas.com/privacy.html
https://caribbeansaas.com/terms.html
https://caribbeansaas.com/data/products.json
```

Source files and local records, such as `scripts/`, `tests/`, `docs/`, and
`PROJECT_BRAIN.md`, should return `404` from the public site.
