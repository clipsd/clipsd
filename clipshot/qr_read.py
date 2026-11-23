# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later. Распространяется по лицензии GNU GPL v3 или более поздней,
# без каких-либо гарантий; полный текст: файл LICENSE или <https://www.gnu.org/licenses/gpl-3.0.html>.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""Чтение QR-кодов и штрихкодов со снимка (1.36). Без интернета: всё считается на этом компьютере.

Читает библиотека zxing-cpp (pip install zxing-cpp): готовые колёса для Windows и Linux без системных библиотек,
около 1 МБ. Если библиотеки в сборке нет, available() даёт False, кнопки «QR» в редакторе нет, остальное работает.
Сеть до нажатия не используется: адрес открывается только по кнопке «Открыть ссылку» и только после подтверждения,
и только если это адрес http или https (web_url)."""

from typing import NamedTuple
from urllib.parse import urlsplit

from PyQt6.QtGui import QImage

try:   # необязательная зависимость: нет её, нет и чтения кода
    import zxingcpp as _zx
except ImportError:   # pragma: no cover — зависит от окружения
    _zx = None

MAX_SIDE = 4000        # огромный снимок читаем уменьшенным: код всё равно крупнее нескольких точек
MAX_CODES = 8


class Code(NamedTuple):
    text: str
    kind: str          # название формата: QRCode, EAN13, Code128...
    link: str          # адрес http/https, если текст это адрес, иначе ""


def available() -> bool:
    return _zx is not None


def web_url(text: str) -> str:
    """Адрес для кнопки «Открыть ссылку»: только http и https, с узлом, без пробелов и управляющих знаков. Иначе "".
    Адреса других видов (file:, javascript:, ftp:, mailto:, tel:, программные) открывать нельзя."""
    if not isinstance(text, str):
        return ""
    s = text.strip()
    if not s or any(ch.isspace() or ord(ch) < 32 or ord(ch) == 127 for ch in s):
        return ""
    try:
        parts = urlsplit(s)
        host = parts.hostname
    except ValueError:
        return ""
    if parts.scheme.lower() not in ("http", "https") or not host:
        return ""
    return s


def _gray(image: QImage) -> QImage:
    img = image.convertToFormat(QImage.Format.Format_Grayscale8)
    longest = max(img.width(), img.height())
    if longest > MAX_SIDE:
        from PyQt6.QtCore import Qt
        img = img.scaled(MAX_SIDE, MAX_SIDE, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
    return img


def find_codes(image: QImage) -> list:
    """Найденные на картинке коды: [Code], в порядке сверху вниз, без повторов. Пусто: кодов нет или читать нечем."""
    if _zx is None or image is None or image.isNull():
        return []
    gray = _gray(image)
    if gray.isNull():
        return []
    width, height = gray.width(), gray.height()
    # строки QImage выровнены по 4 байта: отдаём ровную копию без выравнивания
    data = bytes(gray.constBits().asarray(gray.sizeInBytes()))
    stride = gray.bytesPerLine()
    if stride != width:
        data = b"".join(data[y * stride:y * stride + width] for y in range(height))
    try:
        view = _zx.ImageView(data, width, height, _zx.ImageFormat.Lum)
        found = _zx.read_barcodes(view)
    except Exception:   # noqa: BLE001 — библиотека не смогла прочесть картинку: кода «нет», программа живёт дальше
        return []
    out, seen = [], set()
    for b in sorted(found, key=lambda b: (b.position.top_left.y, b.position.top_left.x)):
        text = b.text or ""
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(Code(text, str(getattr(b.format, "name", b.format)), web_url(text)))
        if len(out) >= MAX_CODES:
            break
    return out
