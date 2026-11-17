"""The app in a window of its own, with no black window behind it.

The Twilight Ledger icon on the desktop starts the app with pythonw, Python
without a console. It serves the books just as `twilight.py serve` does and
opens them in a window of their own: Microsoft Edge's app window, which has
no address bar and no tabs (Chrome's if Edge is not there; a browser tab if
neither is). It stops by itself a few seconds after the last of its windows
is closed (the pages say when: server.Pages). After an update it starts
itself again, and the window reloads once it is back. What the black window
would have shown goes to twilight.log beside the books, and if the app
cannot start at all, a message box says why.

The icon is put on the desktop the first time the app runs on Windows,
however it was started, and not again if it is deleted: `twilight.py icon`
puts it back.

Start Twilight Ledger.bat still starts the app the old way, black window
and all. It is never changed: an update replaces it while it is running, and
Windows reads a running batch file from disk line by line, so a changed one
would carry on from the middle of a line.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import traceback
import webbrowser
from datetime import datetime
from pathlib import Path

from . import db, server
from .words import t

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "twilight.py"
ICON = ROOT / "web" / "icon.ico"
MAKE_ICON = Path(__file__).with_name("desktop.ps1")
LOG = "twilight.log"
LOG_LIMIT = 1_000_000

# Windows' ways of starting a process: on its own, and without a window
NEW_GROUP = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
DETACHED = getattr(subprocess, "DETACHED_PROCESS", 0)
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def run(db_path, argv):
    """`twilight.py window`, with the arguments it was started with."""
    if leave_console(argv):
        return 0
    log = write_beside(Path(db_path).resolve())
    try:
        code = server.serve(db_path, open_browser=True, window=True)
    except SystemExit as exc:              # the books will not be served
        say(t("cli.window_failed", t("cli.not_served"), log))
        return exc.code if isinstance(exc.code, int) else 1
    except Exception as exc:               # noqa: BLE001  anything else that stopped it
        traceback.print_exc()
        say(t("cli.window_failed", exc, log))
        return 1
    if code == server.RESTART:
        start_again(argv)
        return 0
    return code


def leave_console(argv):
    """Started from a black window, start again without one, and let the
    black window close. Returns whether it did."""
    if os.name != "nt" or sys.stdout is None:
        return False
    windowless = Path(sys.executable).with_name("pythonw.exe")
    if not windowless.exists():
        return False
    subprocess.Popen([str(windowless), str(SCRIPT), *argv], cwd=ROOT, close_fds=True,
                     creationflags=NEW_GROUP | DETACHED)
    return True


def start_again(argv):
    """After an update: the same app, new code."""
    env = dict(os.environ, TWILIGHT_RESTARTED="1")
    subprocess.Popen([sys.executable, str(SCRIPT), *argv], cwd=ROOT, env=env,
                     close_fds=True, creationflags=NEW_GROUP)


def write_beside(books):
    """With no black window, what it would have shown goes to a file beside
    the books, started afresh once it grows large."""
    log = books.parent / LOG
    if sys.stdout is None or sys.stderr is None:
        try:
            if log.exists() and log.stat().st_size > LOG_LIMIT:
                log.replace(log.with_suffix(".log.old"))
            out = open(log, "a", encoding="utf-8", buffering=1)   # noqa: SIM115  open as long as the app is
        except OSError:
            out = open(os.devnull, "w", encoding="utf-8")         # noqa: SIM115
        sys.stdout = sys.stderr = out
        print(f"\n{datetime.now().astimezone():%Y-%m-%d %H:%M:%S}")
    return log


def say(text):
    """What went wrong, where it can be seen."""
    print(text, file=sys.stderr)
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, str(text), t("app.name"), 0x10)
        except (OSError, AttributeError):
            pass


# --------------------------------------------------------------- the window

def browser():
    """Microsoft Edge, else Chrome: either can open a page as a window of
    its own. None if neither is there."""
    if os.name == "nt":
        places = [os.environ.get(v) for v in ("PROGRAMFILES(X86)", "PROGRAMFILES", "LOCALAPPDATA")]
        found = [Path(p) / "Microsoft" / "Edge" / "Application" / "msedge.exe" for p in places if p]
        found += [Path(p) / "Google" / "Chrome" / "Application" / "chrome.exe" for p in places if p]
        for f in found:
            if f.exists():
                return str(f)
        names = ("msedge", "chrome")
    else:
        names = ("microsoft-edge", "google-chrome", "chromium", "chromium-browser")
    for n in names:
        if shutil.which(n):
            return shutil.which(n)
    return None


def open_window(url):
    exe = browser()
    if exe:
        try:
            subprocess.Popen([exe, f"--app={url}"], close_fds=True, creationflags=NEW_GROUP)
            return
        except OSError:
            pass
    webbrowser.open(url)


# ----------------------------------------------------------- the desktop icon

def icon_once(con, db_path=None):
    """Put the icon on the desktop the first time the app runs on Windows."""
    try:
        if db.setting(con, "desktop_icon"):
            return
        made = make_icon(db_path)
        with db.tx(con):
            db.set_setting(con, "desktop_icon", made or "-")
    except Exception as exc:               # noqa: BLE001  an icon is never worth not starting over
        print(t("cli.icon_failed", exc))


def make_icon(db_path=None):
    """A Twilight Ledger icon on the desktop that starts the app in its own
    window. Returns where it was put, or None if it could not be."""
    exe = (shutil.which("powershell") or shutil.which("powershell.exe")) if os.name == "nt" else None
    if not exe:
        return None
    python = Path(sys.executable)
    windowless = python.with_name("pythonw.exe")
    args = [str(SCRIPT)]
    if db_path and Path(db_path).resolve() != Path(db.DEFAULT_DB).resolve():
        args += ["--db", str(Path(db_path).resolve())]
    args.append("window")
    request = {"name": t("app.name"), "target": str(windowless if windowless.exists() else python),
               "arguments": subprocess.list2cmdline(args), "folder": str(ROOT), "icon": str(ICON)}
    try:
        p = subprocess.run(
            [exe, "-NoLogo", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
             "-File", str(MAKE_ICON)],
            input=json.dumps(request).encode("ascii"), capture_output=True, timeout=60,
            creationflags=NO_WINDOW, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    m = re.search(r"<<TWILIGHT>>(.*)<<END>>", p.stdout.decode("utf-8", "replace"), re.DOTALL)
    return m.group(1).strip() if p.returncode == 0 and m else None
