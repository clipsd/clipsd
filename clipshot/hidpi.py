# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later. Распространяется по лицензии GNU GPL v3 или более поздней,
# без каких-либо гарантий; полный текст: файл LICENSE или <https://www.gnu.org/licenses/gpl-3.0.html>.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""Снимки на экранах с масштабом (125–200 %): плотность в PNG, размер снимка, буфер обмена.

Снимок хранит физические пиксели и масштаб экрана (devicePixelRatio). На выходе (файл, буфер обмена):
- в PNG пишется плотность pHYs = 96 × масштаб (144 dpi при 150 %): программы, которые её читают
  (LibreOffice; Word по плотности CF_DIB), ставят картинку в размер, как она была на экране. Браузеры
  и Electron плотность не читают (проверено в Chrome 157);
- режим «Как на экране, 100 %» уменьшает снимок до размера в точках (меньше файл, плотность 96 dpi);
- в буфер вместе с картинкой можно положить text/html <img width height> в точках: поля браузеров
  и Electron, которые вставляют HTML, показывают снимок в исходном размере и резко, а не растянутым в 1,5 раза.
"""

import base64
import os
import struct
import sys
import zlib

from PyQt6.QtCore import QBuffer, QByteArray, QIODevice, QMimeData, QSize, Qt
from PyQt6.QtGui import QGuiApplication, QImage

from . import forma

BASE_DPI = 96.0
INCH_M = 0.0254
HTML_LIMIT = 8 * 1024 * 1024   # base64 картинки больше 8 МБ: в буфер только сама картинка, без HTML

SIZE_FULL = "full"       # полное разрешение: резко на любом экране, на экранах с масштабом крупнее в пикселях
SIZE_SCREEN = "screen"   # как на экране, 100 %: уменьшено до размера в точках, файл меньше
SIZE_MODES = (SIZE_FULL, SIZE_SCREEN)

_PNG_SIG = b"\x89PNG\r\n\x1a\n"
# Формат буфера обмена Windows с именем «PNG» (его кладут и читают Chrome, Firefox, Office, Telegram): так Qt кладёт
# байты под зарегистрированный формат, а не под имя image/png, которое в Windows никто не ищет
WINDOWS_PNG = 'application/x-qt-windows-mime;value="PNG"'


def ratio_of(image) -> float:
    """Масштаб снимка (физических пикселей на точку экрана)."""
    ratio = image.devicePixelRatio()
    return ratio if ratio > 0 else 1.0


def is_scaled(ratio: float) -> bool:
    return abs(ratio - 1.0) > 0.01


def dots_per_meter(ratio: float) -> int:
    """Плотность для QImage: 96 dpi × масштаб, в точках на метр (3780 при 100 %, 5669 при 150 %)."""
    return round(BASE_DPI * ratio / INCH_M)


def size_mode(config) -> str:
    mode = (config or {}).get("snapshot_size", SIZE_FULL)
    return mode if mode in SIZE_MODES else SIZE_FULL


def html_enabled(config) -> bool:
    return bool((config or {}).get("clip_html", html_default()))


def html_default() -> bool:
    """HTML с размером в буфере по умолчанию: в Linux да (LibreOffice, Chrome, VS Code проверены, Claude Code,
    Telegram, GIMP по исходникам: вставляют снимок как раньше); в Windows нет: классический Outlook вместо картинки data: из HTML
    показывает красный крестик, поведение Word не установлено. Размер в Word и так задаёт плотность CF_DIB."""
    return sys.platform != "win32"


def prepare(image: QImage, mode: str = SIZE_FULL) -> QImage:
    """Картинка для выдачи: в режиме «как на экране» уменьшена до размера в точках; плотность = 96 × масштаб."""
    ratio = ratio_of(image)
    if mode == SIZE_SCREEN and ratio > 1.01:
        size = image.deviceIndependentSize().toSize()
        out = image.scaled(QSize(max(1, size.width()), max(1, size.height())),
                           Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
        ratio = 1.0
    else:
        out = image.copy()
    out.setDevicePixelRatio(ratio)
    dpm = dots_per_meter(ratio)
    out.setDotsPerMeterX(dpm)
    out.setDotsPerMeterY(dpm)
    return out


# --- PNG: чанк pHYs ---------------------------------------------------------

def _chunks(data: bytes):
    """[(смещение, тип, длина данных)] чанков PNG."""
    out, pos = [], len(_PNG_SIG)
    while pos + 8 <= len(data):
        length, kind = struct.unpack(">I4s", data[pos:pos + 8])
        out.append((pos, kind, length))
        pos += 12 + length
        if kind == b"IEND":
            break
    return out


def read_phys(data: bytes):
    """(x, y, единица) из чанка pHYs PNG; единица 1 = точек на метр. None — чанка нет или это не PNG."""
    data = bytes(data)
    if not data.startswith(_PNG_SIG):
        return None
    for pos, kind, length in _chunks(data):
        if kind == b"pHYs" and length == 9:
            return struct.unpack(">IIB", data[pos + 8:pos + 17])
    return None


def _phys_chunk(dpm: int) -> bytes:
    body = b"pHYs" + struct.pack(">IIB", dpm, dpm, 1)
    return struct.pack(">I", 9) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)


def ensure_phys(data: bytes, dpm: int) -> bytes:
    """PNG с чанком pHYs нужной плотности: Qt пишет его сам; если вдруг не записал или записал другое — правим."""
    data = bytes(data)
    if not data.startswith(_PNG_SIG):
        return data
    if read_phys(data) == (dpm, dpm, 1):
        return data
    chunks = _chunks(data)
    for pos, kind, length in chunks:
        if kind == b"pHYs":
            return data[:pos] + _phys_chunk(dpm) + data[pos + 12 + length:]
    for pos, kind, length in chunks:
        if kind == b"IHDR":   # pHYs должен идти до IDAT: ставим сразу после IHDR
            end = pos + 12 + length
            return data[:end] + _phys_chunk(dpm) + data[end:]
    return data


def png_bytes(image: QImage) -> bytes:
    """PNG картинки с плотностью pHYs по её масштабу (картинка уже из prepare)."""
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buf, "PNG")
    buf.close()
    return ensure_phys(bytes(buf.data()), dots_per_meter(ratio_of(image)))


# --- выдача: файл и буфер обмена --------------------------------------------

def reserve_path(folder: str, stem: str, ext: str) -> str:
    """Свободное имя файла в папке, занятое сразу (пустой файл, O_CREAT | O_EXCL): stem.ext, stem_2.ext, stem_3.ext...
    Второе сохранение в ту же секунду, в этой программе или в другой её копии, получает следующее имя, а не пишет
    поверх первого (Г9 проверки гонок 1.32.2: два редактора, Ctrl+S подряд, первый снимок молча терялся).
    OSError: папки нет или в неё нельзя писать."""
    n = 1
    while True:
        path = os.path.join(folder, f"{stem}.{ext}" if n == 1 else f"{stem}_{n}.{ext}")
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o666)
        except FileExistsError:
            n += 1
            if n > 100_000:
                raise
            continue
        os.close(fd)
        return path


def discard_reserved(path: str) -> None:
    """Сохранение не удалось: убрать пустой файл, занятый reserve_path (файл с содержимым не трогается)."""
    try:
        if path and os.path.getsize(path) == 0:
            os.remove(path)
    except OSError:
        pass


def save_image(image: QImage, path: str, config=None, quality: int = None) -> bool:
    """Сохранить снимок в файл по настройке «Размер снимка». PNG — с плотностью pHYs, JPG — с плотностью JFIF."""
    out = prepare(image, size_mode(config))
    if path.lower().endswith(".png"):
        data = png_bytes(out)
        if not data:
            return False
        try:
            with open(path, "wb") as fh:
                fh.write(data)
        except OSError:
            return False
        return True
    if path.lower().endswith(forma.NO_ALPHA_EXT) and forma.has_transparency(out):
        out = forma.flatten(out, forma.background(config))   # 1.34: JPG без прозрачности, фон за формой белый
    return out.save(path, None, quality) if quality else out.save(path)


def html_fragment(png: bytes, width: int, height: int) -> str:
    b64 = base64.b64encode(png).decode("ascii")
    return f'<img src="data:image/png;base64,{b64}" width="{width}" height="{height}" alt="">'


def clipboard_mime(image: QImage, config=None) -> QMimeData:
    """Данные для буфера обмена: картинка (PNG с плотностью) и, при масштабе экрана ≠ 100 %, HTML с размером в точках."""
    out = prepare(image, size_mode(config))
    mime = QMimeData()
    ratio = ratio_of(out)
    png = b""
    if forma.has_transparency(out):
        # 1.34, форма снимка: прозрачный PNG под именем, которое читают браузеры, мессенджеры и офис («PNG» в Windows,
        # image/png в Linux), и картинка на белом фоне для остальных (CF_DIB без альфы: иначе углы чёрные)
        mime.setImageData(forma.flatten(out, forma.background(config)))
        png = png_bytes(out)
        mime.setData(WINDOWS_PNG if sys.platform == "win32" else "image/png", QByteArray(png))
    else:
        # Qt сам отдаёт image/bmp, image/jpeg…; в Windows CF_DIB (плотность из картинки), PNG только у картинок с альфа-каналом
        mime.setImageData(out)
    if sys.platform != "win32" and not png:
        png = png_bytes(out)
        mime.setData("image/png", QByteArray(png))   # PNG с проверенным pHYs, а не перекодированный по запросу
    if is_scaled(ratio) and html_enabled(config):
        png = png or png_bytes(out)
        if len(png) * 4 // 3 + 4 <= HTML_LIMIT:
            size = out.deviceIndependentSize().toSize()
            mime.setHtml(html_fragment(png, size.width(), size.height()))
    return mime


def copy_image(image: QImage, config=None) -> None:
    QGuiApplication.clipboard().setMimeData(clipboard_mime(image, config))
