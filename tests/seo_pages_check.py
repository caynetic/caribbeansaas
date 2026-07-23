from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SITE_URL = "https://caribbeansaas.com"
PRODUCTS_JSON = ROOT / "data" / "products.json"
SITEMAP = ROOT / "sitemap.xml"
INDEX = ROOT / "index.html"
GENERATOR = ROOT / "scripts" / "generate_seo_pages.py"
GENERATED_ROUTE_DIRS = ("category", "products", "software")
PUBLIC_SITEMAP_URLS = [
    f"{SITE_URL}/",
    f"{SITE_URL}/privacy.html",
    f"{SITE_URL}/terms.html",
]


def main() -> None:
    data = json.loads(PRODUCTS_JSON.read_text())
    products = [
        product
        for product in data.get("products", [])
        if isinstance(product, dict)
    ]
    published_products = [
        product
        for product in products
        if product.get("status") == "published"
    ]
    if not published_products:
        raise AssertionError("Published products are required for the root directory page")

    index_html = INDEX.read_text()
    sitemap_xml = SITEMAP.read_text()
    generator_source = GENERATOR.read_text()

    stale_pages = []
    for route_dir in GENERATED_ROUTE_DIRS:
        stale_pages.extend(sorted((ROOT / route_dir).glob("**/index.html")))
    if stale_pages:
        formatted = ", ".join(str(path.relative_to(ROOT)) for path in stale_pages)
        raise AssertionError(f"Generated landing pages should not exist on a root-only site: {formatted}")

    for route_prefix in ["/category/", "/products/", "/software/"]:
        if f'href="{route_prefix}' in index_html:
            raise AssertionError(f"Homepage should not link generated route prefix: {route_prefix}")
        if f"<loc>{SITE_URL}{route_prefix}" in sitemap_xml:
            raise AssertionError(f"Sitemap should not expose generated route prefix: {route_prefix}")
        if route_prefix in generator_source:
            raise AssertionError(f"Generator should not retain stale route template: {route_prefix}")

    for legacy_marker in [
        "SEO_BROWSE_LINKS_START",
        "SEO_BROWSE_LINKS_END",
        "CATEGORY_LINKS_START",
        "CATEGORY_LINKS_END",
        "Browse CaribbeanSaaS landing pages",
        'id="categoryLinks"',
        'class="category-directory-link',
    ]:
        if legacy_marker in index_html:
            raise AssertionError(f"Homepage should not expose generated-route discovery UI: {legacy_marker}")

    sitemap_urls = re.findall(r"<loc>([^<]+)</loc>", sitemap_xml)
    if sitemap_urls != PUBLIC_SITEMAP_URLS:
        raise AssertionError(f"Sitemap should contain the homepage and legal support pages: {sitemap_urls!r}")

    for sitemap_marker in [
        f"<loc>{SITE_URL}/</loc>",
        f"<lastmod>{date.today().isoformat()}</lastmod>",
        "<changefreq>weekly</changefreq>",
        "<priority>1.0</priority>",
        f"<loc>{SITE_URL}/privacy.html</loc>",
        f"<loc>{SITE_URL}/terms.html</loc>",
    ]:
        if sitemap_marker not in sitemap_xml:
            raise AssertionError(f"Missing root sitemap marker: {sitemap_marker}")


if __name__ == "__main__":
    main()
