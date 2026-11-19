#!/usr/bin/env bash
# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later
#
# A release in two steps. Nothing is pushed or published by this script.
#
# Step 1, prepare (architecture 4.4): the commit and the tag.
#   tools/release.sh 1.30.1            checks, tests, version, commit "выпуск 1.30.1", tag v1.30.1
#   tools/release.sh 1.30.1 --dry-run  the same checks and tests, nothing is changed
#   tools/release.sh 1.30.1 --critical urgent security fix: writes CHANGELOG/1.30.1/CRITICAL, the commit says
#                                      "СРОЧНО (исправление безопасности)"; programs offer it at once
# Checks (any failure stops with a message and leaves the tree as it was):
#   1. the working tree is clean (no changes, no untracked files);
#   2. the version is X.Y.Z, not lower than the current one (clipshot/__init__.py; equal = tag the prepared
#      version), the tag does not exist;
#   3. CHANGELOG/<version>/ru.md and en.md exist and are not empty (en is the fallback of the channel);
#   4. all tests pass (tests/*_test.py offscreen; CLIPSD_TEST_CMD replaces them, used by the test of this script).
# Then: __version__ is written, packaging/stamp_version.py stamps the other files, commit, tag.
#
# Step 2, assemble: the files of the release and the signed channel document.
#   tools/release.sh assemble 1.30.1 --linux ClipSD-1.30.1-linux-x86_64.tar.gz --windows ClipSD-1.30.1-Setup.exe \
#       --out DIR [--channel stable|test] [--base-url URL] [--key PRIVATE.pem] [--days 90] [--critical]
#       [--windows-sums SHA256SUMS-release-windows]   (needed when innoextract is not installed)
#   Refused: names with proba/localtest, a Linux archive whose program does not answer "build: release" to --selfcheck
#   or needs a glibc newer than 2.35, a Windows installer with the PREVIEW mark (innoextract) or not equal to the one
#   the cloud release build checked (--windows-sums).
#   DIR/files/     the two files (as GitHub Actions built them) and SHA256SUMS
#   DIR/channel/   latest.json (channel_sign.py build: version, https addresses, sizes, sha256, notes ru/en,
#                  expires) and, with --key, latest.json.sig (channel_sign.py sign; the card is printed first)
#   Without --key the document is left unsigned and the exact sign command is printed: the private key stays
#   with its owner. --base-url defaults to the release page of the public repository:
#   https://github.com/clipsd/clipsd/releases/download/v<version>
#   The files go to that GitHub release, latest.json and latest.json.sig to the channel page
#   (https://clipsd.github.io/channel/<channel>/); both by the owner, not by this script.
set -euo pipefail

LANGS="ru en"
PUBLIC_REPO="clipsd/clipsd"

die() { echo "release.sh: $*" >&2; exit 1; }

cd "$(dirname "${BASH_SOURCE[0]}")/.."
ROOT="$(pwd)"
PY="${CLIPSD_PYTHON:-python3}"

# ------------------------------------------------------------------------------------------- assemble
if [ "${1:-}" = assemble ]; then
    shift
    VERSION="" LINUX="" WINDOWS="" WSUMS="" OUT="" CHANNEL="stable" BASE="" KEY="" DAYS=90 CRIT=()
    while [ $# -gt 0 ]; do
        case "$1" in
            --linux) LINUX="${2:-}"; shift 2 ;;
            --windows) WINDOWS="${2:-}"; shift 2 ;;
            --windows-sums) WSUMS="${2:-}"; shift 2 ;;
            --out) OUT="${2:-}"; shift 2 ;;
            --channel) CHANNEL="${2:-}"; shift 2 ;;
            --base-url) BASE="${2:-}"; shift 2 ;;
            --key) KEY="${2:-}"; shift 2 ;;
            --days) DAYS="${2:-}"; shift 2 ;;
            --critical) CRIT=(--critical); shift ;;
            -*) die "unknown option $1" ;;
            *) [ -z "$VERSION" ] || die "one version only"; VERSION="$1"; shift ;;
        esac
    done
    [[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || die "usage: tools/release.sh assemble X.Y.Z --linux F --windows F --out DIR"
    [ -n "$OUT" ] || die "--out DIR is required"
    [ -n "$LINUX" ] || [ -n "$WINDOWS" ] || die "at least one of --linux, --windows"
    case "$CHANNEL" in stable|test) ;; *) die "--channel stable or test (the preview channel is assembled by hand)" ;; esac
    [ -d "CHANGELOG/$VERSION" ] || die "no CHANGELOG/$VERSION"
    [ -z "$BASE" ] && BASE="https://github.com/$PUBLIC_REPO/releases/download/v$VERSION"
    if [ -n "$(ls -A "$OUT" 2>/dev/null)" ]; then die "$OUT exists and is not empty"; fi
    # Temporary folders on disk (never /tmp: it lives in memory, and an unpacked archive is ~200 MB)
    WORKBASE="${CLIPSD_WORK_DIR:-$HOME/.cache/clipsd-work/rel}"
    mkdir -p "$WORKBASE"
    TMPS=()
    trap 'for d in ${TMPS[@]+"${TMPS[@]}"}; do rm -rf "$d"; done' EXIT
    # sets NEWTMP (not echoed: a $(...) subshell would lose the list that the EXIT trap cleans up)
    newtmp() { NEWTMP="$(mktemp -d "$WORKBASE/assemble.XXXXXX")"; TMPS+=("$NEWTMP"); }

    # All checks first: on any refusal $OUT stays empty
    for f in "$LINUX" "$WINDOWS"; do
        [ -n "$f" ] || continue
        [ -f "$f" ] || die "no file $f"
        name="$(basename "$f")"
        case "$name" in *"$VERSION"*) ;; *) die "$name does not carry the version $VERSION" ;; esac
        case "$name" in *proba*) die "$name is a preview build: never a release" ;; esac
        case "$name" in *localtest*) die "$name is a local test build (CLIPSD_ALLOW_NEW_GLIBC=1): never a release" ;; esac
    done
    # The Linux archive itself: exactly one top entry clipsd-$VERSION; no LOCALTEST mark; its program answers
    # "build: release"; nothing in it needs a glibc newer than 2.35 (Ubuntu 22.04, the build machine of linux.yml).
    if [ -n "$LINUX" ]; then
        lname="$(basename "$LINUX")"
        # Read and unpacked exactly as the program does on an update (updater.extract_linux_package: tarfile with
        # filter="data"), not with tar: a member "/clipsd-zzz/..." or ".//clipsd-zzz/..." counts as clipsd-zzz here too.
        tops="$(python3 -I -c '
import sys, tarfile
names = set()
try:
    with tarfile.open(sys.argv[1], "r:gz") as tar:
        for m in tar.getmembers():
            n = m.name
            while n.startswith(("./", "/")):
                n = n[2:] if n.startswith("./") else n[1:]
            names.add(n.split("/", 1)[0] or "(empty name)")
except (OSError, tarfile.TarError):
    sys.exit(0)
print("\n".join(sorted(names)))
' "$LINUX" 2>/dev/null || true)"
        [ -n "$tops" ] || die "cannot read $lname"
        [ "$tops" = "clipsd-$VERSION" ] ||
            die "$lname must hold exactly one folder clipsd-$VERSION, it holds: $(printf '%s' "$tops" | tr '\n' ' ')"
        newtmp; CHECK="$NEWTMP"
        python3 -I -c '
import sys, tarfile
with tarfile.open(sys.argv[1], "r:gz") as tar:
    tar.extractall(sys.argv[2], filter="data")   # as the updater: no absolute paths, "..", links out of the folder
' "$LINUX" "$CHECK/x" 2>/dev/null || die "cannot unpack $lname (as the program would: tarfile filter=data)"
        APPDIR="$CHECK/x/clipsd-$VERSION"
        [ -d "$APPDIR" ] && [ ! -L "$APPDIR" ] || die "$lname: clipsd-$VERSION is not a real folder (a link?)"
        [ -f "$APPDIR/clipsd" ] && [ ! -L "$APPDIR/clipsd" ] && [ -x "$APPDIR/clipsd" ] ||
            die "$lname: clipsd-$VERSION/clipsd is not a real executable file (missing or a link)"
        [ "$(head -c 4 "$APPDIR/clipsd" | od -An -tx1 | tr -d ' \n')" = 7f454c46 ] ||
            die "$lname: clipsd-$VERSION/clipsd is not an ELF program (a script or something else)"
        [ -d "$APPDIR/_internal" ] && [ ! -L "$APPDIR/_internal" ] ||
            die "$lname: no folder clipsd-$VERSION/_internal next to the program (not a PyInstaller build)"
        [ ! -e "$APPDIR/LOCALTEST" ] || die "$lname carries the LOCALTEST mark: a local test build, never a release"
        # The kind of build is inside the executable (PyInstaller packs the modules): ask the program itself, in a
        # home of its own (nothing of this computer's ClipSD is read or written). A preview build renamed like a
        # release one answers "build: preview" and would keep everybody on the proba channel.
        SC="$CHECK/selfcheck-home"
        mkdir -p "$SC/home" "$SC/config" "$SC/data" "$SC/cache" "$SC/state" "$SC/runtime"
        chmod 700 "$SC/runtime"
        KIND_LINE="$(cd "$SC" && env -u DISPLAY -u WAYLAND_DISPLAY -u DBUS_SESSION_BUS_ADDRESS HOME="$SC/home" \
            XDG_CONFIG_HOME="$SC/config" XDG_DATA_HOME="$SC/data" XDG_CACHE_HOME="$SC/cache" XDG_STATE_HOME="$SC/state" \
            XDG_RUNTIME_DIR="$SC/runtime" QT_QPA_PLATFORM=offscreen timeout 120 "$APPDIR/clipsd" --selfcheck 2>/dev/null \
            | tail -n 1 || true)"
        [ "$KIND_LINE" = "build: release" ] ||
            die "$lname: selfcheck says '${KIND_LINE:-nothing}', not 'build: release' (a preview or local test build)"
        python3 packaging/linux/system_libs.py glibc "$APPDIR" 2.35 ||
            die "$lname needs a glibc newer than 2.35: take the archive of the ubuntu-22.04 build (GitHub Actions)"
    fi
    # The Windows installer: its program must not be a preview build. With innoextract: unpack and look for the mark
    # PREVIEW that a preview installer carries ({app}\PREVIEW). Without it: the installer must be byte for byte the one
    # the release build in the cloud checked (SHA256SUMS-release-windows from the artifact ClipSD-Setup, --windows-sums).
    if [ -n "$WINDOWS" ]; then
        wname="$(basename "$WINDOWS")"
        if command -v innoextract >/dev/null 2>&1; then
            newtmp; WCHECK="$NEWTMP"
            innoextract --silent --output-dir "$WCHECK" "$WINDOWS" >/dev/null 2>&1 || die "innoextract cannot unpack $wname"
            [ -z "$(find "$WCHECK" -iname PREVIEW -print -quit)" ] || die "$wname is a preview installer (PREVIEW inside)"
            [ -n "$(find "$WCHECK" -iname 'ClipSD-app.exe' -print -quit)" ] || die "$wname: no ClipSD-app.exe inside"
        elif [ -n "$WSUMS" ]; then
            [ -f "$WSUMS" ] || die "no file $WSUMS"
            want="$(awk -v n="$wname" '{ f = $2; sub(/^\*/, "", f); if (f == n) { print tolower($1); exit } }' "$WSUMS" || true)"
            [ -n "$want" ] || die "$wname is not in $WSUMS (the release check of the cloud build)"
            got="$(sha256sum "$WINDOWS" | cut -d' ' -f1)"
            [ "$want" = "$got" ] || die "$wname differs from the installer the cloud release build checked ($WSUMS)"
        else
            die "cannot check $wname: install innoextract or pass --windows-sums SHA256SUMS-release-windows (artifact ClipSD-Setup)"
        fi
    fi

    # Checked: now the files of the release, first in a temporary folder on disk (built, signed, verified there);
    # only when everything passed they are copied into $OUT, so a failed signature or key check leaves $OUT empty
    newtmp; STAGE="$NEWTMP"
    mkdir -p "$STAGE/files" "$STAGE/channel"
    for f in "$LINUX" "$WINDOWS"; do
        if [ -n "$f" ]; then cp -p "$f" "$STAGE/files/$(basename "$f")"; fi
    done
    (cd "$STAGE/files" && sha256sum -- * | grep -v ' SHA256SUMS$' > SHA256SUMS)
    "$PY" tools/channel_sign.py build --version "$VERSION" --channel "$CHANNEL" --sums "$STAGE/files/SHA256SUMS" \
        --dist "$STAGE/files" --changelog CHANGELOG --base-url "$BASE" --out "$STAGE/channel/latest.json" \
        --days "$DAYS" ${CRIT[@]+"${CRIT[@]}"} || die "latest.json was not built"
    if [ -n "$KEY" ]; then
        "$PY" tools/channel_sign.py sign --private "$KEY" --role "$CHANNEL" --in "$STAGE/channel/latest.json" \
            ${CRIT[@]+"${CRIT[@]}"} || die "latest.json was not signed"
        PUB="$("$PY" tools/channel_sign.py pubkey --private "$KEY")"
        "$PY" tools/channel_sign.py verify --public "$PUB" --in "$STAGE/channel/latest.json" --channel "$CHANNEL" ||
            die "the signature of latest.json does not verify"
        "$PY" - "$PUB" "$CHANNEL" <<'PYEOF' || { [ "${CLIPSD_ALLOW_FOREIGN_KEY:-0}" = 1 ] && echo "release.sh: WARNING: this key is not embedded in clipshot/update_channel.py (allowed by CLIPSD_ALLOW_FOREIGN_KEY=1, tests only)" >&2; } || die "this key is not embedded in clipshot/update_channel.py: installed programs would refuse the document"
import ast, base64, sys
tree = ast.parse(open("clipshot/update_channel.py", encoding="utf-8").read())
names = {"stable": "STABLE_PUBLIC_KEYS", "test": "TEST_PUBLIC_KEYS"}
keys = []
for node in tree.body:
    if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == names[sys.argv[2]]:
        keys = ast.literal_eval(node.value)
raw = lambda k: base64.b64decode(k) if len(k) > 40 else b""
sys.exit(0 if raw(sys.argv[1]) in {raw(k) for k in keys if "TODO" not in k} else 1)
PYEOF
    fi
    mkdir -p "$OUT"
    cp -pR "$STAGE/files" "$STAGE/channel" "$OUT/"
    if [ -z "$KEY" ]; then
        echo "release.sh: latest.json is NOT signed. The owner of the key signs it:"
        echo "  $PY tools/channel_sign.py sign --private <key.pem> --role $CHANNEL --in $OUT/channel/latest.json ${CRIT[*]-}"
    fi
    echo "release.sh: assembled in $OUT"
    echo "  files for the GitHub release v$VERSION of $PUBLIC_REPO:"
    sed 's/^/    /' "$OUT/files/SHA256SUMS"
    echo "  channel page (https://clipsd.github.io/channel/$CHANNEL/): latest.json$([ -n "$KEY" ] && echo ' and latest.json.sig')"
    echo "Nothing was uploaded or pushed."
    exit 0
fi

# -------------------------------------------------------------------------------------------- prepare
VERSION=""
DRY=0
CRITICAL=0
URGENT="СРОЧНО (исправление безопасности)"
for arg in "$@"; do
    case "$arg" in
        --dry-run) DRY=1 ;;
        --critical) CRITICAL=1 ;;
        -h|--help) sed -n '5,31p' "$0"; exit 0 ;;
        -*) die "unknown option $arg" ;;
        *) [ -z "$VERSION" ] || die "one version only"; VERSION="$arg" ;;
    esac
done
[ -n "$VERSION" ] || die "usage: tools/release.sh X.Y.Z [--dry-run] [--critical] | tools/release.sh assemble X.Y.Z ..."
[[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || die "version must look like 1.30.1, got '$VERSION'"

git rev-parse --git-dir >/dev/null 2>&1 || die "not a git repository"

# 1. clean tree (and not a preview copy: its generated module is ignored by git, so checked by name)
[ -z "$(git status --porcelain)" ] || { git status --short >&2; die "the working tree is not clean"; }
[ ! -e clipshot/_preview_build.py ] || die "clipshot/_preview_build.py exists: a preview build is never released"

# 2. version
CURRENT="$(sed -n 's/^__version__ = "\([^"]*\)"/\1/p' clipshot/__init__.py)"
[ -n "$CURRENT" ] || die "cannot read __version__ from clipshot/__init__.py"
# the version already in the sources may be released once (the first release of a prepared version: tag only)
python3 - "$CURRENT" "$VERSION" <<'PYEOF' || die "version $VERSION is lower than the current $CURRENT"
import sys
key = lambda v: tuple(int(x) for x in v.split("."))
sys.exit(0 if key(sys.argv[2]) >= key(sys.argv[1]) else 1)
PYEOF
! git rev-parse -q --verify "refs/tags/v$VERSION" >/dev/null || die "tag v$VERSION already exists"

# 3. changelog: Russian (the program's language) and English (the channel's fallback)
for lang in $LANGS; do
    file="CHANGELOG/$VERSION/$lang.md"
    [ -s "$file" ] || die "missing or empty $file (required: $LANGS)"
done

# 3a. urgency is decided here, once: the marker and the option must agree
MARKER="CHANGELOG/$VERSION/CRITICAL"
if [ -e "$MARKER" ] && [ "$CRITICAL" = 0 ]; then
    die "$MARKER exists: pass --critical for an urgent security fix, or remove the marker"
fi
if [ "$CRITICAL" = 1 ]; then
    echo "################################################################"
    echo "### $URGENT: ClipSD $VERSION"
    echo "### programs offer it at once and on every start until installed"
    echo "################################################################"
fi

# 4. tests
echo "release.sh: tests..."
if [ -n "${CLIPSD_TEST_CMD:-}" ]; then
    bash -c "$CLIPSD_TEST_CMD" || die "tests failed"
else
    export QT_QPA_PLATFORM=offscreen
    for t in tests/*_test.py; do
        case "$t" in tests/test_*) continue ;; esac
        echo "  $t"
        "$PY" "$t" >/dev/null 2>&1 || { "$PY" "$t" 2>&1 | tail -20 >&2; die "test failed: $t"; }
    done
fi
[ -z "$(git status --porcelain)" ] || { git status --short >&2; die "tests changed the working tree"; }

SUBJECT="выпуск $VERSION"
if [ "$CRITICAL" = 1 ]; then SUBJECT="выпуск $VERSION: $URGENT"; fi
if [ "$DRY" = 1 ]; then
    echo "release.sh: dry run ok. Would set version $CURRENT -> $VERSION, commit '$SUBJECT', tag v$VERSION."
    exit 0
fi

# 5. version, stamp, urgency marker, commit, tag
if [ "$CRITICAL" = 1 ]; then
    printf '%s\n' "$URGENT" > "$MARKER"
fi
sed -i "s/^__version__ = \".*\"/__version__ = \"$VERSION\"/" clipshot/__init__.py
"$PY" packaging/stamp_version.py
"$PY" packaging/stamp_version.py --check || die "stamp_version.py --check failed after stamping"
git add -A
if git diff --cached --quiet; then
    echo "release.sh: version $VERSION is already in the sources: tag only, no new commit"
else
    git commit -q -m "$SUBJECT"
fi
git tag -a "v$VERSION" -m "ClipSD $VERSION$([ "$CRITICAL" = 1 ] && echo ": $URGENT")"

BRANCH="$(git rev-parse --abbrev-ref HEAD)"
echo "release.sh: done. Commit and tag v$VERSION are local; nothing was pushed."
if [ "$CRITICAL" = 1 ]; then
    echo "release.sh: $URGENT. Assemble with: tools/release.sh assemble $VERSION ... --critical"
fi
echo "Next steps (run them yourself when ready):"
echo "  git push origin $BRANCH v$VERSION     (GitHub Actions build the Linux archive and Setup.exe)"
echo "  tools/release.sh assemble $VERSION --linux <tar.gz> --windows <Setup.exe> --out <folder> [--key <key.pem>]"
