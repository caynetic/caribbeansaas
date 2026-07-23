from __future__ import annotations

import json
import re
import sys
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from site_config import COUNTRY_ROUTE_SLUGS, country_route_slug


SITE_URL = "https://caribbeansaas.com"
PRODUCTS_JSON = ROOT / "data" / "products.json"
SITEMAP = ROOT / "sitemap.xml"
INDEX = ROOT / "index.html"
GENERATOR = ROOT / "scripts" / "generate_seo_pages.py"
GENERATED_ROUTE_DIRS = ("category", "products", "software")
PUBLIC_SUPPORT_URLS = [
    f"{SITE_URL}/curation.html",
    f"{SITE_URL}/open-data.html",
    f"{SITE_URL}/privacy.html",
    f"{SITE_URL}/terms.html",
]


def main() -> None:
    country_slugs = list(COUNTRY_ROUTE_SLUGS.values())
    if len(country_slugs) != len(set(country_slugs)):
        raise AssertionError("Explicit country route slugs should be unique")
    if any(not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", slug) for slug in country_slugs):
        raise AssertionError("Country route slugs should be stable lowercase URL segments")

    data = json.loads(PRODUCTS_JSON.read_text())
    products = [
        product
        for product in data.get("products", [])
        if isinstance(product, dict)
    ]
    listed_products = [
        product
        for product in products
        if product.get("visibility") == "listed"
    ]
    if not listed_products:
        raise AssertionError("Listed products are required for the root directory page")

    listed_by_country: dict[str, list[dict]] = {}
    for product in listed_products:
        listed_by_country.setdefault(product["country"], []).append(product)
    expected_country_slugs = {
        country_route_slug(country)
        for country in listed_by_country
    }
    expected_country_files = {
        f"{slug}.html"
        for slug in expected_country_slugs
    }
    expected_country_urls = [
        f"{SITE_URL}/{country_route_slug(country)}"
        for country in sorted(listed_by_country, key=country_route_slug)
    ]

    index_html = INDEX.read_text()
    sitemap_xml = SITEMAP.read_text()
    generator_source = GENERATOR.read_text()
    render_marker = "country_pages, country_urls = render_country_pages"
    write_marker = "write_text_atomic(INDEX, index_html)"
    if render_marker not in generator_source or write_marker not in generator_source:
        raise AssertionError("Country generator should keep explicit render and atomic-write phases")
    if generator_source.index(render_marker) > generator_source.index(write_marker):
        raise AssertionError(
            "Country templates should validate fully before generated source files are replaced"
        )

    stale_pages = []
    for route_dir in GENERATED_ROUTE_DIRS:
        stale_pages.extend(sorted((ROOT / route_dir).glob("**/index.html")))
    if stale_pages:
        formatted = ", ".join(str(path.relative_to(ROOT)) for path in stale_pages)
        raise AssertionError(f"Legacy nested landing pages should not exist: {formatted}")

    actual_country_files = {
        path.name
        for slug in COUNTRY_ROUTE_SLUGS.values()
        if (path := ROOT / f"{slug}.html").is_file()
    }
    if actual_country_files != expected_country_files:
        raise AssertionError(
            f"Generated country pages should match listed primary countries: {actual_country_files!r}"
        )

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

    for country, country_products in listed_by_country.items():
        slug = country_route_slug(country)
        country_page = ROOT / f"{slug}.html"
        country_html = country_page.read_text()
        expected_ids = [product["id"] for product in country_products]
        actual_ids = re.findall(
            r'<article class="product-card\b[^>]*data-product-id="([^"]+)"',
            country_html,
        )
        if actual_ids != expected_ids:
            raise AssertionError(
                f"{country_page.name} should contain only matching listed cards: {actual_ids!r}"
            )

        structured_match = re.search(
            r'<script id="structured-data" type="application/ld\+json">\s*(.*?)\s*</script>',
            country_html,
            re.DOTALL,
        )
        if structured_match is None:
            raise AssertionError(f"{country_page.name} should include route structured data")
        structured_data = json.loads(structured_match.group(1))
        route_item_lists = [
            node
            for node in structured_data.get("@graph", [])
            if node.get("@id") == f"{SITE_URL}/{slug}#listed-digital-products"
        ]
        if len(route_item_lists) != 1:
            raise AssertionError(f"{country_page.name} should expose one listed-product ItemList")
        structured_ids = [
            entry.get("item", {}).get("@id", "").rsplit("#", 1)[-1]
            for entry in route_item_lists[0].get("itemListElement", [])
        ]
        if structured_ids != expected_ids:
            raise AssertionError(
                f"{country_page.name} structured data should contain only matching listed ids: "
                f"{structured_ids!r}"
            )

        for marker in [
            f'<link rel="canonical" href="{SITE_URL}/{slug}"/>',
            f'<meta property="og:url" content="{SITE_URL}/{slug}"/>',
            f'data-route-region="{country}"',
            f'data-route-slug="{slug}"',
            f'aria-label="Region fixed to {country}" aria-disabled="true"',
            f'"@id": "{SITE_URL}/{slug}#directory"',
            f'"@id": "{SITE_URL}/{slug}#listed-digital-products"',
            f'"numberOfItems": {len(expected_ids)}',
            'href="/#directory">All listings</a>',
            "const PAGE_SIZE = 6;",
            'aria-label="Directory pagination"',
        ]:
            if marker not in country_html:
                raise AssertionError(f"{country_page.name} is missing route marker: {marker}")

        other_country_cards = [
            card_country
            for card_country in re.findall(r'data-country="([^"]+)"', country_html)
            if card_country != country
        ]
        if other_country_cards:
            raise AssertionError(
                f"{country_page.name} should not include other-country cards: {other_country_cards!r}"
            )

    sitemap_urls = re.findall(r"<loc>([^<]+)</loc>", sitemap_xml)
    public_sitemap_urls = [
        f"{SITE_URL}/",
        *expected_country_urls,
        *PUBLIC_SUPPORT_URLS,
    ]
    if sitemap_urls != public_sitemap_urls:
        raise AssertionError(
            f"Sitemap should contain the homepage, country pages, and public support pages: {sitemap_urls!r}"
        )

    for sitemap_marker in [
        f"<loc>{SITE_URL}/</loc>",
        f"<lastmod>{date.today().isoformat()}</lastmod>",
        "<changefreq>weekly</changefreq>",
        "<priority>1.0</priority>",
        *[f"<loc>{url}</loc>" for url in expected_country_urls],
        f"<loc>{SITE_URL}/curation.html</loc>",
        f"<loc>{SITE_URL}/open-data.html</loc>",
        f"<loc>{SITE_URL}/privacy.html</loc>",
        f"<loc>{SITE_URL}/terms.html</loc>",
    ]:
        if sitemap_marker not in sitemap_xml:
            raise AssertionError(f"Missing root sitemap marker: {sitemap_marker}")


if __name__ == "__main__":
    main()
