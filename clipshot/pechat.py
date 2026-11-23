# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later. Распространяется по лицензии GNU GPL v3 или более поздней,
# без каких-либо гарантий; полный текст: файл LICENSE или <https://www.gnu.org/licenses/gpl-3.0.html>.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""Печать и PDF (1.36): снимок с пометками на бумагу или в файл PDF.

PDF: одна страница, картинка в исходном разрешении (Qt кладёт в файл пиксели снимка без пережатия; страница в размере
снимка при его плотности или A4 с полями, снимок вписан с сохранением пропорций). Настройка pdf_page: "image" (по
снимку) или "a4". Печать (1.36.1): своё окно «Печать» (PrintWindow): страница с картинкой, выбор принтера, копий, ориентации, размера и
цвета, зелёная «Печать» отправляет на принтер сама, без системного окна (в Windows 11 оно пишет «предпросмотр не
поддерживается»). Снимок вписан в страницу с полями, ориентация по форме снимка. Принтеров нет: сообщение и предложение
сохранить PDF. Печатающие классы взяты в модуль по имени (QPrinter, QPrinterInfo, QPrintDialog), чтобы тесты подставляли
свои и ничего не уходило на настоящий принтер."""

import os
import struct
import zlib

from PyQt6.QtCore import QBuffer, QIODevice, QMarginsF, QRectF, QSize, Qt
from PyQt6.QtGui import QColor, QImage, QPageLayout, QPainter, QPixmap
from PyQt6.QtPrintSupport import QPrintDialog, QPrinter, QPrinterInfo
from PyQt6.QtWidgets import QComboBox, QDialog, QHBoxLayout, QLabel, QPushButton, QSpinBox, QVBoxLayout

from . import hidpi
from .i18n import tr

PDF_IMAGE, PDF_A4 = "image", "a4"
PDF_PAGES = (PDF_IMAGE, PDF_A4)
MARGIN_MM = 10.0           # поля печати и страницы A4 в PDF
A4_MM = (210.0, 297.0)
_PNG_SIG = b"\x89PNG\r\n\x1a\n"
PDF_DPI_MIN, PDF_DPI_MAX = 72, 1200
MM_INCH = 25.4


def pdf_page_mode(cfg) -> str:
    mode = (cfg or {}).get("pdf_page", PDF_IMAGE)
    return mode if mode in PDF_PAGES else PDF_IMAGE


def is_pdf(path: str) -> bool:
    return str(path).lower().endswith(".pdf")


def _flat(image: QImage) -> QImage:
    """Для страницы: прозрачность (форма снимка) ложится на белый, как на бумаге."""
    from . import forma
    return forma.flatten(image, "#ffffff") if forma.has_transparency(image) else image


def fit_rect(page_w: float, page_h: float, img_w: float, img_h: float) -> QRectF:
    """Прямоугольник картинки на странице: вписан целиком, пропорции сохранены, по центру."""
    if img_w <= 0 or img_h <= 0 or page_w <= 0 or page_h <= 0:
        return QRectF(0, 0, max(page_w, 0), max(page_h, 0))
    k = min(page_w / img_w, page_h / img_h)
    w, h = img_w * k, img_h * k
    return QRectF((page_w - w) / 2, (page_h - h) / 2, w, h)


def orientation_for(image: QImage):
    """Ориентация листа по форме снимка: широкий на альбомном, высокий на книжном (квадратный: книжный)."""
    wide = image.width() > image.height()
    return QPageLayout.Orientation.Landscape if wide else QPageLayout.Orientation.Portrait


def source_image(image: QImage, cfg=None) -> QImage:
    """Снимок для вывода: как для файла (плотность 96 × масштаб экрана), без потери пикселей."""
    return _flat(hidpi.prepare(image, hidpi.SIZE_FULL))


# --- PDF -------------------------------------------------------------------------------------------------------

def pdf_dpi(image: QImage) -> int:
    dpm = image.dotsPerMeterX()
    dpi = round(dpm * 0.0254) if dpm > 0 else hidpi.BASE_DPI
    return max(PDF_DPI_MIN, min(PDF_DPI_MAX, dpi))


def _rgb_stream(img: QImage):
    """(данные, параметры фильтра) для картинки PDF без потери пикселей. Qt при записи PDF сам пережимает цвета в JPEG,
    поэтому PDF собирается здесь: пиксели идут в Flate (без потерь). Данные берутся из IDAT PNG, который Qt пишет без
    потерь: PDF читает их вместе с предсказателем PNG (Predictor 15), ничего перекодировать не надо."""
    rgb = img.convertToFormat(QImage.Format.Format_RGB888)
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    rgb.save(buf, "PNG")
    data = bytes(buf.data())
    buf.close()
    if data.startswith(_PNG_SIG):
        pos, idat, head = 8, [], None
        while pos + 8 <= len(data):
            length, kind = struct.unpack(">I4s", data[pos:pos + 8])
            body = data[pos + 8:pos + 8 + length]
            if kind == b"IHDR":
                head = struct.unpack(">IIBBBBB", body[:13])
            elif kind == b"IDAT":
                idat.append(body)
            pos += 12 + length
        if head and head[2:] == (8, 2, 0, 0, 0) and idat:   # 8 бит, RGB, без перемежения
            parms = f"/DecodeParms << /Predictor 15 /Colors 3 /BitsPerComponent 8 /Columns {rgb.width()} >>"
            return b"".join(idat), parms
    ptr = rgb.constBits()
    ptr.setsize(rgb.sizeInBytes())
    whole, stride, row = bytes(ptr), rgb.bytesPerLine(), rgb.width() * 3
    raw = b"".join(whole[y * stride:y * stride + row] for y in range(rgb.height()))
    return zlib.compress(raw, 6), ""


def build_pdf(img: QImage, page_pt, box_pt) -> bytes:
    """PDF на одну страницу: размер страницы page_pt (ширина, высота в пунктах), картинка в прямоугольнике box_pt
    (x, y сверху, ширина, высота)."""
    w, h = img.width(), img.height()
    data, parms = _rgb_stream(img)
    pw, ph = page_pt
    bx, by, bw, bh = box_pt
    content = f"q {bw:.4f} 0 0 {bh:.4f} {bx:.4f} {ph - by - bh:.4f} cm /Im0 Do Q".encode("ascii")
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {pw:.4f} {ph:.4f}] /Contents 4 0 R "
        "/Resources << /XObject << /Im0 5 0 R >> >> >>".encode("ascii"),
        b"<< /Length %d >>\nstream\n" % len(content) + content + b"\nendstream",
        (f"<< /Type /XObject /Subtype /Image /Width {w} /Height {h} /ColorSpace /DeviceRGB /BitsPerComponent 8 "
         f"/Filter /FlateDecode {parms} /Length {len(data)} >>\nstream\n").encode("ascii") + data + b"\nendstream",
        b"<< /Producer (ClipSD) /Creator (ClipSD) >>",
    ]
    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for i, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode("ascii") + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode("ascii")
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode("ascii")
    out += (f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R /Info 6 0 R >>\nstartxref\n{xref}\n%%EOF\n").encode("ascii")
    return bytes(out)


def write_pdf(image: QImage, path: str, cfg=None) -> bool:
    """Снимок в PDF на одну страницу: по снимку (страница = размер снимка при его плотности) или A4 с полями, снимок
    вписан с сохранением пропорций. Картинка в исходном разрешении, без потерь. True: файл записан."""
    if image is None or image.isNull():
        return False
    img = source_image(image, cfg)
    if pdf_page_mode(cfg) == PDF_A4:
        wide = img.width() > img.height()
        pw, ph = (A4_MM[1], A4_MM[0]) if wide else A4_MM
        pw, ph, m = pw / MM_INCH * 72, ph / MM_INCH * 72, MARGIN_MM / MM_INCH * 72
        box = fit_rect(pw - 2 * m, ph - 2 * m, img.width(), img.height())
        box_pt = (m + box.x(), m + box.y(), box.width(), box.height())
    else:
        pw, ph = img.width() / pdf_dpi(img) * 72, img.height() / pdf_dpi(img) * 72
        box_pt = (0, 0, pw, ph)
    data = build_pdf(img, (pw, ph), box_pt)
    tmp = f"{path}.{os.getpid()}.part"   # рядом с целью: os.replace в одной папке; при сбое прежний файл цел
    try:
        with open(tmp, "wb") as fh:
            fh.write(data)
        os.replace(tmp, path)
    except OSError:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        return False
    return True


# --- печать ----------------------------------------------------------------------------------------------------

def printers_available() -> bool:
    try:
        return bool(QPrinterInfo.availablePrinters()) or not QPrinterInfo.defaultPrinter().isNull()
    except Exception:
        return False


def setup_printer(printer, image: QImage):
    """Страница: ориентация по форме снимка, поля по 10 мм."""
    printer.setPageOrientation(orientation_for(image))
    printer.setPageMargins(QMarginsF(MARGIN_MM, MARGIN_MM, MARGIN_MM, MARGIN_MM), QPageLayout.Unit.Millimeter)
    try:
        printer.setFullPage(False)
    except Exception:
        pass
    printer.setDocName("ClipSD")


def paint_to_printer(printer, image: QImage, actual_size: bool = False) -> bool:
    """Снимок на страницу: вписан в область внутри полей с сохранением пропорций, по центру. Пиксели не пережимаются.
    actual_size: «как есть» (размер по плотности снимка), но не больше страницы."""
    img = source_image(image)
    painter = QPainter()
    if not painter.begin(printer):
        return False
    try:
        page = printer.pageRect(QPrinter.Unit.DevicePixel)
        target = fit_rect(page.width(), page.height(), img.width(), img.height())
        if actual_size:
            dpi = pdf_dpi(img)
            w, h = img.width() / dpi * printer.resolution(), img.height() / dpi * printer.resolution()
            if w <= page.width() and h <= page.height():
                target = QRectF((page.width() - w) / 2, (page.height() - h) / 2, w, h)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.drawImage(target, img)   # начало координат печати уже в углу области внутри полей: сдвигать не надо
    finally:
        painter.end()
    return True


def _no_printers(parent) -> bool:
    """Принтеров нет: понятное сообщение. True: человек выбрал «Сохранить PDF»."""
    from .dialogs import MessageCard
    card = MessageCard(parent, tr("pechat.none_title"), tr("pechat.none_text"), "info",
                       primary=tr("pechat.none_pdf"), secondary=tr("pechat.none_close"))
    card.exec()
    return getattr(card, "choice", None) == "primary"


PRINTER_KEY = "print_printer"   # в настройках: имя принтера, выбранного в прошлый раз


class PrintWindow(QDialog):
    """Окно «Печать» ClipSD (1.36.1): страница с картинкой и выбор принтера, копий, ориентации, размера и цвета, зелёная
    «Печать» отправляет прямо на выбранный принтер. Системное окно печати не открывается (в Windows 11 оно пишет «приложение
    не поддерживает предварительный просмотр»); «Настройки принтера…» открывает его по желанию, для параметров драйвера."""

    def __init__(self, parent, image: QImage, cfg=None, save_pdf=None):
        super().__init__(parent)
        from . import themes
        from .dialogs import style
        self.image, self.cfg, self.save_pdf = image, cfg if cfg is not None else {}, save_pdf
        self.printed = False
        self.setWindowTitle("ClipSD: " + tr("pechat.win_title"))
        self.setStyleSheet(style(themes.is_dark()))
        row = QHBoxLayout(self)
        row.setContentsMargins(18, 16, 18, 16)
        row.setSpacing(18)
        self.preview = QLabel()
        self.preview.setMinimumSize(300, 380)
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        row.addWidget(self.preview, 1)
        side = QVBoxLayout()
        side.setSpacing(8)
        row.addLayout(side)
        title = QLabel(tr("pechat.win_title"))
        title.setObjectName("clipTitle")
        side.addWidget(title)

        def field(key, widget):
            label = QLabel(tr(key))
            label.setObjectName("clipFieldLabel")
            side.addWidget(label)
            side.addWidget(widget)
            return widget
        self.printers = list(QPrinterInfo.availablePrinters())
        self.printer_box = field("pechat.printer", QComboBox())
        default = QPrinterInfo.defaultPrinterName()
        last = self.cfg.get(PRINTER_KEY)
        for info in self.printers:
            self.printer_box.addItem(info.printerName(), info.printerName())
        for want in (last, default):
            at = self.printer_box.findData(want) if want else -1
            if at >= 0:
                self.printer_box.setCurrentIndex(at)
                break
        self.copies = field("pechat.copies", QSpinBox())
        self.copies.setRange(1, 99)
        self.orient = field("pechat.orient", QComboBox())
        for key, data in (("pechat.orient_auto", "auto"), ("pechat.orient_portrait", "portrait"), ("pechat.orient_landscape", "landscape")):
            self.orient.addItem(tr(key), data)
        self.fit = field("pechat.fit", QComboBox())
        self.fit.addItem(tr("pechat.fit_page"), "page")
        self.fit.addItem(tr("pechat.fit_actual"), "actual")
        self.color = field("pechat.color", QComboBox())
        self.color.addItem(tr("pechat.color_color"), "color")
        self.color.addItem(tr("pechat.color_gray"), "gray")
        side.addStretch(1)
        self.system_button = QPushButton(tr("pechat.system_settings"))
        self.system_button.setObjectName("clipLink")
        self.system_button.clicked.connect(self.system_settings)
        side.addWidget(self.system_button)
        buttons = QHBoxLayout()
        self.print_button = QPushButton(tr("pechat.print_button"))
        self.print_button.setObjectName("clipPrimary")
        self.print_button.setDefault(True)
        self.print_button.clicked.connect(self.print_now)
        self.cancel_button = QPushButton(tr("pechat.cancel"))
        self.cancel_button.setObjectName("clipSecondary")
        self.cancel_button.clicked.connect(self.reject)
        buttons.addWidget(self.cancel_button)
        buttons.addWidget(self.print_button, 1)
        side.addLayout(buttons)
        for w in (self.orient, self.fit):
            w.currentIndexChanged.connect(self.refresh)
        self.refresh()

    def _orientation(self):
        mode = self.orient.currentData()
        if mode == "portrait":
            return QPageLayout.Orientation.Portrait
        if mode == "landscape":
            return QPageLayout.Orientation.Landscape
        return orientation_for(self.image)

    def make_printer(self):
        """QPrinter выбранного принтера со всеми выбранными параметрами (в тестах класс подменяется)."""
        name = self.printer_box.currentData()
        info = next((i for i in self.printers if i.printerName() == name), None)
        printer = QPrinter(info, QPrinter.PrinterMode.HighResolution) if info is not None else QPrinter(QPrinter.PrinterMode.HighResolution)
        setup_printer(printer, self.image)
        printer.setPageOrientation(self._orientation())
        printer.setCopyCount(self.copies.value())
        try:
            printer.setColorMode(QPrinter.ColorMode.GrayScale if self.color.currentData() == "gray" else QPrinter.ColorMode.Color)
        except Exception:   # noqa: BLE001
            pass
        return printer

    def refresh(self, *_):
        """Страница в окне: белый лист в пропорциях выбранной страницы, внутри полей картинка так, как она ляжет на бумагу."""
        landscape = self._orientation() == QPageLayout.Orientation.Landscape
        pw, ph = (A4_MM[1], A4_MM[0]) if landscape else A4_MM
        scale = 3.2
        sheet = QImage(round(pw * scale), round(ph * scale), QImage.Format.Format_RGB32)
        sheet.fill(0xFFFFFF)
        img = source_image(self.image)
        m = MARGIN_MM * scale
        inner_w, inner_h = sheet.width() - 2 * m, sheet.height() - 2 * m
        target = fit_rect(inner_w, inner_h, img.width(), img.height())
        if self.fit.currentData() == "actual":
            dpi = pdf_dpi(img)
            w, h = img.width() / dpi * MM_INCH * scale, img.height() / dpi * MM_INCH * scale
            if w <= inner_w and h <= inner_h:
                target = QRectF((inner_w - w) / 2, (inner_h - h) / 2, w, h)
        p = QPainter(sheet)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        p.drawImage(target.translated(m, m), img)
        p.setPen(QColor("#b0b6bf"))
        p.drawRect(sheet.rect().adjusted(0, 0, -1, -1))
        p.end()
        self.preview.setPixmap(QPixmap.fromImage(sheet).scaled(
            self.preview.size().expandedTo(QSize(300, 380)), Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation))

    def print_now(self) -> bool:
        """Печать прямо на выбранный принтер, без системного окна. True: страница отправлена."""
        printer = self.make_printer()
        ok = paint_to_printer(printer, self.image, self.fit.currentData() == "actual")
        if ok:
            self.printed = True
            if self.printer_box.currentData():
                self.cfg[PRINTER_KEY] = self.printer_box.currentData()
            self.accept()
        return ok

    def system_settings(self) -> bool:
        """Параметры драйвера (лоток, качество): системное окно, только по желанию человека. Окно принято («Печать» в
        нём): печатается этим же QPrinter, с ориентацией, копиями и цветом ClipSD, если человек не поменял их в окне
        драйвера, и размером ClipSD («По странице» / «Как есть»); окно ClipSD закрывается как напечатанное (В1 проверки
        1.36.1: раньше итог окна выбрасывался, и «Печать» в нём не печатала ничего). Отменено: ничего не меняется.
        True: страница отправлена."""
        printer = self.make_printer()
        dialog = QPrintDialog(printer, self)
        if dialog.exec() != QDialog.DialogCode.Accepted.value:
            return False
        ok = paint_to_printer(printer, self.image, self.fit.currentData() == "actual")
        if ok:
            self.printed = True
            try:
                name = printer.printerName()
            except Exception:   # noqa: BLE001
                name = ""
            if name and self.printer_box.findData(name) >= 0:
                self.cfg[PRINTER_KEY] = name
            elif self.printer_box.currentData():
                self.cfg[PRINTER_KEY] = self.printer_box.currentData()
            self.accept()
        return ok


def preview_image(parent, image: QImage, cfg=None, save_pdf=None) -> str:
    """«Печать» (кнопка, Ctrl+P, 1.36.1): окно ClipSD «Печать» с предпросмотром страницы и выбором принтера; печатает его
    зелёная кнопка прямо на принтер, системное окно печати по умолчанию не открывается (слова владельца 23.11.2026, а в
    Windows 11 оно ещё и пишет «предпросмотр не поддерживается»). save_pdf: что вызвать, если принтеров нет и человек
    согласился сохранить PDF. Итог: "printed", "shown" (окно закрыто без печати), "no_printers", "failed"."""
    if image is None or image.isNull():
        return "failed"
    if not printers_available():
        if _no_printers(parent) and callable(save_pdf):
            save_pdf()
        return "no_printers"
    window = PrintWindow(parent, image, cfg, save_pdf)
    window.exec()
    return "printed" if window.printed else "shown"


print_image = preview_image   # прежнее имя: все пути печати (редактор, окно выделения, «Ознакомление») ведут в это окно
