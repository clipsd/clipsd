#!/usr/bin/env python3
# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""Images of the Microsoft Store package: made once on a computer with fonts, kept in the repository, checked.

Why: ClipSD 1.31.2 in the Store had empty boxes instead of "Clip" and "SD" on every tile and taskbar icon. The
images were drawn during the cloud build on Windows with Qt's "offscreen" platform, which finds no fonts there.
Now nothing is drawn during a build: make_msix_layout.py copies the ready PNG files of Assets/, and the build
fails when the tile does not look like the logo of ClipSD.

    python3 packaging/windows-store/logo_assets.py --render     draw Assets/*.png and listing/ClipSD-tile-300.png
                                                                (Linux with the font of the logo; refuses when the
                                                                font has no letters or the result is not the logo)
    python packaging/store/logo_assets.py --check-folder DIR    check the tile in a folder of images
    python packaging/store/logo_assets.py --check-msix FILE     check the tile inside a built .msix (CI)

The check: the logo part of Square150x150Logo.scale-100.png (the area with "Clip" and "SD") against
reference/icon-512.png, the logo of the program and the website, scaled to the same size; mean colour difference
per pixel. The good tile: about 13; the 1.31.2 tile with boxes: about 37 (reference/broken-1.31.2-*.png).
"""

import argparse
import os
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
ASSETS = HERE / "Assets"
LISTING = HERE / "listing"
REFERENCE = HERE / "reference" / "icon-512.png"
BROKEN_SAMPLE = HERE / "reference" / "broken-1.31.2-Square150x150Logo.scale-100.png"
TILE = "Square150x150Logo.scale-100.png"
TILE_SHARE = 0.6                       # share of the tile height taken by the logo (make_msix_layout.LOGOS)
LETTERS = (0.22, 0.25, 0.78, 0.80)     # left, top, right, bottom of the lettering inside the logo
THRESHOLD = 22.0                       # mean difference above it: not the logo (boxes, another picture)
LISTING_TILE = "ClipSD-tile-300.png"   # Partner Center, Store listing: 1:1 app tile icon 300 x 300


_app = None


def _qt():
    """A Qt application for images and fonts; kept in _app, else Python frees it at once."""
    global _app
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtGui import QGuiApplication
    _app = QGuiApplication.instance() or _app or QGuiApplication([])
    return _app


def difference(tile, reference=REFERENCE) -> float:
    """Mean colour difference (0-255) of the lettering of a tile (QImage or path or PNG bytes) and the logo."""
    _qt()
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QImage
    if isinstance(tile, (bytes, bytearray)):
        image = QImage()
        image.loadFromData(bytes(tile), "PNG")
    elif isinstance(tile, QImage):
        image = tile
    else:
        image = QImage(str(tile))
    if image.isNull():
        raise ValueError("the tile image cannot be read")
    image = image.convertToFormat(QImage.Format.Format_ARGB32)
    logo = round(min(image.width(), image.height()) * TILE_SHARE)
    crop = image.copy((image.width() - logo) // 2, (image.height() - logo) // 2, logo, logo)
    ref = QImage(str(reference)).convertToFormat(QImage.Format.Format_ARGB32).scaled(
        logo, logo, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
    left, top, right, bottom = (round(v * logo) for v in LETTERS)
    total = count = 0
    for y in range(top, bottom):
        for x in range(left, right):
            a, b = crop.pixelColor(x, y), ref.pixelColor(x, y)
            total += (abs(a.red() - b.red()) + abs(a.green() - b.green()) + abs(a.blue() - b.blue())) / 3
            count += 1
    return total / count


def check_folder(folder: Path) -> float:
    return difference(Path(folder) / TILE)


def check_msix(path: Path) -> float:
    with zipfile.ZipFile(path) as z:
        return difference(z.read(f"Assets/{TILE}"))


def render(assets: Path = ASSETS, listing: Path = LISTING) -> list:
    """Draw every image of make_msix_layout.image_plan() with the logo of the program (clipshot.icons)."""
    _qt()
    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(HERE))
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QFont, QFontMetrics, QImage, QPainter
    from clipshot import icons
    import make_msix_layout as ml
    font = QFont("Sans")
    font.setBold(True)
    missing = [c for c in "ClipSD" if not QFontMetrics(font).inFontUcs4(ord(c))]
    if missing:
        raise SystemExit(f"logo_assets: the font of the logo has no letters {missing}: draw on a computer with fonts")
    assets.mkdir(parents=True, exist_ok=True)
    written = []
    for name, w, h, logo in ml.image_plan():
        image = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(Qt.GlobalColor.transparent)
        p = QPainter(image)
        p.drawPixmap((w - logo) // 2, (h - logo) // 2, icons.logo_pixmap(logo))
        p.end()
        if not image.save(str(assets / name), "PNG"):
            raise SystemExit(f"logo_assets: cannot write {assets / name}")
        written.append(name)
    diff = check_folder(assets)
    if diff > THRESHOLD:
        raise SystemExit(f"logo_assets: {TILE} is not the logo (difference {diff:.1f} > {THRESHOLD})")
    listing.mkdir(parents=True, exist_ok=True)
    tile = icons.logo_pixmap(300).toImage()
    if not tile.save(str(listing / LISTING_TILE), "PNG"):
        raise SystemExit(f"logo_assets: cannot write {listing / LISTING_TILE}")
    print(f"logo_assets: {len(written)} images in {assets}, {LISTING_TILE} in {listing}, difference {diff:.1f}")
    return written


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--render", action="store_true")
    group.add_argument("--check-folder", metavar="DIR")
    group.add_argument("--check-msix", metavar="FILE")
    args = parser.parse_args(argv)
    if args.render:
        render()
        return 0
    try:
        diff = check_msix(Path(args.check_msix)) if args.check_msix else check_folder(Path(args.check_folder))
    except (OSError, KeyError, ValueError) as exc:
        print(f"logo_assets: {exc}", file=sys.stderr)
        return 2
    ok = diff <= THRESHOLD
    print(f"logo_assets: {TILE}: difference from the logo {diff:.1f} (limit {THRESHOLD}): {'ok' if ok else 'NOT THE LOGO'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
