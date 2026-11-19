"""Кириллические строковые литералы в модулях (кроме docstring): что ещё не переведено на ключи tr().
Запуск: python3 tools/find_cyrillic.py [файлы...]   (по умолчанию clipshot/*.py)"""
import ast
import pathlib
import re
import sys

CY = re.compile("[А-Яа-яЁё]")


def scan(path):
    tree = ast.parse(pathlib.Path(path).read_text(encoding="utf-8"))
    skip = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant):
            skip.add(id(n.value))
    out = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and CY.search(n.value) and id(n) not in skip:
            out.append((n.lineno, n.value))
    return sorted(out)


if __name__ == "__main__":
    files = sys.argv[1:] or sorted(str(p) for p in pathlib.Path("clipshot").glob("*.py"))
    total = 0
    for f in files:
        for line, text in scan(f):
            print(f"{f}:{line}: {text[:100]!r}")
            total += 1
    print(f"итого: {total}")
