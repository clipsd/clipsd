#!/usr/bin/env python3
# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""Notice of the additional terms (GPLv3 section 7, file TRADEMARKS.md) in the header of every source file.

GPLv3 section 7: whoever adds terms "must place, in the relevant source files, a statement of the additional
terms that apply to those files, or a notice indicating where to find the applicable terms". Every ClipSD file
whose header says SPDX-License-Identifier: GPL-3.0-or-later (or "Sergey Dayneko, GPL-3.0-or-later", as in
ClipSD.iss) gets one line right after its licence sentence, in the comment style of the file:

    # Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.

    python3 tools/trademark_notice.py           add the line where it is missing (run after adding a new file)
    python3 tools/trademark_notice.py --check   list the files without it, exit 1 (tools/release_check.py too)
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NOTICE = "Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md."
SPDX = "SPDX-License-Identifier: GPL-3.0-or-later"
FOLDERS = ("clipshot", "tools", "tests", "packaging")
SKIP = ("packaging/licenses/",)        # texts of other projects
HEAD_LINES = 20                        # the licence header is at the top of a file


def candidates(root: Path):
    files = [root / "install.sh"] if (root / "install.sh").is_file() else []
    for folder in FOLDERS:
        files += [p for p in sorted((root / folder).rglob("*")) if p.is_file() and "__pycache__" not in p.parts]
    for p in files:
        rel = p.relative_to(root).as_posix()
        if rel.startswith(SKIP):
            continue
        try:
            head = p.read_text(encoding="utf-8-sig").splitlines()[:HEAD_LINES]
        except (UnicodeDecodeError, OSError):
            continue
        for n, line in enumerate(head):
            ours = SPDX in line or ("GPL-3.0-or-later" in line and "Sergey Dayneko" in line)
            if ours and line.lstrip()[:2] in ("# ", "//", "/*", "* ", "<!", "; "):
                yield p, rel, n
                break


def has_notice(path: Path) -> bool:
    return "TRADEMARKS.md" in "\n".join(path.read_text(encoding="utf-8-sig").splitlines()[:HEAD_LINES + 2])


def notice_line(spdx_line: str) -> str:
    stripped = spdx_line.lstrip()
    indent = spdx_line[:len(spdx_line) - len(stripped)]
    if stripped.startswith("<!--"):
        return f"{indent}<!-- {NOTICE} -->"
    if stripped.startswith(";"):
        return f"{indent}; {NOTICE}"
    if stripped.startswith("//"):
        return f"{indent}// {NOTICE}"
    if stripped.startswith("/*"):
        return f"{indent} * {NOTICE}"
    if stripped.startswith("*"):
        return f"{indent}* {NOTICE}"
    return f"{indent}# {NOTICE}"


def add(path: Path, n: int):
    raw = path.read_bytes()
    bom = raw.startswith(b"\xef\xbb\xbf")
    text = raw.decode("utf-8-sig")
    eol = "\r\n" if "\r\n" in text else "\n"
    lines = text.split(eol)
    at = n
    while lines[at].rstrip().endswith(",") and at + 1 < len(lines):   # the licence sentence goes on
        at += 1
    lines.insert(at + 1, notice_line(lines[n]))
    path.write_bytes((b"\xef\xbb\xbf" if bom else b"") + eol.join(lines).encode("utf-8"))


def missing(root: Path = ROOT) -> list:
    return [rel for p, rel, n in candidates(root) if not has_notice(p)]


def main(argv) -> int:
    if "--check" in argv:
        bad = missing()
        for rel in bad:
            print(f"trademark_notice: no notice of TRADEMARKS.md in {rel}")
        return 1 if bad else 0
    done = 0
    for p, rel, n in candidates(ROOT):
        if not has_notice(p):
            add(p, n)
            done += 1
            print(f"trademark_notice: {rel}")
    print(f"trademark_notice: added to {done} files")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
