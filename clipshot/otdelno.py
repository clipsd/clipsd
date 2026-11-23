# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""Куда класть картинку с телефона, из файла или из буфера: в открытый снимок или отдельным снимком (22.11.2026).

Выбор хранится в настройке insert_target_mode ("here" или "apart") и запоминается. Фото с телефона читает его в
момент прихода (phone_ui.deliver_photo), поэтому смена выбора действует на следующее фото. Отдельный снимок
открывается как обычный новый: с автосохранением и историей."""
HERE = "here"
APART = "apart"
CONFIG_KEY = "insert_target_mode"
MODES = (HERE, APART)


def get_mode(config) -> str:
    value = config.get(CONFIG_KEY) if config is not None else None
    return value if value in MODES else HERE


def set_mode(config, mode: str) -> bool:
    """Запомнить выбор; True, если он изменился."""
    if mode not in MODES or get_mode(config) == mode:
        return False
    config[CONFIG_KEY] = mode
    return True


def open_apart(ctx, image, saved=None, phone=False, quality=None):
    """Открыть картинку новым снимком. saved: файл, уже записанный автосохранением (фото с телефона); иначе
    картинка автосохраняется здесь. Возвращает окно редактора или None."""
    if image is None or image.isNull():
        return None
    if saved is None and hasattr(ctx, "autosave"):
        saved = ctx.autosave(image)
    editor = ctx.open_editor(image, None)
    if editor is not None:
        editor.autosave_path = saved
        editor.only_in_memory = not saved
        if phone:
            editor.autosave_quality = quality
            editor.phone_photo = True
    return editor
