from __future__ import annotations

import json
import re
import shutil
from datetime import date
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
SITE_URL = "https://caribbeansaas.com"
PRODUCTS_JSON = ROOT / "data" / "products.json"
INDEX = ROOT / "index.html"
SITEMAP = ROOT / "sitemap.xml"
LASTMOD = date.today().isoformat()
GENERATED_ROUTE_DIRS = ("category", "products", "software")
PUBLIC_SUPPORT_PAGES = (("privacy.html", "0.3"), ("terms.html", "0.3"))
LEGACY_BLOCKS = (
    ("        <!-- SEO_BROWSE_LINKS_START -->", "        <!-- SEO_BROWSE_LINKS_END -->"),
    ("            <!-- CATEGORY_LINKS_START -->", "            <!-- CATEGORY_LINKS_END -->"),
)


def catalog_products() -> list[dict]:
    data = json.loads(PRODUCTS_JSON.read_text())
    return [
        product
        for product in data.get("products", [])
        if isinstance(product, dict)
    ]


def listed_products(products: list[dict]) -> list[dict]:
    return [product for product in products if product.get("visibility") == "listed"]


def remove_generated_route_pages() -> None:
    for route_dir in GENERATED_ROUTE_DIRS:
        route_path = ROOT / route_dir
        if route_path.exists():
            shutil.rmtree(route_path)


def remove_legacy_index_blocks() -> None:
    index_html = INDEX.read_text()

    for start_marker, end_marker in LEGACY_BLOCKS:
        if start_marker not in index_html or end_marker not in index_html:
            continue

        pattern = re.compile(re.escape(start_marker) + r".*?" + re.escape(end_marker), re.DOTALL)
        index_html = pattern.sub("", index_html)

    index_html = re.sub(r"\n{3,}", "\n\n", index_html)
    INDEX.write_text(index_html)


def sitemap_entry(url: str, priority: str) -> str:
    return f"""  <url>
    <loc>{url}</loc>
    <lastmod>{LASTMOD}</lastmod>
    <changefreq>weekly</changefreq>
    <priority>{priority}</priority>
  </url>"""


def write_sitemap(urls: Iterable[tuple[str, str]]) -> None:
    entries = "\n".join(sitemap_entry(url, priority) for url, priority in urls)
    SITEMAP.write_text(f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
{entries}
</urlset>
""")


def main() -> None:
    products = listed_products(catalog_products())
    if not products:
        raise RuntimeError("Listed products are required for the root directory page")

    remove_generated_route_pages()
    remove_legacy_index_blocks()
    support_urls = [
        (f"{SITE_URL}/{path}", priority)
        for path, priority in PUBLIC_SUPPORT_PAGES
    ]
    write_sitemap([(f"{SITE_URL}/", "1.0"), *support_urls])


if __name__ == "__main__":
    main()
