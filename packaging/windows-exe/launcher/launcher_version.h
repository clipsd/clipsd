/* ClipSD launcher version. Copyright (C) 2026 Sergey Dayneko. SPDX-License-Identifier: GPL-3.0-or-later
 * Additional terms under GNU GPL v3 section 7 apply; see TRADEMARKS.md.
 *
 * This is the version of the launcher itself, not of ClipSD. The installer replaces
 * {app}\ClipSD.exe only when this version changes, so bump it on every change of the
 * launcher sources (clipsd_launcher.c, .rc, .manifest) and only then.
 * It started at 2.0.0 so that it is newer than the 1.x ClipSD.exe it replaces.
 */
#ifndef CLIPSD_LAUNCHER_VERSION_H
#define CLIPSD_LAUNCHER_VERSION_H

#define LAUNCHER_VER_MAJOR 2
#define LAUNCHER_VER_MINOR 0
#define LAUNCHER_VER_PATCH 0
#define LAUNCHER_VER_BUILD 0
#define LAUNCHER_VER_STR   "2.0.0"

#endif
