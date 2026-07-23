from __future__ import annotations

import json
import shutil
from pathlib import Path

from generate_seo_pages import main as generate_public_pages
from site_config import country_route_slug


ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
PRODUCTS_JSON = ROOT / "data" / "products.json"
PUBLIC_ROOT_FILES = (
    "index.html",
    "404.html",
    "curation.html",
    "open-data.html",
    "privacy.html",
    "terms.html",
    "robots.txt",
    "sitemap.xml",
    "llms.txt",
    "site.webmanifest",
)
PUBLIC_DIRECTORIES = ("assets", "data")


def generated_country_files() -> tuple[str, ...]:
    catalog = json.loads(PRODUCTS_JSON.read_text())
    listed_countries = {
        product.get("country")
        for product in catalog.get("products", [])
        if isinstance(product, dict) and product.get("visibility") == "listed"
    }
    if not listed_countries or None in listed_countries or "" in listed_countries:
        raise RuntimeError("Every listed product needs a primary country")
    return tuple(
        f"{country_route_slug(country)}.html"
        for country in sorted(listed_countries, key=country_route_slug)
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

    if DIST.exists():
        shutil.rmtree(DIST)
    DIST.mkdir()

    for relative_path in (*PUBLIC_ROOT_FILES, *generated_country_files()):
        shutil.copy2(require_file(relative_path), DIST / relative_path)

    for relative_path in PUBLIC_DIRECTORIES:
        shutil.copytree(
            require_directory(relative_path),
            DIST / relative_path,
            ignore=shutil.ignore_patterns(".DS_Store"),
        )


if __name__ == "__main__":
    main()
