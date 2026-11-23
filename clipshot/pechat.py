# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later. Распространяется по лицензии GNU GPL v3 или более поздней,
# без каких-либо гарантий; полный текст: файл LICENSE или <https://www.gnu.org/licenses/gpl-3.0.html>.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""Печать и PDF (1.36): снимок с пометками на бумагу или в файл PDF.

PDF: одна страница, картинка в исходном разрешении (Qt кладёт в файл пиксели снимка без пережатия; страница в размере
снимка при его плотности или A4 с полями, снимок вписан с сохранением пропорций). Настройка pdf_page: "image" (по
снимку) или "a4". Печать: стандартное окно системы (QPrintDialog; в Linux печать идёт через CUPS, в Windows через
драйвер), снимок вписан в страницу с полями, ориентация по форме снимка; предпросмотр отдельным окном. Принтеров нет:
сообщение и предложение сохранить PDF. Печатающие классы взяты в модуль по имени (QPrinter, QPrintDialog,
QPrintPreviewDialog), чтобы тесты подставляли свои и ничего не уходило на настоящий принтер."""

import os
import struct
import zlib

from PyQt6.QtCore import QBuffer, QIODevice, QMarginsF, QRectF
from PyQt6.QtGui import QImage, QPageLayout, QPainter
from PyQt6.QtPrintSupport import QPrintDialog, QPrinter, QPrinterInfo, QPrintPreviewDialog

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


def paint_to_printer(printer, image: QImage) -> bool:
    """Снимок на страницу: вписан в область внутри полей с сохранением пропорций, по центру. Пиксели не пережимаются."""
    img = source_image(image)
    painter = QPainter()
    if not painter.begin(printer):
        return False
    try:
        page = printer.pageRect(QPrinter.Unit.DevicePixel)
        target = fit_rect(page.width(), page.height(), img.width(), img.height())
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


def print_image(parent, image: QImage, cfg=None, save_pdf=None) -> str:
    """«Печать…» (Ctrl+P): системное окно печати, потом печать. save_pdf: что вызвать, если принтеров нет и человек
    согласился сохранить PDF. Итог: "printed", "cancelled", "no_printers" (и PDF предложен), "failed"."""
    if image is None or image.isNull():
        return "failed"
    if not printers_available():
        if _no_printers(parent) and callable(save_pdf):
            save_pdf()
        return "no_printers"
    printer = QPrinter(QPrinter.PrinterMode.HighResolution)
    setup_printer(printer, image)
    dialog = QPrintDialog(printer, parent)
    dialog.setWindowTitle(tr("pechat.dialog_title"))
    if not dialog.exec():
        return "cancelled"
    return "printed" if paint_to_printer(printer, image) else "failed"


def preview_image(parent, image: QImage, cfg=None) -> str:
    """«Предпросмотр…»: окно предпросмотра с кнопкой печати; «printed»-подобного итога у него нет, только "shown"."""
    if image is None or image.isNull():
        return "failed"
    if not printers_available():
        _no_printers(parent)
        return "no_printers"
    printer = QPrinter(QPrinter.PrinterMode.HighResolution)
    setup_printer(printer, image)
    dialog = QPrintPreviewDialog(printer, parent)
    dialog.setWindowTitle(tr("pechat.preview_title"))
    dialog.paintRequested.connect(lambda p: paint_to_printer(p, image))
    dialog.exec()
    return "shown"
