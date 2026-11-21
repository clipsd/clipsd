# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later. Распространяется по лицензии GNU GPL v3 или более поздней,
# без каких-либо гарантий; полный текст: файл LICENSE или <https://www.gnu.org/licenses/gpl-3.0.html>.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""Window "Photo from phone" (after 1.32; sketch approved 17.11.2026: obzor-2026-11-17/foto-s-telefona-eskiz.html).

Where it opens: the tray menu (the photo becomes a new snapshot in the editor) and the editor's "Insert" menu
(the photo goes on top of that snapshot, like "From file"). Before the code, once until the box is ticked:
"the phone and the computer must be on the same Wi-Fi". The window has three steps (the computer is ready, point
the camera at the code, take a photo), the QR code with the address to type by hand, the time left of the code,
a small line about a VPN on the phone and "Couldn't connect?" (more visible after TROUBLE_AFTER_MS without a
phone), which opens the window of reasons: VPN, Wi-Fi, the firewall of this computer.

The receiver (phone.Receiver) lives exactly as long as this window: closing the window, Esc, quitting the program
close the socket. Its events come from other threads and are passed here through a Qt signal.
"""

import os
import shutil
import sys
import weakref

from PyQt6.QtCore import QObject, QProcess, Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QGuiApplication, QImage, QPainter, QPixmap
from PyQt6.QtWidgets import (QCheckBox, QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget)

from . import phone, qr
from .dialogs import ClipDialog
from .i18n import current, tr
from .themes import GREEN

TROUBLE_AFTER_MS = 20_000
PHOTO_QUALITY = 92          # JPEG quality of the autosaved photo (the page already sent a JPEG of 0.92)
QR_MODULE = 4              # px per module: version 3 (29 + 2 x 4 quiet) -> 148 px, as in the sketch
CONFIG_HIDE_NOTE = "phone_wifi_note_hidden"
CONFIG_FULL = "phone_full_size"   # check box "Save photos in full size": off = fit to the screen of this computer
CONFIG_FW_NETWORKS = "phone_fw_networks"   # subnets for which ClipSD already added a (permanent) ufw rule
PAGE_KEYS = ("page_title", "page_card_title", "page_step1", "page_step2", "page_intro", "page_link_ok", "page_link_lost", "page_shoot", "page_choose", "page_choose_more",
             "page_camera_note", "page_ready", "page_send_more", "page_send_end", "page_retake", "page_cancel",
             "page_finish", "page_resend", "page_queue", "page_left", "page_progress", "page_processing", "page_lost",
             "page_lost_n", "page_sending", "page_sent", "page_sent_more", "page_more", "page_done", "page_done_hint",
             "page_offer_title", "page_offer_text", "page_offer_send", "page_offer_delete", "page_saved",
             "page_offline_title", "page_offline_text", "page_expired_unsent", "page_unsent", "page_heic",
             "page_pcfail", "page_ask_title", "page_ask_text", "page_finish_without", "page_failed", "page_bad_type", "page_too_big", "page_used", "page_closed", "page_limit")
PAGE_KEYS += ("page_zoom_hint", "page_zoom_close")   # the photo big before sending (owner, 21.11.2026)
DOT = {"done": GREEN, "now": "#1660d0", "todo": "#5f6875"}   # white digit: 5.4:1, 5.8:1, 5.6:1

EXTRA_STYLE = """
QLabel#phoneStepTitle { font-weight: bold; font-size: 14px; }
QLabel#phoneStepText { color: #3c4656; font-size: 13px; }
QFrame#phoneLine { background: #eef1f5; border: none; max-height: 1px; min-height: 1px; }
QLabel#phoneAddress { background: #eef1f5; border-radius: 8px; padding: 6px 10px; color: #16181c; }
QLabel#phoneTtl { color: #5a6270; font-size: 13px; }
QLabel#phoneRecv { color: #1660d0; font-weight: bold; font-size: 13px; }
QLabel#phoneRecv[bad="true"] { color: #a32020; }
QLabel#phoneHint { background: #fff5d6; border: 1px solid #efd27e; border-radius: 8px; color: #3b2f05; padding: 6px 10px; font-size: 12px; }
QLabel#phoneAndroid { background: #eef4ff; border-radius: 8px; padding: 6px 10px; color: #16181c; font-size: 12px; }
QLabel#phoneVpn { color: #5a6270; font-size: 12px; }
QLabel#phoneWarn { background: #fff5d6; border: 1px solid #efd27e; border-radius: 8px; color: #4a3a06;
                   padding: 8px 10px; }
QLabel#phoneWifi { background: #eef4ff; border-radius: 10px; padding: 12px 14px; color: #16181c; font-size: 14px; }
QLabel#phoneCommand { background: #eef1f5; border-radius: 8px; padding: 8px 10px; color: #16181c; }
QPushButton#phoneTrouble { background: #fff6e6; color: #8a5200; border: 1px solid #e0b572; border-radius: 8px;
                           padding: 7px 14px; font-weight: bold; font-size: 13px; }
QPushButton#phoneTrouble:hover { background: #fdebc8; }
QPushButton#phoneTrouble[loud="true"] { background: #fde9c8; border: 2px solid #b26a00; color: #6b3f00; }
"""


# --- "Allow": the firewall rule through pkexec (the system shows its own password window) -----------------------

_runners = []   # a running pkexec outlives its window: the object must not be collected before it ends


class AllowRunner(QObject):
    """pkexec <ufw|firewall-cmd> ... without a shell and without waiting in the GUI thread. done(outcome, code):
    "ok", "declined" (password window dismissed), "failed". A permanent ufw rule is remembered in the settings
    here, so the result counts even when the window that asked has been closed meanwhile."""
    done = pyqtSignal(str, int)

    def __init__(self, ctx, argv, network, remember, process_factory=None):
        super().__init__()
        self.ctx, self.argv, self.network, self.remember = ctx, list(argv), network, remember
        self.process = (process_factory or QProcess)()
        self.process.finished.connect(self._finished)
        self.process.errorOccurred.connect(self._error)
        self._over = False

    def start(self):
        _runners.append(self)
        self.process.start(self.argv[0], self.argv[1:])
        self.process.closeWriteChannel()

    def _error(self, error):
        if error == QProcess.ProcessError.FailedToStart:
            self._end("failed", -1)

    def _finished(self, code, status):
        crashed = status != QProcess.ExitStatus.NormalExit
        self._end(phone.allow_outcome(code) if not crashed else "failed", code)

    def _end(self, outcome, code):
        if self._over:
            return
        self._over = True
        if outcome == "ok" and self.remember:
            try:
                nets = list(self.ctx.config.get(CONFIG_FW_NETWORKS) or [])
                if self.network not in nets:
                    nets.append(self.network)
                self.ctx.config[CONFIG_FW_NETWORKS] = nets
                self.ctx.save_config()
            except Exception:   # noqa: BLE001: a settings failure must not hide the result
                pass
        if self in _runners:
            _runners.remove(self)
        try:
            self.done.emit(outcome, code)
        except RuntimeError:
            pass
        self.deleteLater()


def start_allow(ctx, kind, network, on_done, which=None, process_factory=None):
    """Start the "Allow" for the subnet; on_done(outcome, code) later. None: no pkexec or no such tool (the caller
    shows the command to copy instead)."""
    argv = phone.firewall_allow_argv(kind, network, which or shutil.which)
    if argv is None:
        return None
    runner = AllowRunner(ctx, argv, phone.firewall_network(network), kind == "ufw", process_factory)
    runner.done.connect(on_done)
    runner.start()
    return runner


def fw_known(ctx, kind, network) -> bool:
    return kind == "ufw" and phone.firewall_network(network) in (ctx.config.get(CONFIG_FW_NETWORKS) or [])


def mono_font(px: int) -> QFont:
    """Fixed-width font of the system for the address and the command (a family list is not valid in QSS)."""
    from PyQt6.QtGui import QFontDatabase
    f = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
    f.setPixelSize(px)
    return f


def page_texts() -> dict:
    """Texts of the phone page in the language of the program (passed to the receiver, which has no i18n)."""
    return {k: tr("phone." + k) for k in PAGE_KEYS}


def qr_pixmap(text: str, module: int = QR_MODULE, dpr: float = 1.0) -> QPixmap:
    """The QR code with the quiet zone of 4 modules, sharp at any scale (whole device pixels per module)."""
    matrix = qr.encode(text)
    n = len(matrix) + 8
    px = max(1, round(module * dpr))
    image = QImage(n * px, n * px, QImage.Format.Format_RGB32)
    image.fill(QColor("#ffffff"))
    p = QPainter(image)
    for y, row in enumerate(matrix):
        for x, dark in enumerate(row):
            if dark:
                p.fillRect((x + 4) * px, (y + 4) * px, px, px, QColor("#10161f"))
    p.end()
    pix = QPixmap.fromImage(image)
    pix.setDevicePixelRatio(px / module)
    return pix


class _Session:
    """What a received photo needs, whatever happens to the window: the program (ctx), the editor to paste into, the
    receiver to confirm to, and the window itself only while it is open (a closed window must not lose a photo)."""

    def __init__(self, ctx, target, window):
        self.ctx = ctx
        self.target = target
        self.window = weakref.ref(window)
        self.receiver = None
        self.notified = False

    def live_window(self):
        win = self.window()
        if win is None:
            return None
        try:
            return None if win.closing else win
        except RuntimeError:
            return None


class _PhoneSink(QObject):
    """Photos and decode failures go to the program, not to the window: queued into the interface thread."""
    event = pyqtSignal(object, str, object)

    def __init__(self):
        super().__init__()
        self.event.connect(self._handle, Qt.ConnectionType.QueuedConnection)

    def _handle(self, session, kind, data):
        if kind == "photo":
            deliver_photo(session, data)
        else:
            deliver_failure(session, data)


_sink_obj = None
_RECEIVERS = []   # every receiver of this program run: quitting and updating look at them
_quitting = False   # stop_all is running: a photo that is still delivered says nothing about "take another"


def _sink():
    global _sink_obj
    if _sink_obj is None:
        from PyQt6.QtWidgets import QApplication
        _sink_obj = _PhoneSink()
        if QApplication.instance() is not None:
            _sink_obj.setParent(QApplication.instance())   # destroyed with the application, not after it
    return _sink_obj


def _autosave_photo(ctx, image):
    """A photo is saved as JPEG (a 12 MP photo as PNG is 8 MB and takes seconds in the GUI thread)."""
    if not hasattr(ctx, "autosave"):
        return None
    try:
        return ctx.autosave(image, ext="jpg", quality=PHOTO_QUALITY)
    except TypeError:   # a context that knows nothing of the photo format
        return ctx.autosave(image)


def _editor_closing(editor) -> bool:
    """The snapshot is being closed: the question «Снимок не сохранён» is open over it, or the window is closing
    (EditorWindow.closing, set in closeEvent)."""
    try:
        return bool(getattr(editor, "closing", False))
    except RuntimeError:   # the window is already deleted
        return True


def deliver_photo(session, data):
    """A photo came (interface thread): it is saved and opened in an editor even when the window is gone; the phone is
    told only after that. The window, if it is still open, shows what came."""
    image = data["image"]
    count = data.get("count", 0)
    pid = data.get("pid", "")
    ctx = session.ctx
    win = session.live_window()
    info = data.get("info")
    if os.environ.get("CLIPSD_PHONE_DEBUG") and info:   # the demo only: what mode came and what size it became
        src = info.get("src") or (0, 0)
        print(f"[phone-photo] mode={info.get('mode')} screen={info.get('screen')} in={src[0]}x{src[1]} "
              f"out={image.width()}x{image.height()}", flush=True)
    size = f"{image.width()} \u00d7 {image.height()}"
    ok = True
    try:
        if win is not None:
            win.count = count
            win._recv_text(tr("phone.received_open", size=size))
        editors = getattr(ctx, "editors", [])
        target = session.target if session.target is not None and session.target in editors else None
        apart = target is not None and _editor_closing(target)
        if apart:
            # 1.34.1 (Б2 проверки 1.34.0): над снимком открыт вопрос «Снимок не сохранён» (или он уже закрывается).
            # Фото, положенное туда, ушло бы вместе со снимком после «Закрыть без сохранения», а телефон уже
            # удалил свою копию. Фото открывается отдельным снимком, как без снимка-получателя.
            target = None
        screen = (win._screen() if win is not None else None) or QGuiApplication.primaryScreen()
        scale = 1.0
        if screen is not None:   # the picture in points fits the screen with the panels: window by the picture
            area = screen.availableGeometry()
            scale = phone.editor_scale(image.width(), image.height(), area.width(), area.height())
        # saved BEFORE the display scale is set: the setting "snapshot size: as on screen" shrinks by that scale,
        # a photo must keep its pixels (full size when ticked, the screen size otherwise: the computer did that).
        # 1.34.1 (Б2): also when it goes into an open snapshot: the person may still close that snapshot without
        # saving, the phone has already deleted its copy
        saved = _autosave_photo(ctx, image)
        if target is not None:
            image.setDevicePixelRatio(scale)
            target.canvas.insert_image(image)   # on top of that snapshot, like "Insert, from file"
            target.show()
            target.raise_()
            target.activateWindow()
            from .selector import force_foreground
            force_foreground(target)
        else:
            image.setDevicePixelRatio(scale)
            editor = ctx.open_editor(image, None)
            if editor is not None:
                editor.autosave_path = saved
                editor.only_in_memory = not saved
                editor.autosave_quality = PHOTO_QUALITY
                editor.phone_photo = True   # saving and copying do not go through the screen scale
            if apart:
                session.notified = True   # this message already says where the photo is
                _notify(ctx, tr("phone.photo_apart_saved", path=saved) if saved else tr("phone.photo_apart"))
    except Exception as exc:   # noqa: BLE001: a photo that came is never dropped silently
        ok = False
        _notify(ctx, tr("phone.recv_decode", n=count) + f" ({exc})")
    rx = session.receiver
    if rx is not None:
        try:
            (rx.confirm(pid) if ok else rx.reject(pid, count))
        except Exception:   # noqa: BLE001
            pass
    if win is not None and ok:
        try:
            win._photo_ui(image, count, size)
        except RuntimeError:
            win = None
    elif win is None and ok and not session.notified and not _quitting:
        session.notified = True
        _notify(ctx, tr("phone.photo_late"))


def deliver_failure(session, data):
    """The computer could not open a photo that was accepted: visible on the computer, the phone learns it too."""
    win = session.live_window()
    text = tr("phone.recv_decode", n=data.get("count", 0))
    if win is not None:
        win._recv_text(text, bad=True)
    _notify(session.ctx, text)


def _notify(ctx, text):
    notify = getattr(ctx, "notify", None)
    if notify is not None:
        try:
            notify(text)
        except Exception:   # noqa: BLE001: a notification must not break the photo
            pass


def flush_photos(timeout: float = 5.0):
    """Quitting: photos that are being opened are waited for and delivered (the queued events are run)."""
    from PyQt6.QtWidgets import QApplication
    for rx in list(_RECEIVERS):
        rx.wait_idle(timeout)
    if QApplication.instance() is not None:
        for _ in range(5):
            QApplication.processEvents()


def is_busy() -> bool:
    """The reception is open (the window visible or hidden after a photo) or a photo is being opened: the program must
    not be closed for an update now, the same as with an editor that is not saved."""
    if current_window() is not None:
        return True
    for rx in list(_RECEIVERS):
        try:
            if rx.running or rx._busy > 0:
                return True
        except Exception:   # noqa: BLE001
            continue
    return False


class _Bridge(QObject):
    """Events of the receiver from its threads into the GUI thread (queued connection)."""
    event = pyqtSignal(str, object)


class Step(QWidget):
    """A step of the window: a round number (green done, blue now, grey later), a title, a line, extra widgets."""

    def __init__(self, number: int, title: str, text: str = "", pad: int = 10):
        super().__init__()
        row = QHBoxLayout(self)
        row.setContentsMargins(0, pad, 0, pad)
        row.setSpacing(12)
        self.dot = QLabel(str(number))
        self.dot.setFixedSize(30, 30)
        self.dot.setAlignment(Qt.AlignmentFlag.AlignCenter)
        row.addWidget(self.dot, 0, Qt.AlignmentFlag.AlignTop)
        col = QVBoxLayout()
        col.setSpacing(3)
        self.title = QLabel(title)
        self.title.setObjectName("phoneStepTitle")
        self.title.setWordWrap(True)
        self.text = QLabel(text)
        self.text.setObjectName("phoneStepText")
        self.text.setWordWrap(True)
        self.text.setVisible(bool(text))
        col.addWidget(self.title)
        col.addWidget(self.text)
        self.extra = col
        row.addLayout(col, 1)
        self.set_state("todo")

    def set_state(self, state: str):
        self.state = state
        self.dot.setStyleSheet(f"QLabel {{ background: {DOT[state]}; color: #ffffff; border-radius: 15px; "
                               "font-weight: bold; font-size: 15px; }")
        self.dot.setText("✓" if state == "done" else self.dot.property("n") or self.dot.text())

    def set_text(self, title: str = None, text: str = None):
        if title is not None:
            self.title.setText(title)
        if text is not None:
            self.text.setText(text)
            self.text.setVisible(bool(text))


class Check(QCheckBox):
    """A checkbox drawn by us: the same box on Linux and Windows and in the offscreen check (the Fusion box under the
    dialog's style sheet came out empty). 18 px square, blue with a white tick when on, a ring on keyboard focus."""

    BOX = 18
    GAP = 8

    def sizeHint(self):
        from PyQt6.QtCore import QSize
        fm = self.fontMetrics()
        return QSize(self.BOX + self.GAP + fm.horizontalAdvance(self.text()) + 4, max(self.BOX + 6, fm.height() + 6))

    minimumSizeHint = sizeHint

    def hitButton(self, pos):
        return self.rect().contains(pos)

    def paintEvent(self, event):
        from PyQt6.QtCore import QPointF, QRectF
        from PyQt6.QtGui import QPainterPath, QPen
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        y = (self.height() - self.BOX) / 2
        box = QRectF(1, y, self.BOX, self.BOX)
        if self.hasFocus():
            p.setPen(QPen(QColor("#1e78ff"), 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(box.adjusted(-2, -2, 2, 2), 6, 6)
        on = self.isChecked()
        p.setPen(QPen(QColor("#1660d0" if on else "#5f6875"), 1.6))
        p.setBrush(QColor("#1660d0" if on else "#ffffff"))
        p.drawRoundedRect(box.adjusted(0.8, 0.8, -0.8, -0.8), 4, 4)
        if on:
            path = QPainterPath(QPointF(box.left() + 4.5, box.top() + 9.5))
            path.lineTo(QPointF(box.left() + 7.8, box.top() + 12.8))
            path.lineTo(QPointF(box.left() + 13.8, box.top() + 5.6))
            p.setPen(QPen(QColor("#ffffff"), 2.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                          Qt.PenJoinStyle.RoundJoin))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(path)
        p.setPen(QColor("#16181c"))
        p.setFont(self.font())
        p.drawText(QRectF(self.BOX + self.GAP, 0, self.width() - self.BOX - self.GAP, self.height()),
                   int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), self.text())
        p.end()


def fit_to_content(window):
    """Size of the window by its content: the real height of wrapped lines (heightForWidth), at most the screen.
    QWidget.adjustSize would cap a window at 2/3 of the screen: on 1280 x 720 the window of reasons was cut."""
    lay = window.layout()
    if lay is None:
        return
    lay.activate()
    w = window.sizeHint().width()
    h = lay.totalHeightForWidth(w) if lay.hasHeightForWidth() else window.sizeHint().height()
    screen = window.screen() or QGuiApplication.primaryScreen()
    if screen is not None:
        h = min(h, screen.availableGeometry().height())
    window.resize(w, max(h, window.minimumSizeHint().height() if h <= 0 else h))


class _FitMixin:
    def adjustSize(self):   # ClipDialog.open_centered calls it before centring
        fit_to_content(self)


def _line() -> QFrame:
    f = QFrame()
    f.setObjectName("phoneLine")
    return f


class WifiNote(_FitMixin, ClipDialog):
    """Before the code: both devices in one Wi-Fi. "Don't show again" is remembered in the settings."""

    def __init__(self, ctx, on_ok):
        super().__init__(None, tr("phone.title"), "", "info", 520)
        self.card.setFixedWidth(520)
        self.card.setStyleSheet(EXTRA_STYLE)   # on the card: a second sheet on the window did not reach new labels
        self.ctx = ctx
        self._on_ok = on_ok
        note = QLabel(tr("phone.wifi_text"))
        note.setObjectName("phoneWifi")
        note.setWordWrap(True)
        self.body.addWidget(note)
        self.hide_box = Check(tr("phone.wifi_hide"))
        self.hide_box.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.body.addWidget(self.hide_box)
        self.cancel_btn = self.secondary(tr("phone.cancel"))
        self.ok_btn = self.primary(tr("phone.wifi_ok"))
        self.cancel_btn.clicked.connect(self.close)
        self.ok_btn.clicked.connect(self._ok)

    def _ok(self):
        if self.hide_box.isChecked():
            self.ctx.config[CONFIG_HIDE_NOTE] = True
            self.ctx.save_config()
        on_ok, self._on_ok = self._on_ok, None
        self.close()
        if on_ok is not None:
            QTimer.singleShot(200, on_ok)   # the next window after a pause (desktop-app-design, section 4)


class PhoneDialog(_FitMixin, ClipDialog):
    """The window with the code. target: the editor that asked for the photo ("Insert"), else None."""

    def __init__(self, ctx, target=None, candidates=None, receiver_cls=phone.Receiver, firewall=None, which=None,
                 process_factory=None):
        super().__init__(None, tr("phone.title"), "", "info", 600)
        self.card.setFixedWidth(600)   # a known width: wrapped lines get their real height (heightForWidth)
        # not above every window: the editor with the photo has to come up over it
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.card.setStyleSheet(EXTRA_STYLE)   # on the card: a second sheet on the window did not reach new labels
        self.ctx = ctx
        self.session = _Session(ctx, target, self)
        _sink()   # made here, in the interface thread: the receiver's threads only send to it
        self.receiver = None
        self.receiver_cls = receiver_cls
        self._candidates = candidates
        self._firewall = firewall            # None: look at this computer; "": no firewall (tests, snapshots)
        self._which, self._process_factory = which, process_factory
        self._fw_done = False                # "Allow" done or skipped in this window
        self.runner = None
        self.closing = False
        self.hidden_for_photo = False   # the window hid itself after a photo; the receiver is still open
        self._notified = False
        self.candidate = None
        self.count = 0
        self.connected = False
        self.trouble_dialog = None
        self.bridge = _Bridge()
        self.bridge.event.connect(self._on_event, Qt.ConnectionType.QueuedConnection)   # never inside the receiver's lock

        self.step1 = Step(1, tr("phone.step1_title"))
        self.step2 = Step(2, tr("phone.step2_title"), tr("phone.step2_text"))
        self.step3 = Step(3, tr("phone.step3_title"), tr("phone.step3_text"))
        for s, n in ((self.step1, 1), (self.step2, 2), (self.step3, 3)):
            s.dot.setProperty("n", str(n))
        qr_row = QHBoxLayout()
        qr_row.setSpacing(16)
        self.qr_label = QLabel()
        self.qr_label.setAccessibleName(tr("phone.step2_title"))
        qr_row.addWidget(self.qr_label, 0, Qt.AlignmentFlag.AlignTop)
        right = QVBoxLayout()
        right.setSpacing(6)
        manual = QLabel(tr("phone.manual"))
        manual.setObjectName("phoneStepText")
        manual.setWordWrap(True)
        self.address = QLabel()
        self.address.setObjectName("phoneAddress")
        self.address.setFont(mono_font(14))
        self.address.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.ttl = QLabel()
        self.ttl.setObjectName("phoneTtl")
        right.addWidget(manual)
        right.addWidget(self.address, 0, Qt.AlignmentFlag.AlignLeft)
        right.addWidget(self.ttl)
        self.android = QLabel(tr("phone.android17"))
        self.android.setObjectName("phoneAndroid")
        self.android.setWordWrap(True)
        right.addWidget(self.android)
        right.addStretch(1)
        qr_row.addLayout(right, 1)
        self.qr_box = QWidget()
        self.qr_box.setLayout(qr_row)
        qr_row.setContentsMargins(0, 6, 0, 0)
        self.step2.extra.addWidget(self.qr_box)
        self.warn = QLabel()
        self.warn.setObjectName("phoneWarn")
        self.warn.setWordWrap(True)
        self.warn.setVisible(False)
        self.step2.extra.addWidget(self.warn)
        self.hint = QLabel()   # opens by itself 20 s after the code was shown and nobody came; folds when the phone connects
        self.hint.setObjectName("phoneHint")
        self.hint.setWordWrap(True)
        self.hint.setTextFormat(Qt.TextFormat.RichText)
        self.hint.setVisible(False)
        self.step2.extra.addWidget(self.hint)
        self.new_code_btn = QPushButton(tr("phone.new_code"))
        self.new_code_btn.setObjectName("clipSecondary")
        self.new_code_btn.setVisible(False)
        self.new_code_btn.clicked.connect(self.new_code)
        self.step2.extra.addWidget(self.new_code_btn, 0, Qt.AlignmentFlag.AlignLeft)
        self.fw_box = QWidget()   # the "Allow" step (only when a firewall is on): instead of the code
        fw = QVBoxLayout(self.fw_box)
        fw.setContentsMargins(0, 6, 0, 0)
        fw.setSpacing(8)
        self.allow_btn = QPushButton(tr("phone.fw_allow"))
        self.allow_btn.setObjectName("clipPrimary")
        self.allow_btn.clicked.connect(self.allow)
        self.fw_command = QLabel()
        self.fw_command.setObjectName("phoneCommand")
        self.fw_command.setFont(mono_font(12))
        self.fw_command.setWordWrap(True)
        self.fw_command.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.fw_copy_btn = QPushButton(tr("phone.copy_command"))
        self.fw_copy_btn.setObjectName("clipSecondary")
        self.fw_copy_btn.clicked.connect(self.copy_fw_command)
        self.fw_next_btn = QPushButton(tr("phone.show_code_now"))
        self.fw_next_btn.setObjectName("clipPrimary")
        self.fw_next_btn.clicked.connect(self.skip_allow)
        self.fw_status = QLabel()
        self.fw_status.setObjectName("phoneStepText")
        self.fw_status.setWordWrap(True)
        self.fw_status.setVisible(False)
        row_btn = QHBoxLayout()
        row_btn.setSpacing(8)
        for b in (self.allow_btn, self.fw_copy_btn, self.fw_next_btn):
            row_btn.addWidget(b)
        row_btn.addStretch(1)
        fw.addWidget(self.fw_command)
        fw.addLayout(row_btn)
        fw.addWidget(self.fw_status)
        self.fw_box.setVisible(False)
        self.step2.extra.addWidget(self.fw_box)
        self.received_box = QWidget()   # hidden until the first photo (an empty layout would skew the step)
        thumbs = QHBoxLayout(self.received_box)
        thumbs.setContentsMargins(0, 6, 0, 0)
        thumbs.setSpacing(10)
        self.thumb = QLabel()
        self.received = QLabel()
        self.received.setObjectName("phoneStepTitle")
        self.received.setStyleSheet(f"QLabel {{ color: {GREEN}; }}")
        thumbs.addWidget(self.thumb)
        thumbs.addWidget(self.received, 1)
        self.received_box.setVisible(False)
        self.step3.extra.addWidget(self.received_box)
        self.recv = QLabel()   # "Receiving the photo... 40 %", "Photo received: 1920 x 1080. Opening...", the error
        self.recv.setObjectName("phoneRecv")
        self.recv.setWordWrap(True)
        self.recv.setVisible(False)
        self.step3.extra.addWidget(self.recv)
        self.body.setSpacing(0)
        self.body.addWidget(self.step1)
        self.body.addWidget(_line())
        self.body.addWidget(self.step2)
        self.body.addWidget(_line())
        self.body.addWidget(self.step3)
        self.full_box = Check(tr("phone.full_size"))   # the choice lives on the computer, not on the phone
        self.full_box.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.full_box.setChecked(bool(ctx.config.get(CONFIG_FULL)))
        self.full_box.toggled.connect(self._full_toggled)
        self.body.addSpacing(6)
        self.body.addWidget(self.full_box)
        self.vpn = QLabel(tr("phone.vpn_hint"))
        self.vpn.setObjectName("phoneVpn")
        self.vpn.setWordWrap(True)
        self.body.addSpacing(6)
        self.body.addWidget(self.vpn)
        self.trouble_btn = QPushButton(tr("phone.trouble"))
        self.trouble_btn.setObjectName("phoneTrouble")
        self.trouble_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.trouble_btn.clicked.connect(self.show_trouble)
        self.footer_left.addWidget(self.trouble_btn)
        self.retry_btn = self.secondary(tr("phone.retry"))
        self.retry_btn.setVisible(False)
        self.retry_btn.clicked.connect(self.start)
        self.close_btn = self.secondary(tr("phone.close"))
        self.close_btn.clicked.connect(self.close)

        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self._tick)
        self.trouble_timer = QTimer(self)
        self.trouble_timer.setSingleShot(True)
        self.trouble_timer.setInterval(TROUBLE_AFTER_MS)
        self.trouble_timer.timeout.connect(self._no_phone_yet)

    # --- receiver -----------------------------------------------------------------

    def candidates(self) -> list:
        return list(self._candidates) if self._candidates is not None else phone.lan_candidates()

    def start(self) -> bool:
        """Find the home network; if a firewall is on and has no rule for it yet, the "Allow" step first; then open
        the receiver and show the code. False: no network or no socket."""
        self.stop()
        self.retry_btn.setVisible(False)
        self.fw_box.setVisible(False)
        found = self.candidates()
        if not found:
            self._fail(tr("phone.no_network"))
            return False
        self.candidate = found[0]
        key = {"wifi": "phone.step1_wifi", "ethernet": "phone.step1_cable"}.get(self.candidate.get("kind"),
                                                                              "phone.step1_other")
        kind = self.firewall_kind()
        net = phone.network_of(self.candidate)
        if kind and not self._fw_done and phone.firewall_network(net) and not fw_known(self.ctx, kind, net):
            self.step1.set_text(text=tr("phone.step1_net", address=self.candidate["ip"]))   # reception is not open yet
            self.step1.set_state("done")
            self._show_allow(kind, net)
            return True
        return self._open_receiver(key)

    @property
    def target(self):
        return self.session.target

    @target.setter
    def target(self, value):
        self.session.target = value

    def _screen(self):
        return self.screen() or QGuiApplication.primaryScreen()

    def screen_pixels(self):
        """Size of the screen this window is on, in physical pixels (the page fits the photo into it)."""
        sc = self._screen()
        if sc is None:
            return None
        g, dpr = sc.geometry(), sc.devicePixelRatio()
        return (round(g.width() * dpr), round(g.height() * dpr))

    def _full_toggled(self, on: bool):
        """The check box: remembered in the settings, valid for the next photo at once."""
        self.ctx.config[CONFIG_FULL] = bool(on)
        try:
            self.ctx.save_config()
        except Exception:   # noqa: BLE001
            pass
        if self.receiver is not None:
            self.receiver.full_size = bool(on)

    def _route(self, kind, data):
        """Events of the receiver (its threads): photos and decode failures to the program (they must reach it even when
        this window is gone), the rest to this window; both through a queue into the interface thread."""
        if kind == "photo" or (kind == "failed" and data.get("error") == "decode"):
            _sink().event.emit(self.session, kind, data)
        else:
            self.bridge.event.emit(kind, data)

    def firewall_kind(self) -> str:
        if sys.platform == "win32":
            return ""
        return phone.linux_firewall() if self._firewall is None else self._firewall

    def _open_receiver(self, key=None) -> bool:
        if key is None:
            key = {"wifi": "phone.step1_wifi", "ethernet": "phone.step1_cable"}.get(self.candidate.get("kind"),
                                                                                  "phone.step1_other")
        self.receiver = self.receiver_cls(self.candidate["ip"], network=phone.network_of(self.candidate),
                                          on_event=self._route,
                                          texts=page_texts(), lang=current(), screen=self.screen_pixels())
        try:
            self.receiver.start()
        except OSError as exc:
            self.receiver = None
            self._fail(tr("phone.bind_failed", error=str(exc)))
            return False
        self.receiver.full_size = self.full_box.isChecked()
        self.session.receiver = self.receiver
        _RECEIVERS[:] = [r for r in _RECEIVERS if r.running or r._busy > 0]
        _RECEIVERS.append(self.receiver)
        self.step1.set_text(text=tr(key, address=self.candidate["ip"]))
        self.step1.set_state("done")
        self._show_code()
        self.timer.start()
        return True

    # --- "Allow" (the firewall of this computer) ----------------------------------------------------------

    def _show_allow(self, kind: str, net: str):
        self._fw_kind, self._fw_net = kind, net
        self.qr_box.setVisible(False)
        self.warn.setVisible(False)
        self.new_code_btn.setVisible(False)
        self.ttl.setVisible(False)
        self.step2.set_text(tr("phone.fw_title"), tr("phone.fw_text", count=len(phone.PREFERRED_PORTS)))
        self.step2.set_state("now")
        self.step3.set_state("todo")
        can = phone.firewall_allow_argv(kind, net, self._which or shutil.which) is not None
        self.allow_btn.setVisible(can)
        self.allow_btn.setEnabled(True)
        command = "" if can else phone.linux_firewall_command(kind, net)
        self.fw_command.setText(command)
        self.fw_command.setVisible(bool(command))
        self.fw_copy_btn.setVisible(bool(command))
        self.fw_next_btn.setVisible(bool(command))
        self.fw_status.setVisible(not can)
        if not can:
            self.fw_status.setText(tr("phone.fw_nopkexec"))
        self.fw_box.setVisible(True)
        self.trouble_btn.setVisible(True)
        self._relayout()

    def allow(self):
        if self.runner is not None:
            return
        self.allow_btn.setEnabled(False)
        self.fw_status.setText(tr("phone.fw_working"))
        self.fw_status.setVisible(True)
        self.runner = start_allow(self.ctx, self._fw_kind, self._fw_net, self._allow_done, self._which,
                                  self._process_factory)
        if self.runner is None:
            self.allow_btn.setEnabled(True)
            self._show_allow(self._fw_kind, self._fw_net)
        self._relayout()

    def _allow_done(self, outcome: str, code: int):
        self.runner = None
        if self.closing:
            return   # the window was closed while the password window was open: nothing to show
        try:
            if outcome == "ok":
                self._fw_done = True
                self.fw_box.setVisible(False)
                if self._open_receiver():
                    self.step2.set_text(text=tr("phone.fw_ok"))
                    self._relayout()
                return
            self.allow_btn.setEnabled(True)
            self.fw_status.setText(tr("phone.fw_declined") if outcome == "declined"
                                   else tr("phone.fw_failed", code=code))
            self.fw_status.setVisible(True)
            self._relayout()
        except RuntimeError:
            pass   # the window is already deleted

    def copy_fw_command(self):
        QGuiApplication.clipboard().setText(self.fw_command.text())
        self.fw_status.setText(tr("phone.copied"))
        self.fw_status.setVisible(True)

    def skip_allow(self):
        """No pkexec: the person ran the command by hand (or will not): show the code."""
        self._fw_done = True
        self.fw_box.setVisible(False)
        self._open_receiver()

    def stop(self):
        self.timer.stop()
        self.trouble_timer.stop()
        receiver, self.receiver = self.receiver, None
        if receiver is not None:
            receiver.stop()

    def new_code(self):
        if self.receiver is None or not self.receiver.running:
            self.start()
            return
        self.receiver.renew()
        self._show_code()

    def _show_code(self):
        url = self.receiver.url
        dpr = self.devicePixelRatioF() if self.isVisible() else (QGuiApplication.primaryScreen().devicePixelRatio()
                                                                 if QGuiApplication.primaryScreen() else 1.0)
        self.qr_label.setPixmap(qr_pixmap(url, dpr=dpr))
        self.address.setText(url.split("://", 1)[1])
        self.qr_box.setVisible(True)
        self.android.setVisible(not self.hint.isVisible())
        self.warn.setVisible(False)
        self.new_code_btn.setVisible(False)
        self.connected = False
        self.step2.set_text(tr("phone.step2_title"), tr("phone.step2_text"))
        self.step2.set_state("now")
        self.step3.set_state("todo")
        self._update_ttl()
        self._trouble_loud(False)
        self.collapse_hint()
        self.android.setVisible(True)
        self.trouble_timer.start()
        self._relayout()

    def _fail(self, text: str):
        self.step1.set_text(text=text)
        self.step1.set_state("now")
        self.step2.set_state("todo")
        self.qr_box.setVisible(False)
        self.retry_btn.setVisible(True)
        self._relayout()

    def _relayout(self):
        """The window follows its content: smaller when the code is hidden, without empty space under the title."""
        fit_to_content(self)

    def _tick(self):
        if self.receiver is not None:
            self.receiver.tick()
            self._update_ttl()

    def _update_ttl(self):
        if self.receiver is None or self.connected:
            self.ttl.setVisible(False)
            return
        left = self.receiver.remaining()
        self.ttl.setVisible(left > 0)
        self.ttl.setText(tr("phone.ttl", time=f"{left // 60}:{left % 60:02d}"))

    def _no_phone_yet(self):
        """20 s after the code was shown nobody connected: the button gets louder and the hint opens in place of the
        extra lines (the code stays visible, no new window)."""
        self._trouble_loud(True)
        self.expand_hint()

    def expand_hint(self):
        import html
        if self.connected or self.closing or self.receiver is None or not self.qr_box.isVisible():
            return   # the phone came at this very moment (or the code is gone): nothing to open
        e = lambda k, **kw: html.escape(tr("phone." + k, **kw))   # noqa: E731
        self.hint.setText(f"<b>{e('hint_title')}</b><br>1. {e('hint_android')}<br>2. {e('hint_vpn')}<br>3. {e('hint_wifi')}")
        self.hint.setVisible(True)
        for w in (self.android, self.step3, self.vpn):   # room for the hint: the window stays on a 1280 x 720 screen
            w.setVisible(False)
        self._relayout_settled()

    def _relayout_settled(self):
        """A wrapped label gets its height one event later: lay out now and once more right after."""
        from PyQt6.QtCore import QEvent
        from PyQt6.QtWidgets import QApplication
        QApplication.sendPostedEvents(None, QEvent.Type.LayoutRequest.value)
        self._relayout()
        QTimer.singleShot(0, self._relayout_if_alive)

    def collapse_hint(self):
        if not self.hint.isVisible():
            return
        self.hint.setVisible(False)
        self.step3.setVisible(True)
        self.vpn.setVisible(True)
        self._relayout_settled()

    def _trouble_loud(self, loud: bool):
        self.trouble_btn.setProperty("loud", "true" if loud else "false")
        self.trouble_btn.style().unpolish(self.trouble_btn)
        self.trouble_btn.style().polish(self.trouble_btn)

    # --- events ------------------------------------------------------------------

    def _on_event(self, kind: str, data):
        if kind == "connected":
            self.connected = True
            self.trouble_timer.stop()
            self._trouble_loud(False)
            self.collapse_hint()
            self.qr_box.setVisible(False)
            self.android.setVisible(False)
            self.step2.set_text(tr("phone.step2_done"), tr("phone.step2_done_text"))
            self.step2.set_state("done")
            self.step3.set_state("now")
            self._update_ttl()
            self._relayout()
        elif kind == "receiving":
            self._recv_text(tr("phone.receiving", percent=0))
        elif kind == "progress":
            self._recv_text(tr("phone.receiving", percent=data.get("percent", 0)))
        elif kind == "failed":
            if data.get("error") == "decode":   # came and answered, but the computer could not open it
                deliver_failure(self.session, data)
            else:
                self._recv_text(tr("phone.recv_heic") if data.get("error") == "heic" else tr("phone.recv_failed"), bad=True)
        elif kind == "timing":
            if os.environ.get("CLIPSD_PHONE_DEBUG"):   # the demo only: step times measured on the phone, no code, no address
                print("[phone-timing]", data.get("text", ""), flush=True)
        elif kind == "photo":
            deliver_photo(self.session, data)
        elif kind == "closed":
            self._closed(data.get("reason", ""))

    def _recv_text(self, text: str, bad: bool = False):
        if self.closing:
            return
        self.recv.setProperty("bad", "true" if bad else "false")
        self.recv.style().unpolish(self.recv)
        self.recv.style().polish(self.recv)
        changed = not self.recv.isVisible() or abs(len(self.recv.text()) - len(text)) > 3   # a percent changes by 1-2 digits
        self.recv.setText(text)
        self.recv.setVisible(True)
        self.step3.set_state("now")
        if changed:
            self.recv.updateGeometry()
            from PyQt6.QtCore import QEvent
            from PyQt6.QtWidgets import QApplication
            QApplication.sendPostedEvents(None, QEvent.Type.LayoutRequest.value)   # the wrapped label gets its size now
            self._relayout()
            QTimer.singleShot(0, self._relayout_if_alive)   # a wrapped line gets its height one event later

    def _relayout_if_alive(self):
        try:
            if not self.closing:
                self._relayout()
        except RuntimeError:
            pass

    def _closed(self, reason: str):
        texts = {"expired": tr("phone.expired"), "locked": tr("phone.locked"),
                 "limit": tr("phone.limit", max=phone.MAX_PHOTOS), "idle": tr("phone.idle"),
                 "phone": tr("phone.phone_done")}
        if reason not in texts:
            return
        if self.hidden_for_photo and not self.closing:
            if reason == "phone":
                notify = getattr(self.ctx, "notify", None)
                if notify is not None:
                    try:
                        notify(tr("phone.finished_note"))
                    except Exception:   # noqa: BLE001
                        pass
            self.close()   # nobody is looking at this window: the reception ended (2 minutes, the limit): all closes
            return
        self.trouble_timer.stop()
        self.collapse_hint()
        self.qr_box.setVisible(False)
        self.warn.setText(texts[reason])
        self.warn.setVisible(True)
        self.new_code_btn.setVisible(True)
        self.step2.set_state("now")
        self.step3.set_state("done" if self.count else "todo")
        self.ttl.setVisible(False)
        self._relayout()

    def _photo(self, image: QImage, count: int, info=None):
        """A photo came (also called directly): see deliver_photo."""
        deliver_photo(self.session, {"image": image, "count": count, "info": info, "pid": ""})

    def _photo_ui(self, image: QImage, count: int, size: str):
        """What this window shows about a photo that has been opened, then it steps aside."""
        thumb = QPixmap.fromImage(image.scaled(64, 48, Qt.AspectRatioMode.KeepAspectRatio,
                                               Qt.TransformationMode.SmoothTransformation))
        self.thumb.setPixmap(thumb)
        self.received.setText(tr("phone.received_size", count=count, size=size))
        self.recv.setVisible(False)
        self.received_box.setVisible(True)
        self.step3.set_state("now")
        self._relayout()
        self._hide_after_photo()

    def _hide_after_photo(self):
        """The photo is open in its editor, which comes to the front: this window steps aside by itself. The receiver
        stays open (AFTER_PHOTO_TTL) for \"Take another\"; one notification says so; the menu item brings the window back."""
        if self.closing:
            return
        self.hidden_for_photo = True
        self.hide()
        rx = self.receiver
        open_now = rx is not None and rx.running and rx.state != phone.CLOSED
        if not self._notified and open_now and not _quitting:   # nothing to promise when the reception is closing
            self._notified = True
            notify = getattr(self.ctx, "notify", None)
            if notify is not None:
                try:
                    notify(tr("phone.hidden_note", minutes=phone.AFTER_PHOTO_TTL // 60))
                except Exception:   # noqa: BLE001: a notification must not break the photo
                    pass

    def bring_back(self):
        """Menu item while the window is hidden: the same window again (with the same code), not a second one."""
        self.hidden_for_photo = False
        self.open_centered()

    def _autosave(self, image: QImage):
        return _autosave_photo(self.ctx, image)

    # --- the window of reasons ----------------------------------------------------------

    def show_trouble(self):
        if self.trouble_dialog is not None:
            try:
                self.trouble_dialog.raise_()
                self.trouble_dialog.activateWindow()
                return
            except RuntimeError:
                self.trouble_dialog = None
        self.trouble_dialog = TroubleDialog(self)
        self.trouble_dialog.destroyed.connect(lambda *_: setattr(self, "trouble_dialog", None))
        self.trouble_dialog.open_centered()

    def closeEvent(self, event):
        self.closing = True
        self.stop()
        if self.trouble_dialog is not None:
            try:
                self.trouble_dialog.close()
            except RuntimeError:
                pass
        super().closeEvent(event)


class FirewallJob(QThread):
    """Windows, "Allow again": the UAC prompt and the elevated PowerShell (netsh by full path, the whole command in
    -EncodedCommand), awaited in the background; ClipSD itself is not elevated. done(ok, reason, declined)."""
    done = pyqtSignal(bool, str, bool)

    def run(self):
        from . import sysenv
        try:
            code, reason, declined = sysenv.run_elevated_wait(sysenv.powershell_exe(), phone.firewall_parameters(),
                                                              120_000)
        except (OSError, ValueError) as exc:
            code, reason, declined = None, str(exc), False
        self.done.emit(code == 0, reason or f"exit {code}", declined)


_firewall_jobs = []   # live jobs: a QThread must not be deleted while it runs


def _forget_firewall(job):
    if job in _firewall_jobs:
        _firewall_jobs.remove(job)
    job.deleteLater()


class TroubleDialog(_FitMixin, ClipDialog):
    """"The phone has not connected yet": VPN first (the most frequent reason), then Wi-Fi, then this computer."""

    def __init__(self, owner: PhoneDialog, platform: str = None, firewall: str = None, which=None,
                 process_factory=None):
        super().__init__(None, tr("phone.help_title"), "", "warning", 600)
        self.card.setFixedWidth(600)
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.card.setStyleSheet(EXTRA_STYLE)   # on the card: a second sheet on the window did not reach new labels
        self.owner = owner
        self.closing = False
        self.runner = None
        self._which, self._process_factory = which, process_factory
        platform = platform or sys.platform
        s0 = Step(1, tr("phone.help_vpn_title"), tr("phone.help_vpn_text"), pad=5)
        s0.set_state("now")
        s1 = Step(2, tr("phone.help_android_title"), tr("phone.help_android_text"), pad=5)   # Android 17: local network
        s2 = Step(3, tr("phone.help_wifi_title"), tr("phone.help_wifi_text"), pad=5)
        s3 = Step(4, tr("phone.help_fw_title"), pad=5)
        self.command = ""
        self.allow_btn = self.copy_btn = None
        self.status = QLabel()
        self.status.setObjectName("phoneStepText")
        self.status.setWordWrap(True)
        self.status.setVisible(False)
        if platform == "win32":
            s3.set_text(text=tr("phone.help_fw_win") + "\n" + tr("phone.help_fw_public"))
            self.allow_btn = self.secondary(tr("phone.allow_again"))
            self.allow_btn.clicked.connect(self.allow_again)
        else:
            kind = phone.linux_firewall() if firewall is None else firewall
            cand = owner.candidate if owner is not None else None
            network = phone.network_of(cand) if cand else "192.168.0.0/16"
            self.command = phone.linux_firewall_command(kind, network) if kind else ""
            self.fw_kind, self.fw_net = kind, network
            if kind and phone.firewall_allow_argv(kind, network, which or shutil.which) is not None:
                self.command = ""   # pkexec is there: the button, not a command
                s3.set_text(text=tr("phone.help_fw_allow", count=len(phone.PREFERRED_PORTS)))
                self.allow_btn = QPushButton(tr("phone.fw_allow"))
                self.allow_btn.setObjectName("clipPrimary")
                self.allow_btn.clicked.connect(self.allow_linux)
                s3.extra.addWidget(self.allow_btn, 0, Qt.AlignmentFlag.AlignLeft)
            elif self.command:
                s3.set_text(text=tr("phone.help_fw_linux"))
                cmd = QLabel(self.command)
                cmd.setObjectName("phoneCommand")
                cmd.setFont(mono_font(12))
                cmd.setWordWrap(True)
                cmd.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
                s3.extra.addWidget(cmd)
                self.copy_btn = self.secondary(tr("phone.copy_command"))
                self.copy_btn.clicked.connect(self.copy_command)
            else:
                s3.set_text(text=tr("phone.help_fw_other", ports=f"{phone.PREFERRED_PORTS[0]}-{phone.PREFERRED_PORTS[-1]}"))
        s3.extra.addWidget(self.status)
        pcvpn = QLabel(tr("phone.help_pcvpn"))   # a VPN on the computer: usually harmless
        pcvpn.setObjectName("phoneStepText")
        pcvpn.setWordWrap(True)
        s3.extra.addWidget(pcvpn)
        # the reasons and the rows below scroll inside the window: the window never grows over the screen
        from PyQt6.QtWidgets import QScrollArea
        inner = QWidget()
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(0, 0, 6, 0)
        lay.setSpacing(0)
        for i, s in enumerate((s0, s1, s2, s3), 1):
            s.dot.setProperty("n", str(i))
            if i > 1:
                lay.addWidget(_line())
            lay.addWidget(s)
        lay.addWidget(_line())
        after = QLabel(tr("phone.help_after_title"))
        after.setObjectName("phoneStepTitle")
        after.setWordWrap(True)
        after.setContentsMargins(0, 10, 0, 4)
        lay.addWidget(after)
        for key in ("help_r_expired", "help_r_taken", "help_r_limit", "help_r_big", "help_r_heic", "help_r_open",
                    "help_r_iphone"):
            row = QLabel("\u2022 " + tr("phone." + key))
            row.setObjectName("phoneStepText")
            row.setWordWrap(True)
            row.setContentsMargins(0, 0, 0, 5)
            lay.addWidget(row)
        self.steps = (s0, s1, s2, s3)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setWidget(inner)
        inner.setObjectName("phoneInner")
        inner.setStyleSheet("QWidget#phoneInner { background: transparent; }")
        self.scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        try:
            screen = (owner.screen() if owner is not None else None) or QGuiApplication.primaryScreen()
        except RuntimeError:   # the window that asked is already closed
            screen = QGuiApplication.primaryScreen()
        cap = max(220, (screen.availableGeometry().height() if screen else 720) - 235)   # title, buttons, margins
        lay.activate()
        want = lay.totalHeightForWidth(500) + 4 if lay.hasHeightForWidth() else inner.sizeHint().height()
        self.scroll.setFixedHeight(min(want, cap))
        self.body.addWidget(self.scroll)
        self.show_btn = self.primary(tr("phone.show_code"))
        self.show_btn.clicked.connect(self.back_to_code)

    def allow_linux(self):
        if self.runner is not None:
            return
        ctx = self.owner.ctx if self.owner is not None else None
        self.allow_btn.setEnabled(False)
        self.status.setText(tr("phone.fw_working"))
        self.status.setVisible(True)
        self.runner = start_allow(ctx, self.fw_kind, self.fw_net, self._allow_done, self._which, self._process_factory)
        if self.runner is None:
            self.allow_btn.setEnabled(True)

    def _allow_done(self, outcome: str, code: int):
        self.runner = None
        if self.closing:
            return
        try:
            self.allow_btn.setEnabled(outcome != "ok")
            self.status.setText(tr("phone.fw_ok") if outcome == "ok" else tr("phone.fw_declined")
                                if outcome == "declined" else tr("phone.fw_failed", code=code))
            self.status.setVisible(True)
        except RuntimeError:
            pass

    def closeEvent(self, event):
        self.closing = True
        super().closeEvent(event)

    def copy_command(self):
        QGuiApplication.clipboard().setText(self.command)
        self.status.setText(tr("phone.copied"))
        self.status.setVisible(True)

    def allow_again(self):
        """Windows: the UAC prompt and the firewall rule in the background (FirewallJob); the window stays alive."""
        job = FirewallJob()
        _firewall_jobs.append(job)
        job.done.connect(self._allow_again_done)   # a method of the window: Qt drops it if the window is deleted
        job.finished.connect(lambda: _forget_firewall(job))
        self.allow_btn.setEnabled(False)
        self.status.setText(tr("phone.allow_working"))
        self.status.setVisible(True)
        job.start()
        return job

    def _allow_again_done(self, ok: bool, error: str, declined: bool):
        if self.closing:
            return
        try:
            self.allow_btn.setEnabled(True)
            self.status.setText(tr("phone.allow_done") if ok else tr("phone.allow_declined") if declined
                                else tr("phone.allow_failed", error=error))
            self.status.setVisible(True)
        except RuntimeError:
            pass

    def back_to_code(self):
        owner = self.owner
        self.close()
        try:
            if owner is not None and owner.isVisible():
                if owner.receiver is None or owner.receiver.state == phone.CLOSED:
                    owner.new_code()
                owner.raise_()
                owner.activateWindow()
        except RuntimeError:
            pass


# --- opening --------------------------------------------------------------------------------------------------

_window = None


def current_window():
    """The open window of this program: visible, or hidden by itself after a photo (the receiver is still open)."""
    try:
        if _window is not None and not _window.closing and (_window.isVisible() or _window.hidden_for_photo):
            return _window
    except RuntimeError:
        pass
    return None


def open_phone(ctx, target=None):
    """Menu "Photo from phone": the Wi-Fi note (until ticked off), then the window with the code. One window; one that
    hid itself after a photo comes back instead of a second one."""
    win = current_window()
    if win is not None:
        if target is not None:
            win.target = target
        if win.hidden_for_photo or not win.isVisible():
            win.bring_back()
        else:
            win.raise_()
            win.activateWindow()
        return win
    if not ctx.config.get(CONFIG_HIDE_NOTE):
        note = WifiNote(ctx, lambda: _show(ctx, target))
        note.open_centered()
        return note
    return _show(ctx, target)


def _show(ctx, target=None):
    global _window
    win = PhoneDialog(ctx, target)
    _window = win
    win.destroyed.connect(lambda *_: _forget(win))
    win.start()
    win.open_centered()
    return win


def _forget(win):
    global _window
    if _window is win:
        _window = None


def stop_all():
    """Quitting the program: the photos that are being opened are delivered first, then the receiver is closed even if
    the window is still open."""
    global _quitting
    _quitting = True
    try:
        flush_photos()
        win = current_window()
        if win is not None:
            win.stop()
        for rx in list(_RECEIVERS):   # a receiver whose window is gone but that still listens
            try:
                rx.stop()
            except Exception:   # noqa: BLE001
                pass
    finally:
        _quitting = False
