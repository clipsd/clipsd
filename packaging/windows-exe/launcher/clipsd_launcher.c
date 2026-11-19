/* ClipSD launcher for Windows: {app}\ClipSD.exe.
 * Copyright (C) 2026 Sergey Dayneko (Сергей Дайнеко). SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Shortcuts, the pinned taskbar icon and autostart point at this small program, so their path never
 * changes between versions. It lives for a fraction of a second and only touches this layout:
 *
 *   {app}\ClipSD.exe      this launcher (replaced by the installer only when its own version changes)
 *   {app}\app\            the working version, ClipSD-app.exe (PyInstaller onedir)
 *   {app}\staging\        a new version written by the installer; complete when staging\.complete exists
 *   {app}\previous\       the version before the last switch; the new version deletes it after its
 *                        start mark (see below)
 *   {app}\failed\         short-lived: a new version that did not start, removed after the rollback
 *
 * Without arguments (or with arguments for ClipSD):
 *   1. repair the layout after a power loss: no app but previous -> previous becomes app;
 *      no app but a complete staging -> staging becomes app;
 *   2. if a complete staging is waiting and ClipSD is not running, switch to it now;
 *   3. start app\ClipSD-app.exe with the given arguments and exit.
 * --switch [args]: ask the running ClipSD to quit (command "quit-for-update" over its local pipe, the
 *   same channel as clipshot/ipc.py; reply "busy" = unsaved work, the switch is deferred), wait for
 *   the process to exit, rename app -> previous and staging -> app with retries for up to 30 s, keep
 *   the old version on failure, delete staging, write %LOCALAPPDATA%\ClipSD\update-result.json,
 *   then start the working version.
 * --no-start: do everything above but do not start ClipSD (silent reinstall without /UPDATE=1).
 *
 * Start check (rollback): whenever the launcher starts a version that has not confirmed a start yet
 * (previous exists and there is no %LOCALAPPDATA%\ClipSD\started-<version of app>), it waits up to
 * 60 s for that mark, written by the new version as soon as its event loop runs and the tray is set
 * up. An ordinary quit (exit code 0: "Quit" in the tray, "ok" to quit-for-update) is not a failure:
 * the program writes its mark before such a quit if it has not yet, so the mark is there when the
 * process is gone. No mark (a crash, or an exit before the program came up): the new version is
 * stopped, app -> failed, previous -> app, the old version is started, update-result.json says
 * failed / not-started and failed is deleted. The new version deletes previous only after its mark.
 *
 * Pipe name: \\.\pipe\clipsd-<user SID> (the user name only when the SID cannot be read), like
 * ipc.socket_path(): per user, not a name any user of the machine shares.
 *
 * Build (MSVC, see packaging\windows-exe\build.ps1):
 *   rc /I <this dir> /I <dir with clipsd.ico> clipsd_launcher.rc
 *   cl /O1 /MT /utf-8 clipsd_launcher.c clipsd_launcher.res /link /SUBSYSTEM:WINDOWS
 */
#ifndef UNICODE
#define UNICODE
#endif
#ifndef _UNICODE
#define _UNICODE
#endif
#ifndef _WIN32_WINNT
#define _WIN32_WINNT 0x0A00
#endif
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <shellapi.h>
#include <sddl.h>
#include <tlhelp32.h>
#include <stdarg.h>
#include <stdio.h>
#include <string.h>
#include <wchar.h>

#include "launcher_version.h"

#ifdef _MSC_VER
#pragma comment(lib, "kernel32.lib")
#pragma comment(lib, "advapi32.lib")
#pragma comment(lib, "user32.lib")
#pragma comment(lib, "shell32.lib")
#pragma comment(lib, "version.lib")
#endif

#define APP_EXE          L"ClipSD-app.exe"
#define AUMID            L"SergeyDayneko.ClipSD"
#define MARKER           L".complete"
#define MUTEX_NAME       L"Local\\SergeyDayneko.ClipSD.Launcher"
#define PIPE_PREFIX      L"\\\\.\\pipe\\clipsd-"   /* QLocalServer name from clipshot/ipc.py socket_path() */
#define MAXP             1024
#define MAX_PROCS        16
#define RENAME_BUDGET_MS 30000   /* folders are held by antivirus, indexer, Explorer: retry this long */
#define EXIT_WAIT_MS     30000   /* how long the running ClipSD may take to exit */
#define REPLY_WAIT_MS    2000    /* reply to quit-for-update ("ok" / "busy") */
#define LEGACY_GRACE_MS  3000    /* a build without a reply may still be exiting on its own */
#define MUTEX_WAIT_MS    120000
#define START_WAIT_MS    60000   /* how long a new version has to write its start mark */

enum { REPLY_NOPIPE = -2, REPLY_BUSY = -1, REPLY_NONE = 0, REPLY_OK = 1 };
enum { SWITCH_NONE = 0, SWITCH_OK, SWITCH_FAILED, SWITCH_DEFERRED };
enum { CHECK_OK = 0, CHECK_ROLLED_BACK, CHECK_FAILED };

static wchar_t g_root[MAXP];      /* {app} */
static wchar_t g_app[MAXP];       /* {app}\app */
static wchar_t g_staging[MAXP];   /* {app}\staging */
static wchar_t g_previous[MAXP];  /* {app}\previous */
static wchar_t g_failed[MAXP];    /* {app}\failed */
static wchar_t g_data[MAXP];      /* %LOCALAPPDATA%\ClipSD, empty if unknown */

/* ---------------------------------------------------------------- helpers */

static ULONGLONG now_ms(void) { return GetTickCount64(); }

static DWORD left_ms(ULONGLONG end)
{
    ULONGLONG now = now_ms();
    return now >= end ? 0 : (DWORD)(end - now);
}

static BOOL join(wchar_t *dst, const wchar_t *a, const wchar_t *b)
{
    return _snwprintf_s(dst, MAXP, _TRUNCATE, L"%s\\%s", a, b) >= 0;
}

static BOOL exists(const wchar_t *p) { return GetFileAttributesW(p) != INVALID_FILE_ATTRIBUTES; }

static BOOL is_dir(const wchar_t *p)
{
    DWORD a = GetFileAttributesW(p);
    return a != INVALID_FILE_ATTRIBUTES && (a & FILE_ATTRIBUTE_DIRECTORY);
}

static BOOL is_file(const wchar_t *p)
{
    DWORD a = GetFileAttributesW(p);
    return a != INVALID_FILE_ATTRIBUTES && !(a & FILE_ATTRIBUTE_DIRECTORY);
}

static BOOL has_exe(const wchar_t *dir)
{
    wchar_t p[MAXP];
    return join(p, dir, APP_EXE) && is_file(p);
}

static BOOL staging_complete(void)
{
    wchar_t p[MAXP];
    return has_exe(g_staging) && join(p, g_staging, MARKER) && is_file(p);
}

/* %LOCALAPPDATA%\ClipSD\started-<version>: the start mark of clipshot/updater.py mark_started().
 * Characters outside [0-9A-Za-z._+-] become '_' (version numbers never contain them). */
static BOOL mark_path(const wchar_t *ver, wchar_t *out)
{
    wchar_t name[96];
    size_t i;

    if (!g_data[0] || !ver || !ver[0])
        return FALSE;
    if (_snwprintf_s(name, 96, _TRUNCATE, L"started-%s", ver) < 0)
        return FALSE;
    for (i = 8; name[i]; i++) {
        wchar_t c = name[i];
        if (!((c >= L'0' && c <= L'9') || (c >= L'a' && c <= L'z') || (c >= L'A' && c <= L'Z') || c == L'.' ||
              c == L'-' || c == L'+' || c == L'_'))
            name[i] = L'_';
    }
    return join(out, g_data, name);
}

static void iso_time(char *out, size_t n)
{
    SYSTEMTIME st;
    GetSystemTime(&st);
    _snprintf_s(out, n, _TRUNCATE, "%04u-%02u-%02uT%02u:%02u:%02uZ", (unsigned)st.wYear, (unsigned)st.wMonth,
                (unsigned)st.wDay, (unsigned)st.wHour, (unsigned)st.wMinute, (unsigned)st.wSecond);
}

/* Version strings go into JSON: keep only safe ASCII characters. */
static void to_ascii(const wchar_t *src, char *dst, size_t n)
{
    size_t i = 0;
    for (; src && *src && i + 1 < n; src++) {
        wchar_t c = *src;
        int ok = (c >= L'0' && c <= L'9') || (c >= L'a' && c <= L'z') || (c >= L'A' && c <= L'Z') ||
                 c == L'.' || c == L'-' || c == L'+' || c == L'_';
        dst[i++] = ok ? (char)c : '?';
    }
    dst[i] = 0;
}

/* One line per event in %LOCALAPPDATA%\ClipSD\launcher.log (no paths: they contain the user name). */
static void log_line(const char *fmt, ...)
{
    char line[512], stamp[32];
    wchar_t path[MAXP];
    WIN32_FILE_ATTRIBUTE_DATA fa;
    DWORD disp = OPEN_ALWAYS, written = 0;
    HANDLE h;
    va_list ap;
    int n, m;
    LARGE_INTEGER zero;

    if (!g_data[0] || !join(path, g_data, L"launcher.log"))
        return;
    iso_time(stamp, sizeof stamp);
    n = _snprintf_s(line, sizeof line, _TRUNCATE, "%s pid=%lu ", stamp, (unsigned long)GetCurrentProcessId());
    if (n < 0)
        return;
    va_start(ap, fmt);
    m = _vsnprintf_s(line + n, sizeof line - (size_t)n - 2, _TRUNCATE, fmt, ap);
    va_end(ap);
    n += m < 0 ? (int)strlen(line + n) : m;
    line[n++] = '\r';
    line[n++] = '\n';

    CreateDirectoryW(g_data, NULL);
    if (GetFileAttributesExW(path, GetFileExInfoStandard, &fa) && (fa.nFileSizeHigh || fa.nFileSizeLow > 262144))
        disp = CREATE_ALWAYS;
    h = CreateFileW(path, GENERIC_WRITE, FILE_SHARE_READ | FILE_SHARE_WRITE, NULL, disp, FILE_ATTRIBUTE_NORMAL, NULL);
    if (h == INVALID_HANDLE_VALUE)
        return;
    zero.QuadPart = 0;
    SetFilePointerEx(h, zero, NULL, FILE_END);
    WriteFile(h, line, (DWORD)n, &written, NULL);
    CloseHandle(h);
}

/* ProductVersion of dir\ClipSD-app.exe ("2.0.1"), empty string if unknown. */
static void app_version(const wchar_t *dir, wchar_t *out, size_t n)
{
    wchar_t exe[MAXP], query[64];
    DWORD handle = 0, size;
    void *buf;
    UINT len = 0;
    WORD *tr = NULL;
    wchar_t *str = NULL;
    VS_FIXEDFILEINFO *ffi = NULL;

    out[0] = 0;
    if (!join(exe, dir, APP_EXE) || !is_file(exe))
        return;
    size = GetFileVersionInfoSizeW(exe, &handle);
    if (!size)
        return;
    buf = HeapAlloc(GetProcessHeap(), 0, size);
    if (!buf)
        return;
    if (GetFileVersionInfoW(exe, 0, size, buf)) {
        if (VerQueryValueW(buf, L"\\VarFileInfo\\Translation", (LPVOID *)&tr, &len) && tr && len >= 4) {
            _snwprintf_s(query, 64, _TRUNCATE, L"\\StringFileInfo\\%04X%04X\\ProductVersion", tr[0], tr[1]);
            if (VerQueryValueW(buf, query, (LPVOID *)&str, &len) && str && len > 0)
                _snwprintf_s(out, n, _TRUNCATE, L"%s", str);
        }
        if (!out[0] && VerQueryValueW(buf, L"\\", (LPVOID *)&ffi, &len) && ffi && len >= sizeof *ffi)
            _snwprintf_s(out, n, _TRUNCATE, L"%u.%u.%u", (unsigned)HIWORD(ffi->dwProductVersionMS),
                         (unsigned)LOWORD(ffi->dwProductVersionMS), (unsigned)HIWORD(ffi->dwProductVersionLS));
    }
    HeapFree(GetProcessHeap(), 0, buf);
}

/* %LOCALAPPDATA%\ClipSD\update-result.json, written atomically (temporary file + replace). */
static void write_result(const char *result, const char *reason, const wchar_t *from, const wchar_t *to, DWORD err)
{
    char f[64], t[64], stamp[32], json[640];
    wchar_t path[MAXP], tmp[MAXP];
    HANDLE h;
    DWORD written = 0;
    BOOL ok;
    int len;

    to_ascii(from, f, sizeof f);
    to_ascii(to, t, sizeof t);
    iso_time(stamp, sizeof stamp);
    log_line("result=%s reason=%s from=%s to=%s error=%lu", result, reason, f, t, (unsigned long)err);
    len = _snprintf_s(json, sizeof json, _TRUNCATE,
                      "{\"result\": \"%s\", \"reason\": \"%s\", \"from\": \"%s\", \"to\": \"%s\", "
                      "\"error\": %lu, \"time\": \"%s\", \"launcher\": \"%s\"}\n",
                      result, reason, f, t, (unsigned long)err, stamp, LAUNCHER_VER_STR);
    if (len < 0 || !g_data[0] || !join(path, g_data, L"update-result.json") ||
        !join(tmp, g_data, L"update-result.json.tmp"))
        return;
    CreateDirectoryW(g_data, NULL);
    h = CreateFileW(tmp, GENERIC_WRITE, 0, NULL, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
    if (h == INVALID_HANDLE_VALUE)
        return;
    ok = WriteFile(h, json, (DWORD)len, &written, NULL) && written == (DWORD)len;
    FlushFileBuffers(h);
    CloseHandle(h);
    if (!ok || !MoveFileExW(tmp, path, MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH))
        DeleteFileW(tmp);
}

/* Delete a folder with everything inside. Junctions and symlinks are removed, never followed. */
static BOOL delete_tree(const wchar_t *dir)
{
    wchar_t pattern[MAXP], child[MAXP];
    WIN32_FIND_DATAW fd;
    HANDLE h;
    BOOL ok = TRUE;
    DWORD a = GetFileAttributesW(dir);

    if (a == INVALID_FILE_ATTRIBUTES)
        return TRUE;
    if (!(a & FILE_ATTRIBUTE_DIRECTORY)) {
        SetFileAttributesW(dir, FILE_ATTRIBUTE_NORMAL);
        return DeleteFileW(dir);
    }
    if (a & FILE_ATTRIBUTE_REPARSE_POINT)
        return RemoveDirectoryW(dir);
    if (!join(pattern, dir, L"*"))
        return FALSE;
    h = FindFirstFileW(pattern, &fd);
    if (h != INVALID_HANDLE_VALUE) {
        do {
            if (wcscmp(fd.cFileName, L".") == 0 || wcscmp(fd.cFileName, L"..") == 0)
                continue;
            if (!join(child, dir, fd.cFileName)) {
                ok = FALSE;
                continue;
            }
            if (fd.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) {
                if (fd.dwFileAttributes & FILE_ATTRIBUTE_REPARSE_POINT) {
                    if (!RemoveDirectoryW(child))
                        ok = FALSE;
                } else if (!delete_tree(child)) {
                    ok = FALSE;
                }
            } else {
                if (fd.dwFileAttributes & FILE_ATTRIBUTE_READONLY)
                    SetFileAttributesW(child, FILE_ATTRIBUTE_NORMAL);
                if (!DeleteFileW(child))
                    ok = FALSE;
            }
        } while (FindNextFileW(h, &fd));
        FindClose(h);
    }
    if (!RemoveDirectoryW(dir))
        ok = FALSE;
    return ok && !exists(dir);
}

static BOOL delete_tree_retry(const wchar_t *dir, DWORD budget_ms)
{
    ULONGLONG end = now_ms() + budget_ms;
    for (;;) {
        if (delete_tree(dir))
            return TRUE;
        if (now_ms() >= end)
            return FALSE;
        Sleep(500);
    }
}

static BOOL move_retry(const wchar_t *from, const wchar_t *to, DWORD budget_ms, DWORD *err)
{
    ULONGLONG end = now_ms() + budget_ms;
    int tries = 0;
    for (;;) {
        tries++;
        if (MoveFileExW(from, to, MOVEFILE_WRITE_THROUGH)) {
            if (tries > 1)
                log_line("rename succeeded after %d tries", tries);
            return TRUE;
        }
        *err = GetLastError();
        if (now_ms() >= end)
            break;
        Sleep(500);
    }
    log_line("rename failed after %d tries, error=%lu", tries, (unsigned long)*err);
    return FALSE;
}

/* ------------------------------------------------------------- processes */

/* Handles (SYNCHRONIZE) of ClipSD-app.exe processes started from {app}\app. */
static int find_running(HANDLE *out, int max)
{
    wchar_t prefix[MAXP], image[MAXP];
    size_t plen;
    int n = 0;
    HANDLE snap, h;
    PROCESSENTRY32W pe;
    DWORD len;

    if (_snwprintf_s(prefix, MAXP, _TRUNCATE, L"%s\\", g_app) < 0)
        return 0;
    plen = wcslen(prefix);
    snap = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0);
    if (snap == INVALID_HANDLE_VALUE)
        return 0;
    pe.dwSize = sizeof pe;
    if (Process32FirstW(snap, &pe)) {
        do {
            if (n >= max)
                break;
            if (_wcsicmp(pe.szExeFile, APP_EXE) != 0)
                continue;
            h = OpenProcess(SYNCHRONIZE | PROCESS_QUERY_LIMITED_INFORMATION, FALSE, pe.th32ProcessID);
            if (!h)
                continue;
            len = MAXP;
            if (QueryFullProcessImageNameW(h, 0, image, &len) && len > plen && _wcsnicmp(image, prefix, plen) == 0)
                out[n++] = h;
            else
                CloseHandle(h);
        } while (Process32NextW(snap, &pe));
    }
    CloseHandle(snap);
    return n;
}

static void close_all(HANDLE *h, int n)
{
    int i;
    for (i = 0; i < n; i++)
        CloseHandle(h[i]);
}

static int count_running(void)
{
    HANDLE h[MAX_PROCS];
    int n = find_running(h, MAX_PROCS);
    close_all(h, n);
    return n;
}

static BOOL wait_all(HANDLE *h, int n, DWORD ms)
{
    DWORD r;
    if (n <= 0)
        return TRUE;
    r = WaitForMultipleObjects((DWORD)n, h, TRUE, ms);
    return r != WAIT_TIMEOUT && r != WAIT_FAILED;
}

/* Send a command to the running ClipSD over its QLocalServer pipe, read an optional reply line.
 * The protocol is the one of clipshot/ipc.py: raw UTF-8 command, no terminator. */
/* String SID of the current user ("S-1-5-21-..."); empty string if it cannot be read. */
static void user_sid(wchar_t *out, size_t n)
{
    HANDLE token = NULL;
    DWORD len = 0;
    TOKEN_USER *tu;
    LPWSTR text = NULL;

    out[0] = 0;
    if (!OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY, &token))
        return;
    GetTokenInformation(token, TokenUser, NULL, 0, &len);
    if (len) {
        tu = (TOKEN_USER *)HeapAlloc(GetProcessHeap(), 0, len);
        if (tu) {
            if (GetTokenInformation(token, TokenUser, tu, len, &len) && ConvertSidToStringSidW(tu->User.Sid, &text)) {
                _snwprintf_s(out, n, _TRUNCATE, L"%s", text);
                LocalFree(text);
            }
            HeapFree(GetProcessHeap(), 0, tu);
        }
    }
    CloseHandle(token);
}

/* Pipe name for attempt 0 (SID) or 1 (user name, as when the program could not read the SID). */
static BOOL pipe_name(int which, wchar_t *name, size_t n)
{
    wchar_t id[256];
    DWORD len;

    if (which == 0) {
        user_sid(id, 256);
        if (!id[0])
            return FALSE;
    } else {
        len = GetEnvironmentVariableW(L"USERNAME", id, 256);
        if (len == 0 || len >= 256)
            wcscpy_s(id, 256, L"user");
    }
    return _snwprintf_s(name, n, _TRUNCATE, L"%s%s", PIPE_PREFIX, id) >= 0;
}

static HANDLE open_pipe(const wchar_t *name)
{
    HANDLE p;
    ULONGLONG end = now_ms() + 3000;
    for (;;) {
        p = CreateFileW(name, GENERIC_READ | GENERIC_WRITE, 0, NULL, OPEN_EXISTING, 0, NULL);
        if (p != INVALID_HANDLE_VALUE)
            return p;
        if (GetLastError() != ERROR_PIPE_BUSY || now_ms() >= end)
            return INVALID_HANDLE_VALUE;
        WaitNamedPipeW(name, 500);
    }
}

static int pipe_command(const char *cmd, DWORD reply_ms)
{
    wchar_t name[512];
    char buf[32];
    DWORD written = 0, avail = 0, got = 0;
    size_t used = 0;
    HANDLE p = INVALID_HANDLE_VALUE;
    ULONGLONG end;
    int result = REPLY_NONE, which;

    for (which = 0; which < 2 && p == INVALID_HANDLE_VALUE; which++) {
        if (pipe_name(which, name, 512))
            p = open_pipe(name);
    }
    if (p == INVALID_HANDLE_VALUE)
        return REPLY_NOPIPE;
    if (!WriteFile(p, cmd, (DWORD)strlen(cmd), &written, NULL)) {
        CloseHandle(p);
        return REPLY_NOPIPE;
    }
    buf[0] = 0;
    end = now_ms() + reply_ms;
    while (reply_ms) {
        if (!PeekNamedPipe(p, NULL, 0, NULL, &avail, NULL))
            break;   /* ClipSD closed the connection (it is exiting) */
        if (avail) {
            if (used + 1 >= sizeof buf || !ReadFile(p, buf + used, (DWORD)(sizeof buf - 1 - used), &got, NULL))
                break;
            used += got;
            buf[used] = 0;
            if (strchr(buf, '\n'))
                break;
            continue;
        }
        if (now_ms() >= end)
            break;
        Sleep(50);
    }
    CloseHandle(p);
    if (strncmp(buf, "ok", 2) == 0)
        result = REPLY_OK;
    else if (strncmp(buf, "busy", 4) == 0)
        result = REPLY_BUSY;
    return result;
}

/* ----------------------------------------------------------------- layout */

/* After a power loss in the middle of a switch: make {app}\app a working version again. */
static void recover_layout(void)
{
    wchar_t ver[64];
    DWORD err = 0;
    BOOL prev_ok, staging_ok;

    if (has_exe(g_app))
        return;
    prev_ok = has_exe(g_previous);
    staging_ok = staging_complete();
    if (!prev_ok && !staging_ok)
        return;
    if (is_dir(g_app)) {
        log_line("recover: app folder without the program, removing it");
        if (!delete_tree_retry(g_app, 10000))
            return;
    }
    if (prev_ok) {
        if (move_retry(g_previous, g_app, 10000, &err)) {
            app_version(g_app, ver, 64);
            write_result("recovered", "restored-previous", L"", ver, 0);
        }
        return;
    }
    if (move_retry(g_staging, g_app, 10000, &err)) {
        wchar_t marker[MAXP];
        if (join(marker, g_app, MARKER))
            DeleteFileW(marker);
        app_version(g_app, ver, 64);
        write_result("recovered", "promoted-staging", L"", ver, 0);
    }
}

/* Switch from {app}\app to {app}\staging. ask_running: ask a running ClipSD to quit first. */
static int do_switch(BOOL ask_running)
{
    wchar_t from[64], to[64], marker[MAXP];
    HANDLE procs[MAX_PROCS];
    int nprocs, reply;
    DWORD err = 0, err2 = 0;
    ULONGLONG end;

    if (!is_dir(g_staging)) {
        log_line("switch: nothing in staging");
        return SWITCH_NONE;
    }
    app_version(g_app, from, 64);
    app_version(g_staging, to, 64);
    if (!staging_complete()) {
        delete_tree_retry(g_staging, 10000);
        write_result("failed", "staging-incomplete", from, to, 0);
        return SWITCH_FAILED;
    }

    nprocs = find_running(procs, MAX_PROCS);
    if (nprocs > 0) {
        if (!ask_running) {
            close_all(procs, nprocs);
            return SWITCH_NONE;
        }
        reply = pipe_command("quit-for-update", REPLY_WAIT_MS);
        log_line("switch: %d running, quit-for-update reply=%d", nprocs, reply);
        if (reply == REPLY_BUSY) {
            /* ClipSD cannot quit now (for example unsaved edits): the complete staging stays and is
             * applied at the next start of the launcher when ClipSD is not running. */
            close_all(procs, nprocs);
            write_result("deferred", "program-busy", from, to, 0);
            return SWITCH_DEFERRED;
        }
        if (reply != REPLY_OK && !wait_all(procs, nprocs, LEGACY_GRACE_MS)) {
            /* Builds without quit-for-update ignore it: fall back to the plain quit command. */
            log_line("switch: no reply, sending quit");
            pipe_command("quit", 1500);
        }
        if (!wait_all(procs, nprocs, EXIT_WAIT_MS)) {
            close_all(procs, nprocs);
            delete_tree_retry(g_staging, 10000);
            write_result("failed", "program-did-not-exit", from, to, WAIT_TIMEOUT);
            return SWITCH_FAILED;
        }
        close_all(procs, nprocs);
    }

    end = now_ms() + RENAME_BUDGET_MS;
    if (exists(g_previous)) {
        while (!delete_tree(g_previous) && now_ms() < end)
            Sleep(500);
        if (exists(g_previous)) {
            err = GetLastError();
            delete_tree_retry(g_staging, 5000);
            write_result("failed", "previous-locked", from, to, err);
            return SWITCH_FAILED;
        }
    }
    if (is_dir(g_app) && !move_retry(g_app, g_previous, left_ms(end), &err)) {
        delete_tree_retry(g_staging, 5000);
        write_result("failed", "app-locked", from, to, err);
        return SWITCH_FAILED;
    }
    if (!move_retry(g_staging, g_app, left_ms(end), &err)) {
        if (!is_dir(g_app) && is_dir(g_previous) && !move_retry(g_previous, g_app, RENAME_BUDGET_MS, &err2)) {
            /* Nothing in app: the next start of the launcher restores previous (recover_layout). */
            write_result("failed", "rollback-failed", from, to, err2);
            return SWITCH_FAILED;
        }
        delete_tree_retry(g_staging, 5000);
        write_result("failed", "staging-locked", from, to, err);
        return SWITCH_FAILED;
    }
    if (join(marker, g_app, MARKER))
        DeleteFileW(marker);
    /* a mark left by an earlier run of the same version must not confirm this start */
    if (mark_path(to, marker))
        DeleteFileW(marker);
    write_result("ok", ask_running ? "switched" : "switched-at-start", from, to, 0);
    return SWITCH_OK;
}

/* ------------------------------------------------------------ start, args */

static void show_error(void)
{
    LANGID lang = GetUserDefaultUILanguage();
    if (PRIMARYLANGID(lang) == LANG_RUSSIAN)
        MessageBoxW(NULL, L"Не найдены файлы ClipSD. Установите ClipSD заново.", L"ClipSD", MB_OK | MB_ICONERROR);
    else
        MessageBoxW(NULL, L"ClipSD files are missing. Please install ClipSD again.", L"ClipSD", MB_OK | MB_ICONERROR);
}

/* Start ClipSD-app.exe from app (or previous when app has none). proc: receives the process handle
 * (the caller closes it), may be NULL. */
static BOOL launch(const wchar_t *args, HANDLE *proc)
{
    wchar_t exe[MAXP];
    wchar_t *cmd;
    size_t cap;
    STARTUPINFOW si;
    PROCESS_INFORMATION pi;
    BOOL ok;

    if (!(join(exe, g_app, APP_EXE) && is_file(exe)) && !(join(exe, g_previous, APP_EXE) && is_file(exe))) {
        log_line("start: no ClipSD-app.exe");
        show_error();
        return FALSE;
    }
    cap = wcslen(exe) + wcslen(args) + 4;
    cmd = (wchar_t *)HeapAlloc(GetProcessHeap(), 0, cap * sizeof(wchar_t));
    if (!cmd)
        return FALSE;
    if (args[0])
        _snwprintf_s(cmd, cap, _TRUNCATE, L"\"%s\" %s", exe, args);
    else
        _snwprintf_s(cmd, cap, _TRUNCATE, L"\"%s\"", exe);
    ZeroMemory(&si, sizeof si);
    si.cb = sizeof si;
    ZeroMemory(&pi, sizeof pi);
    /* Working folder {app}, not {app}\app: a working folder inside app would block its renaming. */
    ok = CreateProcessW(exe, cmd, NULL, NULL, FALSE, 0, NULL, g_root, &si, &pi);
    if (ok) {
        AllowSetForegroundWindow(pi.dwProcessId);
        CloseHandle(pi.hThread);
        if (proc)
            *proc = pi.hProcess;
        else
            CloseHandle(pi.hProcess);
    } else {
        log_line("start: CreateProcess error=%lu", (unsigned long)GetLastError());
    }
    HeapFree(GetProcessHeap(), 0, cmd);
    return ok;
}

/* ------------------------------------------------------- start check, rollback */

/* A version that has not confirmed a start: previous is still there and app has no start mark. */
static BOOL needs_start_check(const wchar_t *args)
{
    wchar_t ver[64], mark[MAXP];

    if (!has_exe(g_previous) || !has_exe(g_app))
        return FALSE;
    if (args[0] && wcsstr(args, L"--quit"))
        return FALSE;   /* "--quit" does not stay running: there is no start to wait for */
    app_version(g_app, ver, 64);
    if (!mark_path(ver, mark))
        return FALSE;   /* no data folder: nothing to wait for */
    return !is_file(mark);
}

/* Start the new version and wait for its start mark; without it return to previous and start that. */
static int start_checked(const wchar_t *args)
{
    wchar_t from[64], to[64], mark[MAXP];
    HANDLE proc = NULL, procs[MAX_PROCS];
    ULONGLONG end;
    DWORD err = 0, wait_err = WAIT_TIMEOUT;
    BOOL exited = FALSE;
    int n, i;

    app_version(g_previous, from, 64);
    app_version(g_app, to, 64);
    if (!mark_path(to, mark))
        return launch(args, NULL) ? CHECK_OK : CHECK_FAILED;
    log_line("start check: waiting up to %d s for the start mark", START_WAIT_MS / 1000);
    if (launch(args, &proc)) {
        end = now_ms() + START_WAIT_MS;
        while (!is_file(mark) && now_ms() < end) {
            if (WaitForSingleObject(proc, 500) == WAIT_OBJECT_0) {
                /* ClipSD normally stays running. Exit code 0 is an ordinary quit, after which the
                 * mark exists (written before quitting); give the file system a moment to show it. */
                exited = TRUE;
                GetExitCodeProcess(proc, &wait_err);
                if (wait_err == 0 && !is_file(mark))
                    Sleep(300);
                break;
            }
        }
        if (is_file(mark)) {
            CloseHandle(proc);
            if (exited)
                log_line("start check: the new version confirmed its start and quit normally (code %lu)",
                         (unsigned long)wait_err);
            else
                log_line("start check: the new version confirmed its start");
            return CHECK_OK;
        }
    } else {
        exited = TRUE;
        wait_err = GetLastError();
    }

    log_line("start check: no start mark (exited=%d), returning the previous version", exited ? 1 : 0);
    if (proc) {
        if (!exited)
            TerminateProcess(proc, 1);
        WaitForSingleObject(proc, 10000);
        CloseHandle(proc);
    }
    n = find_running(procs, MAX_PROCS);   /* anything else the new version started from app */
    for (i = 0; i < n; i++)
        TerminateProcess(procs[i], 1);
    wait_all(procs, n, 10000);
    close_all(procs, n);

    if (exists(g_failed))
        delete_tree_retry(g_failed, 10000);
    if (!move_retry(g_app, g_failed, RENAME_BUDGET_MS, &err)) {
        write_result("failed", "rollback-failed", from, to, err);
        return CHECK_FAILED;
    }
    if (!move_retry(g_previous, g_app, RENAME_BUDGET_MS, &err)) {
        /* app is empty now: launch() and the next recover_layout() use previous */
        write_result("failed", "rollback-failed", from, to, err);
        launch(args, NULL);
        return CHECK_FAILED;
    }
    write_result("failed", "not-started", from, to, wait_err);
    launch(args, NULL);
    if (!delete_tree_retry(g_failed, 10000))
        log_line("start check: failed folder not removed yet");
    return CHECK_ROLLED_BACK;
}

/* Append one argument quoted by the rules of CommandLineToArgvW / the MSVC runtime. */
static void append_arg(wchar_t *dst, size_t *pos, const wchar_t *arg)
{
    const wchar_t *p;
    size_t i, bs;

    if (*pos)
        dst[(*pos)++] = L' ';
    if (arg[0] && !wcspbrk(arg, L" \t\n\v\"")) {
        for (p = arg; *p; p++)
            dst[(*pos)++] = *p;
        return;
    }
    dst[(*pos)++] = L'"';
    for (p = arg;; p++) {
        bs = 0;
        while (*p == L'\\') {
            p++;
            bs++;
        }
        if (*p == 0) {
            for (i = 0; i < bs * 2; i++)
                dst[(*pos)++] = L'\\';
            break;
        }
        if (*p == L'"') {
            for (i = 0; i < bs * 2 + 1; i++)
                dst[(*pos)++] = L'\\';
        } else {
            for (i = 0; i < bs; i++)
                dst[(*pos)++] = L'\\';
        }
        dst[(*pos)++] = *p;
    }
    dst[(*pos)++] = L'"';
}

/* Leading --switch / --no-start belong to the launcher; everything after goes to ClipSD unchanged. */
static wchar_t *build_args(int argc, wchar_t **argv, BOOL *want_switch, BOOL *no_start)
{
    static wchar_t empty[1] = {0};
    size_t cap = 1, pos = 0;
    int i, first = 1;
    wchar_t *out;

    for (; argv && first < argc; first++) {
        if (_wcsicmp(argv[first], L"--switch") == 0)
            *want_switch = TRUE;
        else if (_wcsicmp(argv[first], L"--no-start") == 0)
            *no_start = TRUE;
        else
            break;
    }
    for (i = first; argv && i < argc; i++)
        cap += wcslen(argv[i]) * 2 + 3;
    out = (wchar_t *)HeapAlloc(GetProcessHeap(), 0, cap * sizeof(wchar_t));
    if (!out)
        return empty;
    for (i = first; argv && i < argc; i++)
        append_arg(out, &pos, argv[i]);
    out[pos] = 0;
    return out;
}

static void set_app_user_model_id(void)
{
    typedef HRESULT(WINAPI * SetAumidFn)(PCWSTR);
    HMODULE shell = GetModuleHandleW(L"shell32.dll");
    SetAumidFn fn;
    if (!shell)
        return;
    fn = (SetAumidFn)(void *)GetProcAddress(shell, "SetCurrentProcessExplicitAppUserModelID");
    if (fn)
        fn(AUMID);
}

static BOOL init_paths(void)
{
    wchar_t self[MAXP], longer[MAXP], local[MAXP];
    wchar_t *slash;
    DWORD n;

    n = GetModuleFileNameW(NULL, self, MAXP);
    if (n == 0 || n >= MAXP)
        return FALSE;
    n = GetLongPathNameW(self, longer, MAXP);
    if (n > 0 && n < MAXP)
        wcscpy_s(self, MAXP, longer);
    slash = wcsrchr(self, L'\\');
    if (!slash)
        return FALSE;
    *slash = 0;
    wcscpy_s(g_root, MAXP, self);
    if (!join(g_app, g_root, L"app") || !join(g_staging, g_root, L"staging") || !join(g_previous, g_root, L"previous") ||
        !join(g_failed, g_root, L"failed"))
        return FALSE;
    g_data[0] = 0;
    n = GetEnvironmentVariableW(L"LOCALAPPDATA", local, MAXP);
    if (n > 0 && n < MAXP && !join(g_data, local, L"ClipSD"))
        g_data[0] = 0;
    return TRUE;
}

int WINAPI wWinMain(HINSTANCE instance, HINSTANCE prev, LPWSTR cmdline, int show)
{
    int argc = 0, rc = 0, sw = SWITCH_NONE, ck;
    wchar_t **argv;
    wchar_t *args;
    BOOL want_switch = FALSE, no_start = FALSE, owned = FALSE, started = FALSE;
    HANDLE mutex;
    DWORD w;

    (void)instance;
    (void)prev;
    (void)cmdline;
    (void)show;
    SetErrorMode(SEM_FAILCRITICALERRORS | SEM_NOOPENFILEERRORBOX);
    set_app_user_model_id();
    if (!init_paths()) {
        show_error();
        return 2;
    }
    argv = CommandLineToArgvW(GetCommandLineW(), &argc);
    args = build_args(argc, argv, &want_switch, &no_start);

    /* One launcher at a time changes the layout (Setup's --switch and a click on the icon can meet). */
    mutex = CreateMutexW(NULL, FALSE, MUTEX_NAME);
    if (mutex) {
        w = WaitForSingleObject(mutex, MUTEX_WAIT_MS);
        owned = (w == WAIT_OBJECT_0 || w == WAIT_ABANDONED);
    }
    if (owned) {
        recover_layout();
        if (exists(g_failed))
            delete_tree_retry(g_failed, 2000);   /* left by a rollback that could not delete it */
        if (want_switch)
            sw = do_switch(TRUE);
        else if (staging_complete() && has_exe(g_app) && count_running() == 0)
            sw = do_switch(FALSE);
        /* a version that never confirmed a start is started under the start check (inside the lock,
         * so that no other launcher changes the layout meanwhile) */
        if (!no_start && sw != SWITCH_FAILED && count_running() == 0 && needs_start_check(args)) {
            ck = start_checked(args);
            started = TRUE;
            if (ck != CHECK_OK)
                rc = 1;
        }
        ReleaseMutex(mutex);
    } else {
        log_line("layout check skipped: another launcher holds the lock");
    }
    if (mutex)
        CloseHandle(mutex);
    if (sw == SWITCH_FAILED)
        rc = 1;

    /* After a deferred switch ClipSD keeps running: starting a second copy without arguments is pointless. */
    if (!started && !no_start && !(want_switch && !args[0] && count_running() > 0)) {
        if (!launch(args, NULL))
            rc = 2;
    }
    if (argv)
        LocalFree(argv);
    return rc;
}
