from __future__ import annotations

import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
PUBLIC_ROOT_FILES = (
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
)
PUBLIC_DIRECTORIES = ("assets", "data")


def require_file(relative_path: str) -> Path:
    path = ROOT / relative_path
    if not path.is_file():
        raise FileNotFoundError(f"Missing required public file: {relative_path}")
    return path


def require_directory(relative_path: str) -> Path:
    path = ROOT / relative_path
    if not path.is_dir():
        raise FileNotFoundError(f"Missing required public directory: {relative_path}")
    return path


def main() -> None:
    if DIST.exists():
        shutil.rmtree(DIST)
    DIST.mkdir()

    for relative_path in PUBLIC_ROOT_FILES:
        shutil.copy2(require_file(relative_path), DIST / relative_path)

    for relative_path in PUBLIC_DIRECTORIES:
        shutil.copytree(
            require_directory(relative_path),
            DIST / relative_path,
            ignore=shutil.ignore_patterns(".DS_Store"),
        )


if __name__ == "__main__":
    main()
