# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later. Распространяется по лицензии GNU GPL v3 или более поздней,
# без каких-либо гарантий; полный текст: файл LICENSE или <https://www.gnu.org/licenses/gpl-3.0.html>.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""Снимок монитора Windows с включённым HDR или расширенным цветом (Advanced Color): DXGI Desktop Duplication.

Зачем. При HDR рабочий стол Windows собирается в линейном scRGB (FP16, 1.0 = 80 нит), белый обычных (SDR) программ
стоит на уровне «Яркость SDR-содержимого» (DISPLAYCONFIG_SDR_WHITE_LEVEL, 80..480 нит). Снимок через GDI (Qt
grabWindow) на таком мониторе выходит блёклым (владелец, Windows 11, Edge: с HDR тускло, без HDR нормально).
Здесь кадр берётся из IDXGIOutput5::DuplicateOutput1 в R16G16B16A16_FLOAT и переводится в обычный sRGB:
    lin = scRGB * 80 / SDR_white (HDR; на мониторе с расширенным цветом без HDR 1.0 = белый монитора, множитель 1),
    отрицательное (вне sRGB) и ярче белого SDR (блики HDR) обрезается до [0, 1], затем кривая sRGB и 8 бит.
Белый SDR даёт 255, цвета обычных программ возвращаются к своим sRGB-значениям (как их видит человек).
Источники: learn.microsoft.com «Use DirectX with Advanced Color» (scRGB 1.0 = 80 нит, умножение на SdrWhiteLevel/80,
SDR-монитор с расширенным цветом: 1.0 = белый монитора; DuplicateOutput1 для захвата HDR), DISPLAYCONFIG_SDR_WHITE_LEVEL
(значение / 1000 * 80 нит), DuplicateOutput1 и AcquireNextFrame (коды ошибок). Поворот кадра как в WebRTC
(dxgi_output_duplicator.cc: текстура не повёрнута, поворот DXGI по часовой стрелке даёт рабочий стол).

Как. Чистый Python (ctypes, вызовы COM по номеру в таблице методов; номера сверены с заголовками mingw-w64 d3d11.h,
dxgi*.h). Перевод цвета на видеокарте: маленький вычислительный шейдер (D3DCompile из d3dcompiler_47.dll, есть в
Windows 10+ и в PyQt6-Qt6), 4K за единицы миллисекунд; не вышло: тот же расчёт в Qt на процессоре (tonemap_qimage).
Устройство D3D11 и шейдер живут между снимками (по LUID видеокарты), дублирование создаётся на каждый снимок и сразу
закрывается: держать его открытым значит заставлять DWM всё время отдавать кадры.

Когда. Только мониторы, у которых DisplayConfig говорит «HDR» или «расширенный цвет» (display_states). Остальные
снимаются как раньше (GDI), D3D даже не загружается. Любая ошибка (UAC и защищённый стол: E_ACCESSDENIED, RDP,
смена режима: DXGI_ERROR_ACCESS_LOST, нет кадра за отведённое время, видеокарта не та) даёт None для монитора,
grab.grab_qt снимает его через GDI и пишет причину в журнал. Ожидание кадра ограничено (FIRST_FRAME_BUDGET_S).

Модуль импортируется и на Linux: математика, сборка картинки и выбор мониторов проверяются там тестами
(tests/hdr_test.py); живой DXGI проверяет tests/hdr_win_test.py в Windows CI (без HDR: путь B8G8R8A8 против GDI
и шейдер на синтетическом кадре FP16).

Журнал и отчёт об ошибке (1.36.1): строку о цвете каждого монитора даёт states_line() поверх display_states(); отдельного
модуля диагностики (прежний hdrinfo) больше нет."""

import ctypes
import struct
import sys
import threading
import time
from dataclasses import dataclass

MODE_SDR, MODE_WCG, MODE_HDR = "sdr", "wcg", "hdr"
NOMINAL_WHITE_NITS = 80.0
FIRST_FRAME_BUDGET_S = 0.25   # первый кадр дублирования обычно сразу; дольше ждать нельзя: снимок «мгновенный»
LOCK_TIMEOUT_S = 1.0          # прогрев в фоне держит замок; снимок не ждёт дольше, а снимает через GDI

last_report = []   # строки о последнем снимке (для журнала и тестов): монитор, путь, время или причина отката


def _log(text):
    last_report.append(text)
    print(f"HDR: {text}", flush=True)


# --- математика (одинаковая для шейдера, процессора и тестов) ---------------------------------------------------

def gain_for(mode: str, white_nits) -> float:
    """Множитель scRGB -> линейный sRGB [0..1]. HDR: 80 / белый SDR (нет уровня: None, тогда снимок через GDI).
    Расширенный цвет без HDR: 1.0 (1.0 = белый монитора). Обычный монитор: None (новый путь не нужен)."""
    if mode == MODE_WCG:
        return 1.0
    if mode == MODE_HDR:
        if not white_nits or white_nits <= 0:
            return None
        return NOMINAL_WHITE_NITS / float(white_nits)
    return None


def srgb_oetf(x: float) -> float:
    """Линейное [0..1] -> sRGB [0..1] (IEC 61966-2-1); вне диапазона и NaN обрезаются (NaN -> 0)."""
    if not x > 0.0:   # и NaN
        return 0.0
    if x >= 1.0:
        return 1.0
    return 12.92 * x if x <= 0.0031308 else 1.055 * x ** (1.0 / 2.4) - 0.055


def tonemap_value(v: float, gain: float) -> int:
    """Одно значение scRGB -> байт sRGB: умножить, обрезать, кривая sRGB, округлить."""
    return int(srgb_oetf(v * gain) * 255.0 + 0.5)


def half_floats(raw: bytes) -> tuple:
    return struct.unpack("<%de" % (len(raw) // 2), raw)


def tonemap_reference(raw_f16: bytes, gain: float) -> bytes:
    """Эталон на чистом Python (медленно, только для тестов): RGBA FP16 -> байты RGB."""
    vals = half_floats(raw_f16)
    out = bytearray()
    for i in range(0, len(vals), 4):
        out += bytes(tonemap_value(v, gain) for v in vals[i:i + 3])
    return bytes(out)


def tonemap_qimage(img16, gain: float):
    """Кадр FP16 (QImage Format_RGBX16FPx4 или RGBA16FPx4, линейный scRGB) -> QImage RGB32 sRGB на процессоре.
    Умножение во float32 (QPainter Multiply не обрезает), затем 16 бит с обрезкой [0, 1] и кривая sRGB средствами Qt
    (QColorSpace SRgbLinear -> SRgb). Расхождение с эталоном не больше 1 в байте (tests/hdr_test.py)."""
    from PyQt6.QtGui import QColor, QColorSpace, QImage, QPainter
    f = img16.convertToFormat(QImage.Format.Format_RGBX32FPx4)
    if abs(gain - 1.0) > 1e-6:
        p = QPainter(f)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Multiply)
        p.fillRect(f.rect(), QColor.fromRgbF(gain, gain, gain, 1.0))
        p.end()
    i64 = f.convertToFormat(QImage.Format.Format_RGBX64)
    i64.setColorSpace(QColorSpace(QColorSpace.NamedColorSpace.SRgbLinear))
    i64.convertToColorSpace(QColorSpace(QColorSpace.NamedColorSpace.SRgb))
    out = i64.convertToFormat(QImage.Format.Format_RGB32)
    out.setColorSpace(QColorSpace())   # как у снимка GDI: без пометки цветового пространства
    return out


ROTATION_DEGREES = {0: 0, 1: 0, 2: 90, 3: 180, 4: 270}   # DXGI_MODE_ROTATION: UNSPECIFIED, IDENTITY, 90, 180, 270


def rotate_to_desktop(img, rotation: int):
    """Текстура дублирования не повёрнута (как её видит монитор); поворот DXGI по часовой стрелке даёт картинку
    рабочего стола (WebRTC DxgiRotationToRotation). QTransform.rotate(+90) в Qt тоже по часовой (ось y вниз)."""
    deg = ROTATION_DEGREES.get(int(rotation), None)
    if deg is None:
        raise CaptureFailed(f"неизвестный поворот {rotation}")
    if deg == 0:
        return img
    from PyQt6.QtGui import QTransform
    return img.transformed(QTransform().rotate(deg))


# --- состояние мониторов и сопоставление с экранами Qt ------------------------------------------------------------

@dataclass
class OutputState:
    """Монитор по DisplayConfig: имя источника (\\\\.\\DISPLAY1), режим, белый SDR в нитах, бит на канал."""
    device: str
    mode: str
    white_nits: float = None
    bits: int = 8


@dataclass
class OutputInfo:
    """Выход DXGI: имя, место на рабочем столе в физических пикселях (x, y, w, h), поворот DXGI_MODE_ROTATION."""
    device: str
    rect: tuple
    rotation: int = 1


def match_screens(screens, outputs) -> dict:
    """{номер экрана Qt: OutputInfo}. screens: [(имя, логическая QRect, devicePixelRatio)]. Qt под Windows держит
    левый верхний угол экрана в родных координатах, размер делит на масштаб; поэтому совпадение: тот же угол и
    размер x масштаб в пределах 2 пикселей. Имя экрана Qt может быть и «\\\\.\\DISPLAY1»: тогда по имени.
    Не нашёлся: экран снимается через GDI."""
    out = {}
    used = set()
    for i, (name, geo, dpr) in enumerate(screens):
        hit = None
        for j, o in enumerate(outputs):
            if j not in used and name and name == o.device:
                hit = j
                break
        if hit is None:
            for j, o in enumerate(outputs):
                x, y, w, h = o.rect
                if j in used or (geo.x(), geo.y()) != (x, y):
                    continue
                if abs(geo.width() * dpr - w) <= 2 and abs(geo.height() * dpr - h) <= 2:
                    hit = j
                    break
        if hit is not None:
            used.add(hit)
            out[i] = outputs[hit]
    return out


def capture_screens(screens, states=None, capturer=None) -> dict:
    """{номер экрана Qt: QPixmap в родных пикселях с devicePixelRatio экрана} для экранов с HDR или расширенным
    цветом; экраны, которых нет в ответе, grab_qt снимает через GDI. Никогда не бросает исключение."""
    last_report.clear()
    try:
        if states is None:
            states = display_states()
        adv = {s.device: s for s in states if s.mode in (MODE_HDR, MODE_WCG)}
        if not adv:
            return {}
        if capturer is None:
            capturer = shared_capturer()
        from PyQt6.QtGui import QPixmap
        geos = [(screen.name(), screen.geometry(), screen.devicePixelRatio()) for screen in screens]
        matched = match_screens(geos, capturer.outputs())
    except Exception as exc:   # noqa: BLE001 — нет сведений о мониторах: все через GDI
        _log(f"сведения о мониторах не получены ({type(exc).__name__}: {exc}), снимок через GDI")
        return {}
    result = {}
    for idx, out in matched.items():
        st = adv.get(out.device)
        if st is None:
            continue
        gain = gain_for(st.mode, st.white_nits)
        if gain is None:
            _log(f"{out.device}: {st.mode} без уровня белого SDR, снимок через GDI")
            continue
        t0 = time.perf_counter()
        try:
            img = capturer.grab(out.device, gain, hdr=True)
            if img is None or img.isNull():
                raise CaptureFailed("пустой кадр")
            x, y, w, h = out.rect
            if (img.width(), img.height()) != (w, h):
                raise CaptureFailed(f"размер {img.width()}x{img.height()} вместо {w}x{h}")
            pm = QPixmap.fromImage(img)
            pm.setDevicePixelRatio(screens[idx].devicePixelRatio())
        except Exception as exc:   # noqa: BLE001 — любой сбой: этот монитор через GDI
            _log(f"{out.device}: {st.mode}, откат на GDI ({type(exc).__name__}: {exc})")
            continue
        ms = (time.perf_counter() - t0) * 1000
        white = f", белый {st.white_nits:.0f} нит" if st.white_nits else ""
        _log(f"{out.device}: {st.mode}{white}, множитель {gain:.3f}, {w}x{h}, {ms:.0f} мс "
             f"({getattr(capturer, 'last_path', '?')})")
        result[idx] = pm
    return result


# --- Windows: DisplayConfig -----------------------------------------------------------------------------------------
# Структуры с типами фиксированной ширины (на Linux c_long 8 байт): размеры одинаковы на обеих системах, их проверяет
# tests/hdr_test.py (Path 72, Mode 64, SourceName 84, AdvColor 32, AdvColor2 36, SdrWhite 24).

U32, I32 = ctypes.c_uint32, ctypes.c_int32


class LUID(ctypes.Structure):
    _fields_ = [("LowPart", U32), ("HighPart", I32)]


class DcHeader(ctypes.Structure):
    _fields_ = [("type", U32), ("size", U32), ("adapterId", LUID), ("id", U32)]


class DcSource(ctypes.Structure):
    _fields_ = [("adapterId", LUID), ("id", U32), ("modeInfoIdx", U32), ("statusFlags", U32)]


class DcTarget(ctypes.Structure):
    _fields_ = [("adapterId", LUID), ("id", U32), ("modeInfoIdx", U32), ("outputTechnology", U32),
                ("rotation", U32), ("scaling", U32), ("refreshNum", U32), ("refreshDen", U32),
                ("scanLineOrdering", U32), ("targetAvailable", I32), ("statusFlags", U32)]


class DcPath(ctypes.Structure):
    _fields_ = [("sourceInfo", DcSource), ("targetInfo", DcTarget), ("flags", U32)]


class DcMode(ctypes.Structure):
    _fields_ = [("raw", ctypes.c_ubyte * 64)]


class DcSourceName(ctypes.Structure):   # DISPLAYCONFIG_SOURCE_DEVICE_NAME, тип 1
    _fields_ = [("header", DcHeader), ("viewGdiDeviceName", ctypes.c_uint16 * 32)]


class DcAdvColor(ctypes.Structure):     # DISPLAYCONFIG_GET_ADVANCED_COLOR_INFO, тип 9
    # value: бит 0 advancedColorSupported, 1 advancedColorEnabled, 2 wideColorEnforced, 3 advancedColorForceDisabled
    _fields_ = [("header", DcHeader), ("value", U32), ("colorEncoding", U32), ("bitsPerColorChannel", U32)]


class DcAdvColor2(ctypes.Structure):    # DISPLAYCONFIG_GET_ADVANCED_COLOR_INFO_2, тип 15 (Windows 11 24H2+)
    # value: бит 0 supported, 1 active, 4 hdrSupported, 5 hdrUserEnabled, 6 wcgSupported, 7 wcgUserEnabled
    _fields_ = [("header", DcHeader), ("value", U32), ("colorEncoding", U32), ("bitsPerColorChannel", U32),
                ("activeColorMode", U32)]   # 0 SDR, 1 WCG, 2 HDR


class DcSdrWhite(ctypes.Structure):     # DISPLAYCONFIG_SDR_WHITE_LEVEL, тип 11
    _fields_ = [("header", DcHeader), ("SDRWhiteLevel", U32)]


QDC_ONLY_ACTIVE_PATHS = 2
GET_SOURCE_NAME, GET_ADVANCED_COLOR_INFO, GET_SDR_WHITE_LEVEL, GET_ADVANCED_COLOR_INFO_2 = 1, 9, 11, 15
ERROR_INSUFFICIENT_BUFFER = 122


def wstr(arr) -> str:
    chars = []
    for c in arr:
        if not c:
            break
        chars.append(chr(c))
    return "".join(chars)


def mode_of(adv=None, adv2=None):
    """Режим монитора из ответов DisplayConfig. Сначала _2 (Windows 11 24H2+: activeColorMode), иначе старый вид:
    advancedColorEnabled и wideColorEnforced (расширенный цвет на SDR-мониторе). None: ответа нет."""
    if adv2 is not None:
        return {2: MODE_HDR, 1: MODE_WCG}.get(adv2.activeColorMode, MODE_SDR), adv2.bitsPerColorChannel
    if adv is not None:
        if not adv.value & 2:
            return MODE_SDR, adv.bitsPerColorChannel
        return (MODE_WCG if adv.value & 4 else MODE_HDR), adv.bitsPerColorChannel
    return None, 8


def display_states(user32=None) -> list:
    """[OutputState] по активным мониторам; [] не на Windows и при любом сбое DisplayConfig (только чтение)."""
    if user32 is None:
        if sys.platform != "win32":
            return []
        user32 = ctypes.WinDLL("user32")
        user32.GetDisplayConfigBufferSizes.argtypes = [U32, ctypes.POINTER(U32), ctypes.POINTER(U32)]
        user32.GetDisplayConfigBufferSizes.restype = I32
        user32.QueryDisplayConfig.argtypes = [U32, ctypes.POINTER(U32), ctypes.c_void_p, ctypes.POINTER(U32),
                                              ctypes.c_void_p, ctypes.c_void_p]
        user32.QueryDisplayConfig.restype = I32
        user32.DisplayConfigGetDeviceInfo.argtypes = [ctypes.c_void_p]
        user32.DisplayConfigGetDeviceInfo.restype = I32
    paths = None
    for _ in range(3):   # конфигурация могла смениться между двумя вызовами: ERROR_INSUFFICIENT_BUFFER
        n_paths, n_modes = U32(0), U32(0)
        if user32.GetDisplayConfigBufferSizes(QDC_ONLY_ACTIVE_PATHS, ctypes.byref(n_paths), ctypes.byref(n_modes)):
            return []
        paths = (DcPath * max(1, n_paths.value))()
        modes = (DcMode * max(1, n_modes.value))()
        rc = user32.QueryDisplayConfig(QDC_ONLY_ACTIVE_PATHS, ctypes.byref(n_paths), paths, ctypes.byref(n_modes),
                                       modes, None)
        if rc == 0:
            break
        if rc != ERROR_INSUFFICIENT_BUFFER:
            return []
    else:
        return []

    def query(cls, kind, adapter, ident):
        s = cls()
        s.header.type, s.header.size = kind, ctypes.sizeof(cls)
        s.header.adapterId.LowPart, s.header.adapterId.HighPart = adapter.LowPart, adapter.HighPart
        s.header.id = ident
        return s if user32.DisplayConfigGetDeviceInfo(ctypes.byref(s)) == 0 else None

    out, seen = [], set()
    for p in paths[:n_paths.value]:
        src = query(DcSourceName, GET_SOURCE_NAME, p.sourceInfo.adapterId, p.sourceInfo.id)
        name = wstr(src.viewGdiDeviceName) if src else ""
        if not name or name in seen:   # клон одного источника на два монитора: первый ответ
            continue
        tgt = p.targetInfo
        mode, bits = mode_of(query(DcAdvColor, GET_ADVANCED_COLOR_INFO, tgt.adapterId, tgt.id),
                             query(DcAdvColor2, GET_ADVANCED_COLOR_INFO_2, tgt.adapterId, tgt.id))
        white = None
        if mode == MODE_HDR:
            w = query(DcSdrWhite, GET_SDR_WHITE_LEVEL, tgt.adapterId, tgt.id)
            if w is not None and w.SDRWhiteLevel:
                white = w.SDRWhiteLevel / 1000.0 * NOMINAL_WHITE_NITS
        seen.add(name)
        out.append(OutputState(name, mode or MODE_SDR, white, int(bits or 8)))
    return out


def states_line(states=None) -> str:
    """Одна строка для журнала: «\\\\.\\DISPLAY1=hdr/240нит/10бит; \\\\.\\DISPLAY2=sdr»."""
    states = display_states() if states is None else states
    parts = []
    for s in states:
        extra = f"/{s.white_nits:.0f}нит" if s.white_nits else ""
        parts.append(f"{s.device}={s.mode}{extra}/{s.bits}бит")
    return "; ".join(parts) or "нет сведений"


# --- Windows: DXGI и D3D11 через ctypes -----------------------------------------------------------------------------

class CaptureFailed(RuntimeError):
    pass


class HResultError(CaptureFailed):
    def __init__(self, what, hr):
        self.hr = hr & 0xFFFFFFFF
        super().__init__(f"{what}: 0x{self.hr:08X} {HR_NAMES.get(self.hr, '')}".rstrip())


S_OK = 0
E_INVALIDARG = 0x80070057
E_ACCESSDENIED = 0x80070005
DXGI_ERROR_NOT_FOUND = 0x887A0002
DXGI_ERROR_UNSUPPORTED = 0x887A0004
DXGI_ERROR_DEVICE_REMOVED = 0x887A0005
DXGI_ERROR_NOT_CURRENTLY_AVAILABLE = 0x887A0022
DXGI_ERROR_ACCESS_LOST = 0x887A0026
DXGI_ERROR_WAIT_TIMEOUT = 0x887A0027
DXGI_ERROR_SESSION_DISCONNECTED = 0x887A0028
HR_NAMES = {E_INVALIDARG: "E_INVALIDARG", E_ACCESSDENIED: "E_ACCESSDENIED", DXGI_ERROR_NOT_FOUND: "NOT_FOUND",
            DXGI_ERROR_UNSUPPORTED: "UNSUPPORTED", DXGI_ERROR_DEVICE_REMOVED: "DEVICE_REMOVED",
            DXGI_ERROR_NOT_CURRENTLY_AVAILABLE: "NOT_CURRENTLY_AVAILABLE", DXGI_ERROR_ACCESS_LOST: "ACCESS_LOST",
            DXGI_ERROR_WAIT_TIMEOUT: "WAIT_TIMEOUT", DXGI_ERROR_SESSION_DISCONNECTED: "SESSION_DISCONNECTED"}

FMT_R16G16B16A16_FLOAT, FMT_R8G8B8A8_UNORM, FMT_B8G8R8A8_UNORM = 10, 28, 87
USAGE_DEFAULT, USAGE_IMMUTABLE, USAGE_STAGING = 0, 1, 3
BIND_CONSTANT_BUFFER, BIND_SHADER_RESOURCE, BIND_UNORDERED_ACCESS = 0x4, 0x8, 0x80
CPU_ACCESS_READ, MAP_READ = 0x20000, 1
D3D_DRIVER_TYPE_UNKNOWN, D3D_DRIVER_TYPE_HARDWARE, D3D_DRIVER_TYPE_WARP = 0, 1, 5
FL_11_0 = 0xB000
D3D11_SDK_VERSION = 7

# Методы COM: имя -> (номер в таблице методов, тип ответа, типы аргументов БЕЗ скрытого this). Номера и списки
# аргументов сверены с mingw-w64 (d3d11.h, dxgi.h, dxgi1_2.h, dxgi1_5.h, d3dcommon.h) и проверяются тестом
# tests/hdr_test.py: число аргументов здесь против SDK и число аргументов в каждом вызове com()/com_hr() против этой
# таблицы (ошибка числа аргументов иначе видна только на Windows).
_P, _PP, _G = ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p   # _G: REFIID (адрес GUID)
METHODS = {
    "IUnknown.QueryInterface": (0, I32, [_G, _PP]),
    "IUnknown.Release": (2, U32, []),
    "IDXGIFactory1.EnumAdapters1": (12, I32, [U32, _PP]),
    "IDXGIAdapter.EnumOutputs": (7, I32, [U32, _PP]),
    "IDXGIAdapter1.GetDesc1": (10, I32, [_P]),
    "IDXGIOutput.GetDesc": (7, I32, [_P]),
    "IDXGIOutput5.DuplicateOutput1": (26, I32, [_P, U32, U32, _P, _PP]),
    "IDXGIDevice.GetAdapter": (7, I32, [_PP]),
    "IDXGIOutputDuplication.AcquireNextFrame": (8, I32, [U32, _P, _PP]),
    "IDXGIOutputDuplication.ReleaseFrame": (14, I32, []),
    "ID3D11Device.CreateBuffer": (3, I32, [_P, _P, _PP]),
    "ID3D11Device.CreateTexture2D": (5, I32, [_P, _P, _PP]),
    "ID3D11Device.CreateShaderResourceView": (7, I32, [_P, _P, _PP]),
    "ID3D11Device.CreateUnorderedAccessView": (8, I32, [_P, _P, _PP]),
    "ID3D11Device.CreateComputeShader": (18, I32, [ctypes.c_char_p, ctypes.c_size_t, _P, _PP]),
    "ID3D11Device.GetDeviceRemovedReason": (39, I32, []),
    "ID3D11DeviceContext.Map": (14, I32, [_P, U32, U32, U32, _P]),
    "ID3D11DeviceContext.Unmap": (15, None, [_P, U32]),
    "ID3D11DeviceContext.Dispatch": (41, None, [U32, U32, U32]),
    "ID3D11DeviceContext.CopyResource": (47, None, [_P, _P]),
    "ID3D11DeviceContext.CSSetShaderResources": (67, None, [U32, U32, _P]),
    "ID3D11DeviceContext.CSSetUnorderedAccessViews": (68, None, [U32, U32, _P, _P]),
    "ID3D11DeviceContext.CSSetShader": (69, None, [_P, _P, U32]),
    "ID3D11DeviceContext.CSSetConstantBuffers": (71, None, [U32, U32, _P]),
    "ID3D11Texture2D.GetDesc": (10, None, [_P]),
    "ID3DBlob.GetBufferPointer": (3, _P, []),
    "ID3DBlob.GetBufferSize": (4, ctypes.c_size_t, []),
}

# Функции DLL: имя -> (DLL, тип ответа, типы аргументов); число аргументов тоже проверяет tests/hdr_test.py.
EXPORTS = {
    "CreateDXGIFactory1": ("dxgi", I32, [_P, _PP]),
    # pAdapter, DriverType, Software, Flags, pFeatureLevels, FeatureLevels, SDKVersion, ppDevice, pFeatureLevel,
    # ppImmediateContext (d3d11.h): 10 аргументов (в 1f7614c не хватало SDKVersion, Windows CI: TypeError)
    "D3D11CreateDevice": ("d3d11", I32, [_P, U32, _P, U32, ctypes.POINTER(U32), U32, U32, _PP, ctypes.POINTER(U32),
                                         _PP]),
    "D3DCompile": ("d3dcompiler_47", I32, [ctypes.c_char_p, ctypes.c_size_t, ctypes.c_char_p, _P, _P,
                                           ctypes.c_char_p, ctypes.c_char_p, U32, U32, _PP, _PP]),
}


class GUID(ctypes.Structure):
    _fields_ = [("Data1", U32), ("Data2", ctypes.c_uint16), ("Data3", ctypes.c_uint16), ("Data4", ctypes.c_ubyte * 8)]

    @classmethod
    def parse(cls, text):
        import uuid
        u = uuid.UUID(text)
        g = cls()
        g.Data1, g.Data2, g.Data3 = u.fields[0], u.fields[1], u.fields[2]
        g.Data4[:] = list(u.bytes[8:])
        return g


IID_IDXGIFactory1 = "770aae78-f26f-4dba-a829-253c83d1b387"
IID_IDXGIOutput5 = "80a07424-ab52-42eb-833c-0c42fd282d98"
IID_ID3D11Texture2D = "6f15aaf2-d208-4e89-9ab4-489535d34f9c"
IID_IDXGIDevice = "54ec77fa-1377-44e6-8c32-88fd5f44c84c"


class RECT(ctypes.Structure):
    _fields_ = [("left", I32), ("top", I32), ("right", I32), ("bottom", I32)]


class DXGI_OUTPUT_DESC(ctypes.Structure):
    _fields_ = [("DeviceName", ctypes.c_uint16 * 32), ("DesktopCoordinates", RECT), ("AttachedToDesktop", I32),
                ("Rotation", U32), ("Monitor", ctypes.c_void_p)]


class DXGI_ADAPTER_DESC1(ctypes.Structure):
    _fields_ = [("Description", ctypes.c_uint16 * 128), ("VendorId", U32), ("DeviceId", U32), ("SubSysId", U32),
                ("Revision", U32), ("DedicatedVideoMemory", ctypes.c_size_t),
                ("DedicatedSystemMemory", ctypes.c_size_t), ("SharedSystemMemory", ctypes.c_size_t),
                ("AdapterLuid", LUID), ("Flags", U32)]


class DXGI_MODE_DESC(ctypes.Structure):
    _fields_ = [("Width", U32), ("Height", U32), ("RefreshNum", U32), ("RefreshDen", U32), ("Format", U32),
                ("ScanlineOrdering", U32), ("Scaling", U32)]


class DXGI_OUTDUPL_DESC(ctypes.Structure):
    _fields_ = [("ModeDesc", DXGI_MODE_DESC), ("Rotation", U32), ("DesktopImageInSystemMemory", I32)]


class DXGI_OUTDUPL_FRAME_INFO(ctypes.Structure):
    _fields_ = [("LastPresentTime", ctypes.c_int64), ("LastMouseUpdateTime", ctypes.c_int64),
                ("AccumulatedFrames", U32), ("RectsCoalesced", I32), ("ProtectedContentMaskedOut", I32),
                ("PointerX", I32), ("PointerY", I32), ("PointerVisible", I32),
                ("TotalMetadataBufferSize", U32), ("PointerShapeBufferSize", U32)]


class D3D11_TEXTURE2D_DESC(ctypes.Structure):
    _fields_ = [("Width", U32), ("Height", U32), ("MipLevels", U32), ("ArraySize", U32), ("Format", U32),
                ("SampleCount", U32), ("SampleQuality", U32), ("Usage", U32), ("BindFlags", U32),
                ("CPUAccessFlags", U32), ("MiscFlags", U32)]


class D3D11_SUBRESOURCE_DATA(ctypes.Structure):
    _fields_ = [("pSysMem", ctypes.c_void_p), ("SysMemPitch", U32), ("SysMemSlicePitch", U32)]


class D3D11_MAPPED_SUBRESOURCE(ctypes.Structure):
    _fields_ = [("pData", ctypes.c_void_p), ("RowPitch", U32), ("DepthPitch", U32)]


class D3D11_BUFFER_DESC(ctypes.Structure):
    _fields_ = [("ByteWidth", U32), ("Usage", U32), ("BindFlags", U32), ("CPUAccessFlags", U32),
                ("MiscFlags", U32), ("StructureByteStride", U32)]


# Перевод scRGB -> sRGB на видеокарте: та же формула, что srgb_oetf/tonemap_value (обрезка, кривая sRGB).
TONEMAP_HLSL = b"""
Texture2D<float4> src : register(t0);
RWTexture2D<unorm float4> dst : register(u0);
cbuffer Params : register(b0) { float gain; uint width; uint height; uint pad; };
[numthreads(16, 16, 1)]
void main(uint3 id : SV_DispatchThreadID)
{
    if (id.x >= width || id.y >= height) return;
    float3 c = saturate(src.Load(int3(id.xy, 0)).rgb * gain);
    float3 lo = c * 12.92;
    float3 hi = 1.055 * pow(c, 1.0 / 2.4) - 0.055;
    dst[id.xy] = float4(c <= 0.0031308 ? lo : hi, 1.0);
}
"""

_FUNCTYPE = getattr(ctypes, "WINFUNCTYPE", ctypes.CFUNCTYPE)   # x64: одно соглашение о вызове
_protos = {}


def vcall(obj, index, restype, argtypes, *args):
    """Вызов метода COM номер index у объекта obj (адрес int); this передаётся первым сам."""
    if not obj:
        raise CaptureFailed("пустой указатель COM")
    if len(args) != len(argtypes):
        raise CaptureFailed(f"метод {index}: {len(args)} аргументов вместо {len(argtypes)}")
    key = (restype, tuple(argtypes))
    proto = _protos.get(key)
    if proto is None:
        proto = _protos[key] = _FUNCTYPE(restype, ctypes.c_void_p, *argtypes)
    vtbl = ctypes.cast(obj, ctypes.POINTER(ctypes.c_void_p))[0]
    fn = ctypes.cast(vtbl, ctypes.POINTER(ctypes.c_void_p))[index]
    return proto(fn)(obj, *args)


def com(name, obj, *args):
    """Метод COM по имени из METHODS."""
    index, restype, argtypes = METHODS[name]
    return vcall(obj, index, restype, argtypes, *args)


def com_hr(name, obj, *args):
    """Метод COM, который отвечает HRESULT: ошибка -> HResultError."""
    hr = com(name, obj, *args)
    if hr < 0:
        raise HResultError(name, hr)
    return hr


def export(lib, name):
    """Функция DLL с типами из EXPORTS."""
    _dll, restype, argtypes = EXPORTS[name]
    fn = getattr(lib, name)
    fn.argtypes, fn.restype = argtypes, restype
    return fn


def release(obj):
    if obj:
        try:
            com("IUnknown.Release", obj)
        except Exception:   # noqa: BLE001
            pass


class _Refs:
    """Объекты COM одного снимка: все отпускаются в конце, что бы ни случилось."""

    def __init__(self):
        self.items = []

    def add(self, ptr):
        if ptr:
            self.items.append(ptr)
        return ptr

    def drop(self, ptr):
        if ptr in self.items:
            self.items.remove(ptr)
            release(ptr)

    def close(self):
        while self.items:
            release(self.items.pop())


PP = ctypes.POINTER(ctypes.c_void_p)


def acquire_frame(acquire, release_frame, recreate, clock=time.monotonic, budget=FIRST_FRAME_BUDGET_S):
    """Получить кадр с картинкой рабочего стола. acquire(timeout_ms) -> (hr, info, resource); release_frame();
    recreate() пересоздаёт дублирование (после ACCESS_LOST, один раз). Кадр только с движением мыши (нет картинки)
    отпускается, ждём дальше. Время ограничено budget: дальше CaptureFailed (снимок через GDI), не зависаем."""
    deadline = clock() + budget
    recreated = False
    while True:
        left_ms = int(max(0.0, deadline - clock()) * 1000)
        hr, info, resource = acquire(max(1, left_ms))
        code = hr & 0xFFFFFFFF
        if code == DXGI_ERROR_WAIT_TIMEOUT:
            if clock() >= deadline:
                raise CaptureFailed(f"нет кадра за {budget * 1000:.0f} мс")
            continue
        if code == DXGI_ERROR_ACCESS_LOST and not recreated:
            recreated = True
            recreate()
            continue
        if hr < 0:
            raise HResultError("AcquireNextFrame", hr)
        if not resource:   # по документации так не бывает; без ресурса читать нечего
            release_frame(None)
            raise CaptureFailed("кадр без ресурса")
        if info.LastPresentTime != 0 or info.AccumulatedFrames > 0:
            return info, resource
        release_frame(resource)   # только указатель мыши: картинки нет
        if clock() >= deadline:
            raise CaptureFailed(f"нет картинки стола за {budget * 1000:.0f} мс")


class DxgiCapturer:
    """Снимок одного выхода DXGI. Устройства D3D11 и шейдеры хранятся по LUID видеокарты, всё остальное (фабрика,
    дублирование, текстуры) создаётся на снимок и отпускается. Все вызовы под замком (прогрев в фоне)."""

    def __init__(self):
        self.lock = threading.Lock()
        self.devices = {}   # (LowPart, HighPart) -> {"device", "context", "level", "cs"}
        self.last_path = ""
        self._dxgi = self._d3d11 = self._compile = None
        self._shader_code = None

    # --- библиотеки ---

    def _libs(self):
        if self._dxgi is None:
            dxgi, d3d11 = ctypes.WinDLL("dxgi"), ctypes.WinDLL("d3d11")
            export(dxgi, "CreateDXGIFactory1")
            export(d3d11, "D3D11CreateDevice")
            self._dxgi, self._d3d11 = dxgi, d3d11
        return self._dxgi, self._d3d11

    def _compiler(self):
        """D3DCompile из системной папки Windows (не по имени: чужую DLL рядом не подхватим), иначе из сборки."""
        if self._compile is None:
            import os
            lib = None
            try:
                from .sysenv import _system_dir
                lib = ctypes.WinDLL(os.path.join(_system_dir(), "d3dcompiler_47.dll"))
            except (OSError, ImportError):
                lib = ctypes.WinDLL("d3dcompiler_47")
            fn = export(lib, "D3DCompile")
            self._compile = fn
        return self._compile

    def shader_code(self) -> bytes:
        if self._shader_code is None:
            code, errors = ctypes.c_void_p(), ctypes.c_void_p()
            hr = self._compiler()(TONEMAP_HLSL, len(TONEMAP_HLSL), b"clipsd_tonemap", None, None, b"main",
                                  b"cs_5_0", 1 << 11, 0, ctypes.byref(code), ctypes.byref(errors))
            try:
                if hr < 0 or not code.value:
                    msg = ""
                    if errors.value:
                        p = com("ID3DBlob.GetBufferPointer", errors.value)
                        n = com("ID3DBlob.GetBufferSize", errors.value)
                        msg = ctypes.string_at(p, n).decode("ascii", "replace").strip()[:200]
                    raise HResultError(f"D3DCompile {msg}", hr)
                p = com("ID3DBlob.GetBufferPointer", code.value)
                n = com("ID3DBlob.GetBufferSize", code.value)
                self._shader_code = ctypes.string_at(p, n)
            finally:
                release(code.value)
                release(errors.value)
        return self._shader_code

    # --- выходы ---

    def _factory(self, refs):
        dxgi, _ = self._libs()
        f = ctypes.c_void_p()
        hr = dxgi.CreateDXGIFactory1(ctypes.byref(GUID.parse(IID_IDXGIFactory1)), ctypes.byref(f))
        if hr < 0:
            raise HResultError("CreateDXGIFactory1", hr)
        return refs.add(f.value)

    def _walk(self, refs):
        """[(адаптер, LUID, выход, DXGI_OUTPUT_DESC)] всех выходов, подключённых к рабочему столу."""
        factory = self._factory(refs)
        found = []
        for a in range(16):
            adapter = ctypes.c_void_p()
            if com("IDXGIFactory1.EnumAdapters1", factory, a, ctypes.byref(adapter)) < 0:
                break
            refs.add(adapter.value)
            ad = DXGI_ADAPTER_DESC1()
            com_hr("IDXGIAdapter1.GetDesc1", adapter.value, ctypes.byref(ad))
            luid = (ad.AdapterLuid.LowPart, ad.AdapterLuid.HighPart)
            for o in range(16):
                output = ctypes.c_void_p()
                if com("IDXGIAdapter.EnumOutputs", adapter.value, o,
                         ctypes.byref(output)) < 0:
                    break
                refs.add(output.value)
                od = DXGI_OUTPUT_DESC()
                com_hr("IDXGIOutput.GetDesc", output.value, ctypes.byref(od))
                if od.AttachedToDesktop:
                    found.append((adapter.value, luid, output.value, od))
        return found

    def outputs(self) -> list:
        if not self.lock.acquire(timeout=LOCK_TIMEOUT_S):
            raise CaptureFailed("занято прогревом")
        refs = _Refs()
        try:
            out = []
            for _a, _l, _o, od in self._walk(refs):
                r = od.DesktopCoordinates
                out.append(OutputInfo(wstr(od.DeviceName), (r.left, r.top, r.right - r.left, r.bottom - r.top),
                                      od.Rotation))
            return out
        finally:
            refs.close()
            self.lock.release()

    # --- устройство ---

    def _device(self, adapter, luid, fresh=False):
        entry = self.devices.get(luid)
        if entry is not None and not fresh:
            if com("ID3D11Device.GetDeviceRemovedReason", entry["device"]) == S_OK:
                return entry
            fresh = True
        if entry is not None and fresh:
            self._drop_device(luid)
        _, d3d11 = self._libs()
        levels = (U32 * 2)(0xB100, FL_11_0)
        dev, ctx, got = ctypes.c_void_p(), ctypes.c_void_p(), U32(0)
        hr = d3d11.D3D11CreateDevice(adapter, D3D_DRIVER_TYPE_UNKNOWN, None, 0, levels, 2, D3D11_SDK_VERSION,
                                     ctypes.byref(dev), ctypes.byref(got), ctypes.byref(ctx))
        if hr < 0:   # видеокарта без 11.x (очень старая): уровни 10.x, перевод цвета тогда на процессоре
            levels = (U32 * 2)(0xA100, 0xA000)
            hr = d3d11.D3D11CreateDevice(adapter, D3D_DRIVER_TYPE_UNKNOWN, None, 0, levels, 2, D3D11_SDK_VERSION,
                                         ctypes.byref(dev), ctypes.byref(got), ctypes.byref(ctx))
        if hr < 0:
            raise HResultError("D3D11CreateDevice", hr)
        entry = {"device": dev.value, "context": ctx.value, "level": got.value, "cs": None, "cs_failed": False}
        self.devices[luid] = entry
        return entry

    def _drop_device(self, luid):
        entry = self.devices.pop(luid, None)
        if entry:
            release(entry["cs"])
            release(entry["context"])
            release(entry["device"])

    def _shader(self, entry):
        """Вычислительный шейдер этого устройства; None: нет (уровень ниже 11.0 или не собрался) -> процессор."""
        if entry["cs"] or entry["cs_failed"]:
            return entry["cs"]
        try:
            if entry["level"] < FL_11_0:
                raise CaptureFailed("уровень D3D ниже 11.0")
            code = self.shader_code()
            cs = ctypes.c_void_p()
            com_hr("ID3D11Device.CreateComputeShader", entry["device"], code, len(code), None, ctypes.byref(cs))
            entry["cs"] = cs.value
        except Exception as exc:   # noqa: BLE001
            entry["cs_failed"] = True
            _log(f"шейдер недоступен ({type(exc).__name__}: {exc}), перевод цвета на процессоре")
        return entry["cs"]

    # --- текстуры ---

    def _texture(self, refs, dev, w, h, fmt, usage, bind, cpu=0, init=None, pitch=0):
        desc = D3D11_TEXTURE2D_DESC(w, h, 1, 1, fmt, 1, 0, usage, bind, cpu, 0)
        data = None
        if init is not None:
            data = D3D11_SUBRESOURCE_DATA(ctypes.cast(init, ctypes.c_void_p), pitch, 0)
        tex = ctypes.c_void_p()
        com_hr("ID3D11Device.CreateTexture2D", dev, ctypes.byref(desc), ctypes.byref(data) if data is not None else None, ctypes.byref(tex))
        return refs.add(tex.value)

    def _read(self, entry, refs, tex, w, h, fmt, bpp):
        """Текстура -> QImage через промежуточную текстуру для чтения процессором."""
        from PyQt6.QtGui import QImage
        dev, ctx = entry["device"], entry["context"]
        staging = self._texture(refs, dev, w, h, fmt, USAGE_STAGING, 0, CPU_ACCESS_READ)
        com("ID3D11DeviceContext.CopyResource", ctx, staging, tex)
        qfmt = {FMT_R8G8B8A8_UNORM: QImage.Format.Format_RGBX8888, FMT_B8G8R8A8_UNORM: QImage.Format.Format_RGB32,
                FMT_R16G16B16A16_FLOAT: QImage.Format.Format_RGBX16FPx4}[fmt]
        img = QImage(w, h, qfmt)
        mapped = D3D11_MAPPED_SUBRESOURCE()
        com_hr("ID3D11DeviceContext.Map", ctx, staging, 0, MAP_READ, 0,
                ctypes.byref(mapped))
        try:
            bits = img.bits()
            bits.setsize(img.sizeInBytes())
            base, bpl, row = int(bits), img.bytesPerLine(), w * bpp
            if mapped.RowPitch == bpl:
                ctypes.memmove(base, mapped.pData, bpl * h)
            else:
                for y in range(h):
                    ctypes.memmove(base + y * bpl, mapped.pData + y * mapped.RowPitch, row)
        finally:
            com("ID3D11DeviceContext.Unmap", ctx, staging, 0)
        return img

    def gpu_tonemap(self, entry, refs, src_f16, w, h, gain):
        """Текстура FP16 (с привязкой SHADER_RESOURCE) -> QImage RGBX8888 sRGB через шейдер; None: шейдера нет."""
        cs = self._shader(entry)
        if not cs:
            return None
        dev, ctx = entry["device"], entry["context"]
        srv, uav, cb = ctypes.c_void_p(), ctypes.c_void_p(), ctypes.c_void_p()
        com_hr("ID3D11Device.CreateShaderResourceView", dev, src_f16, None, ctypes.byref(srv))
        refs.add(srv.value)
        out = self._texture(refs, dev, w, h, FMT_R8G8B8A8_UNORM, USAGE_DEFAULT, BIND_UNORDERED_ACCESS)
        com_hr("ID3D11Device.CreateUnorderedAccessView", dev, out, None, ctypes.byref(uav))
        refs.add(uav.value)
        params = struct.pack("<fIII", gain, w, h, 0)
        pbuf = ctypes.create_string_buffer(params, 16)
        bdesc = D3D11_BUFFER_DESC(16, USAGE_IMMUTABLE, BIND_CONSTANT_BUFFER, 0, 0, 0)
        bdata = D3D11_SUBRESOURCE_DATA(ctypes.cast(pbuf, ctypes.c_void_p), 16, 0)
        com_hr("ID3D11Device.CreateBuffer", dev, ctypes.byref(bdesc), ctypes.byref(bdata), ctypes.byref(cb))
        refs.add(cb.value)
        one = ctypes.c_void_p
        srvs, uavs, cbs = (one * 1)(srv.value), (one * 1)(uav.value), (one * 1)(cb.value)
        none = (one * 1)(None)
        com("ID3D11DeviceContext.CSSetShader", ctx, cs, None, 0)
        com("ID3D11DeviceContext.CSSetShaderResources", ctx, 0, 1, srvs)
        com("ID3D11DeviceContext.CSSetUnorderedAccessViews", ctx, 0, 1, uavs, None)
        com("ID3D11DeviceContext.CSSetConstantBuffers", ctx, 0, 1, cbs)
        com("ID3D11DeviceContext.Dispatch", ctx, (w + 15) // 16, (h + 15) // 16, 1)
        com("ID3D11DeviceContext.CSSetShaderResources", ctx, 0, 1, none)
        com("ID3D11DeviceContext.CSSetUnorderedAccessViews", ctx, 0, 1, none, None)
        com("ID3D11DeviceContext.CSSetConstantBuffers", ctx, 0, 1, none)
        com("ID3D11DeviceContext.CSSetShader", ctx, None, None, 0)
        return self._read(entry, refs, out, w, h, FMT_R8G8B8A8_UNORM, 4)

    # --- снимок ---

    def grab(self, device_name: str, gain: float, hdr: bool = True):
        """QImage выхода device_name в ориентации рабочего стола. hdr=True: просим FP16 и требуем FP16 (кадр 8 бит
        на мониторе HDR был бы тем же блёклым), перевод цвета с множителем gain. hdr=False: B8G8R8A8 как есть
        (проверка в CI на обычном мониторе). Ошибка: CaptureFailed/HResultError."""
        if not self.lock.acquire(timeout=LOCK_TIMEOUT_S):
            raise CaptureFailed("занято прогревом")
        refs = _Refs()
        try:
            return self._grab(refs, device_name, gain, hdr)
        finally:
            refs.close()
            self.lock.release()

    def _grab(self, refs, device_name, gain, hdr):
        candidates = [c for c in self._walk(refs) if wstr(c[3].DeviceName) == device_name]
        if not candidates:
            raise CaptureFailed(f"выход {device_name} не найден")
        first = None
        for adapter, luid, output, od in candidates:   # гибридная графика: тот же выход может числиться у двух карт
            try:
                return self._grab_output(refs, adapter, luid, output, od, gain, hdr)
            except HResultError as exc:
                first = first or exc
                if exc.hr in (E_ACCESSDENIED, DXGI_ERROR_SESSION_DISCONNECTED, DXGI_ERROR_NOT_CURRENTLY_AVAILABLE):
                    break   # защищённый стол, RDP, занято другими: другая видеокарта не поможет
        raise first   # первая ошибка с кодом (HResultError): по коду видно, окружение это или ошибка вызова

    def _duplicate(self, refs, entry, output, hdr):
        out5 = ctypes.c_void_p()
        com_hr("IUnknown.QueryInterface", output, ctypes.byref(GUID.parse(IID_IDXGIOutput5)), ctypes.byref(out5))
        refs.add(out5.value)
        fmts = [FMT_R16G16B16A16_FLOAT, FMT_B8G8R8A8_UNORM] if hdr else [FMT_B8G8R8A8_UNORM]
        arr = (U32 * len(fmts))(*fmts)
        dup = ctypes.c_void_p()
        # DuplicateOutput1 отвечает DXGI_ERROR_UNSUPPORTED процессу без DPI «по мониторам v2» (известное поведение,
        # в документации не описано). Qt 6 ставит его процессу сам; на время вызова ставим и потоку, на всякий случай.
        set_dpi = getattr(ctypes.WinDLL("user32"), "SetThreadDpiAwarenessContext", None)   # Windows 10 1607+
        before = None
        if set_dpi is not None:
            set_dpi.argtypes, set_dpi.restype = [ctypes.c_void_p], ctypes.c_void_p
            before = set_dpi(ctypes.c_void_p(-4))   # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2
        try:
            com_hr("IDXGIOutput5.DuplicateOutput1", out5.value, entry["device"], 0, len(fmts), arr,
                    ctypes.byref(dup))
        finally:
            if before:
                set_dpi(before)
        return refs.add(dup.value)

    def _own_output(self, refs, entry, device_name, fallback):
        """Тот же выход, но перечисленный через адаптер самого устройства (IDXGIDevice::GetAdapter): устройство из кэша
        создано на адаптере прошлой фабрики, а DuplicateOutput1 требует устройство «с адаптера этого выхода». Не вышло:
        выход из текущего перечисления."""
        try:
            dxgi_dev, adapter = ctypes.c_void_p(), ctypes.c_void_p()
            com_hr("IUnknown.QueryInterface", entry["device"], ctypes.byref(GUID.parse(IID_IDXGIDevice)), ctypes.byref(dxgi_dev))
            refs.add(dxgi_dev.value)
            com_hr("IDXGIDevice.GetAdapter", dxgi_dev.value, ctypes.byref(adapter))
            refs.add(adapter.value)
            for o in range(16):
                output = ctypes.c_void_p()
                if com("IDXGIAdapter.EnumOutputs", adapter.value, o,
                         ctypes.byref(output)) < 0:
                    break
                refs.add(output.value)
                od = DXGI_OUTPUT_DESC()
                com_hr("IDXGIOutput.GetDesc", output.value, ctypes.byref(od))
                if wstr(od.DeviceName) == device_name:
                    return output.value
        except CaptureFailed:
            pass
        return fallback

    def _grab_output(self, refs, adapter, luid, output, od, gain, hdr):
        entry = self._device(adapter, luid)
        name = wstr(od.DeviceName)
        output = self._own_output(refs, entry, name, output)
        try:
            dup = self._duplicate(refs, entry, output, hdr)
        except HResultError as exc:
            if exc.hr not in (E_INVALIDARG, DXGI_ERROR_DEVICE_REMOVED):
                raise
            _log(f"{name}: устройство D3D11 создаётся заново ({exc})")
            entry = self._device(adapter, luid, fresh=True)   # устройство устарело (смена видеокарты, драйвера)
            output = self._own_output(refs, entry, name, output)
            dup = self._duplicate(refs, entry, output, hdr)
        holder = {"dup": dup}

        def acquire(timeout_ms):
            info, res = DXGI_OUTDUPL_FRAME_INFO(), ctypes.c_void_p()
            hr = com("IDXGIOutputDuplication.AcquireNextFrame", holder["dup"], timeout_ms,
                       ctypes.byref(info), ctypes.byref(res))
            return hr, info, res.value

        def release_frame(res):
            release(res)
            com("IDXGIOutputDuplication.ReleaseFrame", holder["dup"])

        def recreate():   # DXGI_ERROR_ACCESS_LOST: смена режима, стола; дублирование создаётся заново
            refs.drop(holder["dup"])
            holder["dup"] = self._duplicate(refs, entry, output, hdr)

        _info, res = acquire_frame(acquire, release_frame, recreate)
        try:
            tex = ctypes.c_void_p()
            com_hr("IUnknown.QueryInterface", res, ctypes.byref(GUID.parse(IID_ID3D11Texture2D)), ctypes.byref(tex))
            refs.add(tex.value)
            td = D3D11_TEXTURE2D_DESC()
            com("ID3D11Texture2D.GetDesc", tex.value, ctypes.byref(td))
            w, h, fmt = td.Width, td.Height, td.Format
            dev, ctx = entry["device"], entry["context"]
            if hdr and fmt != FMT_R16G16B16A16_FLOAT:
                raise CaptureFailed(f"кадр в формате {fmt}, а не FP16")
            # Кадр DXGI отпускается только после чтения (Map ждёт конца работы видеокарты): копия не может
            # прочитать уже следующий кадр DWM.
            if fmt == FMT_R16G16B16A16_FLOAT:
                # своя копия с привязкой для шейдера (у текстуры DXGI её может не быть)
                copy = self._texture(refs, dev, w, h, fmt, USAGE_DEFAULT, BIND_SHADER_RESOURCE)
                com("ID3D11DeviceContext.CopyResource", ctx, copy, tex.value)
                try:
                    img = self.gpu_tonemap(entry, refs, copy, w, h, gain)
                except HResultError as exc:   # нехватка памяти видеокарты и т.п.: перевод на процессоре
                    _log(f"шейдер не выполнился ({exc}), перевод цвета на процессоре")
                    img = None
                self.last_path = "DXGI FP16, перевод цвета на видеокарте"
                if img is None:
                    img = tonemap_qimage(self._read(entry, refs, copy, w, h, fmt, 8), gain)
                    self.last_path = "DXGI FP16, перевод цвета на процессоре"
            elif fmt == FMT_B8G8R8A8_UNORM:
                img = self._read(entry, refs, tex.value, w, h, fmt, 4)
                self.last_path = "DXGI B8G8R8A8"
            else:
                raise CaptureFailed(f"неожиданный формат кадра {fmt}")
        finally:
            release_frame(res)
        return rotate_to_desktop(img, od.Rotation)

    # --- прогрев ---

    def prewarm(self, device_names):
        """Создать устройство и шейдер для видеокарт этих выходов заранее (в фоне), чтобы первый снимок не ждал
        загрузки драйвера и сборки шейдера."""
        if not self.lock.acquire(timeout=5.0):
            return
        refs = _Refs()
        try:
            for adapter, luid, _output, od in self._walk(refs):
                if wstr(od.DeviceName) in device_names:
                    self._shader(self._device(adapter, luid))
        finally:
            refs.close()
            self.lock.release()


_shared = None
_shared_lock = threading.Lock()


def shared_capturer() -> DxgiCapturer:
    global _shared
    with _shared_lock:   # прогрев в фоне и снимок не должны создать два набора устройств
        if _shared is None:
            _shared = DxgiCapturer()
        return _shared


def prewarm():
    """Фоновый прогрев (вызывается из grab.prewarm_hdr в отдельном потоке). Без HDR и расширенного цвета ничего не
    делает: D3D не загружается. Любая ошибка только в журнал."""
    try:
        names = {s.device for s in display_states() if s.mode in (MODE_HDR, MODE_WCG)}
        if names:
            t0 = time.perf_counter()
            shared_capturer().prewarm(names)
            _log(f"прогрев {', '.join(sorted(names))}: {(time.perf_counter() - t0) * 1000:.0f} мс")
    except Exception as exc:   # noqa: BLE001
        _log(f"прогрев не удался ({type(exc).__name__}: {exc})")
