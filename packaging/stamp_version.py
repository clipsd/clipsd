#!/usr/bin/env python3
"""Write the version from clipshot/__init__.py into every file that needs it.

The only place to change the version is clipshot/__init__.py (__version__).
Usage: python packaging/stamp_version.py [--check]
--check: exit 1 if any file differs (used by tests and CI).
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def version() -> str:
    text = (ROOT / "clipshot" / "__init__.py").read_text(encoding="utf-8")
    return re.search(r'^__version__ = "([^"]+)"', text, re.M).group(1)


def targets(v: str):
    parts = [int(x) for x in re.findall(r"\d+", v)[:3]] + [0]
    tup = ", ".join(str(x) for x in (parts + [0, 0, 0])[:4])
    win = ROOT / "packaging/windows-exe"
    readme, readme_en = ROOT / "packaging/README.txt", ROOT / "packaging/README.en.txt"
    extra = [ROOT / "README.md", ROOT / "README.en.md"]   # the repository front pages
    if not win.is_dir():  # copy made by packaging/stage_windows.py (build.ps1 runs there)
        win, readme, readme_en, extra = ROOT / "packaging", ROOT / "README.txt", ROOT / "README.en.txt", []
    first_line = [(r"^ClipSD \S+:", f"ClipSD {v}:")]
    return [(p, first_line) for p in [readme_en, *extra] if p.exists()] + [
        (win / "version_info.txt",
         [(r"filevers=\([^)]*\)", f"filevers=({tup})"), (r"prodvers=\([^)]*\)", f"prodvers=({tup})"),
          (r"StringStruct\('FileVersion', '[^']*'\)", f"StringStruct('FileVersion', '{v}')"),
          (r"StringStruct\('ProductVersion', '[^']*'\)", f"StringStruct('ProductVersion', '{v}')")]),
        (win / "ClipSD.iss", [(r'#define AppVersion "[^"]*"', f'#define AppVersion "{v}"')]),
        (readme, [(r"^ClipSD \S+:", f"ClipSD {v}:")]),
    ]


def main() -> int:
    check = "--check" in sys.argv
    v = version()
    bad = []
    for path, subs in targets(v):
        raw = path.read_bytes()
        bom = raw.startswith(b"\xef\xbb\xbf")
        text = raw.decode("utf-8-sig")
        new = text
        for pat, rep in subs:
            new = re.sub(pat, rep, new, count=0, flags=re.M)
        if new != text:
            bad.append(path.relative_to(ROOT))
            if not check:
                path.write_bytes((b"\xef\xbb\xbf" if bom else b"") + new.encode("utf-8"))
    if check and bad:
        print("version mismatch:", ", ".join(map(str, bad)))
        return 1
    print(f"ClipSD {v}: " + ("ok" if not bad else "stamped " + ", ".join(map(str, bad))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
