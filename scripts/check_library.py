#!/usr/bin/env python3
"""Check the Plus381 parts library for problems that would break it for
the rest of the team.

    python3 scripts/check_library.py          # report, exit 1 on errors
    python3 scripts/check_library.py --kicad  # also let kicad-cli parse every file

Errors (fail CI): things that break parts for everyone
  - a symbol links to a Plus381 footprint that does not exist
  - a file name does not match the symbol/footprint name inside it
  - a symbol file holds more than one symbol (one symbol per file avoids
    merge conflicts when two people add parts at the same time)
  - a file KiCad cannot read
Warnings (shown, but CI stays green):
  - footprint without a 3D model, 3D model file missing or outside
    ${PLUS381_PARTS}/3dmodels/, 3D model no footprint uses,
    symbol without footprint/datasheet/MPN
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VAR = "PLUS381_PARTS"
MODEL_PREFIX = "${%s}/3dmodels/" % VAR


def top_level_blocks(text, keyword):
    """Yield (start, end, name) for `(keyword "name" ...)` directly under the root list."""
    depth = 0
    i = 0
    n = len(text)
    head = re.compile(r'\(\s*' + keyword + r'\s+"((?:[^"\\]|\\.)*)"')
    while i < n:
        c = text[i]
        if c == '"':
            i += 1
            while i < n and text[i] != '"':
                i += 2 if text[i] == "\\" else 1
        elif c == "(":
            depth += 1
            if depth == 2:
                m = head.match(text, i)
                if m:
                    end = block_end(text, i)
                    yield i, end, m.group(1)
                    i = end
                    depth -= 1
                    continue
        elif c == ")":
            depth -= 1
        i += 1


def block_end(text, start):
    depth = 0
    i = start
    while i < len(text):
        c = text[i]
        if c == '"':
            i += 1
            while text[i] != '"':
                i += 2 if text[i] == "\\" else 1
        elif c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    raise ValueError("unbalanced parentheses")


def prop(block, name):
    m = re.search(r'\(property\s+"' + re.escape(name) + r'"\s+"((?:[^"\\]|\\.)*)"', block)
    return m.group(1) if m else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--kicad", action="store_true", help="also parse every library with kicad-cli")
    ap.add_argument("--fix", action="store_true",
                    help="create missing category folders (with a .gitkeep so Git keeps them while empty)")
    args = ap.parse_args()

    data = json.loads((ROOT / "categories.json").read_text())
    prefix = data["prefix"]
    errors, warnings = [], []

    # Every category has its symbol and footprint folder from the start, so
    # it is registered in KiCad at Setup (no restart when its first part
    # arrives). Git can't store empty folders, hence the .gitkeep files.
    for cat in data["categories"]:
        for folder in (ROOT / "symbols" / f"{prefix}{cat}.kicad_symdir", ROOT / "footprints" / f"{prefix}{cat}.pretty"):
            if args.fix:
                folder.mkdir(parents=True, exist_ok=True)
                if not any(folder.iterdir()):
                    (folder / ".gitkeep").touch()
            if not folder.is_dir():
                errors.append(f"category {cat}: folder {folder.relative_to(ROOT)} is missing "
                              "(run: python3 scripts/check_library.py --fix)")
    footprints = set()
    used_models = set()

    for lib in sorted((ROOT / "footprints").glob("*.pretty")):
        nick = lib.stem
        if not nick.startswith(prefix):
            errors.append(f"footprints/{lib.name}: library name must start with {prefix}")
        for f in sorted(lib.glob("*.kicad_mod")):
            text = f.read_text(encoding="utf-8")
            footprints.add(f"{nick}:{f.stem}")
            m = re.match(r'\s*\(footprint\s+"((?:[^"\\]|\\.)*)"', text)
            if not m:
                errors.append(f"{f.relative_to(ROOT)}: not a KiCad footprint")
                continue
            if m.group(1) != f.stem:
                errors.append(f"{f.relative_to(ROOT)}: footprint is named '{m.group(1)}' inside the file")
            models = re.findall(r'\(model\s+"((?:[^"\\]|\\.)*)"', text)
            if not models:
                warnings.append(f"{nick}:{f.stem} has no 3D model")
            for path in models:
                if path.startswith("${KICAD") and "3DMODEL_DIR}" in path:
                    continue  # stock KiCad model
                if not path.startswith(MODEL_PREFIX):
                    warnings.append(f"{nick}:{f.stem}: 3D model path should start with {MODEL_PREFIX} (is {path})")
                    continue
                name = path[len(MODEL_PREFIX):]
                used_models.add(name)
                if not (ROOT / "3dmodels" / name).is_file():
                    warnings.append(f"{nick}:{f.stem}: 3D model 3dmodels/{name} is not in the repository")

    for lib in sorted((ROOT / "symbols").glob("*.kicad_symdir")):
        nick = lib.stem
        if not nick.startswith(prefix):
            errors.append(f"symbols/{lib.name}: library name must start with {prefix}")
        for f in sorted(lib.glob("*.kicad_sym")):
            text = f.read_text(encoding="utf-8")
            syms = list(top_level_blocks(text, "symbol"))
            roots = [b for b in syms if not re.match(r'\(symbol\s+"(?:[^"\\]|\\.)*"\s*\(extends\s', text[b[0]:b[1]])]
            if not syms:
                errors.append(f"{f.relative_to(ROOT)}: no symbol in file")
                continue
            if len(roots) > 1:
                errors.append(f"{f.relative_to(ROOT)}: {len(roots)} symbols in one file (one per file)")
            s, e, name = syms[0]
            if name != f.stem:
                errors.append(f"{f.relative_to(ROOT)}: symbol is named '{name}' inside the file")
            block = text[s:e]
            fp = prop(block, "Footprint") or ""
            if not fp:
                warnings.append(f"{nick}:{name} has no footprint")
            elif fp.startswith(prefix) and fp not in footprints:
                errors.append(f"{nick}:{name} links to missing footprint {fp}")
            if not prop(block, "Datasheet") or prop(block, "Datasheet") == "~":
                warnings.append(f"{nick}:{name} has no datasheet link")
            if not (prop(block, "MPN") or prop(block, "Manufacturer Part Number")):
                warnings.append(f"{nick}:{name} has no MPN field")

    models_dir = ROOT / "3dmodels"
    for p in sorted(models_dir.iterdir()) if models_dir.is_dir() else []:
        if p.is_file() and p.name != ".gitkeep" and p.name not in used_models:
            warnings.append(f"3dmodels/{p.name} is not used by any footprint")
        if p.is_file() and p.stat().st_size < 200 and p.read_bytes().startswith(b"version https://git-lfs"):
            errors.append(f"3dmodels/{p.name} is a Git LFS pointer; run 'git lfs pull' (or LFS is not installed)")

    if args.kicad:
        errors += kicad_parse()

    gh = os.environ.get("GITHUB_ACTIONS") == "true"  # also annotate the run summary
    for w in warnings:
        print(("::warning::" if gh else "warning: ") + w)
    for e in errors:
        print(("::error::" if gh else "ERROR: ") + e)
    print(f"\n{len(footprints)} footprints, {len(used_models)} 3D models: "
          f"{len(errors)} errors, {len(warnings)} warnings")
    return 1 if errors else 0


def kicad_parse():
    """Let KiCad itself load every library, to catch files it cannot read."""
    cli = shutil.which("kicad-cli")
    if not cli:
        return ["--kicad given but kicad-cli is not installed"]
    errors = []
    with tempfile.TemporaryDirectory() as tmp:
        for lib in sorted((ROOT / "footprints").glob("*.pretty")):
            r = subprocess.run([cli, "fp", "export", "svg", str(lib), "-o", tmp], capture_output=True, text=True)
            if r.returncode != 0:
                errors.append(f"kicad-cli cannot read footprints/{lib.name}: {(r.stderr or r.stdout).strip()[-300:]}")
        for lib in sorted((ROOT / "symbols").glob("*.kicad_symdir")):
            r = subprocess.run([cli, "sym", "export", "svg", str(lib), "-o", tmp], capture_output=True, text=True)
            if r.returncode != 0:
                errors.append(f"kicad-cli cannot read symbols/{lib.name}: {(r.stderr or r.stdout).strip()[-300:]}")
    return errors


if __name__ == "__main__":
    sys.exit(main())
