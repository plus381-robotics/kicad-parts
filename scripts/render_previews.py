#!/usr/bin/env python3
"""Render pictures of the parts changed between two commits: schematic
symbol, footprint and 3D view, plus a Markdown table showing them.

    python3 scripts/render_previews.py --repo . --base <sha> --head <sha> \
        --out previews/ --url-prefix https://raw.githubusercontent.com/<repo>/previews/<dir>/

Used by .github/workflows/previews.yml. Needs kicad-cli and rsvg-convert.
Only reads library files; nothing from the repository is executed.
"""

import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_library import block_end, prop, top_level_blocks  # noqa: E402

VAR = "${PLUS381_PARTS}"
SIZE = 360
CAT_RE = re.compile(r"^(symbols/(.+)\.kicad_symdir/(.+)\.kicad_sym|footprints/(.+)\.pretty/(.+)\.kicad_mod)$")


def run(*cmd, env=None):
    r = subprocess.run([str(c) for c in cmd], capture_output=True, text=True, env=env)
    if r.returncode != 0:
        print("   ", " ".join(str(c) for c in cmd[:4]), "failed:", (r.stderr or r.stdout).strip()[-300:])
    return r.returncode == 0


def changed_parts(repo, base, head):
    """{(kind, lib, name): status} for symbols/footprints changed in base..head."""
    out = subprocess.run(["git", "-C", repo, "diff", "--name-status", "--no-renames", f"{base}..{head}"],
                         capture_output=True, text=True, check=True).stdout
    parts = {}
    for line in out.splitlines():
        status, _, path = line.partition("\t")
        m = CAT_RE.match(path)
        if not m:
            continue
        if m.group(2):
            parts[("sym", m.group(2), m.group(3))] = status[0]
        else:
            parts[("fp", m.group(4), m.group(5))] = status[0]
    return parts


def pad_svg(svg, frac=0.08):
    """Widen the drawing's viewBox a little so it doesn't touch the edges."""
    text = Path(svg).read_text(encoding="utf-8")
    m = re.search(r'viewBox="([-\d.e]+)[ ,]+([-\d.e]+)[ ,]+([-\d.e]+)[ ,]+([-\d.e]+)"', text)
    if m:
        x, y, w, h = (float(v) for v in m.groups())
        d = frac * max(w, h)
        text = text.replace(m.group(0), f'viewBox="{x - d} {y - d} {w + 2 * d} {h + 2 * d}"', 1)
        Path(svg).write_text(text, encoding="utf-8")


def svg_to_png(svg, png):
    pad_svg(svg)
    return run("rsvg-convert", "--background-color=white", "-w", SIZE, "-h", SIZE, "--keep-aspect-ratio",
               "-o", png, svg)


def render_symbol(repo, lib, name, out):
    tmp = Path(tempfile.mkdtemp())
    if run("kicad-cli", "sym", "export", "svg", Path(repo) / "symbols" / f"{lib}.kicad_symdir" / f"{name}.kicad_sym",
           "--symbol", name, "-o", tmp):
        svgs = sorted(tmp.glob("*.svg"))
        if svgs and svg_to_png(svgs[0], out):
            return True
    return False


def render_footprint(repo, lib, name, out):
    """Pads, silkscreen and courtyard, without the REF**/value texts."""
    tmp = Path(tempfile.mkdtemp())
    text = (Path(repo) / "footprints" / f"{lib}.pretty" / f"{name}.kicad_mod").read_text(encoding="utf-8")
    text = re.sub(r'(\(property\s+"(?:Reference|Value)"\s+"(?:[^"\\]|\\.)*")', r'\1 (hide yes)', text)
    lib_dir = tmp / "lib.pretty"
    lib_dir.mkdir()
    (lib_dir / f"{name}.kicad_mod").write_text(text, encoding="utf-8")
    (tmp / "svg").mkdir()
    if run("kicad-cli", "fp", "export", "svg", lib_dir, "--footprint", name,
           "--layers", "F.Cu,B.Cu,F.SilkS,F.CrtYd,Edge.Cuts", "-o", tmp / "svg"):
        svgs = sorted((tmp / "svg").glob("*.svg"))
        if svgs and svg_to_png(svgs[0], out):
            return True
    return False


def bbox(text):
    xs, ys = [], []
    for m in re.finditer(r'\((?:start|end|center|mid|xy)\s+([-\d.]+)\s+([-\d.]+)\)', text):
        xs.append(float(m.group(1)))
        ys.append(float(m.group(2)))
    for m in re.finditer(r'\(pad\s', text):
        b = text[m.start():block_end(text, m.start())]
        at = re.search(r'\(at\s+([-\d.]+)\s+([-\d.]+)', b)
        size = re.search(r'\(size\s+([-\d.]+)\s+([-\d.]+)\)', b)
        if at:
            r = max(float(size.group(1)), float(size.group(2))) / 2 if size else 0
            xs += [float(at.group(1)) - r, float(at.group(1)) + r]
            ys += [float(at.group(2)) - r, float(at.group(2)) + r]
    return (min(xs), min(ys), max(xs), max(ys)) if xs else (-2.5, -2.5, 2.5, 2.5)


def render_3d(repo, lib, name, out, cfg_home):
    """Same idea as the plugin's preview: a tiny board holding only the part."""
    text = (Path(repo) / "footprints" / f"{lib}.pretty" / f"{name}.kicad_mod").read_text(encoding="utf-8")
    if "(model " not in text:
        return False
    text = text.replace(VAR, str(Path(repo).resolve().as_posix())).strip()
    text = re.sub(r'(\(property\s+"(?:Reference|Value)"\s+"(?:[^"\\]|\\.)*")', r'\1 (hide yes)', text)
    body = text[text.index("\n") + 1:text.rfind(")")]
    x0, y0, x1, y1 = bbox(text)
    margin = max(1.0, 0.15 * max(x1 - x0, y1 - y0))
    board = Path(tempfile.mkdtemp()) / "p.kicad_pcb"
    board.write_text(
        '(kicad_pcb (version 20260206) (generator "plus381_preview") (generator_version "10.0")\n'
        ' (general (thickness 1.6)) (paper "A4")\n'
        ' (layers (0 "F.Cu" signal) (2 "B.Cu" signal) (1 "F.Mask" user) (3 "B.Mask" user)'
        ' (5 "F.SilkS" user) (7 "B.SilkS" user) (13 "F.Paste" user) (15 "B.Paste" user)'
        ' (25 "Edge.Cuts" user) (31 "F.CrtYd" user) (35 "F.Fab" user))\n'
        f' (footprint "preview:part" (layer "F.Cu") (at 100 100)\n{body})\n'
        f' (gr_rect (start {100 + x0 - margin:.3f} {100 + y0 - margin:.3f}) (end {100 + x1 + margin:.3f} '
        f'{100 + y1 + margin:.3f}) (stroke (width 0.05) (type solid)) (fill no) (layer "Edge.Cuts"))\n)\n',
        encoding="utf-8")
    env = dict(__import__("os").environ, KICAD_CONFIG_HOME=str(cfg_home))
    return run("kicad-cli", "pcb", "render", board, "-o", out, "-w", SIZE, "-h", SIZE, "--side", "top",
               "--rotate", "-45,0,45", "--zoom", "0.8", "--background", "opaque", "--quality", "high", env=env)


def render_config(base):
    """Private KiCad settings that show every kind of 3D model."""
    d = Path(base) / "10.0"
    d.mkdir(parents=True, exist_ok=True)
    render = {k: True for k in ("show_footprints_normal", "show_footprints_insert", "show_footprints_virtual",
                                "show_footprints_not_in_posfile", "show_footprints_dnp", "show_board_body")}
    render.update(show_fp_references=False, show_fp_values=False, show_fp_text=False)
    (d / "3d_viewer.json").write_text(json.dumps({"render": render}))
    return base


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=".")
    ap.add_argument("--base", required=True)
    ap.add_argument("--head", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--url-prefix", required=True, help="where out/ will be served from, ending in /")
    args = ap.parse_args()
    repo, out = args.repo, Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    cfg = render_config(tempfile.mkdtemp())

    changed = changed_parts(repo, args.base, args.head)
    # One row per part: a symbol together with the footprint it links to,
    # plus rows for footprints that changed on their own.
    rows = []
    covered = set()
    for (kind, lib, name), status in sorted(changed.items()):
        if kind != "sym":
            continue
        row = {"title": f"{lib}:{name}", "status": status, "sym": (lib, name), "fp": None, "fields": {}}
        f = Path(repo) / "symbols" / f"{lib}.kicad_symdir" / f"{name}.kicad_sym"
        if status != "D" and f.exists():
            text = f.read_text(encoding="utf-8")
            blocks = list(top_level_blocks(text, "symbol"))
            if blocks:
                block = text[blocks[0][0]:blocks[0][1]]
                for field in ("Footprint", "MPN", "Manufacturer", "Datasheet", "LCSC Part", "Description"):
                    v = prop(block, field)
                    if v and v != "~":
                        row["fields"][field] = v
                fp = row["fields"].get("Footprint", "")
                if ":" in fp:
                    flib, fname = fp.split(":", 1)
                    if (Path(repo) / "footprints" / f"{flib}.pretty" / f"{fname}.kicad_mod").exists():
                        row["fp"] = (flib, fname)
                        covered.add(("fp", flib, fname))
        rows.append(row)
    for (kind, lib, name), status in sorted(changed.items()):
        if kind == "fp" and ("fp", lib, name) not in covered:
            rows.append({"title": f"{lib}:{name} (footprint)", "status": status, "sym": None, "fp": (lib, name),
                         "fields": {}})

    words = {"A": "new", "M": "changed", "D": "deleted"}
    md = []
    for i, row in enumerate(rows):
        print("rendering", row["title"])
        cells = []
        if row["status"] == "D":
            md.append(f"### {row['title']} (deleted)\n")
            continue
        if row["sym"]:
            png = out / f"{i}-symbol.png"
            cells.append(f'<img src="{args.url_prefix}{png.name}" width="240" alt="symbol">'
                         if render_symbol(repo, *row["sym"], png) else "(symbol not rendered)")
        else:
            cells.append("")
        if row["fp"]:
            png = out / f"{i}-footprint.png"
            cells.append(f'<img src="{args.url_prefix}{png.name}" width="240" alt="footprint">'
                         if render_footprint(repo, *row["fp"], png) else "(footprint not rendered)")
            png = out / f"{i}-3d.png"
            cells.append(f'<img src="{args.url_prefix}{png.name}" width="240" alt="3D">'
                         if render_3d(repo, *row["fp"], png, cfg) else "**no 3D model**")
        else:
            cells += ["", ""]
        md.append(f"### {row['title']} ({words.get(row['status'], 'changed')})")
        details = [f"**{k}:** {v if not v.startswith('http') else f'[link]({v})'}"
                   for k, v in row["fields"].items()]
        if details:
            md.append(" · ".join(details))
        md.append("\n| Symbol | Footprint | 3D |\n|:-:|:-:|:-:|\n| " + " | ".join(cells) + " |\n")
    (out / "comment.md").write_text("\n".join(md) if md else "", encoding="utf-8")
    print(f"{len(rows)} part(s) rendered")


if __name__ == "__main__":
    main()
