"""Render the independent, curated games catalog into its public HTML page."""
from html import escape
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

from directory_catalog import replace_between

ROOT = Path(__file__).resolve().parents[1]
STATUSES = {"released": "Released", "early-access": "Early access", "demo": "Playable demo", "coming-soon": "Coming soon"}
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
        if set(game) != RECORD_FIELDS:
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
    return games


def card(game):
    title = escape(game["name"])
    links = game["links"]
    platforms = list(dict.fromkeys(link["platform"] for link in links))
    badges = "".join(f'<span class="game-badge platform">{escape(platform)}</span>' for platform in platforms)
    actions = "".join(
        f'<a class="game-action" href="{escape(link["url"], quote=True)}" aria-label="{escape(link["label"], quote=True)}: {title}">{escape(link["label"])}</a>'
        for link in links
    )
    return f'''            <article class="game-card" id="{game["id"]}" aria-labelledby="game-{game["id"]}">
                <div class="game-badges"><span class="game-badge">{STATUSES[game["status"]]}</span>{badges}</div>
                <h3 id="game-{game["id"]}">{title}</h3>
                <p class="game-byline">{escape(game["developer"])} · {escape(game["origin"])}</p>
                <p class="game-description">{escape(game["description"])}</p>
                <div class="game-actions">{actions}</div>
            </article>'''


def render_games_page():
    page = ROOT / "games.html"
    rendered = replace_between(page.read_text(), "            <!-- GAME_CARDS_START -->", "            <!-- GAME_CARDS_END -->", "\n".join(map(card, load_games())))
    candidate = page.with_suffix(".tmp")
    candidate.write_text(rendered)
    candidate.replace(page)


if __name__ == "__main__":
    render_games_page()
