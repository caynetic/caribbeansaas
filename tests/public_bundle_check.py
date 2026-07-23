from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BUILD_SCRIPT = ROOT / "scripts" / "build_public_site.py"
DIST = ROOT / "dist"
PUBLIC_ROOT_FILES = {
    "index.html",
    "404.html",
    "privacy.html",
    "terms.html",
    "robots.txt",
    "sitemap.xml",
    "llms.txt",
    "site.webmanifest",
}
PUBLIC_DIRECTORIES = {"assets", "data"}
INTERNAL_PATHS = {
    "PROJECT_BRAIN.md",
    "DESIGN.md",
    "design-qa.md",
    "screen.png",
    "docs",
    "audits",
    "private",
    ".codex",
    ".agents",
    "skills",
    "tmp",
    "scripts",
    "tests",
    ".env.outreach.example",
    ".env.spaces.example",
}


def main() -> None:
    subprocess.run([sys.executable, str(BUILD_SCRIPT)], check=True)

    if not DIST.is_dir():
        raise AssertionError("Public build should create dist/")

    actual_root_paths = {path.name for path in DIST.iterdir()}
    expected_root_paths = PUBLIC_ROOT_FILES | PUBLIC_DIRECTORIES
    if actual_root_paths != expected_root_paths:
        raise AssertionError(
            f"Public bundle should be an explicit allowlist: {actual_root_paths!r}"
        )

    for relative_path in PUBLIC_ROOT_FILES:
        if not (DIST / relative_path).is_file():
            raise AssertionError(f"Missing public bundle file: {relative_path}")

    for relative_path in PUBLIC_DIRECTORIES:
        if not (DIST / relative_path).is_dir():
            raise AssertionError(f"Missing public bundle directory: {relative_path}")

    for relative_path in INTERNAL_PATHS:
        if (DIST / relative_path).exists():
            raise AssertionError(f"Internal path leaked into public bundle: {relative_path}")


if __name__ == "__main__":
    main()
