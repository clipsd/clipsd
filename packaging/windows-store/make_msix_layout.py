#!/usr/bin/env python3
# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""Layout of the Microsoft Store package (MSIX) from the built program.

    python packaging/store/make_msix_layout.py --app dist/ClipSD-app --out build/msix [--require-identity]

(in the staged Store folder of `packaging/stage_windows.py --store`; in the repository the script lives in
packaging/windows-store/). Writes:
  OUT/layout/   the package content: ClipSD-app.exe and _internal\\ (PyInstaller), LICENSE, LICENSE.ru.txt,
                THIRD-PARTY-NOTICES.txt, TRADEMARKS.txt, TRADEMARKS.ru.txt, AppxManifest.xml, Assets\\*.png,
                Strings\\<language>\\Resources.resw
  OUT/pri/      the same Assets and Strings only: makepri indexes this folder (build_msix.ps1), not the
                program files (folders like clipshot\\i18n\\ru would be taken for language qualifiers)
The package is then made by build_msix.ps1 (makepri, makeappx, test signature) on Windows.

- Identity: store-identity.json next to this script (values from Partner Center). With the placeholders the
  package is for local tests only; --require-identity refuses them (an upload to Partner Center).
- Version: clipshot/__init__.py + ".0" (Store rule: the fourth part is 0).
- Images: ready PNG files of Assets/ (logo_assets.py --render draws them once, on a computer with fonts, with
  the logo of the program; a build never draws text), at scales 100, 150, 200, 400 (125 is skipped: 44 x 1.25 is
  not a whole pixel, WACK checks the sizes) and the target sizes of the taskbar and Start (16, 24, 32, 48, 256,
  also "unplated" for the taskbar of Windows 10/11). Sizes are checked here, the look by logo_assets.py.
- Strings: the description of the app (key app.store_description) in the 12 languages of the program.
No Qt needed.
"""

import argparse
import json
import os
import re
import shutil
import sys
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent          # the project (repository or staged folder)
TEMPLATE = HERE / "AppxManifest.xml.in"
IDENTITY = HERE / "store-identity.json"
ASSETS = HERE / "Assets"           # ready PNG files of logo_assets.py --render

# Program language -> package language (Store supported codes; pt is Brazilian, zh Simplified). en-US first:
# the default language of resources.pri (build_msix.ps1: makepri /dq en-US).
LANGUAGE_TAGS = {"en": "en-US", "ru": "ru", "bg": "bg", "uk": "uk", "de": "de", "fr": "fr", "es": "es", "it": "it",
                 "pt": "pt-BR", "pl": "pl", "tr": "tr", "zh": "zh-CN"}
DESCRIPTION_KEY = "app.store_description"

SCALES = (100, 150, 200, 400)
# base name -> width, height at scale 100, share of the height taken by the logo
LOGOS = {
    "StoreLogo": (50, 50, 1.0),
    "Square44x44Logo": (44, 44, 1.0),
    "Square150x150Logo": (150, 150, 0.6),
    "Wide310x150Logo": (310, 150, 0.6),
}
TARGET_SIZES = (16, 24, 32, 48, 256)
TARGET_FORMS = ("", "_altform-unplated", "_altform-lightunplated")
MAX_IMAGE_BYTES = 204_800           # WACK: "must be smaller than 204800 bytes"
DOCS = ("LICENSE", "LICENSE.ru.txt", "THIRD-PARTY-NOTICES.txt",   # licences travel with the program, and since 1.32
        "TRADEMARKS.txt", "TRADEMARKS.ru.txt")                       # the terms for the name and the icon (GPLv3 s. 7)
PLACEHOLDER = "Placeholder"


class LayoutError(Exception):
    pass


def app_version(root: Path = ROOT) -> str:
    text = (root / "clipshot" / "__init__.py").read_text(encoding="utf-8")
    return re.search(r'^__version__ = "([^"]+)"', text, re.M).group(1)


def package_version(version: str) -> str:
    """1.31.2 -> 1.31.2.0; each part 0..65535, the first not 0, exactly three parts from the program."""
    parts = version.split(".")
    if len(parts) != 3 or not all(p.isdigit() and int(p) <= 65535 for p in parts) or int(parts[0]) == 0:
        raise LayoutError(f"version {version!r} does not fit an MSIX version (N.N.N, first part not 0)")
    return ".".join(str(int(p)) for p in parts) + ".0"


def read_identity(path: Path = IDENTITY, require: bool = False) -> dict:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    name = str(data.get("name", ""))
    publisher = str(data.get("publisher", ""))
    display = str(data.get("publisher_display_name", ""))
    product = str(data.get("store_product_id", ""))
    if not re.fullmatch(r"[A-Za-z0-9.\-]{3,50}", name):
        raise LayoutError(f"identity name {name!r}: 3-50 letters, digits, '.' or '-' (Partner Center: Package/Identity/Name)")
    if not publisher.startswith("CN=") or len(publisher) > 8192:
        raise LayoutError(f"identity publisher {publisher!r} must start with CN= (Partner Center: Package/Identity/Publisher)")
    if not 1 <= len(display) <= 256 or display != display.strip():
        raise LayoutError("publisher_display_name: 1-256 characters without spaces around")
    if product and not re.fullmatch(r"[0-9A-Z]{12}", product):
        raise LayoutError(f"store_product_id {product!r}: 12 letters and digits (Partner Center: Store ID) or empty")
    placeholder = PLACEHOLDER in name or PLACEHOLDER in publisher
    if placeholder and require:
        raise LayoutError("store-identity.json still has placeholders: copy the values from Partner Center")
    return {"name": name, "publisher": publisher, "publisher_display_name": display,
            "store_product_id": product, "placeholder": placeholder}


def descriptions(root: Path = ROOT) -> dict:
    """Package language -> description of the app, from the catalogs of the program (all 12 must have it)."""
    out = {}
    for lang, tag in LANGUAGE_TAGS.items():
        merged = {}
        for f in sorted((root / "clipshot" / "i18n" / lang).glob("*.json")):
            merged.update(json.loads(f.read_text(encoding="utf-8")))
        text = str(merged.get(DESCRIPTION_KEY, "")).strip()
        if not text or len(text) > 2048:
            raise LayoutError(f"{lang}: {DESCRIPTION_KEY} is missing or longer than 2048 characters")
        out[tag] = text
    return out


def manifest_text(identity: dict, version: str, template: Path = TEMPLATE) -> str:
    text = template.read_text(encoding="utf-8")
    resources = "\n".join(f'    <Resource Language="{tag}" />' for tag in LANGUAGE_TAGS.values())
    values = {
        "@NAME@": identity["name"],
        "@PUBLISHER@": identity["publisher"],
        "@PUBLISHER_DISPLAY_NAME@": identity["publisher_display_name"],
        "@VERSION@": version,
    }
    for key, value in values.items():   # attribute values and element text: &, <, >, " escaped
        text = text.replace(key, escape(value, {'"': "&quot;"}))
    text = text.replace("@RESOURCES@", resources)
    left = re.findall(r"@[A-Z_]+@", text)
    if left:
        raise LayoutError(f"manifest template: unfilled {left}")
    return text


def resw_text(strings: dict) -> str:
    rows = "".join(f'  <data name={quoteattr(k)} xml:space="preserve">\n    <value>{escape(v)}</value>\n  </data>\n'
                   for k, v in strings.items())
    return ('<?xml version="1.0" encoding="utf-8"?>\n<root>\n'
            '  <resheader name="resmimetype">\n    <value>text/microsoft-resx</value>\n  </resheader>\n'
            '  <resheader name="version">\n    <value>2.0</value>\n  </resheader>\n'
            '  <resheader name="reader">\n    <value>System.Resources.ResXResourceReader, System.Windows.Forms, '
            'Version=4.0.0.0, Culture=neutral, PublicKeyToken=b77a5c561934e089</value>\n  </resheader>\n'
            '  <resheader name="writer">\n    <value>System.Resources.ResXResourceWriter, System.Windows.Forms, '
            'Version=4.0.0.0, Culture=neutral, PublicKeyToken=b77a5c561934e089</value>\n  </resheader>\n'
            + rows + "</root>\n")


def image_plan() -> list:
    """(file name, width, height, logo size) of every image of the package."""
    plan = []
    for base, (w, h, share) in LOGOS.items():
        for scale in SCALES:
            sw, sh = w * scale // 100, h * scale // 100
            plan.append((f"{base}.scale-{scale}.png", sw, sh, round(min(sw, sh) * share)))
    for size in TARGET_SIZES:
        for form in TARGET_FORMS:
            plan.append((f"Square44x44Logo.targetsize-{size}{form}.png", size, size, size))
    return plan


def png_size(path: Path) -> tuple:
    """(width, height) from the IHDR chunk of a PNG file (no Qt needed)."""
    head = Path(path).read_bytes()[:24]
    if head[:8] != b"\x89PNG\r\n\x1a\n" or head[12:16] != b"IHDR":
        raise LayoutError(f"{path} is not a PNG file")
    return int.from_bytes(head[16:20], "big"), int.from_bytes(head[20:24], "big")


def copy_images(folder: Path, assets: Path = ASSETS) -> list:
    """Copy the ready images of the package (logo_assets.py --render made them on a computer with fonts; 1.31.2
    drew them during the build on Windows, where Qt found no fonts, and the Store got boxes instead of letters)."""
    folder.mkdir(parents=True, exist_ok=True)
    written = []
    for name, w, h, _logo in image_plan():
        src = assets / name
        if not src.is_file():
            raise LayoutError(f"missing {src}: python3 packaging/windows-store/logo_assets.py --render")
        if png_size(src) != (w, h):
            raise LayoutError(f"{name}: {png_size(src)} instead of {(w, h)}")
        if src.stat().st_size >= MAX_IMAGE_BYTES:
            raise LayoutError(f"{name}: {src.stat().st_size} bytes, the limit is {MAX_IMAGE_BYTES}")
        shutil.copy2(src, folder / name)
        written.append(name)
    return written


def write_strings(folder: Path, texts: dict) -> None:
    for tag, text in texts.items():
        target = folder / tag / "Resources.resw"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(resw_text({"AppDescription": text}), encoding="utf-8")


def make(app: Path, out: Path, docs: Path = ROOT, require_identity: bool = False, identity_file: Path = IDENTITY) -> dict:
    app, out = Path(app).resolve(), Path(out).resolve()
    if not (app / "ClipSD-app.exe").is_file():
        raise LayoutError(f"{app} has no ClipSD-app.exe (build.ps1 -AppOnly first)")
    identity = read_identity(identity_file, require_identity)
    version = package_version(app_version())
    texts = descriptions()
    missing = [d for d in DOCS if not (Path(docs) / d).is_file()]
    if missing:
        raise LayoutError(f"licence files missing in {docs}: {missing} (packaging/stage_windows.py makes them)")
    if out.exists():
        shutil.rmtree(out)
    layout, pri = out / "layout", out / "pri"
    shutil.copytree(app, layout)
    for name in DOCS:
        shutil.copy2(Path(docs) / name, layout / name)
    images = copy_images(pri / "Assets")
    write_strings(pri / "Strings", texts)
    shutil.copytree(pri / "Assets", layout / "Assets")
    shutil.copytree(pri / "Strings", layout / "Strings")
    (layout / "AppxManifest.xml").write_text(manifest_text(identity, version), encoding="utf-8")
    return {"version": version, "identity": identity, "images": images, "languages": list(texts)}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--app", required=True, help="PyInstaller folder with ClipSD-app.exe")
    parser.add_argument("--out", required=True)
    parser.add_argument("--docs", default=str(ROOT), help="folder with LICENSE, LICENSE.ru.txt, THIRD-PARTY-NOTICES.txt")
    parser.add_argument("--require-identity", action="store_true", help="refuse the placeholders (Partner Center upload)")
    args = parser.parse_args(argv)
    try:
        result = make(Path(args.app), Path(args.out), Path(args.docs), args.require_identity)
    except (LayoutError, OSError, ValueError) as exc:
        print(f"make_msix_layout: {exc}", file=sys.stderr)
        return 2
    ident = result["identity"]
    print(f"make_msix_layout: {args.out}: ClipSD {result['version']}, {ident['name']} / {ident['publisher']}, "
          f"{len(result['images'])} images, languages {', '.join(result['languages'])}")
    if ident["placeholder"]:
        print("::warning title=MSIX::store-identity.json has placeholders: the package is for local tests only, "
              "Partner Center will refuse it (copy Name, Publisher, PublisherDisplayName from Product identity)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
