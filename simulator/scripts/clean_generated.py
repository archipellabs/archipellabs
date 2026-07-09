#!/usr/bin/env python3
"""Remove generated client files, preserving the static pyproject.toml."""

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GENERATED_DIR = ROOT / "generated"

GENERATED_PACKAGES = [
    "backoffice_api_client",
    "presta_shop_rest_api_client",
]


def main() -> None:
    removed = False
    for pkg in GENERATED_PACKAGES:
        pkg_dir = GENERATED_DIR / pkg
        if pkg_dir.exists():
            shutil.rmtree(pkg_dir)
            print(f"Removed {pkg_dir}")
            removed = True
    if not removed:
        print("Nothing to clean.")


if __name__ == "__main__":
    main()
