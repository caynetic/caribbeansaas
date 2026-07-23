from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from site_config import country_route_slug


BUILD_SCRIPT = ROOT / "scripts" / "build_public_site.py"
BUILD_SOURCE = BUILD_SCRIPT.read_text()
PRODUCTS_JSON = ROOT / "data" / "products.json"
DIST = ROOT / "dist"
PUBLIC_ROOT_FILES = {
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
}
PUBLIC_DIRECTORIES = {"assets", "data"}
INTERNAL_PATHS = {
    "PROJECT_BRAIN.md",
    "DESIGN.md",
    "design-qa.md",
    "screen.png",
    "docs",
    "audits",
    "private",
    ".codex",
    ".agents",
    "skills",
    "tmp",
    "scripts",
    "tests",
    ".env.outreach.example",
    ".env.spaces.example",
}


def expected_country_files() -> set[str]:
    catalog = json.loads(PRODUCTS_JSON.read_text())
    countries = {
        product["country"]
        for product in catalog.get("products", [])
        if isinstance(product, dict) and product.get("visibility") == "listed"
    }
    return {f"{country_route_slug(country)}.html" for country in countries}


def main() -> None:
    if "generate_public_pages()" not in BUILD_SOURCE:
        raise AssertionError(
            "Public build should regenerate and validate country pages before copying dist/"
        )
    if BUILD_SOURCE.index("generate_public_pages()") > BUILD_SOURCE.index("if DIST.exists()"):
        raise AssertionError(
            "Public generation should succeed before the prior dist/ directory is removed"
        )

    subprocess.run([sys.executable, str(BUILD_SCRIPT)], check=True)

    if not DIST.is_dir():
        raise AssertionError("Public build should create dist/")

    actual_root_paths = {path.name for path in DIST.iterdir()}
    generated_country_files = expected_country_files()
    expected_root_paths = PUBLIC_ROOT_FILES | PUBLIC_DIRECTORIES | generated_country_files
    if actual_root_paths != expected_root_paths:
        raise AssertionError(
            f"Public bundle should be an explicit allowlist: {actual_root_paths!r}"
        )

    for relative_path in PUBLIC_ROOT_FILES:
        if not (DIST / relative_path).is_file():
            raise AssertionError(f"Missing public bundle file: {relative_path}")

    for relative_path in generated_country_files:
        if not (DIST / relative_path).is_file():
            raise AssertionError(f"Missing generated country page: {relative_path}")
        if (DIST / relative_path).read_bytes() != (ROOT / relative_path).read_bytes():
            raise AssertionError(
                f"Public bundle country page should match the freshly generated source: {relative_path}"
            )

    if (DIST / "sitemap.xml").read_bytes() != (ROOT / "sitemap.xml").read_bytes():
        raise AssertionError("Public bundle sitemap should match the freshly generated source")

    for relative_path in PUBLIC_DIRECTORIES:
        if not (DIST / relative_path).is_dir():
            raise AssertionError(f"Missing public bundle directory: {relative_path}")

    for relative_path in INTERNAL_PATHS:
        if (DIST / relative_path).exists():
            raise AssertionError(f"Internal path leaked into public bundle: {relative_path}")


if __name__ == "__main__":
    main()
