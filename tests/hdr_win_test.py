# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""Живая проверка clipshot/win_hdr.py на Windows (GitHub Actions, монитор без HDR). На Linux: SKIP, код 0.

1. DisplayConfig читается без ошибок (режим каждого монитора в журнал).
2. DXGI: выходы находятся, их места на столе разумны.
3. Шейдер перевода цвета на настоящем D3D11 (видеокарта раннера или WARP): синтетический кадр FP16 37x23 с
   известными значениями при белом SDR 80, 200, 300 нит не дальше 1 от эталона; тот же кадр через чтение FP16 и
   перевод на процессоре (запасной путь). Время на 3840x2160.
4. Дублирование в B8G8R8A8 (путь обычного монитора) против снимка GDI того же места: пиксели почти равны.
   Окружение без дублирования (нет сеанса с рабочим столом, RDP, защищённый стол): SKIP с причиной, не ошибка;
   ошибка вызова (E_INVALIDARG и т.п., то есть ошибка в коде): FAIL.
5. Полный путь capture_screens с монитором, объявленным «расширенный цвет»: на обычном мониторе кадр приходит не в
   FP16, путь отказывает, снимок остаётся за GDI, исключений наружу нет.

Запуск: python -X utf8 tests/hdr_win_test.py"""
import os
import sys
import time

if sys.platform != "win32":
    print("SKIP: только Windows (на Linux математику и выбор пути проверяет tests/hdr_test.py)")
    print("ИТОГ: пропущено (не Windows)")
    sys.exit(0)

import ctypes
import struct
from ctypes import wintypes

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# Как у ClipSD (Qt 6): DPI «по мониторам v2», иначе GDI видит пересчитанные координаты, а DuplicateOutput1 отказывает
try:
    ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
except (AttributeError, OSError):
    pass

from PyQt6.QtCore import QRect
from PyQt6.QtGui import QImage
from PyQt6.QtWidgets import QApplication

app = QApplication([])
from clipshot import win_hdr as wh

fails = []


def check(ok, text):
    print(("OK   " if ok else "FAIL ") + text, flush=True)
    if not ok:
        fails.append(text)


def step(name, fn, *args):
    """Одна проверка: исключение -> FAIL с трассировкой, дальше следующие (один прогон показывает все ошибки)."""
    try:
        return fn(*args)
    except Exception as exc:   # noqa: BLE001
        import traceback
        traceback.print_exc()
        check(False, f"{name}: {type(exc).__name__}: {exc}")
        return None


ENV_ERRORS = (wh.E_ACCESSDENIED, wh.DXGI_ERROR_UNSUPPORTED, wh.DXGI_ERROR_NOT_CURRENTLY_AVAILABLE,
              wh.DXGI_ERROR_SESSION_DISCONNECTED)

# --- 1. DisplayConfig ----------------------------------------------------------------------------------------------
states = step("DisplayConfig", wh.display_states) or []
print("INFO мониторы:", wh.states_line(states))
check(isinstance(states, list), "DisplayConfig прочитан без исключений")

# --- 2. выходы DXGI ------------------------------------------------------------------------------------------------
cap = wh.DxgiCapturer()
outs = []
try:
    outs = cap.outputs()
    print("INFO выходы DXGI:", [(o.device, o.rect, o.rotation) for o in outs])
    if states:
        check(len(outs) > 0, f"есть активные мониторы ({len(states)}): DXGI их видит ({len(outs)})")
    else:
        print("SKIP нет активных мониторов: выходы и дублирование проверить не на чем")
    check(all(o.device.startswith("\\\\.\\") and o.rect[2] > 0 and o.rect[3] > 0 for o in outs),
          f"выходы DXGI: имена и размеры ({len(outs)})")
except Exception as exc:   # noqa: BLE001
    check(False, f"перечисление выходов DXGI: {type(exc).__name__}: {exc}")

# --- 3. шейдер на синтетическом кадре --------------------------------------------------------------------------------


def make_device(refs):
    """Устройство на первой видеокарте с выходами (как при снимке), иначе любое: видеокарта, потом WARP."""
    for adapter, luid, _out, _od in cap._walk(refs):
        try:
            return cap._device(adapter, luid)
        except wh.CaptureFailed as exc:
            print(f"INFO устройство на видеокарте выхода не создано ({exc}), пробую любое")
            break
    _, d3d11 = cap._libs()
    for driver in (wh.D3D_DRIVER_TYPE_HARDWARE, wh.D3D_DRIVER_TYPE_WARP):
        levels = (wh.U32 * 1)(wh.FL_11_0)
        dev, ctx, got = ctypes.c_void_p(), ctypes.c_void_p(), wh.U32(0)
        if d3d11.D3D11CreateDevice(None, driver, None, 0, levels, 1, wh.D3D11_SDK_VERSION, ctypes.byref(dev),
                                   ctypes.byref(got), ctypes.byref(ctx)) >= 0:
            return {"device": dev.value, "context": ctx.value, "level": got.value, "cs": None, "cs_failed": False}
    raise wh.CaptureFailed("нет устройства D3D11")


def lin(code):
    c = code / 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


W, H = 37, 23
vals = []
for y in range(H):
    for x in range(W):
        i = y * W + x
        vals.append((lin(i % 256) * 2.5, (x / W) * 4.0 - 0.3, lin((i * 7) % 256) * 3.75))
raw = b"".join(struct.pack("<eeee", r, g, b, 1.0) for r, g, b in vals)
def pixel_worst(img, ref):
    worst = 0
    for y in range(img.height()):
        for x in range(img.width()):
            c = img.pixelColor(x, y)
            k = (y * img.width() + x) * 3
            worst = max(worst, abs(c.red() - ref[k]), abs(c.green() - ref[k + 1]), abs(c.blue() - ref[k + 2]))
    return worst


refs = wh._Refs()
entry = step("устройство D3D11", make_device, refs)
src = None
if entry is not None:
    print(f"INFO D3D11: уровень 0x{entry['level']:X}")
    buf = ctypes.create_string_buffer(raw, len(raw))
    src = step("текстура FP16 с данными", cap._texture, refs, entry["device"], W, H, wh.FMT_R16G16B16A16_FLOAT,
               wh.USAGE_DEFAULT, wh.BIND_SHADER_RESOURCE, 0, buf, W * 8)
if src is not None:
    for white in (80, 200, 300):
        gain = wh.gain_for(wh.MODE_HDR, white)
        ref = wh.tonemap_reference(raw, gain)

        def gpu():
            out = cap.gpu_tonemap(entry, refs, src, W, H, gain)
            check(out is not None, f"{white} нит: шейдер собран и выполнен")
            if out is not None:
                worst = pixel_worst(out, ref)
                check(worst <= 1, f"{white} нит: видеокарта не дальше 1 от эталона (наибольшее {worst})")

        def cpu():
            img = wh.tonemap_qimage(cap._read(entry, refs, src, W, H, wh.FMT_R16G16B16A16_FLOAT, 8), gain)
            worst = pixel_worst(img, ref)
            check(worst <= 1, f"{white} нит: чтение FP16 и процессор не дальше 1 от эталона (наибольшее {worst})")

        step(f"{white} нит, видеокарта", gpu)
        step(f"{white} нит, чтение FP16 и процессор", cpu)


def timing_4k():
    BW, BH = 3840, 2160
    row = b"".join(struct.pack("<eeee", (i / BW) * 3.0, 0.5, 2.5, 1.0) for i in range(BW))
    bigbuf = ctypes.create_string_buffer(row * BH, BW * BH * 8)
    big = cap._texture(refs, entry["device"], BW, BH, wh.FMT_R16G16B16A16_FLOAT, wh.USAGE_DEFAULT,
                       wh.BIND_SHADER_RESOURCE, 0, bigbuf, BW * 8)
    t0 = time.perf_counter()
    out = step("4K видеокарта", cap.gpu_tonemap, entry, refs, big, BW, BH, 0.4)
    ms_gpu = (time.perf_counter() - t0) * 1000
    t0 = time.perf_counter()
    cpu = step("4K процессор", lambda: wh.tonemap_qimage(
        cap._read(entry, refs, big, BW, BH, wh.FMT_R16G16B16A16_FLOAT, 8), 0.4))
    ms_cpu = (time.perf_counter() - t0) * 1000
    print(f"INFO 3840x2160: шейдер с чтением {ms_gpu:.0f} мс, чтение FP16 и процессор {ms_cpu:.0f} мс")
    check(out is not None and out.width() == BW, "4K: видеокарта дала кадр")
    check(cpu is not None and cpu.width() == BW, "4K: процессор дал кадр")


if entry is not None:
    step("время на 4K", timing_4k)
refs.close()

# --- 4. дублирование B8G8R8A8 против GDI -----------------------------------------------------------------------------


def gdi_grab(x, y, w, h):
    user32, gdi32 = ctypes.WinDLL("user32"), ctypes.WinDLL("gdi32")
    H_ = ctypes.c_void_p
    user32.GetDC.argtypes, user32.GetDC.restype = [H_], H_
    user32.ReleaseDC.argtypes = [H_, H_]
    gdi32.CreateCompatibleDC.argtypes, gdi32.CreateCompatibleDC.restype = [H_], H_
    gdi32.CreateCompatibleBitmap.argtypes, gdi32.CreateCompatibleBitmap.restype = [H_, ctypes.c_int, ctypes.c_int], H_
    gdi32.SelectObject.argtypes, gdi32.SelectObject.restype = [H_, H_], H_
    gdi32.BitBlt.argtypes = [H_, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, H_, ctypes.c_int,
                             ctypes.c_int, wintypes.DWORD]
    gdi32.GetDIBits.argtypes = [H_, H_, wintypes.UINT, wintypes.UINT, ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT]
    gdi32.DeleteObject.argtypes = [H_]
    gdi32.DeleteDC.argtypes = [H_]
    screen = user32.GetDC(None)
    dc = gdi32.CreateCompatibleDC(screen)
    bmp = gdi32.CreateCompatibleBitmap(screen, w, h)
    old = gdi32.SelectObject(dc, bmp)
    try:
        if not gdi32.BitBlt(dc, 0, 0, w, h, screen, x, y, 0x00CC0020):   # SRCCOPY
            raise OSError("BitBlt")
        gdi32.SelectObject(dc, old)   # GetDIBits: картинка не должна быть выбрана в DC
        old = None
        header = struct.pack("<IiiHHIIiiII", 40, w, -h, 1, 32, 0, 0, 0, 0, 0, 0)
        info = ctypes.create_string_buffer(header, 44)
        data = ctypes.create_string_buffer(w * h * 4)
        if not gdi32.GetDIBits(dc, bmp, 0, h, data, info, 0):
            raise OSError("GetDIBits")
        return QImage(data.raw, w, h, w * 4, QImage.Format.Format_RGB32).copy()
    finally:
        if old is not None:
            gdi32.SelectObject(dc, old)
        gdi32.DeleteObject(bmp)
        gdi32.DeleteDC(dc)
        user32.ReleaseDC(None, screen)


def compare(a, b):
    """Доля точек сетки, где все три канала отличаются не больше чем на 2."""
    good = total = 0
    step = max(1, min(a.width(), a.height()) // 60)
    for y in range(0, a.height(), step):
        for x in range(0, a.width(), step):
            p, q = a.pixelColor(x, y), b.pixelColor(x, y)
            total += 1
            good += max(abs(p.red() - q.red()), abs(p.green() - q.green()), abs(p.blue() - q.blue())) <= 2
    return good / max(1, total), total


dup_ok = False
for o in outs[:2]:
    x, y, w, h = o.rect
    try:
        t0 = time.perf_counter()
        img = cap.grab(o.device, 1.0, hdr=False)
        ms_dup = (time.perf_counter() - t0) * 1000
        t0 = time.perf_counter()
        img2 = cap.grab(o.device, 1.0, hdr=False)
        ms_dup2 = (time.perf_counter() - t0) * 1000
    except wh.CaptureFailed as exc:
        hr = getattr(exc, "hr", None)
        if hr is None or hr in ENV_ERRORS:   # окружение (нет стола, RDP, нет кадра): не ошибка кода
            print(f"SKIP дублирование {o.device} недоступно в этом окружении: {exc}")
            continue
        check(False, f"дублирование {o.device}: ошибка вызова {exc}")
        continue
    except Exception as exc:   # noqa: BLE001 — ошибка в коде (TypeError и т.п.): FAIL, проверка идёт дальше
        import traceback
        traceback.print_exc()
        check(False, f"дублирование {o.device}: {type(exc).__name__}: {exc}")
        continue
    check((img.width(), img.height()) == (w, h), f"{o.device}: кадр DXGI размером с монитор ({img.width()}x{img.height()})")
    t0 = time.perf_counter()
    gdi = step(f"{o.device}: снимок GDI", gdi_grab, x, y, w, h)
    ms_gdi = (time.perf_counter() - t0) * 1000
    print(f"INFO {o.device} {w}x{h}: DXGI {ms_dup:.0f} мс (первый), {ms_dup2:.0f} мс (второй), "
          f"GDI {ms_gdi:.0f} мс, путь «{cap.last_path}»")
    if gdi is not None:
        res = step(f"{o.device}: сравнение с GDI", compare, img, gdi)
        if res is not None:
            share, total = res
            check(share >= 0.98, f"{o.device}: DXGI и GDI совпадают в {share * 100:.1f} % из {total} точек")
    dup_ok = True
if not dup_ok:
    print("INFO дублирование не проверено на живом столе (см. SKIP выше); шейдер и выходы проверены")

# --- 5. полный путь с откатом -----------------------------------------------------------------------------------------


class Scr:
    def __init__(self, o):
        self.o = o

    def name(self):
        return "test"

    def geometry(self):
        x, y, w, h = self.o.rect
        return QRect(x, y, w, h)

    def devicePixelRatio(self):
        return 1.0


if outs:
    o = outs[0]
    fake = [wh.OutputState(o.device, wh.MODE_WCG)]
    try:
        res = wh.capture_screens([Scr(o)], fake, cap)
        print("INFO журнал:", wh.last_report)
        if res:
            check(res[0].width() == o.rect[2], "монитор отдал FP16 (стол в расширенном цвете?): кадр нужного размера")
        else:
            check(any("GDI" in s for s in wh.last_report), "обычный монитор, объявленный WCG: откат на GDI с причиной")
    except Exception as exc:   # noqa: BLE001
        check(False, f"capture_screens бросил исключение: {type(exc).__name__}: {exc}")
    try:
        cap.prewarm({o.device})
        check(True, "прогрев устройства и шейдера без ошибок")
    except Exception as exc:   # noqa: BLE001
        check(False, f"прогрев: {type(exc).__name__}: {exc}")

print("ИТОГ:", "все проверки пройдены" if not fails else f"провалено: {len(fails)}")
from clipshot.exitutil import quick_exit
quick_exit(1 if fails else 0)
