#!/usr/bin/env python3
"""Build the Claude Desktop .mcpb bundle for odoo-mcp.

Thin bundle: the manifest launches `uvx odoo-mcp==<version>` (uv must be
installed), so the archive carries only the manifest. If PATH resolution in
GUI apps proves painful for users, the upgrade path is a fat bundle with
`pip install --target` vendored dependencies and a python entry point.

Usage: python scripts/build_mcpb.py [--version X.Y.Z] [--out dist/]
"""

from __future__ import annotations

import argparse
import json
import re
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def project_version() -> str:
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^version = "([^"]+)"', pyproject, re.MULTILINE)
    if not match:
        raise SystemExit("version not found in pyproject.toml")
    return match.group(1)


def build(version: str, out_dir: Path) -> Path:
    template = (ROOT / "mcpb" / "manifest.template.json").read_text(encoding="utf-8")
    manifest = template.replace("__VERSION__", version)
    json.loads(manifest)  # fail fast on malformed JSON

    out_dir.mkdir(parents=True, exist_ok=True)
    bundle_path = out_dir / f"odoo-mcp-{version}.mcpb"
    with zipfile.ZipFile(bundle_path, "w", zipfile.ZIP_DEFLATED) as bundle:
        bundle.writestr("manifest.json", manifest)
        icon = ROOT / "mcpb" / "icon.png"
        if icon.exists():
            bundle.write(icon, "icon.png")
    return bundle_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", default=None)
    parser.add_argument("--out", default="dist")
    args = parser.parse_args()
    version = args.version or project_version()
    path = build(version, Path(args.out))
    print(path)


if __name__ == "__main__":
    main()
