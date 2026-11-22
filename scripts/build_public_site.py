from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from generate_seo_pages import catalog_products, main as generate_public_pages
from directory_catalog import listing_regions
from site_config import country_route_slug


ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
PUBLIC_ROOT_FILES = (
    "index.html",
    "404.html",
    "curation.html",
    "open-data.html",
    "privacy.html",
    "terms.html",
    "robots.txt",
    "sitemap.xml",
    "site.webmanifest",
    "llms.txt",
)
PUBLIC_DIRECTORIES = ("assets", "data")
EXCLUDED_ASSET_FILENAMES = (
    "caribbean-map.png",
    "caribbeansaas-icon-source.png",
)


def generated_country_files() -> tuple[str, ...]:
    public_countries = {region for product in catalog_products() for region in listing_regions(product)}
    if not public_countries:
        raise RuntimeError("At least one browse region is required")
    return tuple(
        f"{country_route_slug(country)}.html"
        for country in sorted(public_countries, key=country_route_slug)
    )


def require_file(relative_path: str) -> Path:
    path = ROOT / relative_path
    if not path.is_file():
        raise FileNotFoundError(f"Missing required public file: {relative_path}")
    return path


def require_directory(relative_path: str) -> Path:
    path = ROOT / relative_path
    if not path.is_dir():
        raise FileNotFoundError(f"Missing required public directory: {relative_path}")
    return path


def main() -> None:
    generate_public_pages()
    subprocess.run(["npm", "run", "build:css"], cwd=ROOT, check=True)

    if DIST.exists():
        shutil.rmtree(DIST)
    DIST.mkdir()

    for relative_path in (*PUBLIC_ROOT_FILES, *generated_country_files()):
        shutil.copy2(require_file(relative_path), DIST / relative_path)

    for relative_path in PUBLIC_DIRECTORIES:
        shutil.copytree(
            require_directory(relative_path),
            DIST / relative_path,
            ignore=shutil.ignore_patterns(".DS_Store", *EXCLUDED_ASSET_FILENAMES),
        )


if __name__ == "__main__":
    main()
