# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later. Распространяется по лицензии GNU GPL v3 или более поздней,
# без каких-либо гарантий; полный текст: файл LICENSE или <https://www.gnu.org/licenses/gpl-3.0.html>.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""Первый запуск сборки из Microsoft Store: карточка с галочкой «Запускать ClipSD вместе с Windows».

У установки из Store нет окна установщика, где у Setup.exe стоит эта галочка, поэтому её показывает сама
программа при первом запуске (решение владельца 19.11.2026). Галочка отмечена заранее; автозапуск включается,
когда человек закрыл карточку («Готово», крестик, Esc, Alt+F4: галочка была видна, значит согласие), если
галочку не сняли. Закрылась сама (программа вышла, пока карточка открыта): решения нет, карточка покажется
при следующем запуске. Карточка не показывается, если автозапуск уже включён, выключен человеком в параметрах
Windows, запрещён политикой или недоступен: тогда ничего не включается. Решение принимается один раз
(store_startup_offered).
"""

from PyQt6.QtWidgets import QCheckBox

from .dialogs import PALETTES, ClipDialog
from .i18n import tr

OFFERED_KEY = "store_startup_offered"


class StartupOfferDialog(ClipDialog):
    """on_done(enable: bool) вызывается не больше одного раза: когда карточку закрыл человек."""

    def __init__(self, parent=None, hotkey: str = "Alt+W", on_done=None, dark: bool = None):
        # 1.32: карточка в общем стиле окон ClipSD, тёмная в оформлении «Профессиональное», значок программы в шапке
        super().__init__(parent, tr("app.store_welcome_title"), tr("app.store_welcome_sub", hotkey=hotkey), "info", 560,
                         dark=dark, logo=True)
        self.on_done = on_done
        self._done = False
        self.startup = QCheckBox(tr("app.store_startup_check"))
        self.startup.setChecked(True)
        # Главный выбор карточки: крупнее подписи под ним. Фон самой галочки цветом карточки: с общим
        # «background: transparent» стиль рисует рамку квадрата из прозрачного цвета окна, и видна только птичка,
        # а снятую галочку не видно совсем
        c = PALETTES[self.dark]
        self.startup.setStyleSheet(f"QCheckBox {{ font-size: 14px; color: {c['text']}; background: {c['card']}; }}"
                                   " QCheckBox::indicator { width: 18px; height: 18px; }")
        self.body.addWidget(self.startup)
        self.text(tr("app.store_startup_note", section=tr("settings.sec_start")), "clipNote")
        self.done_b = self.primary(tr("tour.finish"))
        self.done_b.clicked.connect(self.finish)
        self.close_b.clicked.disconnect()          # крестик: тоже решение (галочка была видна)
        self.close_b.clicked.connect(self.finish)

    def decide(self):
        if not self._done:
            self._done = True
            if callable(self.on_done):
                self.on_done(self.startup.isChecked())

    def finish(self):
        self.decide()
        self.close()

    def keyPressEvent(self, event):
        from PyQt6.QtCore import Qt
        if event.key() == Qt.Key.Key_Escape:
            self.finish()
            return
        super().keyPressEvent(event)

    def closeEvent(self, event):
        if event.spontaneous():   # закрыл человек средствами Windows (Alt+F4, меню окна)
            self.decide()
        super().closeEvent(event)


def offer_startup(ctx) -> object:
    """Первый запуск Store-сборки (ctx: Clipshot): карточка или ничего. Возвращает окно или None."""
    from . import store
    config = ctx.config
    if config.get(OFFERED_KEY) or not store.has_package_identity():
        return None
    state = store.startup_state()
    if state != "disabled":
        # уже включено; выключено человеком в Windows или политикой; StartupTask недоступна: не спрашиваем
        config[OFFERED_KEY] = True
        ctx.save_config()
        return None

    def done(enable: bool):
        config[OFFERED_KEY] = True
        ctx.save_config()
        if not enable:
            return
        try:
            store.set_startup(True)
        except store.StartupError as exc:
            ctx.notify(tr("app.autostart_failed", error=exc))

    dialog = StartupOfferDialog(None, config.get("hotkey_region") or "Alt+W", done)
    dialog.open_centered()
    return dialog
