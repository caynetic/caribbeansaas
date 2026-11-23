"""Render the independent, curated games catalog into its public HTML page."""
from html import escape
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

from directory_catalog import flag, replace_between

ROOT = Path(__file__).resolve().parents[1]
STATUSES = {"released": "Released", "early-access": "Early access", "demo": "Playable demo", "coming-soon": "Coming soon", "playable-web": "Playable on web"}
RECORD_FIELDS = {"id", "name", "developer", "origin", "originSource", "status", "description", "links"}
FIELD_LENGTHS = {"name": 100, "developer": 110, "origin": 65, "description": 320}


def https(url):
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.hostname or parts.username or parts.password:
        raise ValueError(f"Expected an official HTTPS listing URL: {url!r}")
    return url


def load_games():
    catalog = json.loads((ROOT / "data/games.json").read_text())
    games = catalog.get("games")
    if catalog.get("schemaVersion") != 1 or not isinstance(games, list) or not games:
        raise ValueError("At least one verified game is required")
    ids = set()
    for game in games:
        if set(game) - {"icon"} != RECORD_FIELDS:
            raise ValueError("Incomplete or unknown games record fields")
        game_id = game["id"]
        if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", game_id) or game_id in ids:
            raise ValueError(f"Invalid or duplicate game ID: {game_id!r}")
        ids.add(game_id)
        for field, limit in FIELD_LENGTHS.items():
            value = game[field]
            if not isinstance(value, str) or not value.strip() or len(value) > limit:
                raise ValueError(f"{game_id}: incorrect {field}")
        if game["status"] not in STATUSES:
            raise ValueError(f"{game_id}: unknown public status")
        https(game["originSource"])
        links = game["links"]
        if not isinstance(links, list) or not 1 <= len(links) <= 3:
            raise ValueError(f"{game_id}: expected 1–3 official places to play")
        if len({link["url"] for link in links}) != len(links):
            raise ValueError(f"{game_id}: duplicate store URL")
        for link in links:
            if set(link) != {"platform", "label", "url"} or any(not isinstance(v, str) or not v.strip() for v in link.values()):
                raise ValueError(f"{game_id}: bad official listing metadata")
            https(link["url"])
        if "icon" in game:
            icon = game["icon"]
            keys = {"kind", "width", "height", "sourcePage"}
            if not isinstance(icon, dict) or set(icon) - {"sourceAsset"} != keys:
                raise ValueError(f"{game_id}: bad icon metadata")
            if icon["kind"] not in {"logo", "cover-art", "app-icon"} or any(
                type(icon[side]) is not int or not 1 <= icon[side] <= 512 for side in ("width", "height")
            ):
                raise ValueError(f"{game_id}: bad icon type or dimensions")
            https(icon["sourcePage"])
            if "sourceAsset" in icon:
                https(icon["sourceAsset"])
            image = ROOT / f"assets/games/icons/{game_id}.webp"
            if not image.is_file():
                raise ValueError(f"{game_id}: missing local WebP artwork")
    return games


def card(game):
    title = escape(game["name"])
    initials = escape("".join(word[0] for word in game["name"].split()[:2]).upper())
    media = f'<div class="product-logo logo-sea" aria-hidden="true"><span>{initials}</span></div>'
    if (icon := game.get("icon")) is not None:
        media = (
            f'<img class="product-logo game-logo-image" src="/assets/games/icons/{game["id"]}.webp"'
            f' alt="" width="{icon["width"]}" height="{icon["height"]}" loading="lazy" decoding="async"/>'
        )
    links = game["links"]
    platforms = list(dict.fromkeys(link["platform"] for link in links))
    tags = "".join(f'<span class="product-tag">{escape(platform)}</span>' for platform in platforms)
    actions = "".join(
        f'<a class="game-action focus-ring mt-1 inline-flex items-center justify-center border border-outline px-6 py-3 text-[10px] font-bold uppercase tracking-[0.22em] text-primary transition-all duration-300 hover:border-sea hover:text-sea" href="{escape(link["url"], quote=True)}" aria-label="{escape(link["label"], quote=True)}: {title}">{escape(link["label"])}</a>'
        for link in links
    )
    origin = game["origin"]
    origin_flag = flag("Bahamas" if origin == "The Bahamas" else origin)
    return f'''            <article class="game-card product-card spectral-overlay p-6 text-center transition-all duration-500 hover:border-sea/40" id="{game["id"]}" aria-labelledby="game-{game["id"]}">
                <div class="product-media">{media}</div>
                <h3 id="game-{game["id"]}" class="mt-4 text-base font-bold uppercase tracking-[0.16em] text-white">{title}</h3>
                <p class="mt-4 text-xs italic leading-6 text-white/60">{escape(game["description"])}</p>
                <div class="product-tags"><span class="directory-stage">{STATUSES[game["status"]]}</span>{tags}</div>
                <p class="product-connection">{escape(game["developer"])}</p>
                <div class="game-actions">{actions}</div>
                <div class="product-region">
                    <span class="product-region-label">Region</span>
                    <span class="product-region-value">{origin_flag}<span class="product-region-name">{escape(origin)}</span></span>
                </div>
            </article>'''


def render_games_page():
    page = ROOT / "games.html"
    rendered = replace_between(page.read_text(), "            <!-- GAME_CARDS_START -->", "            <!-- GAME_CARDS_END -->", "\n".join(map(card, load_games())))
    candidate = page.with_suffix(".tmp")
    candidate.write_text(rendered)
    candidate.replace(page)


if __name__ == "__main__":
    render_games_page()
