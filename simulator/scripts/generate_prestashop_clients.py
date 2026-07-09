#!/usr/bin/env python3
"""Generate PrestaShop clients from OpenAPI specs, patching known schema issues."""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OPENAPI_DIR = ROOT / "openapi"
GENERATED_DIR = ROOT / "generated"

CLIENTS = [
    {
        "source": OPENAPI_DIR / "prestashop_webservice_api.json",
        "output": GENERATED_DIR / "presta_shop_rest_api_client",
    },
    {
        "source": OPENAPI_DIR / "prestashop_admin_api.json",
        "output": GENERATED_DIR / "backoffice_api_client",
    },
]

GENERATED_PYPROJECT = """\
[project]
name = "prestashop-clients"
version = "0.1.0"
description = "Generated PrestaShop API clients"
requires-python = ">=3.9"
dependencies = [
    "httpx>=0.23.0,<0.29.0",
    "attrs>=22.2.0",
    "python-dateutil>=2.8.0,<3",
]

[build-system]
requires = ["setuptools"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
where = ["."]
include = ["backoffice_api_client*", "presta_shop_rest_api_client*"]
"""

GENERATED_GITIGNORE = """\
*
!.gitignore
!pyproject.toml
"""


def ensure_generated_dir() -> None:
    GENERATED_DIR.mkdir(exist_ok=True)
    pyproject = GENERATED_DIR / "pyproject.toml"
    if not pyproject.exists():
        pyproject.write_text(GENERATED_PYPROJECT)
    gitignore = GENERATED_DIR / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text(GENERATED_GITIGNORE)


def patch(data: dict) -> dict:
    # openapi-python-client requires properties to be a dict, not a list
    for schema in data.get("components", {}).get("schemas", {}).values():
        if isinstance(schema.get("properties"), list):
            schema["properties"] = {}
    return data


def generate(source: Path, output: Path) -> int:
    with source.open() as f:
        data = json.load(f)

    data = patch(data)

    output.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.NamedTemporaryFile(suffix=".json", mode="w", delete=False) as tmp:
        json.dump(data, tmp)
        tmp_path = tmp.name

    cmd = [
        "uv",
        "tool",
        "run",
        "openapi-python-client",
        "generate",
        "--path",
        tmp_path,
        "--output-path",
        str(output),
        "--overwrite",
        "--meta",
        "none",
    ]

    print(f"Generating client from {source.name} -> {output}")
    return subprocess.run(cmd).returncode


def main() -> None:
    ensure_generated_dir()
    exit_code = 0
    for client in CLIENTS:
        rc = generate(client["source"], client["output"])
        if rc != 0:
            exit_code = rc
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
