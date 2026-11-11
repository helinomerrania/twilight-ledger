"""Updating the app from GitHub without touching the books.

An update replaces code. The books live in data/, which is not in the list of
things an update is allowed to replace, is not in the repository, and is never
opened for writing by anything in this file except to set a copy aside first.

The order is the whole design:

  1. download the new version and unpack it somewhere out of the way
  2. check it: it is this app, it is newer, every Python file in it compiles,
     and it still contains every database migration these books have already
     been through, unchanged — an update that rewrote history would leave the
     app unable to open its own books
  3. set a copy of the books aside, and stop if that fails
  4. keep the code being replaced as a zip, so the update can be undone
  5. swap the new code in, folder by folder, putting the old back if any
     step fails

Only then does the app restart, and on the way up it runs any new migration
with its own copy taken first.
"""
import io
import os
import shutil
import urllib.error
import urllib.request
import zipfile
from datetime import datetime
from pathlib import Path

from . import backup, db

REPO = "helinomerrania/twilight-ledger"
BRANCH = "main"

ROOT = Path(__file__).resolve().parent.parent

# Everything an update may replace. data/ is deliberately not here, and
# nothing outside this list is ever written to.
MANAGED_DIRS = ["ledger", "web", "tools", "tests", "docs"]
MANAGED_FILES = ["twilight.py", "README.md", "VERSION", ".gitignore",
                 "Start Twilight Ledger.bat", "Save tonight from SambaPOS.bat"]

MAX_DOWNLOAD = 30 * 1024 * 1024


def _version_url():
    return os.environ.get("TWILIGHT_UPDATE_VERSION") or \
        f"https://raw.githubusercontent.com/{REPO}/{BRANCH}/VERSION"


def _zip_url():
    return os.environ.get("TWILIGHT_UPDATE_ZIP") or \
        f"https://codeload.github.com/{REPO}/zip/refs/heads/{BRANCH}"


def current(root=ROOT):
    f = Path(root) / "VERSION"
    return f.read_text(encoding="utf-8").strip() if f.exists() else "0"


def parse(version):
    out = []
    for part in str(version).strip().split("."):
        digits = "".join(ch for ch in part if ch.isdigit())
        out.append(int(digits) if digits else 0)
    return tuple(out)


def _get(url, limit=MAX_DOWNLOAD):
    req = urllib.request.Request(url, headers={"User-Agent": "twilight-ledger",
                                               "Cache-Control": "no-cache"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            data = r.read(limit + 1)
    except urllib.error.HTTPError as exc:
        # GitHub was reached and said no; that is not the same as no internet
        if exc.code == 404:
            raise db.LedgerError("GitHub has nothing to offer at that address yet, "
                                 "so nothing was changed.") from exc
        raise db.LedgerError(f"GitHub answered with an error ({exc.code}), so "
                             "nothing was changed.") from exc
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise db.LedgerError(
            "GitHub could not be reached, so nothing was changed. "
            f"({getattr(exc, 'reason', exc)})") from exc
    if len(data) > limit:
        raise db.LedgerError("the download is far larger than this app should be")
    return data


def check(root=ROOT):
    """Is there a newer version? Changes nothing."""
    have = current(root)
    latest = _get(_version_url(), limit=200).decode("utf-8", "replace").strip()
    if not latest or len(latest) > 40 or not any(ch.isdigit() for ch in latest):
        raise db.LedgerError("GitHub answered, but not with a version number")
    return {"current": have, "latest": latest,
            "newer": parse(latest) > parse(have)}


# ------------------------------------------------------------------ checking

def _members(zf):
    """The files in a GitHub zip, with the single top folder stripped off and
    anything that tries to climb out of the app folder refused."""
    names = [n for n in zf.namelist() if not n.endswith("/")]
    tops = {n.split("/", 1)[0] for n in names}
    prefix = tops.pop() + "/" if len(tops) == 1 and all("/" in n for n in names) else ""
    out = {}
    for n in names:
        rel = n[len(prefix):]
        parts = Path(rel).parts
        if not rel or rel.startswith(("/", "\\")) or ".." in parts or ":" in rel:
            raise db.LedgerError(f"the download contains an unsafe path: {n}")
        out[rel] = n
    return out


def inspect(zip_bytes, con=None, root=ROOT):
    """Everything that must be true of a download before it is allowed near
    the app. Returns what it found."""
    try:
        zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
    except zipfile.BadZipFile as exc:
        raise db.LedgerError("the download is not a zip file") from exc
    files = _members(zf)
    for needed in ("twilight.py", "VERSION", "ledger/db.py", "ledger/post.py",
                   "web/index.html"):
        if needed not in files:
            raise db.LedgerError(f"the download is not this app: {needed} is missing")
    if any(rel == "data" or rel.startswith("data/") for rel in files):
        raise db.LedgerError("the download contains a data folder. An update "
                             "never carries books, so this one is refused.")
    version = zf.read(files["VERSION"]).decode("utf-8", "replace").strip()

    for rel, name in files.items():
        if rel.endswith(".py"):
            try:
                compile(zf.read(name).decode("utf-8"), rel, "exec")
            except (SyntaxError, UnicodeDecodeError) as exc:
                raise db.LedgerError(f"the new version is broken ({rel}: {exc}). "
                                     "Nothing was changed.") from exc

    if con is not None:
        applied = {r["name"]: r["sha"] for r in con.execute(
            "SELECT name, sha FROM schema_migrations")}
        for name, sha in applied.items():
            rel = f"ledger/migrations/{name}"
            if rel not in files:
                raise db.LedgerError(
                    f"the new version has lost {name}, which these books have "
                    "already been through. Nothing was changed.")
            text = zf.read(files[rel]).decode("utf-8").replace("\r\n", "\n")
            if not db.same_migration(name, sha, db._sha(text)):
                raise db.LedgerError(
                    f"the new version has rewritten {name}, which these books "
                    "have already been through. Nothing was changed.")
    return {"version": version, "files": files, "zip": zf}


# ------------------------------------------------------------------ applying

def _archive_code(root, dest):
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
        for d in MANAGED_DIRS:
            base = root / d
            if not base.exists():
                continue
            for f in sorted(base.rglob("*")):
                if f.is_file() and "__pycache__" not in f.parts:
                    z.write(f, f.relative_to(root).as_posix())
        for name in MANAGED_FILES:
            if (root / name).exists():
                z.write(root / name, name)


def apply(zip_bytes, con, root=ROOT):
    """Replace the code with the downloaded version. The books are copied
    aside first and are not otherwise touched."""
    root = Path(root).resolve()
    found = inspect(zip_bytes, con, root)
    have, version = current(root), found["version"]
    if parse(version) <= parse(have):
        raise db.LedgerError(f"this is already version {have}; the download is {version}")
    files, zf = found["files"], found["zip"]

    # 3. the books first. If they cannot be set aside, nothing else happens.
    try:
        saved = backup.run(con, why=f"before-update-{version}")
    except (db.LedgerError, OSError) as exc:
        raise db.LedgerError("could not set the books aside first, so nothing "
                             f"was changed: {exc}") from exc

    # 4. the code being replaced, so this can be undone by unzipping it back
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    keep = db.backup_dir(con.path)
    keep.mkdir(parents=True, exist_ok=True)
    old_code = keep / f"code-{have}-{stamp}.zip"
    _archive_code(root, old_code)

    # 1 (done late on disk, but before any swap). unpack out of the way
    stage = root / ".update-staging"
    shutil.rmtree(stage, ignore_errors=True)
    for rel, name in files.items():
        top = rel.split("/", 1)[0]
        if not (top in MANAGED_DIRS or rel in MANAGED_FILES):
            continue                       # not something an update may write
        target = stage / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(zf.read(name))

    # 5. swap folder by folder, able to put every one back
    moved, replaced_files = [], []
    try:
        for d in MANAGED_DIRS:
            new, live, old = stage / d, root / d, root / f".old-{d}-{stamp}"
            if not new.exists():
                continue
            if live.exists():
                live.rename(old)
            moved.append((live, old))
            new.rename(live)
        for name in MANAGED_FILES:
            new, live = stage / name, root / name
            if not new.exists():
                continue
            kept = root / f".old-{name}-{stamp}"
            if live.exists():
                live.rename(kept)
            replaced_files.append((live, kept))
            new.rename(live)
    except OSError as exc:
        for live, old in reversed(replaced_files + moved):
            try:
                if live.exists():
                    shutil.rmtree(live) if live.is_dir() else live.unlink()
                if old.exists():
                    old.rename(live)
            except OSError:
                pass
        shutil.rmtree(stage, ignore_errors=True)
        raise db.LedgerError(
            f"the update could not be put in place ({exc}). The app was left "
            "as it was. Close anything that has the app's folder open and try "
            "again.") from exc

    for _, old in moved + replaced_files:
        try:
            shutil.rmtree(old) if old.is_dir() else old.unlink()
        except OSError:
            pass
    shutil.rmtree(stage, ignore_errors=True)
    db.audit(con, "update", None, {"summary": f"Updated the app from {have} to {version}",
                                   "from": have, "to": version})
    return {"from": have, "to": version, "books_copy": saved["file"],
            "old_code": str(old_code)}


def download_and_apply(con, root=ROOT):
    return apply(_get(_zip_url()), con, root)
