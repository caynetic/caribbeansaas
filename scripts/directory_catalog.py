"""Render public directory content from the catalog using the existing site design."""
from collections import Counter
from html import escape
import json
from pathlib import Path
import re
from urllib.parse import quote, urlsplit

from site_config import country_route_display_name, country_route_slug

FLAGS = {'Antigua and Barbuda':'ag','Anguilla':'ai','Aruba':'aw','Bahamas':'bs','Barbados':'bb','Belize':'bz','Bermuda':'bm','Bonaire':'bq','British Virgin Islands':'vg','Cayman Islands':'ky','Cuba':'cu','Curacao':'cw','Dominica':'dm','Dominican Republic':'do','French Guiana':'gf','Grenada':'gd','Guadeloupe':'gp','Guyana':'gy','Haiti':'ht','Jamaica':'jm','Martinique':'mq','Montserrat':'ms','Puerto Rico':'pr','Saint Barthélemy':'bl','Saint Kitts and Nevis':'kn','Saint Lucia':'lc','Saint Martin':'mf','Saint Vincent and the Grenadines':'vc','Sint Maarten':'sx','Suriname':'sr','Trinidad and Tobago':'tt','Turks and Caicos Islands':'tc','United States Virgin Islands':'vi'}
CATEGORY_LABELS = {'AI and machine learning':'AI','Data and analytics':'Data & analytics','Cybersecurity':'Cybersec'}
STAGES = {'beta':'Beta','early_access':'Early access','preview':'Preview'}

def e(value):
    return escape(str(value or ''), quote=True)

def flag(country, css='region-flag'):
    if country == 'Caribbean':
        filename = 'caribbean.svg'
    else:
        code = FLAGS.get(country)
        if not code:
            raise ValueError(f'Country needs a flag mapping: {country}')
        filename = f'{code}.png'
    asset = Path(__file__).resolve().parents[1] / 'assets' / 'flags' / filename
    if not asset.is_file():
        raise ValueError(f'Country needs a local flag image: {country} ({filename})')
    return (f'<img class="{css}" src="assets/flags/{filename}" alt="" aria-hidden="true" '
            'width="24" height="16" decoding="async"/>')

MARKET_CAPABILITIES = {
    'hr': 'HR',
    'workforceManagement': 'workforce management',
    'talentManagement': 'talent management',
    'localPayroll': 'local payroll',
}

def attach_market_availability(products, config):
    """Join opt-in markets without changing the public products.json schema."""
    if not isinstance(config, dict) or set(config) != {'marketAvailability'}:
        raise ValueError('Expected marketAvailability in the coverage catalog')
    coverage = config['marketAvailability']
    if not isinstance(coverage, dict):
        raise ValueError('marketAvailability must be keyed by catalog product ID')
    unknown = set(coverage) - {product.get('id') for product in products}
    if unknown:
        raise ValueError(f'Market availability refers to unknown products: {sorted(unknown)}')
    return [
        {**product, 'marketAvailability': coverage[product['id']]}
        if product['id'] in coverage else product
        for product in products
    ]

def attach_listing_cta_overrides(products, overrides):
    """Allow query-only CTA overrides without changing canonical product URLs."""
    if not isinstance(overrides, dict):
        raise ValueError('CTA overrides must be keyed by catalog product ID')
    unknown = set(overrides) - {product['id'] for product in products}
    if unknown:
        raise ValueError(f'CTA override refers to unknown products: {sorted(unknown)}')
    result = []
    for product in products:
        if product['id'] not in overrides:
            result.append(product)
            continue
        url = overrides[product['id']]
        if not isinstance(url, str):
            raise ValueError(f'{product["id"]}: CTA override must be a URL')
        canonical, cta = urlsplit(product['websiteUrl']), urlsplit(url)
        if (cta.scheme != 'https' or not cta.query or cta.fragment
                or cta._replace(query='') != canonical._replace(query='')):
            raise ValueError(f'{product["id"]}: CTA override must preserve the canonical HTTPS destination')
        result.append({**product, 'listingCtaUrl': url})
    return result

def listing_regions(product):
    """Only explicit verified marketAvailability opts into secondary browse regions."""
    primary = product['country']
    country_route_slug(primary)
    markets = product.get('marketAvailability', {})
    if not isinstance(markets, dict) or ('marketAvailability' in product and not markets):
        raise ValueError(f'{product["id"]}: marketAvailability must be a non-empty object')
    for region, capabilities in markets.items():
        country_route_slug(region)
        if region == 'Caribbean' or region not in (product.get('countries') or []):
            raise ValueError(f'{product["id"]}: market is not a specific catalog country: {region}')
        if (not isinstance(capabilities, list) or not capabilities
                or any(not isinstance(value, str) or value not in MARKET_CAPABILITIES for value in capabilities)
                or len(set(capabilities)) != len(capabilities)):
            raise ValueError(f'{product["id"]}: invalid market capabilities for {region}')
    return tuple(dict.fromkeys((primary, *markets)))

def market_summaries(product):
    summaries = {}
    for region, capabilities in product.get('marketAvailability', {}).items():
        names = [MARKET_CAPABILITIES[key] for key in capabilities if key != 'localPayroll']
        place = country_route_display_name(region)
        if len(names) > 2:
            names = [', '.join(names[:-1]) + ', and ' + names[-1]]
        labels = ' and '.join(names)
        labels = labels[:1].upper() + labels[1:]
        summary = f'{labels} tools are available in {place}.' if labels else ''
        if 'localPayroll' in capabilities:
            summary += f' Local payroll is also available in {place}.' if labels else f'Local payroll is available in {place}.'
        summaries[region] = summary
    return summaries

def validate_products(products):
    ids, slugs = set(), set()
    for p in products:
        for field in ('id','slug','name','websiteUrl','tagline','description','country','category','industry','caribbeanConnection'):
            if not isinstance(p.get(field), str) or not p[field].strip():
                raise ValueError(f'{p.get("id")}: missing {field}')
        listing_regions(p)
        if p['id'] in ids or p['slug'] in slugs:
            raise ValueError('Duplicate product ID or slug')
        ids.add(p['id']); slugs.add(p['slug'])
        if not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*',p['id']) or not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*',p['slug']):
            raise ValueError('Invalid product ID or slug')
        parts = urlsplit(p['websiteUrl'])
        if parts.scheme != 'https' or not parts.hostname or parts.username or parts.password:
            raise ValueError(f'{p["id"]}: official URL must use HTTPS without credentials')
        if p.get('connectionType') not in (None,'origin','market'):
            raise ValueError(f'{p["id"]}: invalid connection type')
        if p.get('availability') not in (None,*STAGES):
            raise ValueError(f'{p["id"]}: invalid availability label')
        if p.get('logoUrl') and not p['logoUrl'].startswith('https://cdn.caynetic.app/caribbeansaas/products/logos/'):
            raise ValueError(f'{p["id"]}: logo must use the project CDN')
        if p.get('logoBackground') and not re.fullmatch(r'#[0-9A-Fa-f]{6}', p['logoBackground']):
            raise ValueError(f'{p["id"]}: logo background must be a six-digit hex color')

def card(p, *, route_region=None):
    name, pid, country, category = (e(p[k]) for k in ('name','id','country','category'))
    initials = e(''.join(w[0] for w in p['name'].split()[:2]).upper())
    if p.get('logoUrl'):
        media = f'<div class="product-logo logo-sea" data-product-logo="{pid}" aria-hidden="true"><span>{initials}</span></div>'
    else:
        media = f'<div class="product-logo logo-sea" aria-hidden="true"><span>{initials}</span></div>'
    kind_label = {'saas':'SaaS','mobile_app':'Mobile app','digital_platform':'Platform','api_or_developer_tool':'Developer tool','marketplace':'Marketplace'}.get(p['productKind'],p['productKind'].replace('_',' '))
    tags = list(dict.fromkeys(tag for tag in (p.get('tags') or []) if tag.casefold() != p['category'].casefold()))
    for fallback in (p['industry'],kind_label):
        if len(tags)<2 and fallback.casefold() not in {tag.casefold() for tag in tags}: tags.append(fallback)
    market_scope = market_summaries(p)
    market_summary = market_scope.get(route_region)
    detail = market_summary or p['description']
    connection = '' if market_summary else p['caribbeanConnection']
    market_attributes = ''
    anchor = ''
    market_description = ''
    searchable_details = [p['description'],p['caribbeanConnection']]
    if market_scope:
        anchor = f' id="{pid}"'
        market_description = ' data-market-description'
        market_attributes = (
            f' data-market-availability="{e(json.dumps(market_scope, ensure_ascii=False))}"'
            f' data-directory-description="{e(p["description"])}"'
            f' data-directory-connection="{e(p["caribbeanConnection"])}"'
        )
        # Regional cards search the visible scoped copy, not the default cross-market description.
        searchable_details = []
    search = e(' '.join([p['name'],p['country'],p['category'],p['industry'],*searchable_details,*tags,*(p.get('aliases') or [])]).lower())
    stage = f'<span class="directory-stage">{STAGES[p["availability"]]}</span>' if p.get('availability') in STAGES else ''
    return f'''<article class="product-card scroll-reveal spectral-overlay p-6 text-center transition-all duration-500 hover:border-sea/40" data-product-id="{pid}" data-name="{name}" data-country="{country}" data-category="{category}" data-search="{search}"{anchor}{market_attributes}>
                <div class="product-media">{media}</div>
                <h3 class="mt-4 text-base font-bold uppercase tracking-[0.16em] text-white">{name}</h3>
                {stage}
                <p class="mt-4 text-xs italic leading-6 text-white/60"{market_description}>{e(detail)}</p>
                <div class="product-tags">
                    <span class="product-tag">{e(tags[0])}</span>
                    <button class="product-tag product-tag-category" type="button" aria-label="Filter by category: {category}" data-card-category="{category}">{e(CATEGORY_LABELS.get(p['category'],p['category']))}</button>
                    <span class="product-tag">{e(tags[1])}</span>
                </div>
                <p class="product-connection"{' hidden' if market_summary else ''}>{e(connection)}</p>
                <a class="focus-ring mt-1 inline-flex items-center justify-center border border-outline px-6 py-3 text-[10px] font-bold uppercase tracking-[0.22em] text-primary transition-all duration-300 hover:border-sea hover:text-sea" href="{e(p.get('listingCtaUrl', p['websiteUrl']))}" target="_blank" rel="noopener noreferrer">Visit website</a>
                <div class="product-region">
                    <span class="product-region-label">Region</span>
                    <button class="product-region-filter focus-ring" type="button" aria-label="Filter by region: {country}">
                        <span class="product-region-value">{flag(p['country'])}<span class="product-region-name">{country}</span></span>
                    </button>
                </div>
            </article>'''

def item(p, position, site_url):
    application = {'@type':'SoftwareApplication','@id':f'{site_url}/#{p["id"]}','name':p['name'],'url':p['websiteUrl'],'applicationCategory':p['category'],'description':p['description'],'areaServed':{'@type':'Place','name':p['country']}}
    if p.get('marketAvailability'):
        application['areaServed'] = [{'@type':'Place','name':region} for region in listing_regions(p)]
    if p.get('companyName'):
        application['publisher']={'@type':'Organization','name':p['companyName']}
    return {'@type':'ListItem','position':position,'item':application}

def replace_between(text, start, end, value):
    if text.count(start)!=1 or text.count(end)!=1:
        raise RuntimeError(f'Missing or duplicate directory template marker: {start}')
    before, rest = text.split(start,1)
    _, after = rest.split(end,1)
    return before+start+'\n'+value+'\n'+end+after

def render_directory(page, products):
    validate_products(products)
    page=replace_between(page,'<!-- PRODUCT_CARDS_START -->','<!-- PRODUCT_CARDS_END -->','\n            '.join(card(p) for p in products))
    categories=sorted({p['category'] for p in products})
    options='\n'.join(f'<label class="category-option"><input class="category-checkbox" data-category="{e(c)}" value="{e(c)}" type="checkbox"/><span>{e(CATEGORY_LABELS.get(c,c))}</span></label>' for c in categories)
    page=re.sub(r'<label class="category-option">.*?</label>\s*(?=</div>)',lambda m: options,page,count=1,flags=re.S)
    counts=Counter(region for p in products for region in listing_regions(p))
    countries=sorted(counts)
    options='\n'.join(f'<label class="region-option"><input class="region-checkbox" data-region="{e(c)}" value="{e(c)}" type="checkbox"/>{flag(c)}<span>{e(c)}</span></label>' for c in countries)
    page=re.sub(r'<label class="region-option">.*?</label>\s*(?=</div>)',lambda m: options,page,count=1,flags=re.S)
    stats=[]
    for c in countries:
        count=counts[c]
        stats.append(f'''<li><a class="region-stat region-stat-filter spectral-overlay focus-ring" href="/?region={quote(c)}#directory" data-region-stat="{e(c)}" aria-label="Filter directory to {count} {'app' if count==1 else 'apps'} connected to {e(c)}"><span class="region-stat-label">{flag(c,'region-stat-flag')}<span class="region-stat-name">{e(c)}</span></span><span class="flex items-center gap-2"><span class="region-stat-count">{count}</span></span></a></li>''')
    page=re.sub(r'(<ul class="region-stats-grid" aria-label="Apps by region">).*?(</ul>)',lambda m:m[1]+'\n'+'\n'.join(stats)+'\n'+m[2],page,count=1,flags=re.S)
    return re.sub(r"[ \t]+\n", "\n", page)
