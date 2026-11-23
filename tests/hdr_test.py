# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""Снимок монитора Windows с HDR (clipshot/win_hdr.py, grab.grab_qt): всё, что проверяется без Windows.

1. Раскладки структур DisplayConfig, DXGI, D3D11 (размеры и смещения как в SDK x64), GUID.
2. Перевод scRGB -> sRGB: множитель по белому SDR 80/200/300 нит, белый SDR = 255, серый 128 остаётся 128, ярче белого
   и отрицательное обрезаются, все 256 уровней sRGB возвращаются после FP16; тот же расчёт в Qt (tonemap_qimage) не
   дальше 1 от эталона, время на 4K.
3. Поворот кадра (DXGI 90/180/270 по часовой), режим монитора из DisplayConfig (_2 и старый вид), чтение
   DisplayConfig с подменённым user32 (белый 2500 -> 200 нит, повтор при ERROR_INSUFFICIENT_BUFFER).
4. Ожидание кадра: таймауты, ACCESS_LOST (одно пересоздание), кадр только с мышью, предел времени, отказ доступа.
5. Сопоставление выходов DXGI с экранами Qt, выбор пути: HDR-монитор -> новый путь с нужным множителем, ошибка ->
   GDI, обычный монитор не трогается, без HDR DXGI вообще не вызывается.
6. grab_qt: снимок HDR-монитора встаёт в общий кадр и в _native_shots при разном масштабе, GDI для него не зовётся;
   сбой нового пути: тот же монитор через GDI.

Запуск: QT_QPA_PLATFORM=offscreen python3 tests/hdr_test.py
"""
import ctypes
import math
import os
import struct
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt6.QtCore import QRect, Qt
from PyQt6.QtGui import QColor, QImage, QPixmap
from PyQt6.QtWidgets import QApplication

app = QApplication([])
from clipshot import grab, win_hdr as wh

fails = []


def check(ok, text):
    print(("OK   " if ok else "FAIL ") + text)
    if not ok:
        fails.append(text)


# --- 1. структуры ------------------------------------------------------------------------------------------------
sizes = {"DcHeader": 20, "DcPath": 72, "DcMode": 64, "DcSourceName": 84, "DcAdvColor": 32, "DcAdvColor2": 36,
         "DcSdrWhite": 24, "DXGI_OUTPUT_DESC": 96, "DXGI_OUTDUPL_FRAME_INFO": 48, "D3D11_TEXTURE2D_DESC": 44,
         "DXGI_OUTDUPL_DESC": 36, "DXGI_ADAPTER_DESC1": 312, "D3D11_MAPPED_SUBRESOURCE": 16,
         "D3D11_SUBRESOURCE_DATA": 16, "D3D11_BUFFER_DESC": 24, "GUID": 16}
for name, size in sizes.items():
    got = ctypes.sizeof(getattr(wh, name))
    check(got == size, f"sizeof({name}) = {got}, в SDK x64 {size}")
check(wh.DXGI_OUTPUT_DESC.Monitor.offset == 88, "DXGI_OUTPUT_DESC.Monitor со смещения 88")
check(wh.DXGI_OUTPUT_DESC.Rotation.offset == 84, "DXGI_OUTPUT_DESC.Rotation со смещения 84")
check(wh.DXGI_OUTDUPL_FRAME_INFO.AccumulatedFrames.offset == 16, "FRAME_INFO.AccumulatedFrames со смещения 16")
check(wh.DXGI_ADAPTER_DESC1.AdapterLuid.offset == 296, "ADAPTER_DESC1.AdapterLuid со смещения 296")
check(wh.DcAdvColor2.activeColorMode.offset == 32, "ADVANCED_COLOR_INFO_2.activeColorMode со смещения 32")
g = wh.GUID.parse(wh.IID_IDXGIOutput5)
check((g.Data1, g.Data2, g.Data3, list(g.Data4)) == (0x80a07424, 0xab52, 0x42eb,
                                                     [0x83, 0x3c, 0x0c, 0x42, 0xfd, 0x28, 0x2d, 0x98]),
      "GUID IDXGIOutput5 разобран как в dxgi1_5.h")

# --- 1б. сигнатуры COM и функций DLL (класс ошибки 1f7614c: D3D11CreateDevice без SDKVersion, Windows CI) -----------
# Эталон выписан из mingw-w64 (d3d11.h, dxgi.h, dxgi1_2.h, dxgi1_5.h, d3dcommon.h, d3dcompiler.h) скриптом по *Vtbl:
# имя -> (номер метода, число аргументов без this, метод void).
SDK = {
    "IUnknown.QueryInterface": (0, 2, False), "IUnknown.Release": (2, 0, False),
    "IDXGIFactory1.EnumAdapters1": (12, 2, False), "IDXGIAdapter.EnumOutputs": (7, 2, False),
    "IDXGIAdapter1.GetDesc1": (10, 1, False), "IDXGIOutput.GetDesc": (7, 1, False),
    "IDXGIOutput5.DuplicateOutput1": (26, 5, False), "IDXGIDevice.GetAdapter": (7, 1, False),
    "IDXGIOutputDuplication.AcquireNextFrame": (8, 3, False), "IDXGIOutputDuplication.ReleaseFrame": (14, 0, False),
    "ID3D11Device.CreateBuffer": (3, 3, False), "ID3D11Device.CreateTexture2D": (5, 3, False),
    "ID3D11Device.CreateShaderResourceView": (7, 3, False), "ID3D11Device.CreateUnorderedAccessView": (8, 3, False),
    "ID3D11Device.CreateComputeShader": (18, 4, False), "ID3D11Device.GetDeviceRemovedReason": (39, 0, False),
    "ID3D11DeviceContext.Map": (14, 5, False), "ID3D11DeviceContext.Unmap": (15, 2, True),
    "ID3D11DeviceContext.Dispatch": (41, 3, True), "ID3D11DeviceContext.CopyResource": (47, 2, True),
    "ID3D11DeviceContext.CSSetShaderResources": (67, 3, True),
    "ID3D11DeviceContext.CSSetUnorderedAccessViews": (68, 4, True),
    "ID3D11DeviceContext.CSSetShader": (69, 3, True), "ID3D11DeviceContext.CSSetConstantBuffers": (71, 3, True),
    "ID3D11Texture2D.GetDesc": (10, 1, True), "ID3DBlob.GetBufferPointer": (3, 0, False),
    "ID3DBlob.GetBufferSize": (4, 0, False),
}
SDK_EXPORTS = {"CreateDXGIFactory1": 2, "D3D11CreateDevice": 10, "D3DCompile": 11}
bad = [n for n, (idx, nargs, void) in SDK.items()
       if n not in wh.METHODS or wh.METHODS[n][0] != idx or len(wh.METHODS[n][2]) != nargs
       or (wh.METHODS[n][1] is None) != void]
check(not bad and set(wh.METHODS) <= set(SDK), f"METHODS: номера, число аргументов и void как в SDK {bad}")
bad = [n for n, k in SDK_EXPORTS.items() if len(wh.EXPORTS[n][2]) != k]
check(not bad and set(wh.EXPORTS) == set(SDK_EXPORTS), f"EXPORTS: число аргументов как в SDK {bad}")

import ast
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
problems, seen = [], 0
for rel in ("clipshot/win_hdr.py", "tests/hdr_win_test.py"):
    tree = ast.parse(open(os.path.join(here, rel), encoding="utf-8").read())
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or any(isinstance(a, ast.Starred) for a in node.args) or node.keywords:
            continue
        f = node.func
        fname = f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else None
        if fname in ("com", "com_hr") and node.args and isinstance(node.args[0], ast.Constant):
            name, given = node.args[0].value, len(node.args) - 2
            want = len(wh.METHODS[name][2]) if name in wh.METHODS else None
            seen += 1
            if want != given:
                problems.append(f"{rel}:{node.lineno} {name}: {given} вместо {want}")
        elif fname in wh.EXPORTS:
            seen += 1
            if len(node.args) != len(wh.EXPORTS[fname][2]):
                problems.append(f"{rel}:{node.lineno} {fname}: {len(node.args)} вместо {len(wh.EXPORTS[fname][2])}")
        elif isinstance(f, ast.Call) and isinstance(f.func, ast.Attribute) and f.func.attr == "_compiler":
            seen += 1
            if len(node.args) != len(wh.EXPORTS["D3DCompile"][2]):
                problems.append(f"{rel}:{node.lineno} D3DCompile: {len(node.args)} аргументов")
check(not problems and seen >= 40, f"каждый вызов COM и DLL с числом аргументов по таблице ({seen} вызовов) {problems}")
try:
    wh.vcall(0x1000, 3, wh.I32, [wh.U32], 1, 2)
    check(False, "лишний аргумент отклоняется до вызова")
except wh.CaptureFailed:
    check(True, "лишний аргумент к методу COM отклоняется до вызова (не падение, а откат на GDI)")
try:
    wh.com("IUnknown.Release", None)
    check(False, "пустой указатель COM отклоняется")
except wh.CaptureFailed:
    check(True, "пустой указатель COM отклоняется до вызова")

# --- 2. перевод цвета --------------------------------------------------------------------------------------------
check(wh.gain_for(wh.MODE_HDR, 80) == 1.0, "HDR, белый 80 нит: множитель 1")
check(abs(wh.gain_for(wh.MODE_HDR, 200) - 0.4) < 1e-12, "HDR, белый 200 нит: множитель 0.4")
check(abs(wh.gain_for(wh.MODE_HDR, 300) - 80 / 300) < 1e-12, "HDR, белый 300 нит: множитель 80/300")
check(wh.gain_for(wh.MODE_HDR, None) is None and wh.gain_for(wh.MODE_HDR, 0) is None, "HDR без белого: нет множителя")
check(wh.gain_for(wh.MODE_WCG, None) == 1.0, "расширенный цвет без HDR: множитель 1 (1.0 = белый монитора)")
check(wh.gain_for(wh.MODE_SDR, 200) is None, "обычный монитор: новый путь не нужен")


def lin(code):
    c = code / 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def f16(v):
    return struct.unpack("<e", struct.pack("<e", v))[0]


for white in (80, 200, 300):
    gain = wh.gain_for(wh.MODE_HDR, white)
    k = white / 80.0
    check(wh.tonemap_value(f16(k), gain) == 255, f"{white} нит: белый SDR (scRGB {k:.3f}) -> 255")
    check(wh.tonemap_value(f16(lin(128) * k), gain) == 128, f"{white} нит: серый 128 остаётся 128")
    check(wh.tonemap_value(0.0, gain) == 0, f"{white} нит: чёрный 0")
    check(wh.tonemap_value(f16(-0.3), gain) == 0, f"{white} нит: вне sRGB (отрицательное) -> 0")
    check(wh.tonemap_value(f16(3 * k), gain) == 255, f"{white} нит: блик HDR ярче белого -> 255 (обрезка)")
    diffs = [abs(wh.tonemap_value(f16(lin(c) * k), gain) - c) for c in range(256)]
    check(max(diffs) <= 1 and diffs.count(0) >= 250,
          f"{white} нит: 256 уровней sRGB после FP16 (точно {diffs.count(0)}, не дальше {max(diffs)})")
check(wh.tonemap_value(0.2, 1.0) == 124, "линейное 0.2 -> sRGB 124")
check(wh.tonemap_value(float("nan"), 0.4) == 0 and wh.tonemap_value(float("inf"), 0.4) == 255, "NaN -> 0, inf -> 255")
check(wh.tonemap_value(0.002, 1.0) == 7, "тёмный участок (линейная часть sRGB): 0.002 -> 7")


def f16_image(values):
    """QImage RGBX16FPx4 одной строкой: values = [(r, g, b)]."""
    raw = b"".join(struct.pack("<eeee", r, g_, b, 1.0) for r, g_, b in values)
    return QImage(raw, len(values), 1, len(values) * 8, QImage.Format.Format_RGBX16FPx4).copy(), raw


samples = [(i / 50.0, (50 - i) / 25.0, (i % 7) / 3.0 - 0.5) for i in range(51)]
samples += [(lin(c) * 2.5, lin(255 - c) * 2.5, lin(c // 2) * 2.5) for c in range(0, 256, 3)]
for white in (80, 200, 300):
    gain = wh.gain_for(wh.MODE_HDR, white)
    img, raw = f16_image(samples)
    ref = wh.tonemap_reference(raw, gain)
    out = wh.tonemap_qimage(img, gain)
    worst = 0
    for x in range(out.width()):
        c = out.pixelColor(x, 0)
        for ch, got in enumerate((c.red(), c.green(), c.blue())):
            worst = max(worst, abs(got - ref[x * 3 + ch]))
    check(out.format() == QImage.Format.Format_RGB32 and worst <= 1,
          f"{white} нит: перевод в Qt не дальше 1 от эталона (наибольшее {worst}), RGB32")
img, raw = f16_image([(1.0, 0.5, 0.25)])
out = wh.tonemap_qimage(img, 1.0)
c = out.pixelColor(0, 0)
check((c.red(), c.green(), c.blue()) == tuple(wh.tonemap_value(f16(v), 1.0) for v in (1.0, 0.5, 0.25)),
      "множитель 1 (расширенный цвет): только кривая sRGB")

W4, H4 = 3840, 2160
row = b"".join(struct.pack("<eeee", (i / W4) * 3.0, 0.5, 2.5, 1.0) for i in range(W4))
big = QImage(row * H4, W4, H4, W4 * 8, QImage.Format.Format_RGBX16FPx4)
t0 = time.perf_counter()
out = wh.tonemap_qimage(big, 0.4)
ms = (time.perf_counter() - t0) * 1000
check(out.size() == big.size() and ms < 3000, f"4K на процессоре (запасной путь без шейдера): {ms:.0f} мс")
print(f"INFO запасной перевод цвета на процессоре, 3840x2160: {ms:.0f} мс")

# --- 3. поворот, режим, DisplayConfig ------------------------------------------------------------------------------
src = QImage(3, 2, QImage.Format.Format_RGB32)
src.fill(QColor("black"))
src.setPixelColor(0, 0, QColor("red"))     # левый верхний угол текстуры (как её видит монитор)
r90 = wh.rotate_to_desktop(src, 2)
r180 = wh.rotate_to_desktop(src, 3)
r270 = wh.rotate_to_desktop(src, 4)
check(wh.rotate_to_desktop(src, 1) is src and wh.rotate_to_desktop(src, 0) is src, "без поворота: та же картинка")
check(r90.size().width() == 2 and r90.size().height() == 3 and r90.pixelColor(1, 0).name() == "#ff0000",
      "ROTATE90: по часовой, левый верхний угол уходит в правый верхний")
check(r180.pixelColor(2, 1).name() == "#ff0000", "ROTATE180: левый верхний угол в правый нижний")
check(r270.size().width() == 2 and r270.pixelColor(0, 2).name() == "#ff0000", "ROTATE270: левый верхний в левый нижний")
try:
    wh.rotate_to_desktop(src, 9)
    check(False, "неизвестный поворот отклоняется")
except wh.CaptureFailed:
    check(True, "неизвестный поворот отклоняется (снимок через GDI)")


def adv2(mode, bits=10):
    s = wh.DcAdvColor2()
    s.activeColorMode, s.bitsPerColorChannel = mode, bits
    return s


def adv(value, bits=10):
    s = wh.DcAdvColor()
    s.value, s.bitsPerColorChannel = value, bits
    return s


check(wh.mode_of(None, adv2(2)) == (wh.MODE_HDR, 10), "_2: activeColorMode 2 -> HDR")
check(wh.mode_of(adv(0b011), adv2(1)) == (wh.MODE_WCG, 10), "_2 главнее старого: activeColorMode 1 -> WCG")
check(wh.mode_of(adv(0b011), adv2(0, 8)) == (wh.MODE_SDR, 8), "_2: activeColorMode 0 -> SDR")
check(wh.mode_of(adv(0b011), None)[0] == wh.MODE_HDR, "старый вид: включён расширенный цвет без wideColorEnforced -> HDR")
check(wh.mode_of(adv(0b111), None)[0] == wh.MODE_WCG, "старый вид: wideColorEnforced -> WCG")
check(wh.mode_of(adv(0b001), None)[0] == wh.MODE_SDR, "старый вид: поддерживается, но выключен -> SDR")
check(wh.mode_of(None, None)[0] is None, "нет ответов: режим неизвестен")


class FakeUser32:
    """DisplayConfig двух мониторов: DISPLAY1 HDR (белый 2500 = 200 нит), DISPLAY2 обычный; _2 не поддерживается
    (Windows до 24H2), первый QueryDisplayConfig отвечает ERROR_INSUFFICIENT_BUFFER."""

    def __init__(self):
        self.queries = 0

    def GetDisplayConfigBufferSizes(self, flags, n_paths, n_modes):
        n_paths._obj.value, n_modes._obj.value = 2, 4
        return 0

    def QueryDisplayConfig(self, flags, n_paths, paths, n_modes, modes, _topology):
        self.queries += 1
        if self.queries == 1:
            return wh.ERROR_INSUFFICIENT_BUFFER
        for i in range(2):
            paths[i].sourceInfo.id = 10 + i
            paths[i].targetInfo.id = 20 + i
            paths[i].targetInfo.adapterId.LowPart = 7
        return 0

    def DisplayConfigGetDeviceInfo(self, ref):
        s = ref._obj
        t, ident = s.header.type, s.header.id
        if t == wh.GET_SOURCE_NAME:
            name = "\\\\.\\DISPLAY%d" % (ident - 9)
            for i, ch in enumerate(name):
                s.viewGdiDeviceName[i] = ord(ch)
            return 0
        if t == wh.GET_ADVANCED_COLOR_INFO:
            check(ctypes.sizeof(s) == s.header.size == 32 and s.header.adapterId.LowPart == 7,
                  "запрос цвета: размер в заголовке, видеокарта и монитор из пути") if ident == 20 else None
            s.value, s.bitsPerColorChannel = (0b011, 10) if ident == 20 else (0b000, 8)
            return 0
        if t == wh.GET_SDR_WHITE_LEVEL:
            s.SDRWhiteLevel = 2500
            return 0
        return 87   # ERROR_INVALID_PARAMETER: тип 15 неизвестен


states = wh.display_states(FakeUser32())
check([(s.device, s.mode, s.white_nits, s.bits) for s in states] ==
      [("\\\\.\\DISPLAY1", "hdr", 200.0, 10), ("\\\\.\\DISPLAY2", "sdr", None, 8)],
      f"DisplayConfig: HDR 200 нит и обычный монитор ({wh.states_line(states)})")
check(wh.display_states() == [] if sys.platform != "win32" else True, "не Windows: пустой список без вызовов")

# --- 4. ожидание кадра -----------------------------------------------------------------------------------------------


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def frame(present=1, frames=1):
    info = wh.DXGI_OUTDUPL_FRAME_INFO()
    info.LastPresentTime, info.AccumulatedFrames = present, frames
    return info


def run_acquire(script, budget=0.25):
    """script: список ответов acquire: ("timeout", мс) | ("lost",) | ("denied",) | ("mouse",) | ("frame",)."""
    clock, released, recreated, timeouts = Clock(), [], [], []
    steps = list(script)

    def acquire(timeout_ms):
        timeouts.append(timeout_ms)
        kind = steps.pop(0) if steps else ("timeout", timeout_ms)
        if kind[0] == "timeout":
            clock.t += kind[1] / 1000.0
            return wh.DXGI_ERROR_WAIT_TIMEOUT - (1 << 32), None, None
        clock.t += 0.001
        if kind[0] == "lost":
            return wh.DXGI_ERROR_ACCESS_LOST - (1 << 32), None, None
        if kind[0] == "denied":
            return wh.E_ACCESSDENIED - (1 << 32), None, None
        if kind[0] == "mouse":
            return 0, frame(0, 0), "mouse-res"
        return 0, frame(), "res"

    try:
        info, res = wh.acquire_frame(acquire, released.append, lambda: recreated.append(1), clock, budget)
        return "ok", res, released, recreated, timeouts, clock.t
    except wh.HResultError as exc:
        return ("hr", exc.hr), None, released, recreated, timeouts, clock.t
    except wh.CaptureFailed as exc:
        return "failed", str(exc), released, recreated, timeouts, clock.t


r = run_acquire([("frame",)])
check(r[0] == "ok" and r[1] == "res" and r[4] == [250], "кадр сразу: ждём не дольше 250 мс")
r = run_acquire([("timeout", 30), ("timeout", 30), ("frame",)])
check(r[0] == "ok" and r[4][1] < r[4][0], "два таймаута, потом кадр: оставшееся время уменьшается")
r = run_acquire([("lost",), ("frame",)])
check(r[0] == "ok" and r[3] == [1], "ACCESS_LOST: дублирование пересоздаётся один раз, кадр получен")
r = run_acquire([("lost",), ("lost",)])
check(r[0] == ("hr", wh.DXGI_ERROR_ACCESS_LOST) and r[3] == [1], "второй ACCESS_LOST: отказ (снимок через GDI)")
r = run_acquire([("denied",)])
check(r[0] == ("hr", wh.E_ACCESSDENIED), "E_ACCESSDENIED (UAC, защищённый стол): сразу отказ")
r = run_acquire([("mouse",), ("mouse",), ("frame",)])
check(r[0] == "ok" and r[2] == ["mouse-res", "mouse-res"], "кадры только с мышью отпускаются, ждём картинку")
r = run_acquire([("mouse",)] * 1000)
check(r[0] == "failed" and r[5] <= 0.26 and len(r[2]) >= 1, f"одна мышь до предела: отказ за {r[5] * 1000:.0f} мс")
r = run_acquire([])
check(r[0] == "failed" and r[5] <= 0.3, f"нет кадров совсем: отказ за {r[5] * 1000:.0f} мс, без зависания")

# --- 5. сопоставление и выбор пути -----------------------------------------------------------------------------------
O = wh.OutputInfo
outs = [O("\\\\.\\DISPLAY1", (0, 0, 3840, 2160)), O("\\\\.\\DISPLAY2", (3840, 0, 1920, 1080))]
m = wh.match_screens([("DELL U2720Q", QRect(0, 0, 2560, 1440), 1.5), ("LG", QRect(3840, 0, 1920, 1080), 1.0)], outs)
check({k: v.device for k, v in m.items()} == {0: outs[0].device, 1: outs[1].device},
      "экраны Qt и выходы DXGI: угол совпадает, размер x масштаб совпадает")
m = wh.match_screens([("x", QRect(0, 0, 2559, 1439), 1.5)], outs)
check(0 in m, "округление размера при 150 % (2559 x 1.5 = 3838.5): в пределах 2 пикселей")
m = wh.match_screens([("x", QRect(10, 0, 2560, 1440), 1.5), ("y", QRect(3840, 0, 1280, 720), 1.0)], outs)
check(m == {}, "другой угол или другой размер: не сопоставлен (GDI)")
m = wh.match_screens([("\\\\.\\DISPLAY2", QRect(5, 5, 10, 10), 1.0)], outs)
check(m.get(0) is outs[1], "имя экрана Qt «\\\\.\\DISPLAY2»: по имени")


class FakeScreen:
    def __init__(self, name, geo, dpr, color):
        self._name, self._geo, self._dpr, self.color, self.gdi_calls = name, geo, dpr, color, 0

    def name(self):
        return self._name

    def geometry(self):
        return QRect(self._geo)

    def devicePixelRatio(self):
        return self._dpr

    def grabWindow(self, _wid=0):
        self.gdi_calls += 1
        pm = QPixmap(round(self._geo.width() * self._dpr), round(self._geo.height() * self._dpr))
        pm.fill(QColor(self.color))
        pm.setDevicePixelRatio(self._dpr)
        return pm


class FakeCapturer:
    last_path = "проба"

    def __init__(self, outputs, fail=None, size=None, color="#3366cc"):
        self.outs, self.fail, self.size, self.color = outputs, fail, size, color
        self.calls, self.output_calls = [], 0

    def outputs(self):
        self.output_calls += 1
        return self.outs

    def grab(self, device, gain, hdr=True):
        self.calls.append((device, round(gain, 4), hdr))
        if self.fail:
            raise self.fail
        o = next(o for o in self.outs if o.device == device)
        w, h = self.size or o.rect[2:]
        img = QImage(w, h, QImage.Format.Format_RGB32)
        img.fill(QColor(self.color))
        return img


A = FakeScreen("A", QRect(0, 0, 1920, 1080), 1.0, "#888888")
B = FakeScreen("B", QRect(1920, 0, 1280, 720), 1.5, "#444444")
outs = [O("\\\\.\\DISPLAY1", (0, 0, 1920, 1080)), O("\\\\.\\DISPLAY2", (1920, 0, 1920, 1080))]
hdr_a = [wh.OutputState("\\\\.\\DISPLAY1", wh.MODE_HDR, 200.0, 10), wh.OutputState("\\\\.\\DISPLAY2", wh.MODE_SDR)]

cap = FakeCapturer(outs)
res = wh.capture_screens([A, B], hdr_a, cap)
check(cap.calls == [("\\\\.\\DISPLAY1", 0.4, True)], f"HDR-монитор: новый путь с множителем 0.4 ({cap.calls})")
check(set(res) == {0} and res[0].devicePixelRatio() == 1.0 and res[0].width() == 1920,
      "снимок HDR-монитора: родные пиксели, масштаб экрана")
check(any("DISPLAY1" in s and "мс" in s for s in wh.last_report), f"в журнале время снимка: {wh.last_report}")

cap = FakeCapturer(outs, fail=wh.HResultError("DuplicateOutput1", wh.E_ACCESSDENIED))
res = wh.capture_screens([A, B], hdr_a, cap)
check(res == {} and any("откат на GDI" in s and "E_ACCESSDENIED" in s for s in wh.last_report),
      f"ошибка нового пути: монитор через GDI, причина в журнале ({wh.last_report})")
cap = FakeCapturer(outs, fail=RuntimeError("что угодно"))
check(wh.capture_screens([A, B], hdr_a, cap) == {}, "любое исключение нового пути: GDI, наружу не выходит")
cap = FakeCapturer(outs, size=(1000, 1000))
check(wh.capture_screens([A, B], hdr_a, cap) == {}, "кадр не того размера: GDI")
cap = FakeCapturer(outs)
check(wh.capture_screens([A, B], [wh.OutputState("\\\\.\\DISPLAY1", wh.MODE_SDR),
                                  wh.OutputState("\\\\.\\DISPLAY2", wh.MODE_SDR)], cap) == {}
      and cap.output_calls == 0 and cap.calls == [], "без HDR: DXGI не вызывается совсем")
B3 = FakeScreen("B", QRect(1920, 0, 1280, 720), 1.0, "#444444")
cap = FakeCapturer(outs)
wh.capture_screens([A, B3], [wh.OutputState("\\\\.\\DISPLAY2", wh.MODE_WCG)], cap)
check(cap.calls == [], "расширенный цвет на мониторе, который не сопоставлен с экраном Qt: GDI")
B2 = FakeScreen("B", QRect(1920, 0, 1920, 1080), 1.0, "#444444")
cap = FakeCapturer(outs)
wh.capture_screens([A, B2], [wh.OutputState("\\\\.\\DISPLAY2", wh.MODE_WCG)], cap)
check(cap.calls == [("\\\\.\\DISPLAY2", 1.0, True)], "расширенный цвет без HDR: новый путь, множитель 1")
cap = FakeCapturer(outs)
check(wh.capture_screens([A, B], [wh.OutputState("\\\\.\\DISPLAY1", wh.MODE_HDR, None)], cap) == {} and
      cap.calls == [], "HDR без уровня белого: GDI (угадывать яркость нельзя)")


class Boom:
    def outputs(self):
        raise OSError("dxgi.dll")


check(wh.capture_screens([A], hdr_a, Boom()) == {}, "DXGI не загрузился: все мониторы через GDI")

# --- 6. grab_qt -------------------------------------------------------------------------------------------------------
real_screens, real_platform = grab.QGuiApplication.screens, sys.platform
real_capture = wh.capture_screens


def run_grab(screens, capture):
    grab.QGuiApplication.screens = staticmethod(lambda: screens)
    wh.capture_screens = capture
    sys.platform = "win32"
    try:
        return grab.grab_qt()
    finally:
        sys.platform = real_platform
        grab.QGuiApplication.screens = real_screens
        wh.capture_screens = real_capture


A = FakeScreen("A", QRect(0, 0, 1920, 1080), 1.0, "#888888")
B = FakeScreen("B", QRect(1920, 0, 1280, 720), 1.5, "#444444")


def hdr_for_a(screens):
    pm = QPixmap(1920, 1080)
    pm.fill(QColor("#3366cc"))
    pm.setDevicePixelRatio(1.0)
    return {0: pm}


desk = run_grab([A, B], hdr_for_a)
img = desk.toImage()
check(desk.devicePixelRatio() == 1.5 and img.width() == round(3200 * 1.5), "общий кадр в большем масштабе (1.5)")
check(img.pixelColor(100, 100).name() == "#3366cc", "монитор A в общем кадре из нового пути")
check(img.pixelColor(round(2500 * 1.5), 100).name() == "#444444", "монитор B через GDI")
check(A.gdi_calls == 0 and B.gdi_calls == 1, f"GDI для HDR-монитора не зовётся (A {A.gdi_calls}, B {B.gdi_calls})")
check(len(grab._native_shots) == 1 and grab._native_shots[0][1].width() == 1920 and
      grab._native_shots[0][1].toImage().pixelColor(5, 5).name() == "#3366cc",
      "разный масштаб: родной снимок A (из нового пути) в _native_shots")
grab.QGuiApplication.screens = staticmethod(lambda: [A, B])
try:
    part = grab.native_region(desk.copy(QRect(150, 150, 300, 150)), QRect(100, 100, 200, 100))
finally:
    grab.QGuiApplication.screens = real_screens
check((part.width(), part.height(), part.devicePixelRatio()) == (200, 100, 1.0) and
      part.toImage().pixelColor(10, 10).name() == "#3366cc", "область на A: родные пиксели нового пути (200x100, 1.0)")


def broken(screens):
    raise RuntimeError("сбой")


A.gdi_calls = B.gdi_calls = 0
desk = run_grab([A, B], broken)
check(A.gdi_calls == 1 and B.gdi_calls == 1 and desk.toImage().pixelColor(100, 100).name() == "#888888",
      "сбой нового пути целиком: оба монитора через GDI, снимок есть")
A.gdi_calls = 0
desk = run_grab([A, B], lambda s: {})
check(A.gdi_calls == 1, "нет HDR: всё как раньше (GDI)")
grab.QGuiApplication.screens = staticmethod(lambda: [A, B])
sys.platform = "linux"
try:
    A.gdi_calls = 0
    wh.capture_screens = broken
    grab.grab_qt()
    check(A.gdi_calls == 1, "не Windows: win_hdr не вызывается")
finally:
    sys.platform = real_platform
    grab.QGuiApplication.screens = real_screens
    wh.capture_screens = real_capture

print("ИТОГ:", "все проверки пройдены" if not fails else f"провалено: {len(fails)}")
from clipshot.exitutil import quick_exit
quick_exit(1 if fails else 0)
