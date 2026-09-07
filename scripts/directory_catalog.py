"""Render public directory content from the catalog using the existing site design."""
from collections import Counter
from html import escape
from pathlib import Path
import re
from urllib.parse import quote, urlsplit

FLAGS = {'Antigua and Barbuda':'ag','Anguilla':'ai','Aruba':'aw','Bahamas':'bs','Barbados':'bb','Belize':'bz','Bermuda':'bm','Bonaire':'bq','British Virgin Islands':'vg','Cayman Islands':'ky','Cuba':'cu','Curacao':'cw','Dominica':'dm','Dominican Republic':'do','French Guiana':'gf','Grenada':'gd','Guadeloupe':'gp','Guyana':'gy','Haiti':'ht','Jamaica':'jm','Martinique':'mq','Montserrat':'ms','Puerto Rico':'pr','Saint Barthélemy':'bl','Saint Kitts and Nevis':'kn','Saint Lucia':'lc','Saint Martin':'mf','Saint Vincent and the Grenadines':'vc','Sint Maarten':'sx','Suriname':'sr','Trinidad and Tobago':'tt','Turks and Caicos Islands':'tc','United States Virgin Islands':'vi'}
CATEGORY_LABELS = {'AI and machine learning':'AI','Data and analytics':'Data & analytics','Cybersecurity':'Cybersec'}
STAGES = {'beta':'Beta','early_access':'Early access','preview':'Preview'}

def e(value):
    return escape(str(value or ''), quote=True)

def flag(country, css='region-flag'):
    if country == 'Caribbean':
        return f'<span class="{css}" aria-hidden="true">🌐</span>'
    code = FLAGS.get(country)
    if not code:
        raise ValueError(f'Country needs a flag mapping: {country}')
    if (Path(__file__).resolve().parents[1] / 'assets' / 'flags' / f'{code}.png').exists():
        return f'<img class="{css}" src="assets/flags/{code}.png" alt="" aria-hidden="true"/>'
    emoji = ''.join(chr(127397 + ord(c)) for c in code.upper())
    return f'<span class="{css}" aria-hidden="true">{emoji}</span>'

def validate_products(products):
    ids, slugs = set(), set()
    for p in products:
        for field in ('id','slug','name','websiteUrl','tagline','description','country','category','industry','caribbeanConnection'):
            if not isinstance(p.get(field), str) or not p[field].strip():
                raise ValueError(f'{p.get("id")}: missing {field}')
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

def card(p):
    name, pid, country, category = (e(p[k]) for k in ('name','id','country','category'))
    initials = e(''.join(w[0] for w in p['name'].split()[:2]).upper())
    if p.get('logoUrl'):
        media = f'<img class="product-logo product-logo-image" src="assets/brand/caribbeansaas-icon-square.png" data-product-logo="{pid}" alt="{name} logo" width="{int(p.get("logoWidth") or 96)}" height="{int(p.get("logoHeight") or 96)}" loading="lazy"/>'
    else:
        media = f'<div class="product-logo logo-sea" aria-hidden="true"><span>{initials}</span></div>'
    kind_label = {'saas':'SaaS','mobile_app':'Mobile app','digital_platform':'Platform','api_or_developer_tool':'Developer tool','marketplace':'Marketplace'}.get(p['productKind'],p['productKind'].replace('_',' '))
    tags = list(dict.fromkeys(tag for tag in (p.get('tags') or []) if tag.casefold() != p['category'].casefold()))
    for fallback in (p['industry'],kind_label):
        if len(tags)<2 and fallback.casefold() not in {tag.casefold() for tag in tags}: tags.append(fallback)
    search = e(' '.join([p['name'],p['country'],p['category'],p['industry'],p['description'],p['caribbeanConnection'],*tags,*(p.get('aliases') or [])]).lower())
    stage = f'<span class="directory-stage">{STAGES[p["availability"]]}</span>' if p.get('availability') in STAGES else ''
    return f'''<article class="product-card scroll-reveal spectral-overlay p-6 text-center transition-all duration-500 hover:border-sea/40" data-product-id="{pid}" data-name="{name}" data-country="{country}" data-category="{category}" data-search="{search}">
                <div class="product-media">{media}</div>
                <h3 class="mt-4 text-base font-bold uppercase tracking-[0.16em] text-white">{name}</h3>
                {stage}
                <p class="mt-4 text-xs italic leading-6 text-white/60">{e(p['description'])}</p>
                <div class="product-tags">
                    <span class="product-tag">{e(tags[0])}</span>
                    <button class="product-tag product-tag-category" type="button" aria-label="Filter by category: {category}" data-card-category="{category}">{e(CATEGORY_LABELS.get(p['category'],p['category']))}</button>
                    <span class="product-tag">{e(tags[1])}</span>
                </div>
                <p class="product-connection">{e(p['caribbeanConnection'])}</p>
                <a class="focus-ring mt-1 inline-flex items-center justify-center border border-outline px-6 py-3 text-[10px] font-bold uppercase tracking-[0.22em] text-primary transition-all duration-300 hover:border-sea hover:text-sea" href="{e(p['websiteUrl'])}" target="_blank" rel="noopener noreferrer">Visit website</a>
                <div class="product-region">
                    <span class="product-region-label">Region</span>
                    <button class="product-region-filter focus-ring" type="button" aria-label="Filter by region: {country}">
                        <span class="product-region-value">{flag(p['country'])} {country}</span>
                    </button>
                </div>
            </article>'''

def item(p, position, site_url):
    application = {'@type':'SoftwareApplication','@id':f'{site_url}/#{p["id"]}','name':p['name'],'url':p['websiteUrl'],'applicationCategory':p['category'],'description':p['description'],'areaServed':{'@type':'Place','name':p['country']}}
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
    countries=sorted({p['country'] for p in products})
    options='\n'.join(f'<label class="region-option"><input class="region-checkbox" data-region="{e(c)}" value="{e(c)}" type="checkbox"/>{flag(c)}<span>{e(c)}</span></label>' for c in countries)
    page=re.sub(r'<label class="region-option">.*?</label>\s*(?=</div>)',lambda m: options,page,count=1,flags=re.S)
    counts=Counter(p['country'] for p in products)
    stats=[]
    for c in countries:
        count=counts[c]
        stats.append(f'''<li><a class="region-stat region-stat-filter spectral-overlay focus-ring" href="/?region={quote(c)}#directory" data-region-stat="{e(c)}" aria-label="Filter directory to {count} {'app' if count==1 else 'apps'} connected to {e(c)}"><span class="region-stat-label">{flag(c,'region-stat-flag')}<span class="region-stat-name">{e(c)}</span></span><span class="flex items-center gap-2"><span class="region-stat-count">{count}</span></span></a></li>''')
    page=re.sub(r'(<ul class="region-stats-grid" aria-label="Apps by region">).*?(</ul>)',lambda m:m[1]+'\n'+'\n'.join(stats)+'\n'+m[2],page,count=1,flags=re.S)
    return re.sub(r"[ \t]+\n", "\n", page)
