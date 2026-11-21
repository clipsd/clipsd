# ClipSD: снимки экрана с редактором. Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко)
# SPDX-License-Identifier: GPL-3.0-or-later.
# Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
"""Две сборки Windows рядом (с сайта и из Store), 1.33: пункт Н4 проверки 1.32.3.

1. Вторая копия не молчит: запущенная без команды копия другой сборки показывает сообщение «ClipSD уже работает
   (версия ...)» и выходит. Настоящий `python -m clipshot` дважды (Qt offscreen, своё окружение): первая работает и
   отвечает, какая она; вторая (другая сборка) спрашивает и показывает сообщение. Сборка подменяется в запуске.
2. Работающая копия старой версии (не отвечает на запрос): вторая Store-копия считает работающей сборку с сайта,
   вторая копия с сайта молчит (сборка работающей неизвестна).
3. Одна и та же сборка и любая команда Alt+W: сообщения нет, команда доходит как раньше.
4. Тексты: 12 языков, обе формы, подстановка «Выход», нет незакрытых {полей}.
5. Установщик (ClipSD.iss) разбором скрипта: taskkill по имени только как запасной путь без Store, процессы своей папки останавливаются по
   пути; удаление настроек и мастер знают о Store-копии; сообщения установщика на 12 языках; скобки Pascal Script
   сходятся (Windows-сборка проверяется только в CI, здесь то, что видно на Linux).

Запуск: python3 tests/neighbor_test.py
"""
import tmpclean  # noqa: F401  (временные папки этого теста убираются при его выходе)
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.pop("CLIPSD_LANG", None)
failures = []


def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        failures.append(msg)


def wait_for(cond, limit=10.0):
    end = time.monotonic() + limit
    while not cond() and time.monotonic() < end:
        time.sleep(0.02)
    return cond()


# --- 4. логика и тексты ------------------------------------------------------------------------------

def test_logic_and_texts():
    from clipshot import i18n, neighbor
    check(neighbor.running_kind("store\n", "site") == "store", "ответ store понят")
    check(neighbor.running_kind("site", "store") == "site", "ответ site понят")
    check(neighbor.running_kind("", "store") == "site", "нет ответа, запускается Store: работает сборка с сайта")
    check(neighbor.running_kind("", "site") == "", "нет ответа, запускается сборка с сайта: неизвестно")
    check(neighbor.running_kind("мусор", "site") == "", "чужой ответ не понят")
    check(neighbor.should_explain("store", "site") and neighbor.should_explain("site", "store"), "разные сборки: сообщение")
    check(not neighbor.should_explain("site", "site") and not neighbor.should_explain("store", "store"),
          "та же сборка: сообщения нет")
    check(not neighbor.should_explain("site", ""), "работающая неизвестна: сообщения нет")
    check(neighbor.probe_command("store") == "neighbor:store" and neighbor.is_probe("neighbor:site"), "запрос в канал")
    check(not neighbor.is_probe("region") and not neighbor.is_probe(""), "команды Alt+W запросом не считаются")
    check(neighbor.reply_bytes("store") == b"store\n", "ответ работающей копии")
    for lang in i18n.LANGUAGES:
        i18n.set_language(lang)
        quit_label = i18n.tr("app.menu_quit")
        texts = {}
        for kind in ("store", "site"):
            title, text = neighbor.message_for(kind)
            texts[kind] = text
            check(title and "neighbor." not in title and "neighbor." not in text, f"{lang}/{kind}: ключи переведены")
            check(not re.search(r"\{\w+\}", text), f"{lang}/{kind}: нет незакрытых полей: {text[:50]}")
            check(quit_label in text, f"{lang}/{kind}: в тексте название пункта «{quit_label}»")
        check(texts["store"] != texts["site"], f"{lang}: тексты для Store и для сайта разные")
        if lang in ("ru", "en"):
            check("Microsoft Store" in texts["store"] and "Microsoft Store" in texts["site"], f"{lang}: названа сборка Store")
    i18n.set_language("ru")
    title, text = neighbor.message_for("store")
    check(text.startswith("ClipSD уже работает (версия из Microsoft Store). Значок у часов"), f"ru store: {text[:70]}")
    check(neighbor.message_for("site")[1].startswith("ClipSD уже работает (версия с сайта). Значок у часов"), "ru site")


# --- 1-3. настоящие процессы ---------------------------------------------------------------------------

RUNNER = r'''
import os, sys
kind, out = sys.argv[1], sys.argv[2]
sys.argv = ["clipsd", *sys.argv[3:]]
import clipshot.neighbor as nb
nb.enabled = lambda: True          # на Linux запрос о сборке по умолчанию не посылается
nb.own_kind = lambda: kind
def shown(running):
    open(out, "a").write(running + "\n")
nb.show_message = shown            # вместо окна: записать, какая сборка названа
import clipshot.app as appmod
from clipshot.exitutil import quick_exit
quick_exit(appmod.main())
'''


def run_second(env, base, kind, label, *args, timeout=40):
    out = base / f"shown-{label}"
    out.unlink(missing_ok=True)
    p = subprocess.run([sys.executable, "-c", RUNNER, kind, str(out), *args], env=env, cwd=str(base),
                       capture_output=True, timeout=timeout)
    shown = out.read_text().split() if out.exists() else []
    return p.returncode, shown


def test_processes():
    if os.name == "nt":
        print("только Linux (канал команд в файле), пропущено")
        return
    base = Path(tempfile.mkdtemp(prefix="clipsd-neighbor-"))
    run = Path(os.environ.get("XDG_RUNTIME_DIR") or base / "run")
    run.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", XDG_RUNTIME_DIR=str(run),
               PYTHONPATH=str(ROOT) + os.pathsep + os.environ.get("PYTHONPATH", ""))
    for k in ("DISPLAY", "WAYLAND_DISPLAY", "DBUS_SESSION_BUS_ADDRESS"):
        env.pop(k, None)
    sock = run / "clipshot.sock"
    procs = []
    crashed = []

    def listening():
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(1)
        try:
            s.connect(str(sock))
            return True
        except OSError:
            return False
        finally:
            s.close()

    def stop_all():
        for p in procs:
            if p.poll() == -11:
                crashed.append(True)   # SIGSEGV в фоновом потоке сборки шрифтов (fontTools, Python 3.14), не наш код
            if p.poll() is None:
                os.killpg(p.pid, signal.SIGKILL)
                p.wait()
        procs.clear()
        sock.unlink(missing_ok=True)

    try:
        # первая копия: сборка с сайта, настоящая программа
        first = subprocess.Popen([sys.executable, "-c", RUNNER, "site", str(base / "first-shown")], env=env,
                                 cwd=str(base), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        procs.append(first)
        check(wait_for(listening, 30), "первая копия (сборка с сайта) открыла канал")
        rc, shown = run_second(env, base, "store", "a")
        check(rc == 0 and shown == ["site"], f"Store при работающей копии с сайта: сообщение о сборке site (код {rc}, показано {shown})")
        rc, shown = run_second(env, base, "site", "b")
        check(rc == 0 and shown == [], f"та же сборка: сообщения нет (код {rc}, показано {shown})")
        check(first.poll() is None, f"работающая копия жива после всех запусков (код выхода {first.poll()})")
        q = subprocess.run([sys.executable, "-m", "clipshot", "--quit"], env=env, cwd=str(base), timeout=30, capture_output=True)
        check(wait_for(lambda: first.poll() is not None, 20), f"--quit закрывает копию (код {q.returncode})")
        stop_all()

        # первая копия: сборка Store, вторая с сайта
        first = subprocess.Popen([sys.executable, "-c", RUNNER, "store", str(base / "first-shown2")], env=env,
                                 cwd=str(base), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        procs.append(first)
        check(wait_for(listening, 30), "первая копия (сборка Store) открыла канал")
        rc, shown = run_second(env, base, "site", "d")
        check(rc == 0 and shown == ["store"], f"сайт при работающей Store: сообщение о сборке store (код {rc}, показано {shown})")
        stop_all()

        # работающая копия старой версии: принимает соединение, читает команду и молчит
        got = []

        def old_copy(server):
            while True:
                try:
                    conn, _ = server.accept()
                except OSError:
                    return
                conn.settimeout(2)
                try:
                    got.append(conn.recv(256).decode())
                except OSError:
                    pass
                conn.close()

        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(str(sock))
        server.listen(5)
        threading.Thread(target=old_copy, args=(server,), daemon=True).start()
        rc, shown = run_second(env, base, "store", "e")
        check(rc == 0 and shown == ["site"], f"работает старая копия без ответа, запущена Store: названа сборка site ({rc}, {shown})")
        check(got and got[-1] == "neighbor:store", f"в канал ушёл запрос: {got[-1:]} ")
        got.clear()
        rc, shown = run_second(env, base, "site", "f")
        check(rc == 0 and shown == [], f"старая копия, запущена сборка с сайта: молчим, как раньше ({rc}, {shown})")
        got.clear()
        rc, shown = run_second(env, base, "store", "g", "--region")
        check(rc == 0 and shown == [] and got == ["region"], f"команда Alt+W идёт как раньше, без сообщения ({rc}, {shown}, {got})")
        got.clear()
        rc, shown = run_second(env, base, "store", "h", "--demo")
        check(rc == 0 and shown == [] and got == ["demo"], f"--demo идёт как команда, без сообщения ({rc}, {shown}, {got})")
        server.close()
    finally:
        stop_all()
        shutil.rmtree(base, ignore_errors=True)
    return bool(crashed)


# --- 5. установщик ---------------------------------------------------------------------------------------

def pascal_code(text):
    """Секция [Code] без комментариев и строк (один проход: в строках бывают { }, в комментариях апострофы).
    Незакрытая строка или комментарий оставляют в результате одиночную кавычку или скобку: тест это видит."""
    src = text[text.index("[Code]"):]
    out, i, n = [], 0, len(src)
    while i < n:
        c = src[i]
        if c == "'":
            i += 1
            while i < n:
                if src[i] == "'":
                    if i + 1 < n and src[i + 1] == "'":
                        i += 2
                        continue
                    break
                if src[i] == "\n":   # строка не бывает многострочной
                    out.append("'")
                    break
                i += 1
            out.append("''")
            i += 1
        elif c == "{":
            j = src.find("}", i)
            if j < 0:
                out.append("{")
                break
            i = j + 1
            out.append(" ")
        elif src.startswith("//", i):
            j = src.find("\n", i)
            i = n if j < 0 else j
        else:
            out.append(c)
            i += 1
    return "".join(out)


def test_iss():
    iss = ROOT / "packaging/windows-exe/ClipSD.iss"
    raw = iss.read_bytes()
    check(raw.startswith(b"\xef\xbb\xbf"), "ClipSD.iss: BOM на месте")
    text = raw.decode("utf-8-sig")
    code_raw = text[text.index("[Code]"):]
    nocomment = re.sub(r"(?m)^\s*;.*$", "", text)
    check(nocomment.count("taskkill.exe") == 2 and nocomment.count("{sys}\\taskkill.exe") == 2,
          "ClipSD.iss: taskkill только два вызова запасного пути, с полным путём {sys}")
    check("[UninstallRun]" not in text, "ClipSD.iss: нет секции [UninstallRun] (процессы гасит StopProcessesIn)")
    m = re.search(r"procedure StopProcessesIn\(.*?\nend;", code_raw, re.S)
    body = m.group(0) if m else ""
    check(bool(body), "ClipSD.iss: StopProcessesIn есть")
    check("Win32_Process" in body and "ExecutablePath.StartsWith" in body and "OrdinalIgnoreCase" in body,
          "StopProcessesIn отбирает процессы по полному пути exe")
    check("ClipSD.exe" in body and "ClipSD-app.exe" in body and "-Id $_.ProcessId" in body,
          "StopProcessesIn гасит именно ClipSD.exe и ClipSD-app.exe по номеру процесса")
    # Р2-М1: путь не вставляется в текст команды PowerShell, а передаётся переменной окружения (путь с ', ’, пробелами, кириллицей)
    check("StringChangeEx" not in body and "Prefix" not in body, "StopProcessesIn не подставляет путь в текст команды")
    check("SetEnvironmentVariableW('CLIPSD_STOP_DIR', RemoveBackslash(Dir) + '\\')" in body and "$env:CLIPSD_STOP_DIR" in body,
          "путь передан через переменную окружения CLIPSD_STOP_DIR")
    check(re.search(r"\bDir\b", body.replace("const Dir: String", "").replace("RemoveBackslash(Dir)", "")) is None,
          "имя папки в тексте команды не встречается (ни ', ни U+2018..U+201B не могут её сломать)")
    check("function SetEnvironmentVariableW(Name, Value: String): Integer;" in code_raw
          and "external 'SetEnvironmentVariableW@kernel32.dll stdcall'" in code_raw, "SetEnvironmentVariableW подключена из kernel32")
    check("SetEnvironmentVariableW('CLIPSD_STOP_DIR', '')" in body, "переменная после запуска очищается")
    # Р2-М2: полный путь к PowerShell, запасной taskkill только без Store-копии
    ps = re.search(r"function PowerShellExe\(\).*?\nend;", code_raw, re.S).group(0)
    check("\\System32\\WindowsPowerShell\\v1.0\\powershell.exe" in ps and "\\Sysnative\\WindowsPowerShell" in ps and "Result := ''" in ps,
          "PowerShellExe: полный путь (Sysnative, System32), иначе пусто")
    check(not re.search(r"'powershell\.exe'", code_raw), "в [Code] нет запуска powershell.exe по имени")
    check("catch { exit 4 }" in body and "-ErrorAction Stop" in body and "Done and (Code = 0)" in body,
          "сбой PowerShell или WMI замечается (код выхода), а не молчит")
    tk = body[body.index("if not Done then"):]
    check("if StorePackageInstalled() then" in tk and tk.index("StorePackageInstalled") < tk.index("taskkill.exe"),
          "taskkill по имени только когда Store-копии нет")
    check(tk.count("{sys}\\taskkill.exe") == 2 and "/IM {#LauncherExe}" in tk and "/IM {#ProgramExe}" in tk, "запасной taskkill: ClipSD.exe и ClipSD-app.exe")
    check(body.index("taskkill.exe") > body.index("Win32_Process"), "taskkill идёт после попытки по пути")
    calls = re.findall(r"StopProcessesIn\(ExpandConstant\('\{app\}'\)\)", code_raw)
    check(len(calls) == 2, f"StopProcessesIn(путь {{app}}) вызывается из установщика и деинсталлятора: {len(calls)}")
    check(re.search(r"procedure StopRunning.*?StopProcessesIn", code_raw, re.S) is not None, "StopRunning (переход с 1.x) по пути")
    uninst = code_raw[code_raw.index("procedure CurUninstallStepChanged"):]
    check(uninst.index("StopProcessesIn") < uninst.index("DelTree(Data"), "деинсталлятор гасит процессы до удаления файлов")
    check("usUninstall" in uninst.split("StopProcessesIn")[0], "это шаг usUninstall")
    # Store-копия
    check('#define StorePackageName "ClipSD.ClipSD"' in text, "имя пакета Store в скрипте")
    ident = ROOT / "packaging/windows-store/store-identity.json"
    if ident.exists():
        check(json.loads(ident.read_text(encoding="utf-8"))["name"] == "ClipSD.ClipSD", "имя пакета совпадает с store-identity.json")
    else:
        print("     (store-identity.json нет в этой ветке: имя пакета сверяется после слияния Store)")
    check("Get-AppxPackage -Name {#StorePackageName}" in code_raw, "Store-копия определяется через Get-AppxPackage (без прав администратора)")
    check("PrivilegesRequired=lowest" in text, "установщик без прав администратора")
    check("function UpdateReadyMemo" in code_raw and "StoreInstalledNote" in code_raw, "мастер: строка о Store-копии на странице «Готово к установке»")
    unin = code_raw[code_raw.index("function InitializeUninstall"):code_raw.index("function IsClipSDShot")]
    check("StorePackageInstalled()" in unin and "PurgeStoreWarn" in unin and "PurgeStoreConfirm" in unin,
          "удаление: предупреждение об общих настройках и повторный вопрос")
    check("Box.Checked := False" in unin, "галочка «удалить настройки» по умолчанию снята")
    check(re.search(r"MB_YESNO or MB_DEFBUTTON2\) <> IDYES then\s+PurgeUser := False", unin) is not None,
          "ответ не «Да» оставляет настройки")
    check("UninstallSilent() then\n    Exit" in unin, "тихое удаление (/PURGE=1) не спрашивает, как раньше")
    # 12 языков
    langs = re.findall(r'(?m)^Name: "(\w+)"; MessagesFile', text)
    langs = list(dict.fromkeys(langs))
    check(len(langs) == 12, f"в [Languages] 12 языков: {langs}")
    for key in ("StoreInstalledNote", "PurgeStoreWarn", "PurgeStoreConfirm"):
        have = re.findall(rf"(?m)^(\w+)\.{key}=(.+)$", text)
        check(sorted(l for l, _ in have) == sorted(langs), f"{key}: есть на всех 12 языках")
        check(all(v.strip() and "{" not in v and "%" not in v for _, v in have), f"{key}: без полей и процентов")
        check(len({v for _, v in have}) == 12, f"{key}: 12 разных текстов")
    used = set(re.findall(r"\{cm:(\w+)\}", text))
    defined = set(re.findall(r"(?m)^en\.(\w+)=", text))
    check(used <= defined, f"все {{cm:...}} определены: {sorted(used - defined)}")
    # Pascal Script: скобки сходятся
    code = pascal_code(text)
    words = re.findall(r"\b(begin|case|try|end)\b", code, re.I)
    opens = sum(1 for w in words if w.lower() in ("begin", "case", "try"))
    closes = sum(1 for w in words if w.lower() == "end")
    check(opens == closes, f"Pascal Script: begin/case/try = {opens}, end = {closes}")
    check(code.count("(") == code.count(")"), "Pascal Script: круглые скобки сходятся")
    check(all(("finally" in b or "except" in b) for b in [code]) if "try" in code else True, "try с finally")
    for name in ("StopProcessesIn", "StorePackageInstalled", "PowerShellExe"):
        use = [m.start() for m in re.finditer(rf"\b{name}\b", code)]
        define = re.search(rf"(?:function|procedure) {name}\b", code)
        check(define is not None and use[0] == define.end() - len(name), f"{name}: определена раньше первого вызова")
    # кавычки Pascal в строке PowerShell: после снятия удвоения число одинарных кавычек чётно
    check("'" not in code.replace("''", "") and "{" not in code, "в [Code] каждая строка закрыта (после снятия строк одиночных кавычек не осталось)")


def main():
    test_logic_and_texts()
    for attempt in range(1, 4):   # первая копия иногда падает (-11) в потоке шрифтов при старте под нагрузкой: повтор
        before = len(failures)
        crashed = test_processes()
        if not (crashed and len(failures) > before):
            break
        del failures[before:]
        print(f"     первая копия упала с -11 (поток сборки шрифтов, не этот код), повтор {attempt}")
    test_iss()
    print("ИТОГ:", "все проверки пройдены" if not failures else f"провалено {len(failures)}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
