# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""1.36: печать и сохранение в PDF (clipshot/pechat.py).

PDF: файл создаётся, страница одна, картинка в исходном разрешении без потерь (Flate, не JPEG), размер страницы по
настройке («по снимку» или A4, альбомная для широкого снимка), имя по обычному шаблону и папка снимков, PDF есть в окне
«Сохранить» и не берётся для автосохранения, из окна выделения тоже. Печать: окно печати получает настоящий
QPrinter (подмена, на принтер ничего не уходит), снимок вписан в страницу с сохранением пропорций, ориентация по форме
снимка, предпросмотр, принтеров нет: сообщение и предложение сохранить PDF. Ctrl+P, меню кнопки, настройка, 12 языков.

Запуск: python3 tests/pechat_pdf_test.py
"""
import tmpclean  # noqa: F401  (временные папки этого теста убираются при его выходе)
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(here))
os.environ.pop("CLIPSD_LANG", None)
tmp = tempfile.mkdtemp(prefix="clipsd-pechat-")
for name in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME"):
    os.environ[name] = os.path.join(tmp, name)
_screen = os.path.join(tmp, "screen.json")
with open(_screen, "w", encoding="utf-8") as _f:
    json.dump({"screens": [{"name": "demo", "x": 0, "y": 0, "width": 1600, "height": 1000,
                            "logicalDpi": 96, "logicalBaseDpi": 96}]}, _f)
os.environ["QT_QPA_PLATFORM"] = "offscreen:configfile=" + _screen

from PyQt6.QtCore import QObject, QRect, QRectF, Qt, QTimer, pyqtSignal  # noqa: E402
from PyQt6.QtGui import QColor, QImage, QPageLayout  # noqa: E402
from PyQt6.QtPrintSupport import QPrinter  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402
from PyQt6.QtWidgets import QApplication, QFileDialog  # noqa: E402

qapp = QApplication(sys.argv)
qapp.setQuitOnLastWindowClosed(False)
from clipshot import app as appmod, dialogs, editor as editor_mod, hidpi, i18n, novoe, oznakomlenie, pechat  # noqa: E402
from clipshot.settings import SettingsDialog  # noqa: E402

failures = []
checks = [0]


def check(cond, msg):
    checks[0] += 1
    print(("OK   " if cond else "FAIL ") + msg, flush=True)
    if not cond:
        failures.append(msg)


i18n.set_language("ru")
a = appmod.Clipshot(qapp)
a.save_config = lambda: None
notes = []
a.notify = lambda t, *_x: notes.append(t)
folder = os.path.join(tmp, "shots")
os.makedirs(folder)
a.config.update(theme_chosen=True, tour_done=True, novoe_enabled=False, auto_save=False, save_dir=folder,
                save_ask=False)


def pic(w=900, h=500, ratio=1.0):
    img = QImage(w, h, QImage.Format.Format_RGB32)
    img.fill(QColor("#ffffff"))
    for y in range(h):
        for x in range(0, w, 5):
            img.setPixel(x, y, QColor((x * 7 + y) % 256, (y * 3) % 256, (x + 2 * y) % 256).rgb())
    img.setDevicePixelRatio(ratio)
    return img


def pdf_info(path):
    data = open(path, "rb").read()
    pages = len(re.findall(rb"/Type /Page(?!s)", data))
    box = [float(v) for v in re.search(rb"/MediaBox \[([^\]]*)\]", data).group(1).split()]
    w = int(re.search(rb"/Width (\d+)", data).group(1))
    h = int(re.search(rb"/Height (\d+)", data).group(1))
    return {"data": data, "pages": pages, "w": box[2], "h": box[3], "iw": w, "ih": h,
            "flate": b"/FlateDecode" in data, "dct": b"DCTDecode" in data}


# --- 1. PDF: страница одна, пиксели без потерь -------------------------------------------------------------------
src = pic(900, 500)
p1 = os.path.join(tmp, "a.pdf")
check(pechat.write_pdf(src, p1, {"pdf_page": "image"}) and os.path.getsize(p1) > 0, "PDF создан")
i = pdf_info(p1)
check(i["data"].startswith(b"%PDF-") and i["data"].rstrip().endswith(b"%%EOF"), "это PDF (заголовок и конец файла)")
check(i["pages"] == 1, f"страница одна ({i['pages']})")
check(i["iw"] >= src.width() and i["ih"] >= src.height(), f"разрешение картинки не меньше исходного ({i['iw']}x{i['ih']})")
check(i["flate"] and not i["dct"], "картинка без потерь (Flate), не пережата в JPEG")
check(abs(i["w"] - 900 * 72 / 96) < 0.01 and abs(i["h"] - 500 * 72 / 96) < 0.01,
      f"«по снимку»: страница {i['w']}x{i['h']} pt = размер снимка при 96 dpi")
if shutil.which("pdfimages"):
    out = os.path.join(tmp, "ex")
    subprocess.run(["pdfimages", "-png", p1, out], check=True, capture_output=True)
    back = QImage(out + "-000.png").convertToFormat(QImage.Format.Format_RGB32)
    check(back == src.convertToFormat(QImage.Format.Format_RGB32), "пиксели в PDF совпадают с исходными до точки")
else:
    print("SKIP pdfimages нет: сравнение пикселей не выполнено")
if shutil.which("pdftoppm"):
    subprocess.run(["pdftoppm", "-r", "30", "-png", p1, os.path.join(tmp, "pg")], check=True, capture_output=True)
    check(not QImage(os.path.join(tmp, "pg-1.png")).isNull(), "PDF открывается просмотрщиком (poppler)")

# экран с масштабом 200%: пикселей столько же, страница по снимку вдвое меньше в пунктах
hi = pic(1800, 1000, ratio=2.0)
p2 = os.path.join(tmp, "hi.pdf")
pechat.write_pdf(hi, p2, {})
j = pdf_info(p2)
check(j["iw"] == 1800 and j["ih"] == 1000, f"снимок 200%: в PDF все пиксели ({j['iw']}x{j['ih']})")
check(abs(j["w"] - 1800 / 192 * 72) < 0.01, f"снимок 200%: страница в размере снимка на экране ({j['w']} pt)")

# A4
p3 = os.path.join(tmp, "a4.pdf")
pechat.write_pdf(src, p3, {"pdf_page": "a4"})
k = pdf_info(p3)
check(abs(k["w"] - 841.89) < 0.1 and abs(k["h"] - 595.28) < 0.1, f"A4: широкий снимок на альбомной странице ({k['w']}x{k['h']})")
check(k["iw"] == 900 and k["ih"] == 500 and k["pages"] == 1, "A4: страница одна, картинка в исходном разрешении")
tall = pic(400, 900)
p4 = os.path.join(tmp, "a4t.pdf")
pechat.write_pdf(tall, p4, {"pdf_page": "a4"})
t = pdf_info(p4)
check(abs(t["w"] - 595.28) < 0.1 and abs(t["h"] - 841.89) < 0.1, f"A4: высокий снимок на книжной странице ({t['w']}x{t['h']})")
cm = re.search(rb"q ([\d.]+) 0 0 ([\d.]+) ([\d.]+) ([\d.]+) cm", t["data"])
bw, bh, bx, by = (float(cm.group(n)) for n in (1, 2, 3, 4))
check(abs(bw / bh - 400 / 900) < 0.002, "A4: пропорции снимка сохранены")
check(bx >= 28.3 and by >= 28.3 and bx + bw <= t["w"] - 28.3 and by + bh <= t["h"] - 28.3, "A4: снимок внутри полей 10 мм")
check(pechat.pdf_page_mode({"pdf_page": "что-то"}) == "image" and pechat.pdf_page_mode({}) == "image", "настройка страницы: неизвестное значение = «по снимку»")
check(not pechat.write_pdf(QImage(), os.path.join(tmp, "n.pdf"), {}), "пустой снимок: PDF не создаётся")
check(not pechat.write_pdf(src, os.path.join(tmp, "нет-папки", "x.pdf"), {}), "папки нет: запись не удалась, без падения")

# прозрачность (форма снимка) ложится на белый
tr_img = QImage(200, 100, QImage.Format.Format_ARGB32)
tr_img.fill(Qt.GlobalColor.transparent)
p5 = os.path.join(tmp, "tr.pdf")
check(pechat.write_pdf(tr_img, p5, {}) and pdf_info(p5)["iw"] == 200, "прозрачный снимок: PDF создан")

# --- 2. имя, папка, формат в окне «Сохранить» -----------------------------------------------------------------------
cfg = dict(a.config, save_ask=False)
path = editor_mod.ask_save_path(None, cfg, "pdf")
check(os.path.dirname(path) == folder and path.endswith(".pdf") and os.path.basename(path).startswith("Screenshot_"),
      f"имя по обычному шаблону Screenshot_…pdf в папке снимков ({os.path.basename(path)})")
path2 = editor_mod.ask_save_path(None, cfg, "pdf")
check(path2 != path and os.path.exists(path), "второй PDF в ту же секунду получает другое имя")
check(editor_mod.ask_save_path(None, dict(cfg, save_format="png")).endswith(".png")
      and editor_mod.ask_save_path(None, dict(cfg, save_format="jpg")).endswith(".jpg"),
      "сохранение без вопроса: PDF по настройке формата не выбирается (png/jpg)")
check(not hasattr(appmod.Clipshot, "snapshot_path") or a.snapshot_path().endswith((".png", ".jpg")),
      "автосохранение: имя снимка png/jpg, не PDF")

calls = []
real_dialog = QFileDialog.getSaveFileName


def fake_dialog(answer):
    def f(parent, title, start, filters, selected=""):
        calls.append((start, filters, selected))
        return answer(start)
    return f


editor_mod.QFileDialog.getSaveFileName = staticmethod(fake_dialog(lambda s: (s, "PNG (*.png)")))
asked = dict(a.config, save_ask=True)
editor_mod.ask_save_path(None, asked)
check("PDF (*.pdf)" in calls[-1][1] and calls[-1][1].split(";;")[0].startswith("PNG"), "окно «Сохранить»: PDF среди форматов, первым PNG")
editor_mod.ask_save_path(None, dict(asked, save_format="jpg"))
check(calls[-1][1].split(";;")[0].startswith("JPEG") and "PDF (*.pdf)" in calls[-1][1], "формат из настроек первый, PDF в списке")
editor_mod.ask_save_path(None, asked, "pdf")
check(calls[-1][1].split(";;")[0].startswith("PDF") and calls[-1][0].endswith(".pdf"), "«Сохранить в PDF»: формат PDF выбран, имя .pdf")
editor_mod.QFileDialog.getSaveFileName = staticmethod(fake_dialog(lambda s: (os.path.join(folder, "мой снимок"), "PDF (*.pdf)")))
check(editor_mod.ask_save_path(None, asked).endswith("мой снимок.pdf"), "имя без расширения: берётся расширение выбранного формата")
editor_mod.QFileDialog.getSaveFileName = staticmethod(fake_dialog(lambda s: (s, "PDF (*.pdf)")))
check(editor_mod.ask_save_path(None, asked).endswith(".pdf"), "формат сменили на PDF, имя оставили: расширение .pdf")
editor_mod.QFileDialog.getSaveFileName = staticmethod(fake_dialog(lambda s: ("", "")))
check(editor_mod.ask_save_path(None, asked) is None, "отмена окна: None")
editor_mod.QFileDialog.getSaveFileName = real_dialog

# --- 3. редактор: «Сохранить в PDF», кнопка, меню, Ctrl+P ---------------------------------------------------------
def mk(w=900, h=500):
    ed = a.open_editor(pic(w, h), None)
    ed.autosave_path = None
    QTest.qWait(60)
    return ed


def close_all():
    for e in list(a.editors):
        e.exported = True
        e.canvas.modified = False
        e.close()
    QTest.qWait(60)


ed = mk()
before = set(os.listdir(folder))
ed.save_pdf()
new = [f for f in set(os.listdir(folder)) - before if f.endswith(".pdf")]
check(len(new) == 1 and pdf_info(os.path.join(folder, new[0]))["pages"] == 1, f"редактор: «Сохранить в PDF» создал один PDF ({new})")
check(any(new[0] in n for n in notes), "редактор: итог «Сохранено» с именем файла")
QTest.qWait(60)
close_all()

# через «Сохранить» с выбором PDF в окне
editor_mod.QFileDialog.getSaveFileName = staticmethod(fake_dialog(lambda s: (os.path.join(folder, "через-окно.pdf"), "PDF (*.pdf)")))
ed = mk()
a.config["save_ask"] = True
ed.save_and_close()
check(os.path.exists(os.path.join(folder, "через-окно.pdf")) and pdf_info(os.path.join(folder, "через-окно.pdf"))["pages"] == 1,
      "«Сохранить» с форматом PDF в окне: PDF записан")
a.config["save_ask"] = False
editor_mod.QFileDialog.getSaveFileName = real_dialog
close_all()

# настройка «A4» доходит до файла
a.config["pdf_page"] = "a4"
ed = mk(900, 500)
before = set(os.listdir(folder))
ed.save_pdf()
new = [f for f in set(os.listdir(folder)) - before if f.endswith(".pdf")]
info = pdf_info(os.path.join(folder, new[0]))
check(abs(info["w"] - 841.89) < 0.1, "настройка «A4» применяется при сохранении из редактора")
a.config["pdf_page"] = "image"
close_all()

# кнопка, меню, подсказки
ed = mk()
ed.show()
ed.resize(1500, 800)
QTest.qWait(100)
check(ed.print_button.isVisible() and ed.print_button.text().strip() == "Печать", "кнопка «Печать» внизу редактора (широкое окно, с подписью)")
acts = ed.print_menu.actions()
check([x.text().split("\t")[0] for x in acts] == ["Печать…", "Предпросмотр…", "Сохранить в PDF…"], "меню кнопки: Печать…, Предпросмотр…, Сохранить в PDF…")
check("Ctrl+P" in acts[0].text(), "в пункте «Печать…» подсказана клавиша Ctrl+P")

rec = []
real_print, real_prev = pechat.print_image, pechat.preview_image
pechat.print_image = lambda parent, image, cfg=None, save_pdf=None: (rec.append(("print", image.size(), save_pdf)), "cancelled")[1]
pechat.preview_image = lambda parent, image, cfg=None: (rec.append(("preview", image.size())), "shown")[1]
ed.activateWindow()
ed.show()
QTest.qWait(60)
QTest.keyClick(ed, Qt.Key.Key_P, Qt.KeyboardModifier.ControlModifier)
QTest.qWait(30)
check(rec and rec[-1][0] == "print" and rec[-1][1] == ed.canvas.render().size(), "Ctrl+P: окно печати для снимка редактора")
check(callable(rec[-1][2]), "печать получает «Сохранить PDF» на случай, когда принтеров нет")
n = len(rec)
acts[1].trigger()
check(rec[-1][0] == "preview", "пункт «Предпросмотр…» открывает предпросмотр")
pechat.print_image, pechat.preview_image = real_print, real_prev
close_all()
pdf_calls = []
real_save_pdf = editor_mod.EditorWindow.save_pdf
editor_mod.EditorWindow.save_pdf = lambda self: pdf_calls.append(1)
ed = mk()
ed.show()
QTest.qWait(60)
QTest.keyClick(ed, Qt.Key.Key_P, Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)
QTest.qWait(30)
check(pdf_calls == [1], "Ctrl+Shift+P: «Сохранить в PDF»")
acts = ed.print_menu.actions()
acts[2].trigger()
check(pdf_calls == [1, 1], "пункт «Сохранить в PDF…» в меню кнопки")
editor_mod.EditorWindow.save_pdf = real_save_pdf
close_all()

# --- 4. печать: подмена QPrinter и QPrintDialog ----------------------------------------------------------------------
made = []


class FakePrinter(QPrinter):
    """Настоящий QPrinter, но вывод в PDF-файл: на принтер ничего не уходит."""

    def __init__(self, mode=QPrinter.PrinterMode.ScreenResolution):
        super().__init__(mode)
        self.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
        self.out = os.path.join(tmp, f"print{len(made)}.pdf")
        self.setOutputFileName(self.out)
        made.append(self)


dialogs_made = []


class FakeDialog(QObject):
    answer = 1

    def __init__(self, printer, parent=None):
        super().__init__()
        self.printer, self.title = printer, ""
        dialogs_made.append(self)

    def setWindowTitle(self, t):
        self.title = t

    def exec(self):
        return FakeDialog.answer


class FakePreview(QObject):
    paintRequested = pyqtSignal(QPrinter)

    def __init__(self, printer, parent=None):
        super().__init__()
        self.printer, self.title = printer, ""
        dialogs_made.append(self)

    def setWindowTitle(self, t):
        self.title = t

    def exec(self):
        self.paintRequested.emit(self.printer)
        return 0


pechat.QPrinter, pechat.QPrintDialog, pechat.QPrintPreviewDialog = FakePrinter, FakeDialog, FakePreview
real_avail = pechat.printers_available
pechat.printers_available = lambda: True

wide = pic(900, 500)
res = pechat.print_image(None, wide, a.config)
pr, dlg = made[-1], dialogs_made[-1]
check(res == "printed" and dlg.printer is pr, "печать: окно печати получило QPrinter, снимок напечатан")
check(isinstance(dlg.printer, QPrinter), "в окно печати передан настоящий QPrinter")
check(pr.pageLayout().orientation() == QPageLayout.Orientation.Landscape, "широкий снимок: альбомная ориентация")
m = pr.pageLayout().margins(QPageLayout.Unit.Millimeter)
check(all(abs(v - 10.0) < 0.01 for v in (m.left(), m.top(), m.right(), m.bottom())), "поля 10 мм")
check(os.path.exists(pr.out) and pdf_info(pr.out)["pages"] == 1 and pdf_info(pr.out)["iw"] >= 900, "в печать ушла одна страница со снимком в исходных пикселях")
if shutil.which("pdftoppm"):
    # где на листе оказался снимок: внутри полей 10 мм и по центру (поля не прибавляются дважды)
    subprocess.run(["pdftoppm", "-r", "50", "-png", pr.out, os.path.join(tmp, "lst")], check=True, capture_output=True)
    sheet = QImage(os.path.join(tmp, "lst-1.png")).convertToFormat(QImage.Format.Format_RGB32)
    xs, ys = [], []
    for yy in range(sheet.height()):
        for xx in range(sheet.width()):
            if sheet.pixel(xx, yy) & 0xFFFFFF != 0xFFFFFF:
                xs.append(xx)
                ys.append(yy)
    mpx = 10 / 25.4 * 50
    left, right, top, bottom = min(xs), sheet.width() - 1 - max(xs), min(ys), sheet.height() - 1 - max(ys)
    check(min(left, right, top, bottom) >= mpx - 2, f"на листе снимок внутри полей: отступы {left},{right},{top},{bottom} px >= {mpx:.0f}")
    check(abs(left - right) <= 3 and abs(top - bottom) <= 3 or abs(left - right) <= 3 and min(top, bottom) >= 0,
          f"на листе снимок по центру по ширине ({left} и {right})")
    check(min(left, right) <= mpx + 3 or min(top, bottom) <= mpx + 3, "снимок вписан во всю область между полями (касается одной пары полей)")
pechat.print_image(None, pic(500, 900), a.config)
check(made[-1].pageLayout().orientation() == QPageLayout.Orientation.Portrait, "высокий снимок: книжная ориентация")
pechat.print_image(None, pic(600, 600), a.config)
check(made[-1].pageLayout().orientation() == QPageLayout.Orientation.Portrait, "квадратный снимок: книжная ориентация")
count = len(made)
FakeDialog.answer = 0
check(pechat.print_image(None, wide, a.config) == "cancelled" and not os.path.exists(made[-1].out),
      "«Отмена» в окне печати: ничего не напечатано")
FakeDialog.answer = 1

# вписывание: пропорции, поля, по центру
for pw, ph, iw, ih in ((600, 800, 900, 500), (800, 600, 400, 900), (800, 600, 100, 50), (500, 500, 500, 500)):
    r = pechat.fit_rect(pw, ph, iw, ih)
    inside = r.left() >= -1e-6 and r.top() >= -1e-6 and r.right() <= pw + 1e-6 and r.bottom() <= ph + 1e-6
    touches = abs(r.width() - pw) < 1e-6 or abs(r.height() - ph) < 1e-6
    centered = abs(r.center().x() - pw / 2) < 1e-6 and abs(r.center().y() - ph / 2) < 1e-6
    check(inside and touches and centered and abs(r.width() / r.height() - iw / ih) < 1e-9,
          f"вписывание {iw}x{ih} в {pw}x{ph}: пропорции, в пределах страницы, по центру")
page_pr = made[count - 1 if count > 1 else 0]
pg = page_pr.pageRect(QPrinter.Unit.DevicePixel)
check(pg.width() < page_pr.paperRect(QPrinter.Unit.DevicePixel).width(), "область печати уже листа: поля учтены")

# предпросмотр
res = pechat.preview_image(None, wide, a.config)
pv = dialogs_made[-1]
check(res == "shown" and isinstance(pv, FakePreview) and os.path.exists(pv.printer.out), "предпросмотр: страница нарисована для окна предпросмотра")
check(pv.title == i18n.tr("pechat.preview_title") and dialogs_made[-2].title == i18n.tr("pechat.dialog_title"),
      "заголовки окон печати и предпросмотра на языке программы")
check(pechat.print_image(None, QImage(), a.config) == "failed", "пустой снимок: печать не начинается")

# принтеров нет
pechat.printers_available = lambda: False
shown = []
real_exec = dialogs.MessageCard.exec


def card_exec(self):
    shown.append((self.title.text() if hasattr(self, "title") else "", self.choice))
    self.choice = card_exec.pick
    return 0


dialogs.MessageCard.exec = card_exec
card_exec.pick = "primary"
made_before, got = len(made), []
res = pechat.print_image(None, wide, a.config, save_pdf=lambda: got.append("pdf"))
check(res == "no_printers" and len(made) == made_before, "принтеров нет: печать не начинается, QPrinter не создаётся")
check(shown and got == ["pdf"], "принтеров нет: понятное сообщение и по кнопке «Сохранить в PDF» вызывается сохранение")
card_exec.pick = "secondary"
got.clear()
pechat.print_image(None, wide, a.config, save_pdf=lambda: got.append("pdf"))
check(got == [], "принтеров нет, «Закрыть»: PDF не сохраняется")
check(pechat.preview_image(None, wide, a.config) == "no_printers", "принтеров нет: предпросмотр тоже говорит об этом")
dialogs.MessageCard.exec = real_exec
check(all(i18n.tr(k) != k for k in ("pechat.none_title", "pechat.none_text", "pechat.none_pdf")), "тексты сообщения «принтер не найден» есть")
pechat.printers_available = real_avail
from PyQt6.QtPrintSupport import QPrintDialog, QPrintPreviewDialog  # noqa: E402
pechat.QPrinter, pechat.QPrintDialog, pechat.QPrintPreviewDialog = QPrinter, QPrintDialog, QPrintPreviewDialog

# печать из редактора: итог плашкой; «Печать» в редакторе вызывает окно печати с картинкой редактора
pechat.QPrinter, pechat.QPrintDialog, pechat.QPrintPreviewDialog = FakePrinter, FakeDialog, FakePreview
pechat.printers_available = lambda: True
ed = mk()
ed.print_image()
check(os.path.exists(made[-1].out) and isinstance(dialogs_made[-1], FakeDialog), "редактор: «Печать…» открыла окно печати и напечатала")
close_all()

# окно выделения: Ctrl+Shift+P печатает рамку через приложение
sel_calls = []


class FakeSel:
    def suspend_for_dialog(self):
        sel_calls.append("hide")

    def resume_after_dialog(self):
        sel_calls.append("show")


from PyQt6.QtGui import QPixmap  # noqa: E402
a.print_from_selector(FakeSel(), QPixmap.fromImage(pic(300, 200)))
check(sel_calls == ["hide", "show"] and os.path.exists(made[-1].out), "окно выделения: печать рамки, окно прячется на время печати")
pechat.printers_available = real_avail
pechat.QPrinter, pechat.QPrintDialog, pechat.QPrintPreviewDialog = QPrinter, QPrintDialog, QPrintPreviewDialog

# сохранение из окна выделения в PDF
editor_mod.QFileDialog.getSaveFileName = staticmethod(fake_dialog(lambda s: (os.path.join(folder, "из-выделения.pdf"), "PDF (*.pdf)")))
a.config["save_ask"] = True
res = a.save_from_selector(FakeSel(), QPixmap.fromImage(pic(300, 200)), QRect(0, 0, 300, 200))
check(res and res.endswith("из-выделения.pdf") and pdf_info(res)["pages"] == 1 and pdf_info(res)["iw"] == 300,
      "окно выделения: «Сохранить» с форматом PDF записал PDF")
a.config["save_ask"] = False
editor_mod.QFileDialog.getSaveFileName = real_dialog

# hidpi.save_image понимает .pdf, остальные форматы как прежде
check(hidpi.save_image(pic(50, 40), os.path.join(tmp, "h.pdf"), {}) and hidpi.save_image(pic(50, 40), os.path.join(tmp, "h.png"), {})
      and QImage(os.path.join(tmp, "h.png")).width() == 50, "общая запись файла: .pdf и .png")

# --- 5. настройка -----------------------------------------------------------------------------------------------------
dlg = SettingsDialog(dict(appmod.DEFAULTS))
check([dlg.save_format.itemData(n) for n in range(dlg.save_format.count())] == ["png", "jpg"], "формат автосохранения: только PNG и JPEG, PDF не предлагается")
check([dlg.pdf_page.itemData(n) for n in range(dlg.pdf_page.count())] == ["image", "a4"] and dlg.pdf_page.currentData() == "image",
      "настройка «Страница PDF»: «по снимку» (по умолчанию) и «A4»")
dlg.pdf_page.setCurrentIndex(1)
check(dlg.values()["pdf_page"] == "a4", "выбор «A4» попадает в настройки")
check(dict(appmod.DEFAULTS).get("pdf_page") == "image", "значение по умолчанию: по снимку")
dlg.close()

# --- 6. 12 языков: строки, кнопка и меню не обрезаны, обе темы, узкое окно -----------------------------------------------
KEYS = ["editor.print", "editor.print_tip", "editor.print_item", "editor.print_preview", "editor.save_pdf", "pechat.none_title",
        "pechat.none_text", "pechat.none_pdf", "pechat.none_close", "pechat.dialog_title", "pechat.preview_title", "pechat.sent",
        "pechat.failed", "settings.pdf_page", "settings.pdf_page_image", "settings.pdf_page_a4", "settings.pdf_page_tip",
        "novoe.pechat_title", "novoe.pechat_text", "novoe.pdf_title", "novoe.pdf_text", "ozn.pechat_text", "ozn.pdf_text"]
langs = ["ru", "en", "bg", "de", "es", "fr", "it", "pl", "pt", "tr", "uk", "zh"]
for theme_dark in (False, True):
    a.config["ui_theme"] = "pro" if theme_dark else "standard"
    for lang in langs:
        i18n.set_language(lang)
        missing = [k for k in KEYS if i18n.tr(k) == k or not i18n.tr(k).strip()]
        check(not missing, f"{lang}: строки переведены ({missing[:2]})")
        ed = mk()
        ed.show()
        ed.resize(1500, 800)
        QTest.qWait(80)
        b = ed.print_button
        check(b.text().strip() != "", f"{lang}: в широком окне у кнопки есть подпись")
        check(b.isVisible() and b.width() >= b.sizeHint().width() - 1, f"{lang} {'тёмная' if theme_dark else 'светлая'}: кнопка «Печать» не обрезана ({b.width()} >= {b.sizeHint().width()})")
        check(all(ed.print_menu.fontMetrics().horizontalAdvance(x.text().split('\t')[0]) > 0 for x in ed.print_menu.actions()), f"{lang}: пункты меню не пустые")
        # узкое окно «Все инструменты»: самое узкое содержимое, внизу значки
        ed.resize(ed.min_content_width() + ed._rim()[0], ed.height())
        QTest.qWait(60)
        bl = ed.bottom.layout()
        check(ed.print_button.isVisible() and ed.print_button.width() >= 30 and bl.minimumSize().width() <= ed.bottom.width() + 1,
              f"{lang} узкое окно: «Печать» значком, нижняя строка помещается ({bl.minimumSize().width()} <= {ed.bottom.width()})")
        check(ed.print_button.toolTip() == i18n.tr("editor.print_tip"), f"{lang}: подсказка кнопки")
        close_all()
    a.config["ui_theme"] = "standard"
i18n.set_language("ru")

# --- 7. новинка 1.36 и «Ознакомление» ------------------------------------------------------------------------------------
new136 = [it for it in novoe.ITEMS if it[0] == "1.36.0"]
ids = [it[1] for it in new136]
check({"pechat", "pdf"} <= set(ids), f"novoe.ITEMS: новинки 1.36.0 {ids}")
check(all(i in oznakomlenie.BY_ID for i in ids) and oznakomlenie.BY_ID["pechat"][1] == "save" and oznakomlenie.BY_ID["pdf"][1] == "save",
      "«Ознакомление»: оба пункта в группе «Сохранение и копирование»")
for lang in langs:
    i18n.set_language(lang)
    ok = all(oznakomlenie.item_title(i) not in ("", f"novoe.{i}_title") and oznakomlenie.item_line(i) != f"ozn.{i}_text"
             and oznakomlenie.item_hint(i) != f"novoe.{i}_text" for i in ids)
    check(ok, f"{lang}: тексты новинок и «Ознакомления» есть")
i18n.set_language("ru")
check(novoe.badges is not None and any(it[2] == "editor:print_button" for it in new136), "метка «Новое» стоит на кнопке «Печать»")

# --- запись через временный файл: при сбое прежний файл цел, следа .part нет --------------------------------------------
keep = os.path.join(tmp, "keep.pdf")
with open(keep, "wb") as fh:
    fh.write(b"OLD-CONTENT")
_orig_replace = os.replace
def _boom(*_a, **_k):
    raise OSError("сбой замены")
os.replace = _boom
res = pechat.write_pdf(src, keep, {})
os.replace = _orig_replace
check(res is False and open(keep, "rb").read() == b"OLD-CONTENT", "сбой записи: прежний PDF цел, возвращено False")
check(not [n for n in os.listdir(tmp) if n.endswith(".part")], "сбой записи: временный файл убран")
check(pechat.write_pdf(src, keep, {}) and open(keep, "rb").read().startswith(b"%PDF-")
      and not [n for n in os.listdir(tmp) if n.endswith(".part")], "успех: файл заменён целиком, временного файла нет")

print(f"\nИТОГ: {'ВСЁ ХОРОШО' if not failures else str(len(failures)) + ' ошибок'} (проверок: {checks[0]})")
sys.exit(1 if failures else 0)
