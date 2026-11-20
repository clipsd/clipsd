# ClipSD. Copyright (C) 2026 Sergey Dayneko. SPDX-License-Identifier: GPL-3.0-or-later
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""tools/release.sh in a temporary copy of the project: checks, --dry-run, commit, tag, no push.

The copy is a fresh git repository (no remote), so a push would fail loudly; the real repository is not touched.
CLIPSD_TEST_CMD replaces the full test run (this test is itself part of it)."""
import tmpclean  # noqa: F401  (временные папки этого теста убираются при его выходе)
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix="clipsd-release-"))
LANGS = "ru en".split()
failures = []


def check(name, ok):
    print(("ok  " if ok else "FAIL"), name, flush=True)
    if not ok:
        failures.append(name)


def git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True).stdout.strip()


def make_repo(name):
    repo = TMP / name
    shutil.copytree(ROOT, repo, ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc"))
    # The scenarios below work as if 1.31.0 was the last release and 1.31.1 is the next one: the copy is pinned
    # to that state, so the test keeps passing in the tree where 1.31.1 itself is being prepared.
    shutil.rmtree(repo / "CHANGELOG" / "1.31.1", ignore_errors=True)
    init = repo / "clipshot" / "__init__.py"
    init.write_text(re.sub(r'^__version__ = ".*"', '__version__ = "1.31.0"', init.read_text(encoding="utf-8"), flags=re.M), encoding="utf-8")
    for cmd in (["init", "-q"], ["config", "user.name", "Test"], ["config", "user.email", "t@example.invalid"],
                ["add", "-A"], ["commit", "-q", "-m", "base"]):
        git(repo, *cmd)
    return repo


def changelog(repo, version, langs=LANGS):
    folder = repo / "CHANGELOG" / version
    folder.mkdir(parents=True, exist_ok=True)
    for lang in langs:
        (folder / f"{lang}.md").write_text(f"- {lang} {version}\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", f"changelog {version}")


def run(repo, *args, tests="true"):
    env = dict(os.environ, CLIPSD_TEST_CMD=tests, CLIPSD_PYTHON=sys.executable)
    env.pop("QT_QPA_PLATFORM", None)
    return subprocess.run(["bash", "tools/release.sh", *args], cwd=repo, capture_output=True, text=True, env=env)


def version_of(repo):
    for line in (repo / "clipshot" / "__init__.py").read_text(encoding="utf-8").splitlines():
        if line.startswith("__version__"):
            return line.split('"')[1]


repo = make_repo("main")
base = git(repo, "rev-parse", "HEAD")
current = version_of(repo)

r = run(repo, "1.31.1")
check("нет CHANGELOG новой версии: выпуск отказан", r.returncode != 0 and "CHANGELOG/1.31.1" in r.stderr)
changelog(repo, "1.31.1", LANGS[:-1])
r = run(repo, "1.31.1")
check("нет английского (запасной язык канала): выпуск отказан и назван файл", r.returncode != 0 and "en.md" in r.stderr)
changelog(repo, "1.31.1")

(repo / "dirty.txt").write_text("x")
r = run(repo, "1.31.1")
check("дерево не чистое: выпуск отказан", r.returncode != 0 and "not clean" in r.stderr)
(repo / "dirty.txt").unlink()

r = run(repo, current, "--dry-run")
check("версия, уже записанная в исходниках (первый выпуск 1.30.0): проверки проходят, будет только тег",
      r.returncode == 0 and "dry run ok" in r.stdout)
r = run(repo, "1.9.9")
check("версия меньше текущей: отказ", r.returncode != 0 and "lower than the current" in r.stderr)
r = run(repo, "1.31")
check("неверный формат версии: отказ", r.returncode != 0)

r = run(repo, "1.31.1", tests="false")
check("тесты упали: выпуск отказан, ничего не изменено",
      r.returncode != 0 and version_of(repo) == current and not git(repo, "tag"))

head = git(repo, "rev-parse", "HEAD")
r = run(repo, "1.31.1", "--dry-run")
check("--dry-run проходит", r.returncode == 0 and "dry run ok" in r.stdout)
check("--dry-run ничего не меняет: версия, коммит, тег, дерево",
      version_of(repo) == current and git(repo, "rev-parse", "HEAD") == head and not git(repo, "tag")
      and not git(repo, "status", "--porcelain"))

r = run(repo, "1.31.1")
check("выпуск проходит", r.returncode == 0)
check("версия записана в __init__.py", version_of(repo) == "1.31.1")
check("коммит «выпуск 1.31.1»", git(repo, "log", "-1", "--format=%s") == "выпуск 1.31.1")
check("тег v1.31.1 на этом коммите", git(repo, "rev-parse", "v1.31.1^{commit}") == git(repo, "rev-parse", "HEAD"))
check("остальные файлы версии согласованы (stamp_version --check)",
      subprocess.run([sys.executable, "packaging/stamp_version.py", "--check"], cwd=repo,
                     capture_output=True).returncode == 0)
check("дерево чистое после выпуска", not git(repo, "status", "--porcelain"))
check("push не выполнен, команда напечатана",
      "git push origin" in r.stdout and "v1.31.1" in r.stdout and "nothing was pushed" in r.stdout and not git(repo, "remote"))
r = run(repo, "1.31.1")
check("повторный выпуск той же версии: отказ", r.returncode != 0)
changelog(repo, "1.31.2")
r = run(repo, "1.31.2")
check("следующий выпуск 1.31.2 проходит", r.returncode == 0 and version_of(repo) == "1.31.2")

# urgent security fix: --critical writes the marker, the commit says so; a marker without the option is refused
changelog(repo, "1.31.3")
(repo / "CHANGELOG" / "1.31.3" / "CRITICAL").write_text("x\n", encoding="utf-8")
git(repo, "add", "-A")
git(repo, "commit", "-q", "-m", "marker")
r = run(repo, "1.31.3")
check("метка CRITICAL без --critical: выпуск отказан", r.returncode != 0 and "--critical" in r.stderr and version_of(repo) == "1.31.2")
r = run(repo, "1.31.3", "--critical", "--dry-run")
check("--critical --dry-run: пометка СРОЧНО видна, ничего не изменено",
      r.returncode == 0 and "СРОЧНО (исправление безопасности)" in r.stdout and version_of(repo) == "1.31.2")
r = run(repo, "1.31.3", "--critical")
check("выпуск --critical проходит, коммит с пометкой СРОЧНО",
      r.returncode == 0 and git(repo, "log", "-1", "--format=%s") == "выпуск 1.31.3: СРОЧНО (исправление безопасности)"
      and "СРОЧНО (исправление безопасности)" in r.stdout)
changelog(repo, "1.31.4")
r = run(repo, "1.31.4", "--critical")
check("--critical без заготовленной метки: метка CHANGELOG/1.31.4/CRITICAL записана и в коммите",
      r.returncode == 0 and (repo / "CHANGELOG" / "1.31.4" / "CRITICAL").is_file()
      and "CHANGELOG/1.31.4/CRITICAL" in git(repo, "show", "--name-only", "--format=", "HEAD"))
rc = subprocess.run([sys.executable, "tools/release_check.py"], cwd=repo, capture_output=True, text=True)
check("release_check: срочный выпуск отмечен «СРОЧНО (исправление безопасности)»",
      rc.returncode == 0 and "СРОЧНО (исправление безопасности)" in rc.stdout and "::warning title=" in rc.stdout)
changelog(repo, "1.31.5")
r = run(repo, "1.31.5")
rc = subprocess.run([sys.executable, "tools/release_check.py"], cwd=repo, capture_output=True, text=True)
check("обычный выпуск после срочного: без пометки", r.returncode == 0 and "СРОЧНО" not in rc.stdout)

# preview build: packaging/preview_build.py makes a separate copy; a release never has its module
import base64  # noqa: E402
fake_key = base64.b64encode(bytes(range(32))).decode()
pv = TMP / "proba-copy"
proba_key_file = repo / "packaging" / "proba-public-key.txt"
real_key_text = proba_key_file.read_text(encoding="utf-8")
proba_key_file.write_text("# placeholder\nTODO-proba-public-key\n", encoding="utf-8")
r = subprocess.run([sys.executable, "packaging/preview_build.py", str(pv), "--version", "1.31.9"], cwd=repo,
                   capture_output=True, text=True)
check("preview_build без настоящего ключа proba (заглушка): отказ", r.returncode != 0 and not pv.exists())
proba_key_file.write_text(real_key_text, encoding="utf-8")
r = subprocess.run([sys.executable, "packaging/preview_build.py", str(TMP / "proba-real")], cwd=repo,
                   capture_output=True, text=True)
check("preview_build с ключом из packaging/proba-public-key.txt: копия сделана, ключ тот же, что запрещён для stable",
      r.returncode == 0 and "SBq9Ms9skCqSpbhz2IUefATXQ8YZ0muE6/pnbuJUWKY=" in
      (TMP / "proba-real" / "clipshot" / "_preview_build.py").read_text(encoding="utf-8"))
r = subprocess.run([sys.executable, "packaging/preview_build.py", str(pv), "--version", "1.31.9", "--public-key", fake_key],
                   cwd=repo, capture_output=True, text=True)
module = pv / "clipshot" / "_preview_build.py"
check("preview_build: копия с версией 1.31.9 и модулем пробной сборки, репозиторий не тронут",
      r.returncode == 0 and module.is_file() and fake_key in module.read_text(encoding="utf-8")
      and version_of(pv) == "1.31.9" and not (repo / "clipshot" / "_preview_build.py").exists()
      and not (pv / ".git").exists())
check("preview_build: в копии номера версий согласованы",
      subprocess.run([sys.executable, "packaging/stamp_version.py", "--check"], cwd=pv, capture_output=True).returncode == 0)
rc = subprocess.run([sys.executable, "tools/release_check.py"], cwd=pv, capture_output=True, text=True)
check("release_check: дерево пробной сборки не проходит", rc.returncode != 0 and "_preview_build.py" in rc.stdout)
r = subprocess.run([sys.executable, "packaging/preview_build.py", str(pv), "--public-key", fake_key], cwd=repo,
                   capture_output=True, text=True)
check("preview_build: в непустую папку не пишет", r.returncode != 0)
(repo / "clipshot" / "_preview_build.py").write_text(module.read_text(encoding="utf-8"), encoding="utf-8")
check("модуль пробной сборки не попадает в git (.gitignore)", not git(repo, "status", "--porcelain"))
changelog(repo, "1.31.6")
r = run(repo, "1.31.6")
check("release.sh: при модуле пробной сборки выпуск отказан", r.returncode != 0 and "_preview_build.py" in r.stderr
      and version_of(repo) == "1.31.5")
(repo / "clipshot" / "_preview_build.py").unlink()
proba_key_file.write_text("# test\n" + fake_key + "\n", encoding="utf-8")
rc = subprocess.run([sys.executable, "tools/release_check.py"], cwd=repo, capture_output=True, text=True)
check("release_check: ключ в proba-public-key.txt не совпадает с PREVIEW_ONLY_KEYS: ошибка",
      rc.returncode != 0 and "PREVIEW_ONLY_KEYS" in rc.stdout)
proba_key_file.write_text(real_key_text, encoding="utf-8")
uc_file = repo / "clipshot" / "update_channel.py"
uc_text = uc_file.read_text(encoding="utf-8")
_alias = "SBq9Ms9skCqSpbhz2IUefATXQ8YZ0muE6/pnbuJUWKZ="   # the same 32 bytes, another base64 spelling
uc_file.write_text(uc_text.replace("STABLE_PUBLIC_KEYS = (", "STABLE_PUBLIC_KEYS = (\n    " + repr(_alias) + ",", 1), encoding="utf-8")   # independent of the real keys
rc = subprocess.run([sys.executable, "tools/release_check.py"], cwd=repo, capture_output=True, text=True)
check("release_check: ключ proba в STABLE_PUBLIC_KEYS в другом написании base64: ошибка",
      rc.returncode != 0 and "STABLE_PUBLIC_KEYS has the proba" in rc.stdout)
uc_file.write_text(uc_text, encoding="utf-8")
proba_key_file.write_text("# test\n" + fake_key + "\n", encoding="utf-8")
uc_file = repo / "clipshot" / "update_channel.py"
uc_text = uc_file.read_text(encoding="utf-8")
uc_file.write_text(uc_text.replace('"TODO-test-channel-public-key"', repr(fake_key)), encoding="utf-8")
rc = subprocess.run([sys.executable, "tools/release_check.py"], cwd=repo, capture_output=True, text=True)
check("release_check: ключ proba в TEST_PUBLIC_KEYS: ошибка", rc.returncode != 0 and "proba" in rc.stdout)

# name and icon (GPLv3 section 7): a source header without the notice of TRADEMARKS.md, then no TRADEMARKS.md
tm_repo = make_repo("trademark")
tm_file = tm_repo / "clipshot" / "keys.py"
tm_text = tm_file.read_text(encoding="utf-8")
tm_file.write_text("\n".join(l for l in tm_text.split("\n") if "TRADEMARKS.md" not in l), encoding="utf-8")
rc = subprocess.run([sys.executable, "tools/release_check.py"], cwd=tm_repo, capture_output=True, text=True)
rs = subprocess.run([sys.executable, "tools/release_check.py", "--strict"], cwd=tm_repo, capture_output=True, text=True)
check("release_check: исходник без строки о TRADEMARKS.md: предупреждение, с --strict ошибка",
      "::warning::name and icon notice: clipshot/keys.py" in rc.stdout
      and rs.returncode != 0 and "::error::name and icon notice: clipshot/keys.py" in rs.stdout)
subprocess.run([sys.executable, "tools/trademark_notice.py"], cwd=tm_repo, capture_output=True, text=True)
check("trademark_notice.py возвращает строку в заголовок", tm_file.read_text(encoding="utf-8") == tm_text)
(tm_repo / "TRADEMARKS.md").unlink()
rs = subprocess.run([sys.executable, "tools/release_check.py", "--strict"], cwd=tm_repo, capture_output=True, text=True)
check("release_check --strict: нет TRADEMARKS.md: ошибка", rs.returncode != 0 and "TRADEMARKS.md is missing" in rs.stdout)


# --- step 2: assemble (files, SHA256SUMS, latest.json, signature) ---------------------------------------
sys.path.insert(0, str(ROOT / "tools"))
import channel_sign as cs  # noqa: E402
arepo = make_repo("assemble")
ver = "1.31.7"
changelog(arepo, ver)
built = TMP / "built"
built.mkdir()
lin = built / f"ClipSD-{ver}-linux-x86_64.tar.gz"
win = built / f"ClipSD-{ver}-Setup.exe"
import tarfile  # noqa: E402

_STUBS = {}


def stub_elf(script: str) -> bytes:
    """A real ELF program (release.sh assemble requires one) that runs the given sh script with its arguments."""
    if script not in _STUBS:
        d = Path(tempfile.mkdtemp(prefix="stub-", dir=TMP))
        (d / "s.c").write_text('#include <unistd.h>\nint main(int c, char **v) { char *a[64]; int i = 0; '
                               'a[i++] = "sh"; a[i++] = "-c"; a[i++] = ' + json.dumps(script) + '; a[i++] = "clipsd"; '
                               'for (int k = 1; k < c && i < 62; k++) a[i++] = v[k]; a[i] = 0; '
                               'execv("/bin/sh", a); return 127; }\n')
        subprocess.run(["cc", "-O1", "-o", str(d / "stub"), str(d / "s.c")], check=True)
        _STUBS[script] = (d / "stub").read_bytes()
    return _STUBS[script]


def put_program(folder: Path, script: str):
    """clipsd-<version>/clipsd as an ELF stand-in and the _internal/ folder next to it (PyInstaller onedir)."""
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "clipsd").write_bytes(stub_elf(script))
    (folder / "clipsd").chmod(0o755)
    (folder / "_internal").mkdir(exist_ok=True)


def linux_archive(path, version, extra=None, kind="release"):
    """A Linux archive as build_linux.sh lays it out: clipsd-<version>/clipsd (+ extra files); the stand-in program
    answers --selfcheck like the real one: last line "build: <kind>"."""
    src = TMP / f"tree-{path.parent.name}-{path.name}"
    put_program(src / f"clipsd-{version}",
                f'[ "$1" = --selfcheck ] && {{ echo "ClipSD {version} selfcheck ok"; echo "build: {kind}"; }}\nexit 0\n')
    for rel, data in (extra or {}).items():
        target = src / f"clipsd-{version}" / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    with tarfile.open(path, "w:gz") as tar:
        tar.add(src / f"clipsd-{version}", arcname=f"clipsd-{version}")


linux_archive(lin, "1.31.7")
win.write_bytes(b"windows setup " * 100)
wsums = built / "SHA256SUMS-release-windows"   # written by the release build of windows.yml
import hashlib  # noqa: E402
wsums.write_text(f"{hashlib.sha256(win.read_bytes()).hexdigest()}  {win.name}")
keydir = Path(tempfile.mkdtemp(prefix="clipsd-release-key-"))
keyfile = keydir / "test-channel.key"
pub = cs.keygen(keyfile)


def assemble(out, *extra):
    env = dict(os.environ, CLIPSD_PYTHON=sys.executable)
    env["PATH"] = "/usr/bin:/bin"   # no innoextract: the installer is checked against the cloud sums
    return subprocess.run(["bash", "tools/release.sh", "assemble", ver, "--linux", str(lin), "--windows", str(win),
                           "--windows-sums", str(wsums), "--out", str(out), *extra],
                          cwd=arepo, capture_output=True, text=True, env=env)


r = assemble(TMP / "out1")
sums = (TMP / "out1/files/SHA256SUMS").read_text() if (TMP / "out1/files/SHA256SUMS").exists() else ""
check(f"assemble без ключа: файлы и SHA256SUMS ({r.returncode} {r.stderr[-300:]})",
      r.returncode == 0 and lin.name in sums and win.name in sums and len(sums.splitlines()) == 2
      and (TMP / "out1/files" / win.name).read_bytes() == win.read_bytes())
doc = json.loads((TMP / "out1/channel/latest.json").read_text(encoding="utf-8")) if r.returncode == 0 else {}
check("assemble: latest.json с адресами GitHub Releases clipsd/clipsd, размерами, суммами, изменениями ru и en",
      doc.get("version") == ver and doc.get("channel") == "stable"
      and doc["files"]["linux"]["url"] == f"https://github.com/clipsd/clipsd/releases/download/v{ver}/{lin.name}"
      and doc["files"]["windows"]["size"] == win.stat().st_size and set(doc["notes"]) == {"ru", "en"})
check("assemble без ключа: подписи нет, напечатана команда подписи",
      not (TMP / "out1/channel/latest.json.sig").exists() and "channel_sign.py sign" in r.stdout)
r = assemble(TMP / "out-foreign", "--channel", "test", "--key", str(keyfile))
check("assemble: ключ, которого нет в программе, останавливает выпуск, папка выпуска пуста (подпись во временной папке)",
      r.returncode != 0 and "not embedded" in r.stderr and not any((TMP / "out-foreign").rglob("*")))
os.environ["CLIPSD_ALLOW_FOREIGN_KEY"] = "1"
r = assemble(TMP / "out2", "--channel", "test", "--key", str(keyfile))
del os.environ["CLIPSD_ALLOW_FOREIGN_KEY"]
sig = TMP / "out2/channel/latest.json.sig"
check(f"assemble с ключом: latest.json.sig проверяется открытым ключом ({r.returncode} {r.stderr[-300:]})",
      r.returncode == 0 and sig.exists() and cs.verify_bytes([pub], (TMP / "out2/channel/latest.json").read_bytes(),
                                                              sig.read_bytes()))
check("assemble: ключ не вшит в программу: предупреждение", "not embedded" in r.stderr)
r = assemble(TMP / "out2")
check("assemble: в непустую папку не пишет", r.returncode != 0 and "not empty" in r.stderr)
bad = built / "ClipSD-1.31.7-proba-linux-x86_64.tar.gz"
bad.write_bytes(b"x")
env = dict(os.environ, CLIPSD_PYTHON=sys.executable)
r = subprocess.run(["bash", "tools/release.sh", "assemble", ver, "--linux", str(bad), "--out", str(TMP / "out3")],
                   cwd=arepo, capture_output=True, text=True, env=env)
check("assemble: пробная сборка в выпуск не идёт", r.returncode != 0 and "preview" in r.stderr)
shutil.copy2(lin, built / "ClipSD-1.31.7-localtest-linux-x86_64.tar.gz")
r = subprocess.run(["bash", "tools/release.sh", "assemble", ver, "--linux", str(built / "ClipSD-1.31.7-localtest-linux-x86_64.tar.gz"),
                    "--out", str(TMP / "out4")], cwd=arepo, capture_output=True, text=True, env=env)
check("assemble: локальная пробная сборка по имени (-localtest) отказана", r.returncode != 0 and "local test" in r.stderr)
marked = TMP / "marked" / f"ClipSD-{ver}-linux-x86_64.tar.gz"
marked.parent.mkdir()
linux_archive(marked, ver, {"LOCALTEST": b"local\n"})
r = subprocess.run(["bash", "tools/release.sh", "assemble", ver, "--linux", str(marked), "--out", str(TMP / "out5")],
                   cwd=arepo, capture_output=True, text=True, env=env)
check("assemble: архив с меткой LOCALTEST под обычным именем отказан", r.returncode != 0 and "LOCALTEST" in r.stderr)
sys.path.insert(0, str(ROOT / "packaging" / "linux"))
import system_libs  # noqa: E402
_new = next((Path(c) for c in ("/usr/lib/x86_64-linux-gnu/libexpat.so.1", "/usr/lib/x86_64-linux-gnu/libsystemd.so.0",
                                "/usr/lib/x86_64-linux-gnu/libstdc++.so.6") if Path(c).exists()), None)
_probe = TMP / "probe" / "_internal"
if _new is not None and shutil.which("readelf"):
    _probe.mkdir(parents=True)
    shutil.copy2(_new, _probe / _new.name)
if _new is not None and shutil.which("readelf") and system_libs.glibc_too_new(_probe.parent, "2.35"):
    newer = TMP / "newer" / f"ClipSD-{ver}-linux-x86_64.tar.gz"
    newer.parent.mkdir()
    linux_archive(newer, ver, {f"_internal/{_new.name}": _new.read_bytes()})
    r = subprocess.run(["bash", "tools/release.sh", "assemble", ver, "--linux", str(newer), "--out", str(TMP / "out6")],
                       cwd=arepo, capture_output=True, text=True, env=env)
    check("assemble: библиотека в архиве требует glibc новее 2.35: отказ", r.returncode != 0 and "2.35" in r.stderr)
else:
    print("skip: on this machine no library needs a glibc newer than 2.35 (the build machine of releases)")
# a preview archive of the cloud renamed like a release one: its program answers "build: preview"
renamed = TMP / "renamed" / f"ClipSD-{ver}-linux-x86_64.tar.gz"
renamed.parent.mkdir()
linux_archive(renamed, ver, kind="preview")
r = subprocess.run(["bash", "tools/release.sh", "assemble", ver, "--linux", str(renamed), "--out", str(TMP / "out7")],
                   cwd=arepo, capture_output=True, text=True, env=env)
check(f"assemble: переименованный пробный архив отклонён по selfcheck ({r.stderr.strip()[-120:]})",
      r.returncode != 0 and "build: preview" in r.stderr)
# Windows without innoextract: only the installer the cloud release build checked
_env = dict(env, PATH="/usr/bin:/bin")
other = TMP / "otherwin" / win.name
other.parent.mkdir()
other.write_bytes(b"a preview setup renamed " * 50)
r = subprocess.run(["bash", "tools/release.sh", "assemble", ver, "--windows", str(other), "--windows-sums", str(wsums),
                    "--out", str(TMP / "out8")], cwd=arepo, capture_output=True, text=True, env=_env)
check("assemble: другой Setup.exe под именем выпускного (сумма не та, что у облачной выпускной сборки) отклонён",
      r.returncode != 0 and "differs" in r.stderr)
r = subprocess.run(["bash", "tools/release.sh", "assemble", ver, "--windows", str(win), "--out", str(TMP / "out9")],
                   cwd=arepo, capture_output=True, text=True, env=_env)
check("assemble: без innoextract и без --windows-sums установщик не принимается", r.returncode != 0 and "--windows-sums" in r.stderr)
# several top folders: the checked one must be exactly clipsd-<version>, the only entry
def run_assemble(archive, out, *extra, env_=None):
    return subprocess.run(["bash", "tools/release.sh", "assemble", ver, "--linux", str(archive), "--out", str(out), *extra],
                          cwd=arepo, capture_output=True, text=True, env=env_ or env)


multi = TMP / "multi" / f"ClipSD-{ver}-linux-x86_64.tar.gz"
multi.parent.mkdir()
src_multi = TMP / "multi-src"
for top, kind in (("clipsd-0", "release"), (f"clipsd-{ver}", "preview"), ("clipsd-zzz", "release")):
    put_program(src_multi / top, f'[ "$1" = --selfcheck ] && echo "build: {kind}"\nexit 0\n')
with tarfile.open(multi, "w:gz") as tar:
    for top in ("clipsd-0", f"clipsd-{ver}", "clipsd-zzz"):
        tar.add(src_multi / top, arcname=top)
r = run_assemble(multi, TMP / "out10")
check(f"assemble: архив с лишними папками clipsd-0, clipsd-zzz отклонён ({r.stderr.strip()[-110:]})",
      r.returncode != 0 and "exactly one folder" in r.stderr and not any((TMP / "out10").rglob("*")))
# members the program would unpack differently from tar: a leading "/" or ".//"; links in place of the folder or program
import io  # noqa: E402


def odd_archive(name, members):
    """members: [(arcname, kind, data)] with kind file | dir | symlink (data = link target)."""
    path = TMP / name / f"ClipSD-{ver}-linux-x86_64.tar.gz"
    path.parent.mkdir()
    with tarfile.open(path, "w:gz") as tar:
        for arcname, kind, data in members:
            info = tarfile.TarInfo(arcname)
            if kind == "dir":
                info.type, info.mode = tarfile.DIRTYPE, 0o755
                tar.addfile(info)
            elif kind == "symlink":
                info.type, info.linkname = tarfile.SYMTYPE, data
                tar.addfile(info)
            else:
                body = data if isinstance(data, bytes) else data.encode()
                info.size, info.mode = len(body), 0o755
                tar.addfile(info, io.BytesIO(body))
    return path


_prog = stub_elf('[ "$1" = --selfcheck ] && echo "build: release"\nexit 0\n')
_script = '#!/bin/sh\n[ "$1" = --selfcheck ] && echo "build: release"\nexit 0\n'
_real = [(f"clipsd-{ver}", "dir", ""), (f"clipsd-{ver}/_internal", "dir", ""), (f"clipsd-{ver}/clipsd", "file", _prog)]
for _name, _members, _what in (
        ("abs-member", _real + [("/clipsd-zzz/clipsd", "file", _prog)], "член /clipsd-zzz/clipsd"),
        ("dotslash-member", _real + [(".//clipsd-zzz/clipsd", "file", _prog)], "член .//clipsd-zzz/clipsd"),
        ("link-folder", [("real", "dir", ""), ("real/clipsd", "file", _prog), (f"clipsd-{ver}", "symlink", "real")],
         "симлинк вместо папки clipsd-<версия> (и лишняя папка)"),
        ("link-folder-only", [(f"clipsd-{ver}", "symlink", "."), (f"clipsd-{ver}/clipsd", "file", _prog)],
         "единственный член clipsd-<версия> оказался симлинком на «.»"),
        ("link-program", [(f"clipsd-{ver}", "dir", ""), (f"clipsd-{ver}/clipsd", "symlink", "/bin/true")],
         "абсолютный симлинк вместо программы"),
        ("rel-link-program", [(f"clipsd-{ver}", "dir", ""), (f"clipsd-{ver}/real", "file", _prog),
                              (f"clipsd-{ver}/clipsd", "symlink", "real")], "симлинк внутри папки вместо программы"),
        ("script-program", [(f"clipsd-{ver}", "dir", ""), (f"clipsd-{ver}/_internal", "dir", ""),
                            (f"clipsd-{ver}/clipsd", "file", _script)], "скрипт вместо программы (не ELF)"),
        ("no-internal", [(f"clipsd-{ver}", "dir", ""), (f"clipsd-{ver}/clipsd", "file", _prog)], "нет папки _internal"),
        ("link-internal", [(f"clipsd-{ver}", "dir", ""), (f"clipsd-{ver}/inner", "dir", ""),
                           (f"clipsd-{ver}/_internal", "symlink", "inner"), (f"clipsd-{ver}/clipsd", "file", _prog)],
         "_internal симлинком")):
    r = run_assemble(odd_archive(_name, _members), TMP / f"out-{_name}")
    check(f"assemble: {_what}: отклонён ({r.stderr.strip()[-110:]})",
          r.returncode != 0 and not any((TMP / f"out-{_name}").rglob("*")))
_ok = run_assemble(odd_archive("plain-ok", _real), TMP / "out-plain-ok")
check(f"assemble: настоящий архив из папки и программы проходит ({_ok.returncode} {_ok.stderr.strip()[-160:]})",
      _ok.returncode == 0 and (TMP / "out-plain-ok/files" / f"ClipSD-{ver}-linux-x86_64.tar.gz").is_file())
wrongver = TMP / "wrongver" / f"ClipSD-{ver}-linux-x86_64.tar.gz"
wrongver.parent.mkdir()
src_w = TMP / "wrongver-src" / "clipsd-1.31.6"
put_program(src_w, 'echo "build: release"\n')
with tarfile.open(wrongver, "w:gz") as tar:
    tar.add(src_w, arcname="clipsd-1.31.6")
r = run_assemble(wrongver, TMP / "out11")
check("assemble: папка в архиве другой версии (clipsd-1.31.6 при 1.31.7) отклонена", r.returncode != 0 and "clipsd-1.31.7" in r.stderr)
# the name is not in the sums of the cloud build: a clear message, not a silent stop
other_sums = TMP / "other-sums"
other_sums.write_text("0" * 64 + "  ClipSD-9.9.9-Setup.exe\n")
r = subprocess.run(["bash", "tools/release.sh", "assemble", ver, "--windows", str(win), "--windows-sums", str(other_sums),
                    "--out", str(TMP / "out12")], cwd=arepo, capture_output=True, text=True, env=_env)
check(f"assemble: имени установщика нет в суммах: понятное сообщение ({r.stderr.strip()[-90:]})",
      r.returncode != 0 and "is not in" in r.stderr and not any((TMP / "out12").rglob("*")))
# every refusal leaves --out empty (the checks run before any copy)
check("assemble: при отказах папка выпуска пуста", all(not any((TMP / o).rglob("*")) for o in ("out3", "out4", "out5", "out7", "out8")))
# the selfcheck runs in a home of its own: the stand-in writes into $HOME and the test home stays clean
spy = TMP / "spy" / f"ClipSD-{ver}-linux-x86_64.tar.gz"
spy.parent.mkdir()
src_s = TMP / "spy-src" / f"clipsd-{ver}"
put_program(src_s, 'touch "$HOME/selfcheck-was-here" "$XDG_CONFIG_HOME/cfg-was-here"\necho "build: release"\n')
with tarfile.open(spy, "w:gz") as tar:
    tar.add(src_s, arcname=f"clipsd-{ver}")
_home = Path(os.environ.get("HOME", "/nonexistent"))
r = run_assemble(spy, TMP / "out13")
check(f"assemble: selfcheck со своим временным HOME и XDG ({r.returncode})",
      r.returncode == 0 and not (_home / "selfcheck-was-here").exists())
check("assemble: временные папки на диске (~/.cache/clipsd-work/rel) убраны после работы",
      (_home / ".cache/clipsd-work/rel").is_dir() and not list((_home / ".cache/clipsd-work/rel").iterdir()))
check("assemble: в репозитории ничего не изменено", not git(arepo, "status", "--porcelain"))
shutil.rmtree(keydir, ignore_errors=True)

shutil.rmtree(TMP, ignore_errors=True)
print()
print("ИТОГ: все проверки пройдены" if not failures else "ПРОВАЛЕНО: " + "; ".join(failures))
sys.exit(1 if failures else 0)
