# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later
"""Windows or GNOME in a dark theme: the windows of ClipSD stay readable (1.31.2).

19.11.2026, Windows in the dark theme: in the tour (language step) the language buttons, «Как в системе», «Назад» and
«Пропустить» were almost white on white. Qt 6.5+ Fusion gives a palette by the system theme (qt_fusionPalette: text
240,240,240), themes.apply_app took it for the light «Standard» theme, and our white cards and buttons took the text
colour from that palette.

The dark system is modelled here: the application starts with the dark Fusion palette (the same formula as
qt_fusionPalette for a dark scheme) and QStyle.standardPalette() returns it, as on Windows/GNOME in dark mode. Then
for both themes of ClipSD (Standard, Professional) the windows are drawn offscreen and every visible text is measured
by its pixels: the most frequent colour of the widget is the background, the text is the colour with the highest
contrast to it. Contrast (WCAG) of text to background must be at least 4.5; for white text on a coloured accent
(blue «Далее», the chosen language, green main button of ClipSD windows) at least 3.0: those colours are approved as
they are (measured: 4.05 and 3.5).

Run: QT_QPA_PLATFORM=offscreen python3 tests/dark_system_test.py [folder for snapshots]
"""
import os
import sys
import tempfile
from collections import Counter
from datetime import datetime, timedelta, timezone

here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(here))
tmp = tempfile.mkdtemp(prefix="clipsd-dark-")
for name in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME"):
    os.environ[name] = os.path.join(tmp, name)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.pop("CLIPSD_LANG", None)
SNAP = sys.argv[1] if len(sys.argv) > 1 else ""

from PyQt6.QtCore import QPoint, QRect, Qt  # noqa: E402
from PyQt6.QtGui import QColor, QFont, QImage, QPalette  # noqa: E402
from PyQt6.QtWidgets import (QAbstractButton, QApplication, QCommonStyle, QLabel, QPlainTextEdit, QProxyStyle,  # noqa: E402
                             QStyle, QTextEdit, QWidget)

app = QApplication(sys.argv)
_font = app.font()
_font.setStyleStrategy(QFont.StyleStrategy.NoAntialias)   # text pixels in exactly the text colour: exact measurement
app.setFont(_font)

failures = []
measured = [0]


def check(cond, msg):
    print(("OK   " if cond else "FAIL ") + msg, flush=True)
    if not cond:
        failures.append(msg)


# --- the dark system -----------------------------------------------------------------------------------------
def dark_fusion() -> QPalette:
    """qt_fusionPalette() of Qt 6.11 for a dark colour scheme (qplatformtheme.cpp)."""
    R, G = QPalette.ColorRole, QPalette.ColorGroup
    window_text, window = QColor(240, 240, 240), QColor(50, 50, 50)
    light, mid, dark = window.lighter(150), window.darker(130), window.darker(150)
    base = window.darker(140)
    pal = QPalette(window_text, window, light, dark, mid, window_text, light, base, window)
    pal.setColor(R.Midlight, mid.lighter(110))
    pal.setColor(R.Shadow, dark.darker(135))
    pal.setColor(R.HighlightedText, window_text)
    pal.setColor(R.Highlight, QColor(48, 140, 198))
    pal.setColor(R.Link, QColor(48, 140, 198))
    for r in (R.Text, R.WindowText, R.ButtonText):
        pal.setColor(G.Disabled, r, QColor(130, 130, 130))
    return pal


for cls in (QStyle, QCommonStyle, QProxyStyle):
    cls.standardPalette = lambda self: dark_fusion()   # what Fusion returns on a dark Windows/GNOME
app.setStyle("Fusion")
app.setPalette(dark_fusion())

from clipshot import app as appmod, i18n, themes  # noqa: E402
from clipshot import update_channel as uc  # noqa: E402
from clipshot import updater as up  # noqa: E402
from clipshot.editor import EditorWindow  # noqa: E402
from clipshot.settings import SettingsDialog  # noqa: E402


def settle(n=4):
    for _ in range(n):
        app.processEvents()


def lum(c: QColor) -> float:
    def ch(v):
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    return 0.2126 * ch(c.red()) + 0.7152 * ch(c.green()) + 0.0722 * ch(c.blue())


def contrast(a: QColor, b: QColor) -> float:
    la, lb = sorted((lum(a), lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def text_contrast(img: QImage, rect: QRect, inset: int):
    """(contrast, background, text) of a widget region of the window image."""
    r = rect.adjusted(inset, inset, -inset, -inset).intersected(img.rect())
    counts = Counter()
    for y in range(r.top(), r.bottom() + 1):
        for x in range(r.left(), r.right() + 1):
            counts[img.pixel(x, y) & 0xFFFFFF] += 1
    if not counts:
        return None
    bg = QColor(counts.most_common(1)[0][0])
    best, fg = 1.0, bg
    for rgb, n in counts.items():
        if n < 2:
            continue
        c = QColor(rgb)
        k = contrast(bg, c)
        if k > best:
            best, fg = k, c
    return best, bg, fg


ACCENT_NAMES = {"tourNext", "clipPrimary", "primary"}


def accent(w) -> bool:
    """White text on an accent fill: «Далее», a chosen (checked) button, the main button of ClipSD windows."""
    return w.objectName() in ACCENT_NAMES or (isinstance(w, QAbstractButton) and w.isCheckable() and w.isChecked()
                                              and not hasattr(w, "checkState"))


def texts_of(root: QWidget):
    out = []
    for w in root.findChildren(QWidget):
        if not w.isVisible() or w.width() < 8 or w.height() < 8:
            continue
        if isinstance(w, QLabel) and w.text().strip() and w.pixmap().isNull():
            out.append((w, 0))
        elif isinstance(w, QAbstractButton) and w.text().strip():
            out.append((w, 4))
        elif isinstance(w, (QPlainTextEdit, QTextEdit)):
            out.append((w.viewport(), 2))
    return out


def audit(window: QWidget, where: str, root: QWidget = None, enabled_only=True):
    """Measure every visible text of root (default: the window) in the picture of the window."""
    window.ensurePolished()
    settle()
    img = window.grab().toImage().convertToFormat(QImage.Format.Format_RGB32)
    ratio = img.width() / max(window.width(), 1)
    bad = []
    for w, inset in texts_of(root or window):
        if enabled_only and not w.isEnabled():
            continue
        seen = w.visibleRegion().boundingRect()   # the part not cut off by a scroll area or the window edge
        if seen.isEmpty():
            continue
        top_left = w.mapTo(window, seen.topLeft())
        rect = QRect(int(top_left.x() * ratio), int(top_left.y() * ratio), int(seen.width() * ratio), int(seen.height() * ratio))
        res = text_contrast(img, rect, inset)
        if res is None:
            continue
        k, bg, fg = res
        owner = w.parentWidget() if w.objectName() == "qt_scrollarea_viewport" else w
        need = 3.0 if accent(owner) else 4.5
        measured[0] += 1
        label = getattr(owner, "text", lambda: owner.objectName())()
        if k < need:
            bad.append(f"«{str(label)[:40]}» {k:.2f} (text {fg.name()} on {bg.name()})")
    check(not bad, f"{where}: every text readable (≥4.5, accent ≥3.0){': ' + '; '.join(bad) if bad else ''}")
    return img


class Ctx:
    def __init__(self, theme):
        self.config = dict(appmod.DEFAULTS, tour_done=True, theme_chosen=True, ui_theme=theme)
        self.icon = appmod.make_icon()

    def save_config(self):
        pass

    def notify(self, text):
        pass


NOW = datetime(2026, 11, 19, 18, 0, tzinfo=timezone.utc)
RECORD = {"trace_id": "t" * 32, "attempt_id": "a" * 32, "from": "1.31.0", "to": "1.31.2", "time": "2026-11-19T17:39:10Z",
          "platform": "linux", "channel": "stable"}

for theme in ("standard", "pro"):
    for lang in ("ru", "en"):
        i18n.set_language(lang)
        ctx = Ctx(theme)
        themes.apply_app(app, ctx.config)
        tag = f"{theme}/{lang}"
        if theme == "standard":
            pal = app.palette()
            check(pal.color(QPalette.ColorRole.ButtonText).lightness() < 60 and pal.color(QPalette.ColorRole.Window).lightness() > 200,
                  f"{tag}: Standard theme keeps a light palette on a dark system")
        # tour: language step and the next one
        image = QImage(300, 200, QImage.Format.Format_RGB32)
        image.fill(QColor("#ffffff"))
        ed = EditorWindow(image, ctx, QPoint(0, 0))
        ed.present()
        settle()
        ed.start_tour()
        settle()
        tour = ed.tour
        check(not tour.back.isVisible(), f"{tag}: first step of the tour: no «Back» button (not a pale disabled one)")
        img = audit(ed, f"{tag} tour, language step", tour.card)
        if SNAP and theme == "standard":
            card = QRect(tour.card.mapTo(ed, QPoint(0, 0)), tour.card.size()).adjusted(-16, -16, 16, 16)
            ratio = img.width() / max(ed.width(), 1)
            img.copy(QRect(int(card.x() * ratio), int(card.y() * ratio), int(card.width() * ratio),
                           int(card.height() * ratio))).save(os.path.join(SNAP, f"tour-lang-{lang}.png"))
        tour.show_step(1)
        settle()
        check(tour.back.isVisible(), f"{tag}: second step: «Back» is there")
        audit(ed, f"{tag} tour, second step", tour.card)
        tour.finish()
        ed.canvas.modified, ed.exported = False, True
        ed.close()
        # settings
        dlg = SettingsDialog(ctx.config)
        dlg.show()
        audit(dlg, f"{tag} settings")
        dlg.close()
        # update windows
        manifest = uc.Manifest(channel="stable", version="1.31.2", released=NOW, expires=NOW + timedelta(days=30),
                               files={}, notes={"ru": "- Пример", "en": "- Example"})
        windows = [("offer", lambda: up.OfferDialog(manifest, "1.31.0")),
                   ("what's new", lambda: up.WhatsNewDialog("1.31.2", "- Example notes"))]
        if hasattr(up, "FailedDialog"):   # 1.31.2
            report = up.failure_report(RECORD, "helper_exit_1", "switch", "linux", "1.31.0", now=NOW, log_lines=["start"])
            windows += [("failure", lambda: up.FailedDialog("1.31.2", report, "Update failed")),
                        ("report", lambda: up.ReportDialog(report, "Update failed"))]
        for name, make in windows:
            w = make()
            w.show()
            audit(w, f"{tag} update window: {name}")
            w.close()
        ui = up.UpdaterUI()
        ui.progress_start("1.31.2", lambda: None)
        ui.progress_update(10, 100)
        settle()
        audit(ui.progress, f"{tag} update window: download")
        if hasattr(ui, "progress_stage"):
            ui.progress_stage(i18n.tr("updater.install.started", version="1.31.2"))
            audit(ui.progress, f"{tag} update window: installing")
            ui.deferred_notice(i18n.tr("updater.wait.unsaved", version="1.31.2"), lambda: None)
            settle()
            audit(ui._notice, f"{tag} update window: waiting")
            ui._notice.close()
        ui.progress_close()
        # About (ClipDialog: white card in both themes)
        about = appmod.Clipshot.build_about(ctx)
        about.show()
        audit(about, f"{tag} About")
        about.close()

check(measured[0] > 200, f"texts measured: {measured[0]}")
print("ИТОГ:", "все проверки пройдены" if not failures else f"провалено {len(failures)}")
sys.exit(1 if failures else 0)
