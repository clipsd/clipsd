#!/usr/bin/env python3
# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later. Распространяется по лицензии GNU GPL v3 или более поздней,
# без каких-либо гарантий; полный текст: файл LICENSE или <https://www.gnu.org/licenses/gpl-3.0.html>.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""Build checks run by GitHub Actions before a build.

1. Placeholders that must never reach a release: STABLE_PUBLIC_KEYS in clipshot/update_channel.py
   (empty, TODO, not base64 of 32 bytes), addresses on the reserved .invalid domain anywhere in
   clipshot/*.py. (1.x has no error reports and no statistics: nothing else is sent anywhere.) With --strict (runs for tags v*) they fail
   the build; otherwise they are printed as warnings.
2. Packages pinned in both packaging/requirements-build-linux.txt and -windows.txt have the same
   version (always an error).
3. Preview builds never become releases: clipshot/_preview_build.py (packaging/preview_build.py)
   must not exist, and the proba public key (packaging/proba-public-key.txt) must not be listed in
   STABLE_PUBLIC_KEYS or TEST_PUBLIC_KEYS (always an error).
4. Urgency: CHANGELOG/<version>/CRITICAL (written by tools/release.sh --critical) makes the build log
   start with "СРОЧНО (исправление безопасности)" as a GitHub warning, so it is seen before signing.
5. Name and icon (GPLv3 section 7): TRADEMARKS.md and TRADEMARKS.ru.md exist and every source file with the GPL
   header points to them (tools/trademark_notice.py adds the line). Like placeholders: an error with --strict.

Values are read from the source with ast: nothing of the program is imported.
Run: python3 tools/release_check.py [--strict] [project]
"""

import ast
import base64
import binascii
import re
import sys
from pathlib import Path


def module_constants(path: Path) -> dict:
    """Module-level NAME = <literal> assignments of a source file."""
    tree = ast.parse(path.read_text(encoding="utf-8"), str(path))
    found = {}
    for node in tree.body:
        targets = node.targets if isinstance(node, ast.Assign) else [node.target] if isinstance(node, ast.AnnAssign) else []
        for target in targets:
            if isinstance(target, ast.Name) and node.value is not None:
                try:
                    found[target.id] = ast.literal_eval(node.value)
                except ValueError:
                    pass
    return found


def strings_in(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from strings_in(item)
    elif isinstance(value, (list, tuple, set, frozenset)):
        for item in value:
            yield from strings_in(item)


def is_raw_key(text) -> bool:
    try:
        return isinstance(text, str) and len(base64.b64decode(text.strip(), validate=True)) == 32
    except (binascii.Error, ValueError):
        return False


def placeholder_problems(root: Path) -> list:
    problems = []
    channel = module_constants(root / "clipshot" / "update_channel.py")
    keys = channel.get("STABLE_PUBLIC_KEYS")
    if not keys:
        problems.append("clipshot/update_channel.py: STABLE_PUBLIC_KEYS is empty")
    else:
        for key in keys:
            if "TODO" in str(key) or not is_raw_key(key):
                problems.append(f"clipshot/update_channel.py: STABLE_PUBLIC_KEYS has a placeholder {key!r}")
    for path in sorted((root / "clipshot").glob("*.py")):
        for name, value in module_constants(path).items():
            for text in strings_in(value):
                if re.search(r"\.invalid(?=[/:?#]|$)", text):
                    problems.append(f"clipshot/{path.name}: {name} = {text!r} (.invalid address)")
    return problems


def key_bytes(text):
    """Raw 32 bytes of a base64 key, or None. Compared as bytes: one key has several base64 spellings."""
    try:
        raw = base64.b64decode(str(text).strip(), validate=True)
    except (binascii.Error, ValueError):
        return None
    return raw if len(raw) == 32 else None


def preview_problems(root: Path) -> list:
    problems = []
    if (root / "clipshot" / "_preview_build.py").exists():
        problems.append("clipshot/_preview_build.py exists: this tree is a preview build (packaging/preview_build.py)")
    key_file = root / "packaging" / "proba-public-key.txt"
    file_keys = set()
    if key_file.is_file():
        file_keys = {key_bytes(ln) for ln in key_file.read_text(encoding="utf-8").splitlines()
                     if ln.strip() and not ln.lstrip().startswith("#")} - {None}
    channel = module_constants(root / "clipshot" / "update_channel.py")
    embedded = {key_bytes(k) for k in channel.get("PREVIEW_ONLY_KEYS") or ()} - {None}
    for raw in sorted(file_keys - embedded):
        problems.append("packaging/proba-public-key.txt has a key that is not in PREVIEW_ONLY_KEYS of "
                        f"clipshot/update_channel.py ({base64.b64encode(raw).decode()}): stable and test would not refuse it")
    forbidden = file_keys | embedded
    for name in ("STABLE_PUBLIC_KEYS", "TEST_PUBLIC_KEYS"):
        for key in channel.get(name) or ():
            if key_bytes(key) in forbidden:
                problems.append(f"clipshot/update_channel.py: {name} has the proba (preview) key {key!r}")
    return problems


def read_pins(path: Path) -> dict:
    pins = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^([A-Za-z0-9_.\-]+)==([^\s\\;]+)", line)
        if match:
            pins[re.sub(r"[-_.]+", "-", match.group(1)).lower()] = match.group(2)
    return pins


def pin_problems(root: Path) -> list:
    linux = read_pins(root / "packaging" / "requirements-build-linux.txt")
    windows = read_pins(root / "packaging" / "requirements-build-windows.txt")
    return [f"{name}: Linux {linux[name]} != Windows {windows[name]}"
            for name in sorted(set(linux) & set(windows)) if linux[name] != windows[name]]


def trademark_problems(root: Path) -> list:
    """Additional terms on the name and icon: the two files and the notice in every GPL source header."""
    problems = [f"{name} is missing" for name in ("TRADEMARKS.md", "TRADEMARKS.ru.md") if not (root / name).is_file()]
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import trademark_notice
    problems += [f"{rel}: no notice of TRADEMARKS.md (run python3 tools/trademark_notice.py)"
                 for rel in trademark_notice.missing(root)]
    return problems


URGENT_BANNER = "СРОЧНО (исправление безопасности)"


def current_version(root: Path) -> str:
    match = re.search(r'^__version__ = "([^"]+)"', (root / "clipshot" / "__init__.py").read_text(encoding="utf-8"), re.M)
    return match.group(1) if match else ""


def urgent_release(root: Path) -> str:
    """Version of this tree if CHANGELOG/<version>/CRITICAL marks it as an urgent security fix, else ""."""
    version = current_version(root)
    return version if version and (root / "CHANGELOG" / version / "CRITICAL").is_file() else ""


def main(argv) -> int:
    strict = "--strict" in argv
    rest = [a for a in argv if a != "--strict"]
    root = Path(rest[0] if rest else Path(__file__).resolve().parent.parent)
    failed = False
    urgent = urgent_release(root)
    if urgent:
        print(f"::warning title={URGENT_BANNER}::ClipSD {urgent}: {URGENT_BANNER}. Programs offer it at once "
              "and on every start until installed; channel_sign.py build needs --critical.")
        print(f"release_check: {URGENT_BANNER}: ClipSD {urgent}")
    for problem in pin_problems(root):
        print(f"::error::build pins differ: {problem}")
        failed = True
    for problem in preview_problems(root):
        print(f"::error::preview build: {problem}")
        failed = True
    for problem in trademark_problems(root):
        print(f"::{'error' if strict else 'warning'}::name and icon notice: {problem}")
        failed = failed or strict
    for problem in placeholder_problems(root):
        print(f"::{'error' if strict else 'warning'}::release placeholder: {problem}")
        failed = failed or strict
    if failed:
        print("release_check: FAILED")
        return 1
    print("release_check: ok" + ("" if strict else " (placeholders are only warnings outside a v* tag)"))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
