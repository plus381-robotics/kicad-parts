# Plus381 KiCad parts

The team's shared library of symbols, footprints and 3D models, for every
season and every project.

**Don't edit this repo by hand.** Use the **Plus381 Tools** KiCad plugin
from [kicad-plugins](https://github.com/plus381-robotics/kicad-plugins). It
downloads this repo, keeps it up to date in the background, registers the
libraries in KiCad, imports vendor parts, and publishes your changes.

## Layout

```text
symbols/Plus381_<Category>.kicad_symdir/<Part>.kicad_sym   one symbol per file
footprints/Plus381_<Category>.pretty/<Footprint>.kicad_mod  one footprint per file
3dmodels/<model>.step                                      every 3D model, stored once (Git LFS)
categories.json                                            the list of categories
scripts/check_library.py                                   checks run by CI and the plugin
```

* Projects use parts as `Plus381_<Category>:<Part>`. Every computer has the
  same library names, so project files work for everyone.
* Footprints load 3D models from `${PLUS381_PARTS}/3dmodels/…`.
  `PLUS381_PARTS` is a KiCad path variable that the plugin sets to wherever
  this repo is on your computer.
* One file per symbol and per footprint means two people adding parts at the
  same time never conflict.

## Rules

1. Use KiCad's stock libraries for generic parts (0603/0805 R and C,
   SOT-23, standard headers). Only add what KiCad doesn't have.
2. Symbol name = manufacturer part number. Fill in `Datasheet`, `MPN` and
   `Manufacturer`.
3. Every footprint has a 3D model in `3dmodels/`, positioned correctly.
4. Never delete or rename a 3D model. Old boards still point to it.
5. Edits to existing parts are welcome. Existing boards only change when
   someone runs *Update from Library* on them.

## Checks

```sh
python3 scripts/check_library.py            # quick
python3 scripts/check_library.py --kicad    # also loads every library in kicad-cli
```

The *Library check* workflow runs the full check on every push. Missing 3D
models only show as warnings.

## Part previews

When parts are added or changed, the *Part previews* workflow renders the
symbol, footprint and 3D view and posts them as a comment: on the commit for
pushes to `main`, and on the pull request for pull requests (updated on every
push). The pictures are kept on the `previews` branch. To render an older
commit, use **Actions → Part previews → Run workflow** and enter its full commit SHA.
