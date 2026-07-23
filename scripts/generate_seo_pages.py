from __future__ import annotations

import json
import re
import shutil
from copy import deepcopy
from datetime import date
from pathlib import Path
from typing import Iterable

from site_config import (
    COUNTRY_ROUTE_SLUGS,
    country_route_display_name,
    country_route_slug,
)


ROOT = Path(__file__).resolve().parents[1]
SITE_URL = "https://caribbeansaas.com"
PRODUCTS_JSON = ROOT / "data" / "products.json"
INDEX = ROOT / "index.html"
SITEMAP = ROOT / "sitemap.xml"
LASTMOD = date.today().isoformat()
GENERATED_ROUTE_DIRS = ("category", "products", "software")
PUBLIC_SUPPORT_PAGES = (
    ("curation.html", "0.6"),
    ("open-data.html", "0.5"),
    ("privacy.html", "0.3"),
    ("terms.html", "0.3"),
)
LEGACY_BLOCKS = (
    ("        <!-- SEO_BROWSE_LINKS_START -->", "        <!-- SEO_BROWSE_LINKS_END -->"),
    ("            <!-- CATEGORY_LINKS_START -->", "            <!-- CATEGORY_LINKS_END -->"),
)
PRODUCT_CARDS_START = "<!-- PRODUCT_CARDS_START -->"
PRODUCT_CARDS_END = "<!-- PRODUCT_CARDS_END -->"
PRODUCT_CARD_PATTERN = re.compile(
    r'<article class="product-card\b.*?</article>',
    re.DOTALL,
)
PRODUCT_ID_PATTERN = re.compile(r'data-product-id="([^"]+)"')
STRUCTURED_DATA_PATTERN = re.compile(
    r'(<script id="structured-data" type="application/ld\+json">)\s*(.*?)\s*(</script>)',
    re.DOTALL,
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


def listed_products_by_country(products: list[dict]) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for product in products:
        country = product.get("country")
        if not isinstance(country, str) or not country.strip():
            raise RuntimeError(f"Listed product is missing its primary country: {product.get('id')!r}")
        country_route_slug(country)
        grouped.setdefault(country, []).append(product)
    return grouped


def remove_legacy_route_directories() -> None:
    for route_dir in GENERATED_ROUTE_DIRS:
        route_path = ROOT / route_dir
        if route_path.exists():
            shutil.rmtree(route_path)


def remove_stale_country_pages(active_slugs: set[str]) -> None:
    for slug in COUNTRY_ROUTE_SLUGS.values():
        if slug in active_slugs:
            continue
        country_page = ROOT / f"{slug}.html"
        if country_page.exists():
            country_page.unlink()


def without_legacy_index_blocks(index_html: str) -> str:
    for start_marker, end_marker in LEGACY_BLOCKS:
        if start_marker not in index_html or end_marker not in index_html:
            continue

        pattern = re.compile(re.escape(start_marker) + r".*?" + re.escape(end_marker), re.DOTALL)
        index_html = pattern.sub("", index_html)

    return re.sub(r"\n{3,}", "\n\n", index_html)


def sitemap_entry(url: str, priority: str) -> str:
    return f"""  <url>
    <loc>{url}</loc>
    <lastmod>{LASTMOD}</lastmod>
    <changefreq>weekly</changefreq>
    <priority>{priority}</priority>
  </url>"""


def sitemap_xml(urls: Iterable[tuple[str, str]]) -> str:
    entries = "\n".join(sitemap_entry(url, priority) for url, priority in urls)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
{entries}
</urlset>
"""


def write_text_atomic(path: Path, contents: str) -> None:
    temporary_path = path.with_name(f".{path.name}.tmp")
    try:
        temporary_path.write_text(contents)
        temporary_path.replace(path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def replace_once(page: str, old: str, new: str, description: str) -> str:
    if page.count(old) != 1:
        raise RuntimeError(f"Expected one {description}, found {page.count(old)}")
    return page.replace(old, new, 1)


def filtered_product_cards(index_html: str, product_ids: list[str]) -> str:
    if PRODUCT_CARDS_START not in index_html or PRODUCT_CARDS_END not in index_html:
        raise RuntimeError("Homepage product-card generation markers are missing")

    before_cards, remainder = index_html.split(PRODUCT_CARDS_START, 1)
    card_source, after_cards = remainder.split(PRODUCT_CARDS_END, 1)
    card_by_id: dict[str, str] = {}

    for match in PRODUCT_CARD_PATTERN.finditer(card_source):
        card = match.group(0)
        product_id_match = PRODUCT_ID_PATTERN.search(card)
        if product_id_match is None:
            raise RuntimeError("Homepage product card is missing data-product-id")
        card_by_id[product_id_match.group(1)] = card

    missing_ids = sorted(set(product_ids) - set(card_by_id))
    if missing_ids:
        raise RuntimeError(f"Country route cannot find homepage cards: {missing_ids!r}")

    selected_cards = [card_by_id[product_id] for product_id in product_ids]
    card_block = "\n            ".join(selected_cards)
    return (
        f"{before_cards}{PRODUCT_CARDS_START}\n"
        f"            {card_block}\n"
        f"            {PRODUCT_CARDS_END}{after_cards}"
    )


def product_id_from_structured_item(item: dict) -> str | None:
    item_url = item.get("item", {}).get("@id")
    if not isinstance(item_url, str) or "#" not in item_url:
        return None
    return item_url.rsplit("#", 1)[1]


def ordered_item_list_entries(
    node: dict,
    product_ids: list[str],
    *,
    context: str,
) -> list[dict]:
    entry_by_id = {
        product_id: entry
        for entry in node.get("itemListElement", [])
        if (product_id := product_id_from_structured_item(entry))
    }
    missing_ids = sorted(set(product_ids) - set(entry_by_id))
    if missing_ids:
        raise RuntimeError(f"{context} cannot find structured-data entries: {missing_ids!r}")

    entries = [entry_by_id[product_id] for product_id in product_ids]
    for position, entry in enumerate(entries, start=1):
        entry["position"] = position
    return entries


def replace_structured_data(
    index_html: str,
    match: re.Match[str],
    structured_data: dict,
) -> str:
    replacement = (
        f'{match.group(1)}\n'
        f'{json.dumps(structured_data, indent=2, ensure_ascii=False)}\n'
        f'{match.group(3)}'
    )
    return index_html[: match.start()] + replacement + index_html[match.end() :]


def ordered_homepage_structured_data(index_html: str, product_ids: list[str]) -> str:
    match = STRUCTURED_DATA_PATTERN.search(index_html)
    if match is None:
        raise RuntimeError("Homepage structured data block is missing")

    structured_data = json.loads(match.group(2))
    graph = structured_data.get("@graph")
    if not isinstance(graph, list):
        raise RuntimeError("Homepage structured data graph is unavailable")

    for node in graph:
        node_id = node.get("@id")
        if isinstance(node_id, str) and node_id.endswith("#listed-digital-products"):
            entries = ordered_item_list_entries(
                node,
                product_ids,
                context="Homepage",
            )
            node["numberOfItems"] = len(entries)
            node["itemListElement"] = entries
            break
    else:
        raise RuntimeError("Homepage listed-product ItemList is missing")

    return replace_structured_data(index_html, match, structured_data)


def country_structured_data(
    index_html: str,
    *,
    country: str,
    route_url: str,
    description: str,
    product_ids: list[str],
) -> str:
    match = STRUCTURED_DATA_PATTERN.search(index_html)
    if match is None:
        raise RuntimeError("Homepage structured data block is missing")

    structured_data = json.loads(match.group(2))
    graph = structured_data.get("@graph")
    if not isinstance(graph, list):
        raise RuntimeError("Homepage structured data graph is unavailable")

    graph = deepcopy(graph)
    for node in graph:
        node_id = node.get("@id")
        if node.get("@type") == "CollectionPage":
            node["@id"] = f"{route_url}#directory"
            node["url"] = route_url
            node["name"] = f"{country} Software Directory"
            node["description"] = description
            node["mainEntity"] = {"@id": f"{route_url}#listed-digital-products"}
        elif isinstance(node_id, str) and node_id.endswith("#listed-digital-products"):
            entries = ordered_item_list_entries(
                node,
                product_ids,
                context="Country route",
            )
            for entry in entries:
                item = entry.get("item")
                if isinstance(item, dict):
                    product_id = product_id_from_structured_item(entry)
                    item["@id"] = f"{route_url}#{product_id}"

            node["@id"] = f"{route_url}#listed-digital-products"
            node["name"] = f"Listed software from {country_route_display_name(country)}"
            node["description"] = description
            node["numberOfItems"] = len(entries)
            node["itemListElement"] = entries

    return replace_structured_data(
        index_html,
        match,
        {"@context": structured_data.get("@context"), "@graph": graph},
    )


def country_page_html(country: str, products: list[dict], index_html: str) -> str:
    slug = country_route_slug(country)
    route_url = f"{SITE_URL}/{slug}"
    display_name = country_route_display_name(country)
    title = f"{country} Software Directory | CaribbeanSaaS"
    description = (
        f"Discover reviewed software and digital products built by founders "
        f"and teams connected to {display_name}."
    )
    product_id_order = [product["id"] for product in products]

    page = filtered_product_cards(index_html, product_id_order)
    page = replace_once(
        page,
        "<title>CaribbeanSaaS | Caribbean SaaS &amp; Software Directory</title>",
        f"<title>{title}</title>",
        "homepage title",
    )
    page = replace_once(
        page,
        '<meta name="description" content="Discover reviewed Caribbean-built SaaS products, AI tools, fintech platforms, cybersecurity products, healthcare apps, tourism software, and developer tools."/>',
        f'<meta name="description" content="{description}"/>',
        "meta description",
    )
    page = replace_once(
        page,
        '<link rel="canonical" href="https://caribbeansaas.com/"/>',
        f'<link rel="canonical" href="{route_url}"/>',
        "canonical URL",
    )
    page = replace_once(
        page,
        '<meta property="og:title" content="CaribbeanSaaS | Caribbean SaaS &amp; Software Directory"/>',
        f'<meta property="og:title" content="{title}"/>',
        "Open Graph title",
    )
    page = replace_once(
        page,
        '<meta property="og:description" content="A curated directory for reviewed Caribbean-built SaaS products, AI tools, fintech platforms, cybersecurity products, healthcare apps, tourism software, and developer tools."/>',
        f'<meta property="og:description" content="{description}"/>',
        "Open Graph description",
    )
    page = replace_once(
        page,
        '<meta property="og:url" content="https://caribbeansaas.com/"/>',
        f'<meta property="og:url" content="{route_url}"/>',
        "Open Graph URL",
    )
    page = replace_once(
        page,
        '<meta name="twitter:title" content="CaribbeanSaaS | Caribbean SaaS &amp; Software Directory"/>',
        f'<meta name="twitter:title" content="{title}"/>',
        "Twitter title",
    )
    page = replace_once(
        page,
        '<meta name="twitter:description" content="Discover reviewed Caribbean-built SaaS products, AI tools, fintech platforms, cybersecurity products, healthcare apps, tourism software, and developer tools."/>',
        f'<meta name="twitter:description" content="{description}"/>',
        "Twitter description",
    )
    page = replace_once(
        page,
        '<body class="bg-background text-primary antialiased">',
        f'<body class="bg-background text-primary antialiased" data-route-region="{country}" data-route-slug="{slug}">',
        "body route metadata",
    )
    page = replace_once(
        page,
        '<a class="header-brand focus-ring rounded-md text-white/70 hover:text-white" href="#" aria-label="CaribbeanSaaS home">',
        '<a class="header-brand focus-ring rounded-md text-white/70 hover:text-white" href="/" aria-label="CaribbeanSaaS home">',
        "header home link",
    )
    page = replace_once(
        page,
        '<a class="focus-ring rounded-sm hover:text-white" href="#directory">All listings</a>',
        '<a class="focus-ring rounded-sm hover:text-white" href="/#directory">All listings</a>',
        "footer all-listings link",
    )
    page = replace_once(
        page,
        '<summary class="region-summary focus-ring" aria-label="Filter by one or more regions">',
        f'<summary class="region-summary focus-ring" aria-label="Region fixed to {country}" aria-disabled="true">',
        "fixed route-region label",
    )

    heading_pattern = re.compile(
        r'<h1 class="max-w-3xl[^>]+aria-label="Discover Caribbean-Built Software">.*?</h1>',
        re.DOTALL,
    )
    heading = f'''<h1 class="max-w-3xl text-[2.75rem] font-semibold uppercase leading-[0.95] tracking-normal text-white sm:text-6xl md:text-7xl" aria-label="Discover software from {display_name}">
            <span class="hero-title-line">Discover</span>
            <span class="hero-title-line">Software From</span>
            <span class="hero-title-line">{display_name.title()}</span>
        </h1>'''
    page, heading_count = heading_pattern.subn(heading, page, count=1)
    if heading_count != 1:
        raise RuntimeError("Expected one homepage hero heading")

    page = replace_once(
        page,
        "CaribbeanSaaS showcases reviewed SaaS products, AI tools, fintech platforms, cybersecurity products, healthcare apps, developer tools, tourism software, and more from founders and teams across the region.",
        f"Browse reviewed software and digital products from founders and teams connected to {display_name}.",
        "hero supporting copy",
    )
    page = country_structured_data(
        page,
        country=country,
        route_url=route_url,
        description=description,
        product_ids=product_id_order,
    )
    return page


def render_country_pages(
    grouped_products: dict[str, list[dict]],
    index_html: str,
) -> tuple[dict[str, str], list[tuple[str, str]]]:
    pages: dict[str, str] = {}
    sitemap_urls: list[tuple[str, str]] = []
    for country in sorted(grouped_products, key=lambda value: country_route_slug(value)):
        slug = country_route_slug(country)
        pages[slug] = country_page_html(country, grouped_products[country], index_html)
        sitemap_urls.append((f"{SITE_URL}/{slug}", "0.8"))
    return pages, sitemap_urls


def main() -> None:
    products = listed_products(catalog_products())
    if not products:
        raise RuntimeError("Listed products are required for the root directory page")

    grouped_products = listed_products_by_country(products)
    index_html = without_legacy_index_blocks(INDEX.read_text())
    product_id_order = [product["id"] for product in products]
    index_html = filtered_product_cards(index_html, product_id_order)
    index_html = ordered_homepage_structured_data(index_html, product_id_order)
    country_pages, country_urls = render_country_pages(grouped_products, index_html)
    support_urls = [
        (f"{SITE_URL}/{path}", priority)
        for path, priority in PUBLIC_SUPPORT_PAGES
    ]
    rendered_sitemap = sitemap_xml(
        [(f"{SITE_URL}/", "1.0"), *country_urls, *support_urls]
    )

    # All catalog, template, route, and structured-data validation above must
    # succeed before the last known-good generated surface is replaced.
    write_text_atomic(INDEX, index_html)
    for slug, page in country_pages.items():
        write_text_atomic(ROOT / f"{slug}.html", page)
    write_text_atomic(SITEMAP, rendered_sitemap)
    remove_stale_country_pages(set(country_pages))
    remove_legacy_route_directories()


if __name__ == "__main__":
    main()
