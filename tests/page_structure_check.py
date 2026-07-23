from __future__ import annotations

from html import unescape
import json
import re
import struct
import zlib
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ENTRYPOINT = ROOT / "index.html"
OLD_ENTRYPOINT = ROOT / "code.html"
MANIFEST = ROOT / "site.webmanifest"
ROBOTS = ROOT / "robots.txt"
SITEMAP = ROOT / "sitemap.xml"
LLMS = ROOT / "llms.txt"
NOT_FOUND = ROOT / "404.html"
CURATION = ROOT / "curation.html"
OPEN_DATA = ROOT / "open-data.html"
BAHAMAS = ROOT / "bahamas.html"
PRIVACY = ROOT / "privacy.html"
TERMS = ROOT / "terms.html"
PRODUCTS_JSON = ROOT / "data" / "products.json"

if not ENTRYPOINT.exists():
    raise AssertionError("Static entrypoint should be index.html")

if OLD_ENTRYPOINT.exists():
    raise AssertionError("Static entrypoint should not remain as code.html")

if not MANIFEST.exists():
    raise AssertionError("Web app manifest should exist")

for discovery_file in [ROBOTS, SITEMAP, LLMS, NOT_FOUND, CURATION, OPEN_DATA, BAHAMAS, PRIVACY, TERMS]:
    if not discovery_file.exists():
        raise AssertionError(f"Static discovery file should exist: {discovery_file.name}")

for generated_route_dir in ["category", "products", "software"]:
    stale_pages = sorted((ROOT / generated_route_dir).glob("**/index.html"))
    if stale_pages:
        formatted = ", ".join(str(path.relative_to(ROOT)) for path in stale_pages)
        raise AssertionError(f"Site should not keep legacy nested route pages: {formatted}")

HTML = ENTRYPOINT.read_text()
MANIFEST_TEXT = MANIFEST.read_text()
ROBOTS_TEXT = ROBOTS.read_text()
SITEMAP_TEXT = SITEMAP.read_text()
LLMS_TEXT = LLMS.read_text()
NOT_FOUND_TEXT = NOT_FOUND.read_text()
CURATION_TEXT = CURATION.read_text()
OPEN_DATA_TEXT = OPEN_DATA.read_text()
BAHAMAS_TEXT = BAHAMAS.read_text()
PRIVACY_TEXT = PRIVACY.read_text()
TERMS_TEXT = TERMS.read_text()
PRODUCT_LOGO_URL = "https://cdn.caynetic.app/caribbeansaas/products/logos/cayneticvpn-logo.png"
PRODUCT_LOGO_CDN_PREFIX = "https://cdn.caynetic.app/caribbeansaas/products/logos/"
PUBLIC_EMAIL = "hello@caribbeansaas.com"
OLD_PUBLIC_EMAIL = "submissions" + "@caribbeansaas.com"
CAYNETIC_URL = "https://caynetic.ltd"
GITHUB_URL = "https://github.com/caynetic/caribbeansaas"
CATALOG_SCHEMA_VERSION = 2
CATALOG_VISIBILITIES = {"listed", "unlisted"}
PRODUCT_KINDS = {
    "saas",
    "mobile_app",
    "digital_platform",
    "marketplace",
    "api_or_developer_tool",
    "web_tool",
    "software_enabled_service",
    "open_source_project",
}
PUBLIC_PRODUCT_FIELDS = {
    "id",
    "slug",
    "name",
    "tagline",
    "description",
    "productKind",
    "websiteUrl",
    "country",
    "countries",
    "category",
    "industry",
    "tags",
    "aliases",
    "officialAppStoreIds",
    "logoUrl",
    "logoAlt",
    "logoWidth",
    "logoHeight",
    "screenshotUrls",
    "companyName",
    "founderNames",
    "caribbeanConnection",
    "visibility",
    "publishedAt",
    "updatedAt",
}
LISTED_PRODUCT_IDS = [
    "caribtrends",
    "cay-declarations",
    "cayneticvpn",
    "clearfile",
    "dilly",
    "kemispay",
    "lawbey",
    "rezbs",
    "schoolmate-sis",
    "triblockhr",
]
CATEGORY_SLUG_OVERRIDES = {
    "Cybersecurity": "cybersec",
}
ADVERTISING_MARKERS = ("pagead2.googlesyndication.com", "adsbygoogle.js", "ca-pub-")


def read_png_rgba_rows(path: Path) -> tuple[int, int, list[list[int]]]:
    data = path.read_bytes()
    return decode_png_rgba_rows(data)


def decode_png_rgba_rows(data: bytes) -> tuple[int, int, list[list[int]]]:
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise AssertionError("Icon frame should be PNG encoded")

    position = 8
    width = 0
    height = 0
    bit_depth = 0
    color_type = 0
    interlace = 0
    idat_chunks: list[bytes] = []

    while position < len(data):
        chunk_length = struct.unpack(">I", data[position : position + 4])[0]
        chunk_type = data[position + 4 : position + 8]
        chunk_data = data[position + 8 : position + 8 + chunk_length]
        position += 12 + chunk_length

        if chunk_type == b"IHDR":
            (
                width,
                height,
                bit_depth,
                color_type,
                _compression,
                _filter_method,
                interlace,
            ) = struct.unpack(">IIBBBBB", chunk_data)
        elif chunk_type == b"IDAT":
            idat_chunks.append(chunk_data)
        elif chunk_type == b"IEND":
            break

    if bit_depth != 8 or color_type != 6 or interlace != 0:
        raise AssertionError(
            f"Icon PNG should be non-interlaced 8-bit RGBA, got bit_depth={bit_depth}, "
            f"color_type={color_type}, interlace={interlace}"
        )

    raw = zlib.decompress(b"".join(idat_chunks))
    bytes_per_pixel = 4
    stride = width * bytes_per_pixel
    rows: list[list[int]] = []
    previous_row = [0] * stride
    offset = 0

    for _row_index in range(height):
        filter_type = raw[offset]
        offset += 1
        scanline = list(raw[offset : offset + stride])
        offset += stride
        row = [0] * stride

        for index, value in enumerate(scanline):
            left = row[index - bytes_per_pixel] if index >= bytes_per_pixel else 0
            up = previous_row[index]
            upper_left = previous_row[index - bytes_per_pixel] if index >= bytes_per_pixel else 0

            if filter_type == 0:
                reconstructed = value
            elif filter_type == 1:
                reconstructed = value + left
            elif filter_type == 2:
                reconstructed = value + up
            elif filter_type == 3:
                reconstructed = value + ((left + up) // 2)
            elif filter_type == 4:
                predictor = left + up - upper_left
                left_distance = abs(predictor - left)
                up_distance = abs(predictor - up)
                upper_left_distance = abs(predictor - upper_left)
                if left_distance <= up_distance and left_distance <= upper_left_distance:
                    paeth = left
                elif up_distance <= upper_left_distance:
                    paeth = up
                else:
                    paeth = upper_left
                reconstructed = value + paeth
            else:
                raise AssertionError(f"Unsupported PNG filter type: {filter_type}")

            row[index] = reconstructed & 255

        rows.append(row)
        previous_row = row

    return width, height, rows


def alpha_margins(width: int, height: int, rows: list[list[int]], threshold: int = 8) -> tuple[int, int, int, int]:
    visible_pixels: list[tuple[int, int]] = []
    for y, row in enumerate(rows):
        for x in range(width):
            if row[(x * 4) + 3] >= threshold:
                visible_pixels.append((x, y))

    if not visible_pixels:
        raise AssertionError("Icon should contain visible pixels")

    min_x = min(x for x, _y in visible_pixels)
    max_x = max(x for x, _y in visible_pixels)
    min_y = min(y for _x, y in visible_pixels)
    max_y = max(y for _x, y in visible_pixels)
    return min_x, min_y, width - 1 - max_x, height - 1 - max_y


def assert_icon_visually_centered(path: Path) -> None:
    width, height, rows = read_png_rgba_rows(path)
    left, top, right, bottom = alpha_margins(width, height, rows)
    if abs(top - bottom) > 1:
        raise AssertionError(
            f"{path.relative_to(ROOT)} reads vertically off-center: top margin {top}px, "
            f"bottom margin {bottom}px"
        )
    if abs(left - right) > 1:
        raise AssertionError(
            f"{path.relative_to(ROOT)} reads horizontally off-center: left margin {left}px, "
            f"right margin {right}px"
        )


def assert_ico_frames_visually_centered(path: Path) -> None:
    data = path.read_bytes()
    if len(data) < 6:
        raise AssertionError("ICO file is too small")

    reserved, icon_type, icon_count = struct.unpack("<HHH", data[:6])
    if reserved != 0 or icon_type != 1 or icon_count == 0:
        raise AssertionError("ICO file should contain one or more icon frames")

    for frame_index in range(icon_count):
        offset = 6 + (frame_index * 16)
        width_byte, height_byte, _colors, _reserved, _planes, _bit_count, size, image_offset = struct.unpack(
            "<BBBBHHII", data[offset : offset + 16]
        )
        frame_width = 256 if width_byte == 0 else width_byte
        frame_height = 256 if height_byte == 0 else height_byte
        png_data = data[image_offset : image_offset + size]
        width, height, rows = decode_png_rgba_rows(png_data)
        if (width, height) != (frame_width, frame_height):
            raise AssertionError(f"ICO frame dimensions are inconsistent for frame {frame_index}")

        left, top, right, bottom = alpha_margins(width, height, rows)
        if abs(top - bottom) > 1:
            raise AssertionError(
                f"{path.relative_to(ROOT)} frame {frame_width}x{frame_height} reads vertically "
                f"off-center: top margin {top}px, bottom margin {bottom}px"
            )
        if abs(left - right) > 1:
            raise AssertionError(
                f"{path.relative_to(ROOT)} frame {frame_width}x{frame_height} reads horizontally "
                f"off-center: left margin {left}px, right margin {right}px"
            )


def marker_position(marker: str) -> int:
    position = HTML.find(marker)
    if position == -1:
        raise AssertionError(f"Missing page marker: {marker}")
    return position


def assert_before(left: str, right: str) -> None:
    left_position = marker_position(left)
    right_position = marker_position(right)
    if left_position >= right_position:
        raise AssertionError(f"Expected {left} to appear before {right}")


def slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def category_slug(category: str) -> str:
    return CATEGORY_SLUG_OVERRIDES.get(category, slugify(category))


def element_blocks(page_text: str, tag_name: str) -> list[str]:
    return re.findall(
        rf"<{tag_name}\b[^>]*>.*?</{tag_name}>",
        page_text,
        re.IGNORECASE | re.DOTALL,
    )


def opening_tags(page_text: str, tag_name: str) -> list[str]:
    return re.findall(rf"<{tag_name}\b[^>]*>", page_text, re.IGNORECASE)


def attribute_value(tag_text: str, attribute: str) -> str | None:
    match = re.search(
        rf"\b{re.escape(attribute)}\s*=\s*([\"'])(.*?)\1",
        tag_text,
        re.IGNORECASE | re.DOTALL,
    )
    return unescape(match.group(2)) if match else None


def visible_text(fragment: str) -> str:
    text = re.sub(r"<[^>]+>", " ", fragment)
    return " ".join(unescape(text).split())


def element_with_id(page_text: str, tag_name: str, element_id: str) -> str | None:
    for tag_text in opening_tags(page_text, tag_name):
        if attribute_value(tag_text, "id") == element_id:
            return tag_text
    return None


def block_with_id(page_text: str, tag_name: str, element_id: str) -> str | None:
    for block in element_blocks(page_text, tag_name):
        opening_tag = block[: block.find(">") + 1]
        if attribute_value(opening_tag, "id") == element_id:
            return block
    return None


def assert_labeled_control(page_text: str, tag_name: str, control_id: str) -> str:
    control = element_with_id(page_text, tag_name, control_id)
    if control is None:
        raise AssertionError(f"Open-data page is missing {tag_name}#{control_id}")

    label = None
    for block in element_blocks(page_text, "label"):
        opening_tag = block[: block.find(">") + 1]
        labels_by_id = attribute_value(opening_tag, "for") == control_id
        wraps_control = any(
            attribute_value(nested_control, "id") == control_id
            for nested_control in opening_tags(block, tag_name)
        )
        if labels_by_id or wraps_control:
            label = block
            break

    if label is None or not visible_text(label):
        raise AssertionError(f"Open-data control #{control_id} should have a visible associated label")

    return control


def assert_open_data_shell_links(page_name: str, page_text: str, required_regions: tuple[str, ...]) -> None:
    for region_name in required_regions:
        regions = element_blocks(page_text, region_name)
        if not regions:
            raise AssertionError(f"{page_name} is missing its {region_name}")

        open_data_hrefs = []
        for region in regions:
            for anchor in element_blocks(region, "a"):
                if visible_text(anchor).casefold() != "open data":
                    continue
                opening_tag = anchor[: anchor.find(">") + 1]
                open_data_hrefs.append(attribute_value(opening_tag, "href"))

        if not open_data_hrefs:
            raise AssertionError(f"{page_name} {region_name} should retain its Open data link")
        if any(href != "open-data.html" for href in open_data_hrefs):
            raise AssertionError(
                f"{page_name} {region_name} Open data links should target open-data.html: "
                f"{open_data_hrefs!r}"
            )


def assert_open_data_page(products: list[dict]) -> None:
    for marker in [
        "<title>",
        '<link rel="canonical" href="https://caribbeansaas.com/open-data.html"/>',
        "Open Data",
        "Listed",
        "Unlisted",
    ]:
        if marker not in OPEN_DATA_TEXT:
            raise AssertionError(f"Open-data page is missing required visible marker: {marker}")

    section = next(
        (
            tag_text
            for tag_text in opening_tags(OPEN_DATA_TEXT, "section")
            if attribute_value(tag_text, "aria-labelledby") == "openDataHeading"
        ),
        None,
    )
    if section is None:
        raise AssertionError("Open-data content should be a section labelled by openDataHeading")

    heading = element_with_id(OPEN_DATA_TEXT, "h1", "openDataHeading")
    if heading is None:
        raise AssertionError("Open-data page should expose h1#openDataHeading")

    raw_json_link = next(
        (
            block
            for block in element_blocks(OPEN_DATA_TEXT, "a")
            if attribute_value(block[: block.find(">") + 1], "id") == "rawJsonLink"
        ),
        None,
    )
    if raw_json_link is None:
        raise AssertionError("Open-data page should keep an always-visible #rawJsonLink")
    raw_json_opening_tag = raw_json_link[: raw_json_link.find(">") + 1]
    if attribute_value(raw_json_opening_tag, "href") != "data/products.json":
        raise AssertionError("Open-data raw JSON link should target data/products.json directly")
    if "json" not in visible_text(raw_json_link).casefold():
        raise AssertionError("Open-data raw JSON link should visibly identify its JSON format")

    filter_form = element_with_id(OPEN_DATA_TEXT, "form", "catalogFilters")
    if filter_form is None or attribute_value(filter_form, "role") != "search":
        raise AssertionError("Open-data filters should use form#catalogFilters with role=search")

    search_input = assert_labeled_control(OPEN_DATA_TEXT, "input", "catalogSearch")
    if attribute_value(search_input, "type") != "search":
        raise AssertionError("Open-data search control should use input type=search")

    assert_labeled_control(OPEN_DATA_TEXT, "select", "visibilityFilter")
    visibility_select = block_with_id(OPEN_DATA_TEXT, "select", "visibilityFilter")
    if visibility_select is None:
        raise AssertionError("Open-data page is missing the visibility filter options")
    option_values = [
        attribute_value(option[: option.find(">") + 1], "value")
        for option in element_blocks(visibility_select, "option")
    ]
    if option_values != ["all", "listed", "unlisted"]:
        raise AssertionError(
            "Open-data visibility filter should offer All, listed, and unlisted in that order: "
            f"{option_values!r}"
        )

    status = element_with_id(OPEN_DATA_TEXT, "p", "catalogStatus")
    if status is None:
        raise AssertionError("Open-data page should expose p#catalogStatus")
    if (
        attribute_value(status, "role") != "status"
        or attribute_value(status, "aria-live") != "polite"
        or attribute_value(status, "aria-atomic") != "true"
    ):
        raise AssertionError("Open-data catalog status should be an atomic polite live status")

    counts = element_with_id(OPEN_DATA_TEXT, "dl", "catalogCounts")
    if counts is None:
        raise AssertionError("Open-data page should expose semantic total/listed/unlisted counts")

    results = next(
        (
            tag_text
            for tag_text in opening_tags(OPEN_DATA_TEXT, "ul")
            + opening_tags(OPEN_DATA_TEXT, "div")
            if attribute_value(tag_text, "id") == "catalogResults"
        ),
        None,
    )
    if results is None or attribute_value(results, "aria-busy") is None:
        raise AssertionError("Open-data results should expose their loading state")
    if element_with_id(OPEN_DATA_TEXT, "p", "catalogEmpty") is None:
        raise AssertionError("Open-data page should expose a no-results state")
    for control in [
        search_input,
        element_with_id(OPEN_DATA_TEXT, "select", "visibilityFilter"),
        element_with_id(OPEN_DATA_TEXT, "select", "categoryFilter"),
    ]:
        if control is None or attribute_value(control, "aria-controls") != "catalogResults":
            raise AssertionError("Open-data search, visibility, and category controls should target #catalogResults")

    for marker in [
        'id="catalogPagination"',
        'aria-label="Catalog result pages"',
        'id="previousCatalogPage"',
        'id="nextCatalogPage"',
        'id="catalogPageStatus"',
        'aria-controls="catalogResults"',
        "const PAGE_SIZE = 6;",
        "new URLSearchParams(window.location.search)",
        'setUrlParameter(url, "q", query, "")',
        'setUrlParameter(url, "visibility", visibilityFilter.value, "all")',
        'setUrlParameter(url, "category", categoryFilter.value, "all")',
        'setUrlParameter(url, "page", String(currentPage), "1")',
        '"pushState" : "replaceState"',
        'window.addEventListener("popstate"',
        "const pageProducts = matching.slice(pageStart, pageEnd);",
        "pageProducts.forEach((product) => catalogGrid.append(makeProductCard(product)));",
        "Showing ${pageStart + 1}–${pageEnd} of ${matching.length} public records",
        "searchInput.focus({ preventScroll: true });",
    ]:
        if marker not in OPEN_DATA_TEXT:
            raise AssertionError(f"Open-data pagination or URL state is missing: {marker}")

    catalog_ids = {product["id"] for product in products}
    static_ids = catalog_ids & set(re.findall(r'data-product-id="([^"]+)"', OPEN_DATA_TEXT))
    if static_ids:
        if static_ids != catalog_ids:
            missing_ids = sorted(catalog_ids - static_ids)
            raise AssertionError(
                f"Open-data static results should include every public catalog record: {missing_ids!r}"
            )
    else:
        all_products_match = re.search(
            r"(?:const|let)\s+([A-Za-z_$][\w$]*)\s*=\s*"
            r"Array\.isArray\(data\.products\)\s*\?\s*data\.products\s*:\s*\[\s*\]",
            OPEN_DATA_TEXT,
        )
        if all_products_match is not None:
            all_products_variable = all_products_match.group(1)
        else:
            all_products_assignment = re.search(
                r"\b([A-Za-z_$][\w$]*)\s*=\s*([A-Za-z_$][\w$]*)\.products"
                r"\s*\.slice\(\)",
                OPEN_DATA_TEXT,
            )
            if all_products_assignment is None:
                raise AssertionError(
                    "Open-data renderer should retain the complete catalog products array before filtering"
                )
            all_products_variable, catalog_variable = all_products_assignment.groups()
            if f"Array.isArray({catalog_variable}.products)" not in OPEN_DATA_TEXT:
                raise AssertionError("Open-data renderer should validate the complete products array")

        if not re.search(
            rf"\b{re.escape(all_products_variable)}\s*\.(?:forEach|map|filter)\s*\(",
            OPEN_DATA_TEXT,
        ):
            raise AssertionError(
                "Open-data renderer should pass every catalog record into its card rendering path"
            )

        if "makeProductCard" not in OPEN_DATA_TEXT or not re.search(
            r"\b[A-Za-z_$][\w$]*\.forEach\s*\([\s\S]{0,240}?makeProductCard",
            OPEN_DATA_TEXT,
        ):
            raise AssertionError(
                "Open-data renderer should visibly create one card for each matching record"
            )

    for marker_group, description in [
        (("catalog-card",), "catalog card"),
        (("dataset.productId", "data-product-id"), "product-id hook"),
        (("dataset.visibility", "data-visibility"), "visibility hook"),
        (("visibility-badge",), "visible visibility badge"),
        (('value="all"',), "default all-record visibility filter"),
        (
            (
                'visibility === "all" || product.visibility === visibility',
                "visibility === 'all' || product.visibility === visibility",
            ),
            "all-record default filter behavior",
        ),
        (('visibility === "listed"', "visibility === 'listed'"), "listed count/filter path"),
        (('visibility === "unlisted"', "visibility === 'unlisted'"), "unlisted count/filter path"),
        (("catch (", "catch("), "catalog load failure state"),
    ]:
        if not any(marker in OPEN_DATA_TEXT for marker in marker_group):
            raise AssertionError(f"Open-data page is missing its {description}")

    if not any(
        re.search(pattern, OPEN_DATA_TEXT, re.DOTALL)
        for pattern in [
            r"appendText\([^;]{0,500}?visibility-badge[^;]{0,500}?"
            r"(?:humanize\()?product\.visibility",
            r"\.textContent\s*=\s*(?:humanize\()?product\.visibility",
            r"product\.visibility\s*===\s*[\"']listed[\"'][^;]{0,300}?"
            r"[\"']Listed[\"'][^;]{0,300}?[\"']Unlisted[\"']",
        ]
    ):
        raise AssertionError(
            "Open-data cards should visibly label each record from its listed/unlisted visibility"
        )

    status_variable = next(
        (
            match.group(1)
            for match in re.finditer(
                r"\b(?:const|let)\s+([A-Za-z_$][\w$]*)\s*=\s*"
                r'document\.querySelector\("#catalogStatus"\)',
                OPEN_DATA_TEXT,
            )
        ),
        None,
    )
    if status_variable is None or f"{status_variable}.textContent" not in OPEN_DATA_TEXT:
        raise AssertionError("Open-data page should update its live result-count/loading/error state")

    empty_variable = next(
        (
            match.group(1)
            for match in re.finditer(
                r"\b(?:const|let)\s+([A-Za-z_$][\w$]*)\s*=\s*"
                r'document\.querySelector\("#catalogEmpty"\)',
                OPEN_DATA_TEXT,
            )
        ),
        None,
    )
    if empty_variable is None or f"{empty_variable}.hidden" not in OPEN_DATA_TEXT:
        raise AssertionError("Open-data page should update its no-results state")


def main() -> None:
    if not PRODUCTS_JSON.exists():
        raise AssertionError("Product data should exist at data/products.json")

    products_data = json.loads(PRODUCTS_JSON.read_text())
    if products_data.get("schemaVersion") != CATALOG_SCHEMA_VERSION:
        raise AssertionError(
            f"Catalog schema version should be {CATALOG_SCHEMA_VERSION}: "
            f"{products_data.get('schemaVersion')!r}"
        )

    products = products_data.get("products")
    if not isinstance(products, list):
        raise AssertionError("Product data should expose a products list")

    product_ids = []
    for product in products:
        if not isinstance(product, dict):
            raise AssertionError("Every product catalog entry should be an object")

        product_id = product.get("id", "unknown")
        if not isinstance(product_id, str) or not product_id:
            raise AssertionError("Every product catalog entry should have a stable id")
        product_ids.append(product_id)

        unexpected_fields = sorted(set(product) - PUBLIC_PRODUCT_FIELDS)
        if unexpected_fields:
            raise AssertionError(
                f"Catalog entry {product_id} has fields outside the public schema: "
                f"{unexpected_fields!r}"
            )

        if "status" in product:
            raise AssertionError(f"Catalog entry {product_id} should not retain legacy status")

        visibility = product.get("visibility")
        if visibility not in CATALOG_VISIBILITIES:
            raise AssertionError(
                f"Catalog entry {product_id} has invalid visibility: {visibility!r}"
            )

        product_kind = product.get("productKind")
        if product_kind not in PRODUCT_KINDS:
            raise AssertionError(
                f"Catalog entry {product_id} has invalid productKind: {product_kind!r}"
            )

        logo_url = product.get("logoUrl")
        if visibility == "listed":
            if not isinstance(logo_url, str) or not logo_url.startswith(PRODUCT_LOGO_CDN_PREFIX):
                raise AssertionError(
                    f"Listed product logo should use the Caynetic CDN for {product_id}: {logo_url}"
                )
        elif logo_url not in (None, "") and (
            not isinstance(logo_url, str) or not logo_url.startswith(PRODUCT_LOGO_CDN_PREFIX)
        ):
            raise AssertionError(
                f"Unlisted product logo must be blank or use the Caynetic CDN for {product_id}: {logo_url}"
            )

    if len(product_ids) != len(set(product_ids)):
        raise AssertionError("Product catalog ids should be unique")

    product_by_id = {
        product.get("id"): product
        for product in products
        if isinstance(product, dict)
    }
    cayneticvpn = product_by_id.get("cayneticvpn")
    if cayneticvpn is None:
        raise AssertionError("Product data should include CayneticVPN by id")

    listed_products = [
        product
        for product in products
        if product.get("visibility") == "listed"
    ]
    assert_open_data_page(products)

    listed_ids = [product.get("id") for product in listed_products]
    if listed_ids != LISTED_PRODUCT_IDS:
        raise AssertionError(f"Listed product ids are stale or misordered: {listed_ids!r}")

    for key, expected in {
        "name": "CayneticVPN",
        "visibility": "listed",
        "productKind": "digital_platform",
        "country": "Bahamas",
        "category": "Cybersecurity",
        "logoUrl": PRODUCT_LOGO_URL,
        "logoAlt": "CayneticVPN logo",
        "logoWidth": 500,
        "logoHeight": 500,
    }.items():
        if cayneticvpn.get(key) != expected:
            raise AssertionError(f"CayneticVPN product data has wrong {key}: {cayneticvpn.get(key)!r}")

    expected_order = [
        'id="hero"',
        'id="directoryControls"',
        'id="productGrid"',
        'id="directoryStatus"',
        'id="directoryPagination"',
        'id="regionStats"',
        'id="submit"',
        'aria-label="Footer navigation"',
    ]

    for earlier, later in zip(expected_order, expected_order[1:]):
        assert_before(earlier, later)

    for asset_path in [
        "assets/brand/caribbeansaas-logo.png",
        "assets/brand/caribbeansaas-logo-mark-wide.png",
        "assets/brand/caribbeansaas-logo-mark.png",
        "assets/brand/caribbeansaas-logo-mark-centered.png",
        "assets/brand/caribbeansaas-icon-square.png",
        "assets/brand/caribbeansaas-icon-source.png",
        "assets/brand/caribbean-network-bg.svg",
        "assets/brand/favicon.ico",
        "assets/brand/favicon-centered.ico",
        "assets/brand/favicon-16.png",
        "assets/brand/favicon-32.png",
        "assets/brand/favicon-48.png",
        "assets/brand/favicon-16-centered.png",
        "assets/brand/favicon-32-centered.png",
        "assets/brand/favicon-48-centered.png",
        "assets/brand/apple-touch-icon.png",
        "assets/brand/apple-touch-icon-centered.png",
        "assets/brand/icon-192.png",
        "assets/brand/icon-512.png",
        "assets/brand/icon-192-centered.png",
        "assets/brand/icon-512-centered.png",
    ]:
        if not (ROOT / asset_path).exists():
            raise AssertionError(f"Missing brand or hero image asset: {asset_path}")

    for icon_path in [
        "assets/brand/favicon-16.png",
        "assets/brand/favicon-16-centered.png",
        "assets/brand/favicon-32.png",
        "assets/brand/favicon-32-centered.png",
        "assets/brand/favicon-48.png",
        "assets/brand/favicon-48-centered.png",
        "assets/brand/apple-touch-icon.png",
        "assets/brand/apple-touch-icon-centered.png",
        "assets/brand/icon-192.png",
        "assets/brand/icon-192-centered.png",
        "assets/brand/icon-512.png",
        "assets/brand/icon-512-centered.png",
    ]:
        assert_icon_visually_centered(ROOT / icon_path)
    assert_ico_frames_visually_centered(ROOT / "assets/brand/favicon.ico")
    assert_ico_frames_visually_centered(ROOT / "assets/brand/favicon-centered.ico")

    for head_marker in [
        '<title>CaribbeanSaaS | Caribbean SaaS &amp; Software Directory</title>',
        '<meta name="description" content="Discover reviewed Caribbean-built SaaS products, AI tools, fintech platforms, cybersecurity products, healthcare apps, tourism software, and developer tools."/>',
        '<meta name="robots" content="index, follow, max-image-preview:large"/>',
        '<meta name="author" content="Caynetic Ltd."/>',
        '<meta name="application-name" content="CaribbeanSaaS"/>',
        '<meta name="theme-color" content="#0B0F12"/>',
        '<link rel="canonical" href="https://caribbeansaas.com/"/>',
        '<meta property="og:type" content="website"/>',
        '<meta property="og:site_name" content="CaribbeanSaaS"/>',
        '<meta property="og:title" content="CaribbeanSaaS | Caribbean SaaS &amp; Software Directory"/>',
        '<meta property="og:url" content="https://caribbeansaas.com/"/>',
        '<meta property="og:image" content="https://caribbeansaas.com/assets/brand/caribbeansaas-logo.png"/>',
        '<meta property="og:image:alt" content="CaribbeanSaaS island technology logo"/>',
        '<meta name="twitter:card" content="summary_large_image"/>',
        '<meta name="twitter:title" content="CaribbeanSaaS | Caribbean SaaS &amp; Software Directory"/>',
        '<link rel="icon" href="assets/brand/favicon-centered.ico" sizes="any"/>',
        '<link rel="icon" type="image/png" sizes="16x16" href="assets/brand/favicon-16-centered.png"/>',
        '<link rel="icon" type="image/png" sizes="32x32" href="assets/brand/favicon-32-centered.png"/>',
        '<link rel="icon" type="image/png" sizes="48x48" href="assets/brand/favicon-48-centered.png"/>',
        '<link rel="apple-touch-icon" sizes="180x180" href="assets/brand/apple-touch-icon-centered.png"/>',
        '<link rel="manifest" href="site.webmanifest"/>',
        "family=Space+Grotesk:wght@600;700",
    ]:
        if head_marker not in HTML:
            raise AssertionError(f"Missing brand head marker: {head_marker}")

    for advertising_marker in ADVERTISING_MARKERS:
        if advertising_marker in HTML:
            raise AssertionError(f"Homepage should not load advertising code: {advertising_marker}")

    for manifest_marker in [
        '"name": "CaribbeanSaaS"',
        '"short_name": "CaribSaaS"',
        '"src": "assets/brand/icon-192-centered.png"',
        '"sizes": "192x192"',
        '"src": "assets/brand/icon-512-centered.png"',
        '"sizes": "512x512"',
        '"theme_color": "#0B0F12"',
    ]:
        if manifest_marker not in MANIFEST_TEXT:
            raise AssertionError(f"Missing web manifest marker: {manifest_marker}")

    for robots_marker in [
        "User-agent: *",
        "Allow: /",
        "Sitemap: https://caribbeansaas.com/sitemap.xml",
    ]:
        if robots_marker not in ROBOTS_TEXT:
            raise AssertionError(f"Missing robots marker: {robots_marker}")

    for sitemap_marker in [
        "<loc>https://caribbeansaas.com/</loc>",
        f"<lastmod>{date.today().isoformat()}</lastmod>",
        "<changefreq>weekly</changefreq>",
    ]:
        if sitemap_marker not in SITEMAP_TEXT:
            raise AssertionError(f"Missing sitemap marker: {sitemap_marker}")

    for llms_marker in [
        "# CaribbeanSaaS",
        "Caribbean SaaS products",
        "Caribbean software directory",
        "Caribbean AI tools",
        "Listings are reviewed before display.",
        "Founders and teams can get listed",
    ]:
        if llms_marker not in LLMS_TEXT:
            raise AssertionError(f"Missing llms.txt marker: {llms_marker}")

    for not_found_marker in [
        '<title>Page not found | CaribbeanSaaS</title>',
        '<meta name="robots" content="noindex, nofollow"/>',
        '<a href="/">Return to CaribbeanSaaS</a>',
    ]:
        if not_found_marker not in NOT_FOUND_TEXT:
            raise AssertionError(f"Missing 404 page marker: {not_found_marker}")

    if "Caribbean Cybersecurity Software" in NOT_FOUND_TEXT or "/category/cybersecurity/" in NOT_FOUND_TEXT:
        raise AssertionError("404 page should not preserve deprecated category content")

    for brand_marker in [
        ".header-brand {",
        ".brand-wordmark {",
        ".brand-wordmark-primary {",
        ".brand-wordmark-accent {",
        "body::before {",
        "animation: backgroundDrift 26s ease-in-out infinite alternate;",
        "background-repeat: no-repeat, repeat-y;",
        'url("assets/brand/caribbean-network-bg.svg")',
        ".hero-logo-wrap {",
        ".hero-logo {",
        "animation: logoFloat 6.5s ease-in-out infinite;",
        ".hero-wordmark {",
        'font-family: "Space Grotesk", "Geist", ui-sans-serif, system-ui, sans-serif;',
        ".hero-wordmark-caribbean {",
        "color: #00C2D7;",
        ".hero-wordmark-saas {",
        "color: #FF7A59;",
        "@keyframes backgroundDrift",
        "@keyframes logoFloat",
        '<span class="brand-wordmark"><span class="brand-wordmark-primary">Caribbean</span><span class="brand-wordmark-accent">SaaS</span></span>',
        'class="hero-logo" src="assets/brand/caribbeansaas-logo-mark-centered.png" alt="CaribbeanSaaS island technology logo"',
        'class="hero-wordmark" aria-label="CaribbeanSaaS"',
        '<span class="hero-wordmark-caribbean">Caribbean</span><span class="hero-wordmark-saas">SaaS</span>',
    ]:
        if brand_marker not in HTML:
            raise AssertionError(f"Missing logo or page background marker: {brand_marker}")

    header_block = HTML[
        marker_position("<header") : marker_position("</header>") + len("</header>")
    ]
    if '<img class="header-brand-logo"' in header_block or ".header-brand-logo {" in HTML:
        raise AssertionError("Header brand should be text-only because the logo image already appears in the hero")
    if header_block.count('<span class="brand-wordmark"') != 1:
        raise AssertionError("Header should keep exactly one text wordmark after removing the image logo")

    for hero_backdrop_marker in [
        ".hero-shell::before",
        ".hero-shell::after",
        ".hero-logo-wrap::before",
        ".hero-logo-wrap::after",
    ]:
        if hero_backdrop_marker in HTML:
            raise AssertionError("Hero should stay unboxed without hero-specific backdrop or outline layers")

    if 'aria-label="CaribSaaS"' in HTML or '<span class="hero-wordmark-carib">Carib</span>' in HTML:
        raise AssertionError("Hero wordmark should use full CaribbeanSaaS text")

    if "linear-gradient(90deg, #00C2D7 0%, #2ED6A3 44%, #FF7A59 100%)" in HTML:
        raise AssertionError("Hero wordmark should use two solid colors, not a text gradient")

    if 'url("assets/caribbean-map.png")' in HTML:
        raise AssertionError("Page background should use the abstract network asset, not the old map")

    for seo_marker in [
        '<script id="structured-data" type="application/ld+json">',
        '"@type": "Organization"',
        '"@type": "WebSite"',
        '"@type": "CollectionPage"',
        '"@type": "SoftwareApplication"',
        '"name": "Caribbean SaaS and Software Directory"',
        '"@id": "https://caribbeansaas.com/#listed-digital-products"',
        '"name": "Listed CaribbeanSaaS digital products"',
        '"name": "Caribbean SaaS"',
        '"name": "Caribbean software directory"',
        '"name": "Caribbean AI tools"',
        '"name": "Caribbean fintech"',
        '"name": "Jamaica"',
        '"name": "Trinidad and Tobago"',
        '"name": "Tourism software"',
        '"name": "Cybersecurity"',
        '"audienceType": "Caribbean founders"',
        '"itemListOrder": "https://schema.org/ItemListOrderAscending"',
        '"numberOfItems": 10',
        '"applicationCategory": "AI legal research software"',
        '"applicationCategory": "HR and payroll software"',
    ]:
        if seo_marker not in HTML:
            raise AssertionError(f"Missing SEO or structured-data marker: {seo_marker}")

    if HTML.count('"@type": "SoftwareApplication"') != len(LISTED_PRODUCT_IDS):
        raise AssertionError("Structured data should expose one SoftwareApplication per listed product")

    structured_match = re.search(
        r'<script id="structured-data" type="application/ld\+json">\s*(.*?)\s*</script>',
        HTML,
        re.DOTALL,
    )
    if structured_match is None:
        raise AssertionError("Homepage structured data should be parseable")
    structured_data = json.loads(structured_match.group(1))
    homepage_item_lists = [
        node
        for node in structured_data.get("@graph", [])
        if node.get("@id") == "https://caribbeansaas.com/#listed-digital-products"
    ]
    if len(homepage_item_lists) != 1:
        raise AssertionError("Homepage should expose one listed-product ItemList")
    structured_ids = [
        entry.get("item", {}).get("@id", "").rsplit("#", 1)[-1]
        for entry in homepage_item_lists[0].get("itemListElement", [])
    ]
    structured_positions = [
        entry.get("position")
        for entry in homepage_item_lists[0].get("itemListElement", [])
    ]
    if structured_ids != LISTED_PRODUCT_IDS:
        raise AssertionError(
            f"Homepage structured-data order should match the listed catalog: {structured_ids!r}"
        )
    if structured_positions != list(range(1, len(LISTED_PRODUCT_IDS) + 1)):
        raise AssertionError("Homepage structured-data positions should be contiguous")

    if '"@type": "Product"' in HTML:
        raise AssertionError("Mock listings should not be exposed as Product schema")

    for removed_copy in [
        "Browse the directory",
        "Search or filter the current example catalog",
        "Example listings are illustrative",
        "resultCount",
        "Email a product",
        "Email a Caribbean-built product for review.",
    ]:
        if removed_copy in HTML:
            raise AssertionError(f"Removed preview directory copy should not appear: {removed_copy}")

    for removed_accent in [
        "text-coral",
        "logo-coral",
        "coral:",
        "#FFD4C8",
    ]:
        if removed_accent in HTML:
            raise AssertionError(f"Old coral highlight should not appear in active HTML: {removed_accent}")

    if HTML.count('class="product-card') != len(LISTED_PRODUCT_IDS):
        raise AssertionError("Expected one visible product card for each listed product")

    for real_listing_marker in [
        'data-product-id="cayneticvpn"',
        'data-name="CayneticVPN"',
        'data-country="Bahamas"',
        'data-category="Cybersecurity"',
        'href="https://cayneticvpn.com"',
        'target="_blank"',
        'rel="noopener noreferrer"',
        'data-product-logo="cayneticvpn"',
        'alt="CayneticVPN logo"',
        'class="product-tag product-tag-category" type="button" aria-label="Filter by category: Cybersecurity" data-card-category="Cybersecurity"',
        'const PRODUCT_DATA_URL = "data/products.json";',
        'fetch(PRODUCT_DATA_URL, { cache: "no-store" });',
        'hydrateProductMedia',
    ]:
        if real_listing_marker not in HTML:
            raise AssertionError(f"Missing CayneticVPN listing marker: {real_listing_marker}")

    for product_id in LISTED_PRODUCT_IDS:
        if f'data-product-id="{product_id}"' not in HTML:
            raise AssertionError(f"Missing visible product card for {product_id}")
        if f'data-product-logo="{product_id}"' not in HTML:
            raise AssertionError(f"Missing JSON-backed product logo hook for {product_id}")
        if f'"@id": "https://caribbeansaas.com/#{product_id}"' not in HTML:
            raise AssertionError(f"Missing structured-data entry for listed product {product_id}")

    card_ids = set(re.findall(r'data-product-id="([^"]+)"', HTML))
    catalog_listed_ids = {product["id"] for product in listed_products}
    if card_ids != catalog_listed_ids:
        raise AssertionError(f"Visible cards should match listed catalog records: {card_ids!r}")

    for product in products:
        if product["visibility"] != "unlisted":
            continue

        product_id = product["id"]
        if f'data-product-id="{product_id}"' in HTML:
            raise AssertionError(f"Unlisted product {product_id} should not render a visible card")
        if f'"@id": "https://caribbeansaas.com/#{product_id}"' in HTML:
            raise AssertionError(f"Unlisted product {product_id} should not appear in structured data")

    for mock_listing in [
        "HarborPOS Cloud",
        "ReefLedger",
        "IslandStay Ops",
        "BlueMed Connect",
        "CayDev Monitor",
        "SecureHarbor Training",
        "TropicAI Desk",
        "EduWave LMS",
        "MarketMango",
        "DataCove Insights",
        "CropLink Planner",
        "CivicFlow Forms",
        "productLogoAssets",
        "hydrateProductLogos",
    ]:
        if mock_listing in HTML:
            raise AssertionError(f"Mock listing content should not remain: {mock_listing}")

    if 'id="regionStatsHeading"' not in HTML or "Apps by region" not in HTML:
        raise AssertionError("Apps by region stats section is missing")

    country_counts: dict[str, int] = {}
    for country in re.findall(r'data-country="([^"]+)"', HTML):
        country_counts[country] = country_counts.get(country, 0) + 1

    region_stats_block = HTML[
        marker_position('id="regionStats"') : marker_position('id="submit"')
    ]
    if region_stats_block.count('class="region-stat spectral-overlay focus-ring"') != len(country_counts):
        raise AssertionError("Apps by region stats should include one compact row for each listed region")

    for country, count in country_counts.items():
        route_display_name = "the Bahamas" if country == "Bahamas" else country
        expected_label = (
            f'aria-label="Browse {count} {"app" if count == 1 else "apps"} '
            f'from {route_display_name}"'
        )
        if expected_label not in region_stats_block:
            raise AssertionError(f"Apps by region route link is missing or stale for {country}")

    for country, flag_asset in [
        ("Bahamas", "assets/flags/bs.png"),
    ]:
        if f'class="region-stat-flag" src="{flag_asset}" alt="" aria-hidden="true"' not in region_stats_block:
            raise AssertionError(f"Apps by region stats should include the flag for {country}")

    product_grid_block = HTML[
        marker_position('id="productGrid"') : marker_position('id="emptyState"')
    ]
    homepage_card_ids = re.findall(
        r'<article class="product-card\b[^>]*data-product-id="([^"]+)"',
        product_grid_block,
    )
    if homepage_card_ids != LISTED_PRODUCT_IDS:
        raise AssertionError(
            f"Homepage card order should match the listed catalog: {homepage_card_ids!r}"
        )

    if "country-flag" in product_grid_block:
        raise AssertionError("Product cards should not use the old country-flag class")

    if PRODUCT_LOGO_URL in product_grid_block:
        raise AssertionError("Product card logo URL should come from data/products.json, not inline card markup")

    if "product-logo product-logo-image" not in HTML:
        raise AssertionError("Product card should use a real image logo")

    if HTML.count('class="product-region"') != len(LISTED_PRODUCT_IDS):
        raise AssertionError("Expected each product card to show a lower region row")

    if HTML.count('class="product-tags"') != len(LISTED_PRODUCT_IDS):
        raise AssertionError("Expected each product card to have a boxed tag group")

    for marker in [
        'id="productGrid" class="focus-ring',
        'tabindex="-1" aria-label="Directory results"',
        'id="directoryStatus"',
        'role="status" aria-live="polite" aria-atomic="true"',
        'id="directoryPagination"',
        'aria-label="Directory pagination"',
        'id="directoryPrevious"',
        'id="directoryNext"',
        'aria-controls="productGrid"',
        'id="directoryPageLabel"',
        "const PAGE_SIZE = 6;",
        'const ROUTE_REGION = document.body.dataset.routeRegion || "";',
        "new URLSearchParams(window.location.search)",
        'params.getAll("category")',
        'params.getAll("region")',
        'url.searchParams.set("q", query)',
        'url.searchParams.set("page", String(currentPage))',
        "window.history.pushState",
        "window.history.replaceState",
        'window.addEventListener("popstate"',
        "matchingCards.slice(pageStart, pageStart + PAGE_SIZE)",
        "Showing ${firstVisible}–${lastVisible} of ${matchingCards.length} products",
        "function preferredScrollBehavior()",
        '"(prefers-reduced-motion: reduce)"',
        'if (!/^[1-9]\\d*$/.test(pageValue))',
        "categorySummaryControl.focus({ preventScroll: true });",
        "regionSummaryControl.focus({ preventScroll: true });",
    ]:
        if marker not in HTML:
            raise AssertionError(f"Homepage pagination or URL state is missing: {marker}")

    if HTML.count('class="product-tag"') != len(LISTED_PRODUCT_IDS) * 2 or HTML.count('class="product-tag product-tag-category"') != len(LISTED_PRODUCT_IDS):
        raise AssertionError("Expected each product card to show three boxed tag chips")

    for product in listed_products:
        product_id = product["id"]
        product_match = re.search(
            rf'<article class="product-card[^"]*"[^>]*data-product-id="{re.escape(product_id)}".*?</article>',
            product_grid_block,
            re.DOTALL,
        )
        if product_match is None:
            raise AssertionError(f"Could not find product card block for {product_id}")

        product_block = product_match.group(0)
        category_label = product["category"]
        button_marker = (
            f'<button class="product-tag product-tag-category" type="button" '
            f'aria-label="Filter by category: {category_label}" data-card-category="{category_label}"'
        )
        if button_marker not in product_block:
            raise AssertionError(f"Product card {product_id} should filter by its category chip in-page")
        if '<a class="product-tag product-tag-category"' in product_block:
            raise AssertionError(f"Product card {product_id} should not link category chips to generated routes")
        if f'<span class="product-tag product-tag-category" aria-label="Category: {category_label}"' in product_block:
            raise AssertionError(f"Product card {product_id} should not render category chip as a non-clickable span")

    if HTML.count('class="hero-title-line"') != 3:
        raise AssertionError("Hero title should reveal as three text lines")

    if HTML.count("scroll-reveal") < 6:
        raise AssertionError("Page should include scroll reveal hooks for controls, cards, stats, submit, and footer")

    if "mt-5 flex flex-wrap justify-center gap-3" in HTML:
        raise AssertionError("Product tags should use boxed chip styles, not plain text spans")

    for marker in [
        "--caribbean-gradient: linear-gradient(135deg, #00C2D7 0%, #2ED6A3 58%, #7FE7F2 100%);",
        "--marketplace-orange: #FF7A59;",
        ".product-card {",
        "min-height: 26.75rem;",
        ".product-card h3 {",
        ".product-card > p {",
        "min-height: 4.5rem;",
        ".product-card > a {",
        "min-height: 2.9rem;",
        "background: var(--caribbean-surface-gradient) padding-box, var(--caribbean-gradient) border-box;",
        "background: var(--caribbean-surface-gradient) padding-box, linear-gradient(135deg, #FF7A59 0%, #FFB085 100%) border-box;",
        "box-shadow: 0 22px 70px var(--marketplace-orange-glow);",
        "text-sunset/85",
        ".product-tags {",
        "min-height: 3rem;",
        ".product-tag {",
        ".product-tag-category {",
        '.product-tag-category::before {',
        'content: "Category";',
        "margin-bottom: 1.35rem;",
        ".hero-title-line {",
        "@keyframes titleRise",
        ".scroll-reveal {",
        ".scroll-reveal.is-visible {",
        ".filter-toolbar {",
        ".category-menu {",
        ".category-option {",
        ".category-checkbox {",
        ".region-menu {",
        ".region-option {",
        ".region-checkbox {",
        ".region-flag {",
        ".filter-clear {",
        ".region-stats-grid {",
        ".region-stat {",
        ".region-stat-count {",
        ".region-stat-flag {",
        "white-space: nowrap;",
        ".logo-tide {",
    ]:
        if marker not in HTML:
            raise AssertionError(f"Missing visual structure marker: {marker}")

    for clear_marker in [
        'id="clearPreferences"',
        'id="clearCategories"',
        'id="clearRegions"',
        "Clear preferences",
        "Clear categories",
        "Clear regions",
    ]:
        if clear_marker not in HTML:
            raise AssertionError(f"Missing clear-preference control: {clear_marker}")

    hero_cta_block = HTML[
        marker_position("Explore directory") : marker_position('id="directory"')
    ]
    if 'href="#submit"' not in hero_cta_block or "Get listed" not in hero_cta_block:
        raise AssertionError("Hero Get listed CTA should scroll to the submit section")

    submit_block = HTML[
        marker_position('id="submit"') : marker_position('aria-label="Footer navigation"')
    ]
    if "Get listed in the CaribbeanSaaS directory." not in submit_block:
        raise AssertionError("Submission section should use Get listed language")

    all_categories = sorted({product["category"] for product in products if isinstance(product, dict) and product.get("category")})
    for category in sorted({product["category"] for product in listed_products}):
        if f'data-category="{category}" value="{category}"' not in HTML:
            raise AssertionError(f"Missing multi-category checkbox value for {category}")

    for removed_category_link_marker in [
        'id="categoryLinks"',
        'class="category-link-grid"',
        'class="category-directory-link',
        "CATEGORY_LINKS_START",
        "CATEGORY_LINKS_END",
    ]:
        if removed_category_link_marker in HTML:
            raise AssertionError(f"Directory controls should not show a separate category link list: {removed_category_link_marker}")

    for category in all_categories:
        canonical_slug = category_slug(category)
        default_slug = slugify(category)
        if default_slug != canonical_slug and f'href="/category/{default_slug}/"' in HTML:
            raise AssertionError(f"Homepage should not link deprecated category URL for {category}")

    for generated_route_prefix in [
        'href="/category/',
        'href="/products/',
        'href="/software/',
    ]:
        if generated_route_prefix in HTML:
            raise AssertionError(f"Homepage should not link generated route prefix: {generated_route_prefix}")

    sitemap_urls = re.findall(r"<loc>([^<]+)</loc>", SITEMAP_TEXT)
    expected_sitemap_urls = [
        "https://caribbeansaas.com/",
        "https://caribbeansaas.com/bahamas",
        "https://caribbeansaas.com/curation.html",
        "https://caribbeansaas.com/open-data.html",
        "https://caribbeansaas.com/privacy.html",
        "https://caribbeansaas.com/terms.html",
    ]
    if sitemap_urls != expected_sitemap_urls:
        raise AssertionError(
            f"Sitemap should include the homepage, country pages, and public support pages: {sitemap_urls!r}"
        )

    bahamas_ids = re.findall(
        r'<article class="product-card\b[^>]*data-product-id="([^"]+)"',
        BAHAMAS_TEXT,
    )
    if bahamas_ids != LISTED_PRODUCT_IDS:
        raise AssertionError(
            f"Bahamas route should contain the matching listed cards in catalog order: {bahamas_ids!r}"
        )
    for marker in [
        '<link rel="canonical" href="https://caribbeansaas.com/bahamas"/>',
        '<meta property="og:url" content="https://caribbeansaas.com/bahamas"/>',
        'data-route-region="Bahamas"',
        'data-route-slug="bahamas"',
        'aria-label="Region fixed to Bahamas" aria-disabled="true"',
        'aria-label="Discover software from the Bahamas"',
        '"@id": "https://caribbeansaas.com/bahamas#directory"',
        '"@id": "https://caribbeansaas.com/bahamas#listed-digital-products"',
        '"numberOfItems": 10',
    ]:
        if marker not in BAHAMAS_TEXT:
            raise AssertionError(f"Bahamas route is missing generated page marker: {marker}")

    for page_name, page_text, canonical, required_markers in [
        (
            "curation.html",
            CURATION_TEXT,
            "https://caribbeansaas.com/curation.html",
            ["How we curate", "Built for discovery. Reviewed before display.", "Caribbean connection", "Clear public evidence", "Independent review", "visibility", "listed", "unlisted", "not a rejection", "open-data.html"],
        ),
        (
            "open-data.html",
            OPEN_DATA_TEXT,
            "https://caribbeansaas.com/open-data.html",
            ["Open Data Explorer", "data/products.json", "Listed", "Unlisted", "catalogStatus"],
        ),
        (
            "privacy.html",
            PRIVACY_TEXT,
            "https://caribbeansaas.com/privacy.html",
            ["Privacy Policy", "does not load advertising or analytics scripts", "open-data.html", "hello@caribbeansaas.com"],
        ),
        (
            "terms.html",
            TERMS_TEXT,
            "https://caribbeansaas.com/terms.html",
            ["Terms of Use", "data/products.json", "visibility", "unlisted", "not a rejection"],
        ),
    ]:
        if f'<link rel="canonical" href="{canonical}"/>' not in page_text:
            raise AssertionError(f"{page_name} is missing its canonical URL")
        for marker in required_markers:
            if marker not in page_text:
                raise AssertionError(f"{page_name} is missing required public-page marker: {marker}")

    for country, flag_asset in [
        ("Bahamas", "assets/flags/bs.png"),
    ]:
        if f'value="{country}"' not in HTML:
            raise AssertionError(f"Missing multi-region checkbox value for {country}")
        if f'class="region-flag" src="{flag_asset}" alt="" aria-hidden="true"' not in HTML:
            raise AssertionError(f"Missing image-backed flag marker for {country}")

    if "🇦🇬" in HTML or "🇧🇸" in HTML or "🇯🇲" in HTML:
        raise AssertionError("Region selector should use image-backed flags, not emoji flags")

    for script_marker in [
        'const categoryCheckboxes = Array.from(document.querySelectorAll(".category-checkbox[data-category]"));',
        'const cardCategoryButtons = Array.from(document.querySelectorAll(".product-tag-category[data-card-category]"));',
        'const regionCheckboxes = Array.from(document.querySelectorAll(".region-checkbox[data-region]"));',
        "let activeCategories = new Set();",
        "let activeRegions = new Set();",
        "const matchesCategory = activeCategories.size === 0 || activeCategories.has(card.dataset.category);",
        "const matchesRegion = activeRegions.size === 0 || activeRegions.has(card.dataset.country);",
        "function clearCategories()",
        "function clearRegions()",
        "function clearAllPreferences()",
        "function selectCardCategory(category)",
        "cardCategoryButtons.forEach((button) => {",
        "function updateClearButton()",
        "function closeOpenFiltersOnOutsideClick(event)",
        "function initializeScrollReveals()",
        'document.querySelectorAll(".scroll-reveal")',
        "new IntersectionObserver",
        'document.addEventListener("click", closeOpenFiltersOnOutsideClick);',
        "initializeScrollReveals();",
        "updateCategorySummary();",
        "updateRegionSummary();",
    ]:
        if script_marker not in HTML:
            raise AssertionError(f"Missing country filter script marker: {script_marker}")

    if 'class="category-button' in HTML or 'class="country-button' in HTML:
        raise AssertionError("Category and region filtering should use square dropdown controls, not button grids")

    if 'id="categoryFilter"' not in HTML or 'id="categorySummary"' not in HTML:
        raise AssertionError("Multi-category filter menu or summary is missing")

    if 'id="regionFilter"' not in HTML or 'id="regionSummary"' not in HTML:
        raise AssertionError("Multi-region filter menu or summary is missing")

    search_position = marker_position('id="productSearch"')
    controls_position = marker_position('id="directoryControls"')
    grid_position = marker_position('id="productGrid"')
    if not controls_position < search_position < grid_position:
        raise AssertionError("Search input must sit in the directory controls before listings")

    header_block = HTML[
        marker_position("<header") : marker_position("</header>") + len("</header>")
    ]
    for page_name, page_text, required_regions in [
        ("homepage", HTML, ("footer",)),
        ("curation page", CURATION_TEXT, ("header", "footer")),
        ("privacy page", PRIVACY_TEXT, ("header", "footer")),
        ("terms page", TERMS_TEXT, ("header", "footer")),
    ]:
        assert_open_data_shell_links(page_name, page_text, required_regions)

    for href in ['href="#directory"', 'href="#categories"', 'href="#submit"']:
        if href not in header_block:
            raise AssertionError(f"Header is missing navigation link {href}")

    primary_nav_start = header_block.find('aria-label="Primary navigation"')
    if primary_nav_start == -1:
        raise AssertionError("Header is missing primary navigation")
    primary_nav_open = header_block.rfind("<nav", 0, primary_nav_start)
    primary_nav_close = header_block.find(">", primary_nav_start)
    primary_nav_tag = header_block[primary_nav_open:primary_nav_close]
    if "justify-center" not in primary_nav_tag:
        raise AssertionError("Primary navigation should be centered")
    if "sm:justify-end" in primary_nav_tag:
        raise AssertionError("Primary navigation should stay centered on desktop")

    footer_block = HTML[
        marker_position("<footer") : marker_position("</footer>") + len("</footer>")
    ]
    for removed_marker in [
        "SEO_BROWSE_LINKS_START",
        "SEO_BROWSE_LINKS_END",
        'aria-label="Browse CaribbeanSaaS landing pages"',
    ]:
        if removed_marker in footer_block:
            raise AssertionError(f"Footer should not expose generated crawl-link block: {removed_marker}")

    footer_pollution_terms = set()
    for product in listed_products:
        footer_pollution_terms.add(product["name"])
        footer_pollution_terms.add(product["category"])
        footer_pollution_terms.add(product["country"])
    footer_pollution_terms.add("The Bahamas")
    for term in sorted(footer_pollution_terms):
        if term != "CaribbeanSaaS" and term in footer_block:
            raise AssertionError(f"Footer should not list catalog terms that scale poorly: {term}")

    footer_ecosystem_copy = "Discover software, tools, and product teams shaping the Caribbean tech ecosystem."
    if footer_ecosystem_copy not in footer_block:
        raise AssertionError("Footer should use the ecosystem-focused brand line")
    for href in [
        'href="#directory"',
        'href="curation.html"',
        'href="open-data.html"',
        'href="#submit"',
        'href="privacy.html"',
        'href="terms.html"',
    ]:
        if href not in footer_block:
            raise AssertionError(f"Footer is missing public information link {href}")
    old_redundant_footer_copy = (
        "A curated showcase for Caribbean-built software, independently reviewed by Caynetic Ltd."
    )
    if old_redundant_footer_copy in footer_block:
        raise AssertionError("Footer should not repeat the curator/review message")

    caynetic_ltd_link = (
        f'<a class="focus-ring rounded-sm hover:text-white" href="{CAYNETIC_URL}" '
        'target="_blank" rel="noopener noreferrer">Caynetic Ltd.</a>'
    )
    if f"Curated by {caynetic_ltd_link}" not in header_block:
        raise AssertionError("Header Caynetic curator mention should link to caynetic.ltd")
    if f"Independently curated by {caynetic_ltd_link}" not in footer_block:
        raise AssertionError("Footer Caynetic curator mention should link to caynetic.ltd")
    if HTML.count(f'href="{CAYNETIC_URL}"') != 2:
        raise AssertionError("Only header and footer Caynetic attribution should link to caynetic.ltd")
    github_link_marker = (
        f'href="{GITHUB_URL}" target="_blank" rel="noopener noreferrer" '
        'aria-label="Follow CaribbeanSaaS on GitHub" title="Follow on GitHub"'
    )
    for page_name, page_text in [
        ("homepage", HTML),
        ("curation page", CURATION_TEXT),
        ("open-data page", OPEN_DATA_TEXT),
        ("privacy page", PRIVACY_TEXT),
        ("terms page", TERMS_TEXT),
    ]:
        page_footer = page_text[page_text.find("<footer") : page_text.find("</footer>") + len("</footer>")]
        if github_link_marker not in page_footer:
            raise AssertionError(f"{page_name} footer should include the accessible GitHub icon link")
        if page_footer.count(GITHUB_URL) != 1:
            raise AssertionError(f"{page_name} footer should include exactly one GitHub repository link")
        if 'viewBox="0 0 16 16" fill="currentColor" aria-hidden="true"' not in page_footer:
            raise AssertionError(f"{page_name} GitHub icon should be decorative and inherit text color")
    if CAYNETIC_URL in product_grid_block:
        raise AssertionError("Product card body copy should not link standalone Caynetic mentions")
    if "A privacy-focused VPN from Caynetic for encrypted internet access and safer browsing." not in product_grid_block:
        raise AssertionError("Product card body copy should keep Caynetic as plain text")

    if 'id="curation"' in HTML or 'aria-labelledby="curationHeading"' in HTML:
        raise AssertionError("Homepage should link to the standalone curation page instead of embedding the curation section")

    for curation_marker in [
        'id="curation"',
        "Built for discovery. Reviewed before display.",
        "Open catalog data (JSON)",
        "visibility",
        "listed",
        "unlisted",
    ]:
        if curation_marker not in CURATION_TEXT:
            raise AssertionError(f"Standalone curation page is missing disclosure: {curation_marker}")

    for trust_copy in [
        "Curated by",
        "Reviewed submissions",
        "Not a marketplace",
    ]:
        if trust_copy not in header_block:
            raise AssertionError(f"Header is missing trust copy: {trust_copy}")

    for expanded_copy in [
        'id="headerTrust"',
        "Independent regional technology curation, not automated scraping.",
        "Every public listing should pass manual review before display.",
        "The goal is discovery and credibility, not checkout or ranking.",
    ]:
        if expanded_copy in header_block:
            raise AssertionError(f"Header should use compact original trust copy, not: {expanded_copy}")

    if 'id="trustStrip"' in HTML:
        raise AssertionError("Trust copy should live in the header, not a separate trust strip")

    if PUBLIC_EMAIL not in HTML:
        raise AssertionError(f"Public page should use {PUBLIC_EMAIL}")

    if OLD_PUBLIC_EMAIL in HTML:
        raise AssertionError("Public page should not expose the old intake email address")


if __name__ == "__main__":
    main()
