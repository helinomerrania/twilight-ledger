"""The local web server: one user, one machine, loopback only.

This is deliberately the least clever file in the project. It serves the
screens out of web/, answers /api, and binds 127.0.0.1 so nothing on the
network can reach the books. There is no framework, no session, no login — on
a single PC a login is theatre, and the real protection is that the port is not
listening anywhere else.

Three things it does take seriously:

  * it refuses to start if the ledger does not balance, rather than serving
    figures from books that have lost money
  * every write is one transaction, and the balancing check runs before commit
  * a write is only accepted from the app's own page. The server listens on
    this PC only, but a web page open in the same browser could otherwise
    still send it a request; requiring JSON from our own origin stops that
"""
import json
import mimetypes
import os
import socket
import sys
import threading
import time
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import api, backup, db, lang, queries, update
from .close import ready
from .dates import month_of, tonight
from .pos import auto
from .words import t

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
KINDS = {".html": "text/html", ".js": "text/javascript", ".css": "text/css",
         ".json": "application/json", ".svg": "image/svg+xml", ".png": "image/png",
         ".ico": "image/x-icon", ".woff2": "font/woff2"}
HOST = "127.0.0.1"
PORT = int(os.environ.get("TWILIGHT_PORT", "8788"))
RESTART = 3                      # exit code that asks the start file to run us again

# A browser will not let a page reach another origin without permission, and
# these are the only names the screens are ever served under.
ALLOWED_HOSTS = {"127.0.0.1", "localhost", "[::1]"}
NOBODY = 120                     # seconds a window has to open before the app gives up on it


class Pages:
    """The app's own pages that are open, each by the name it gave itself.

    Started from its desktop icon, the app has no black window to close: it
    stops once the last of its windows has gone. A page says it is here when
    it loads and every so often after, and goodbye when it goes. A page being
    loaded again says both, so the app waits a moment after the last goodbye
    for anyone to come back before it stops."""

    GRACE = 10

    def __init__(self, when_all_gone=None):
        self.lock = threading.Lock()
        self.open = set()
        self.heard = False           # has any page said it is here yet
        self.when_all_gone = when_all_gone

    def here(self, page):
        # a page names itself in twenty-odd letters; nothing else is kept
        if page and len(page) <= 64 and len(self.open) < 1000:
            with self.lock:
                self.open.add(page)
                self.heard = True

    def bye(self, page):
        with self.lock:
            if page not in self.open:
                return
            self.open.discard(page)
            if self.open or not self.when_all_gone:
                return
        later(self.GRACE, self._gone)

    def _gone(self):
        with self.lock:
            if self.open:
                return
        self.when_all_gone()


def later(seconds, fn):
    timer = threading.Timer(seconds, fn)
    timer.daemon = True
    timer.start()


def whole(text, default):
    """A whole number from an address, or the default when it is not one."""
    return int(text) if text and text.isdecimal() and len(text) < 10 else default


def this_month():
    """The month the lounge is in: until six in the morning, last night's."""
    return month_of(tonight())


class Handler(BaseHTTPRequestHandler):
    server_version = "TwilightLedger"
    protocol_version = "HTTP/1.1"
    db_path = None               # set by serve(); each thread opens its own
    restart = False              # set once an update has been put in place
    pages = Pages()              # the app's pages that are open

    # ------------------------------------------------------------- plumbing
    def log_message(self, fmt, *args):
        if os.environ.get("TWILIGHT_VERBOSE"):
            sys.stderr.write("  %s %s\n" % (self.address_string(), fmt % args))

    def send_json(self, obj, status=200):
        body = json.dumps(obj, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        if self.close_connection:
            self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)

    def send_error_json(self, exc, status=None):
        out = {"error": str(exc)}
        out.update(getattr(exc, "extra", None) or {})
        self.send_json(out, status or getattr(exc, "status", 400))

    def send_file(self, path):
        if not path.exists() or not path.is_file():
            return self.send_json({"error": t("server.not_found")}, 404)
        # Serve nothing outside web/, whatever the URL asks for.
        try:
            path.resolve().relative_to(WEB.resolve())
        except ValueError:
            return self.send_json({"error": t("server.not_found")}, 404)
        body = path.read_bytes()
        # Windows' registry can say otherwise for any of these, and a browser
        # told not to guess will not run a script, nor use a stylesheet, that
        # is sent as something else: the screens would come up blank, or bare
        kind = (KINDS.get(path.suffix.lower()) or mimetypes.guess_type(path.name)[0]
                or "application/octet-stream")
        self.send_response(200)
        self.send_header("Content-Type", kind + ("; charset=utf-8"
                                                 if kind.startswith("text/")
                                                 or kind.endswith("json") else ""))
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    @property
    def con(self):
        """This thread's own connection to the books."""
        return db.thread_connection(self.db_path)

    def finish(self):
        # Each browser connection is answered on a thread of its own, which
        # ends with it: its connection to the books is closed here rather
        # than left for the garbage collector.
        try:
            super().finish()
        finally:
            db.close_thread_connection()

    def _safe_host(self):
        host = (self.headers.get("Host") or "").rsplit(":", 1)[0]
        return host in ALLOWED_HOSTS or host == ""

    def _own_page(self):
        """Was this write sent by the app's own page?"""
        if "application/json" not in (self.headers.get("Content-Type") or ""):
            return False
        origin = self.headers.get("Origin")
        if origin:
            host = urlparse(origin).hostname or ""
            return host in {"127.0.0.1", "localhost", "::1"}
        return True

    # ----------------------------------------------------------------- GET
    def do_GET(self):
        if not self._safe_host():
            return self.send_json({"error": t("server.localhost")}, 403)
        url = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(url.query).items()}
        try:
            if url.path == "/api/state":
                auto.kick()           # a screen is open: look for SambaPOS backups
                return self.send_json(api.state(self.con, month=q.get("month"),
                                                on=q.get("on"),
                                                count_date=q.get("count_date")))
            if url.path == "/api/entries":
                return self.send_json(queries.entries(               # the search box
                    self.con, q=q.get("q"), limit=min(whole(q.get("limit"), 300), 2000)))
            if url.path == "/api/supplier":
                out = queries.supplier_lines(self.con, whole(q.get("id"), 0),
                                             api.asked_month(q.get("month")) or this_month())
                if out is None:
                    return self.send_json({"error": t("server.no_supplier")}, 404)
                return self.send_json(out)
            if url.path == "/api/close":
                return self.send_json(ready(self.con,
                                            api.asked_month(q.get("month")) or this_month()))
            if url.path == "/api/here":            # a page is still open
                Handler.pages.here(q.get("page"))
                return self.send_json({})
            if url.path == "/api/health":
                out = db.integrity(self.con)
                out["version"] = update.RUNNING
                out["books"] = str(self.con.path)
                return self.send_json(out)
            if url.path == "/api/update":
                return self.send_json(update.check())
            if url.path == "/api/lang":                # the Kurdish kept in the books
                return self.send_json(lang.texts(self.con))
            if url.path.startswith("/api/"):
                return self.send_json({"error": t("server.no_endpoint")}, 404)
        except (api.ApiError, db.LedgerError) as exc:
            return self.send_error_json(exc)
        except Exception as exc:                       # noqa: BLE001
            return self.send_json({"error": f"{type(exc).__name__}: {exc}"}, 500)

        name = url.path.lstrip("/") or "index.html"
        return self.send_file(WEB / name)

    # ---------------------------------------------------------------- POST
    def do_POST(self):
        if urlparse(self.path).path == "/api/bye" and self._safe_host():
            # A page going away. It cannot send JSON as it goes, and it only
            # says it has gone, so it needs nothing else of a write.
            self.close_connection = True
            Handler.pages.bye(parse_qs(urlparse(self.path).query).get("page", [""])[0])
            return self.send_json({})
        refused = (t("server.localhost") if not self._safe_host() else
                   t("server.own_page") if not self._own_page() else None)
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = -1
        if refused or length < 0:
            # The body is left unread, so the connection ends here: what is
            # left of it must not be taken for the next request.
            self.close_connection = True
            return self.send_json({"error": refused or t("server.bad_json")},
                                  403 if refused else 400)
        url = urlparse(self.path)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw or b"{}")
            if not isinstance(body, dict):
                raise ValueError
        except ValueError:
            return self.send_json({"error": t("server.bad_json")}, 400)
        # A page left open across an update still has the old screens, and
        # what they send may no longer mean what the new app takes it to mean.
        page = self.headers.get("X-Twilight-Version")
        if page and page != update.RUNNING:
            return self.send_json({"error": t("server.updated"), "reload": True}, 409)

        try:
            if url.path == "/api/update":
                out = update.download_and_apply(self.con)
                Handler.restart = True
                threading.Timer(1.0, self.server.shutdown).start()
                return self.send_json(out)
            if not url.path.startswith("/api/do/"):
                return self.send_json({"error": t("server.no_endpoint")}, 404)
            name = url.path[len("/api/do/"):]
            out = api.run(self.con, name, body)
        except (api.ApiError, db.LedgerError) as exc:
            return self.send_error_json(exc)
        except Exception as exc:                       # noqa: BLE001
            return self.send_json({"error": f"{type(exc).__name__}: {exc}"}, 500)
        # Saved. Nothing after this point may make it look as if it was not, or
        # it would be entered again: a failure is said beside the answer.
        out.update(self._after_save(name, body))
        return self.send_json(out)

    def _after_save(self, name, body):
        """The day's copy of the books, and the new state for the screen."""
        out, problems = {}, []
        try:
            if name == "business_set":
                api.load_settings(self.con)
            backup.daily(self.con)
        except Exception as exc:                       # noqa: BLE001
            problems.append(t("server.no_daily_copy", exc))
        try:
            out["state"] = api.state(self.con, month=body.get("view_month"),
                                     on=body.get("view_on"),
                                     count_date=body.get("view_count"))
        except Exception as exc:                       # noqa: BLE001
            problems.append(t("server.no_state", exc))
        if problems:
            out["warning"] = (t("server.saved_but", problems[0]) if len(problems) == 1
                              else t("server.saved_but_two", *problems))
        return out


def free_port(port):
    with socket.socket() as s:
        try:
            s.bind((HOST, port))
            return True
        except OSError:
            return False


def running_at(port, books):
    """Where this app is already serving these books, if it is. Started a
    second time, it must not run beside itself: two copies would both write
    to the books, and after an update one of them would go on with the old
    code against the new books."""
    direct = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for p in range(port, port + 20):
        if free_port(p):
            continue
        try:
            with direct.open(f"http://{HOST}:{p}/api/health", timeout=2) as r:
                info = json.loads(r.read())
        except (OSError, ValueError):
            continue
        if info.get("books") == str(books):
            return f"http://{HOST}:{p}/"
    return None


def show(url, window):
    """The books, in a browser, or in a window of their own."""
    if window:
        from . import window as own
        own.open_window(url)
    else:
        webbrowser.open(url)


class Server(ThreadingHTTPServer):
    def handle_error(self, request, client_address):
        # A page that went away before its answer was sent (reloaded, closed,
        # moved on) is not a fault, and its traceback would only fill the log.
        if isinstance(sys.exc_info()[1], ConnectionError):
            return
        super().handle_error(request, client_address)


def take_back(port):
    """Started again after an update: the same port as before, so that the
    pages left open find the app where they left it. The version it replaced
    has let go of it, or is just letting go; its last connections linger a
    while yet, which only a real attempt to listen there sees past."""
    for _ in range(50):
        try:
            return Server((HOST, port), Handler)
        except OSError:
            time.sleep(0.2)
    return None


def serve(db_path=None, port=PORT, *, open_browser=True, window=False):
    """Serve the books until stopped. `window` is the app started from its
    desktop icon: it opens in a window of its own, and stops once the last
    of its windows is closed."""
    already = running_at(port, Path(db_path or db.DEFAULT_DB).resolve())
    if already:
        print(t("cli.already_open", already))
        if open_browser:
            show(already, window)
        return 0
    con = db.connect(db_path or db.DEFAULT_DB)
    api.bootstrap(con)
    rep = db.integrity(con)
    if not rep["ok"]:
        print(t("cli.not_served"))
        for key in ("sqlite", "foreign_keys", "unbalanced"):
            if rep[key] and rep[key] != [{"integrity_check": "ok"}]:
                print(f"  {key}: {rep[key]}")
        raise SystemExit(2)
    try:
        backup.daily(con)
    except (db.LedgerError, OSError) as exc:
        print(t("cli.no_backup_today", exc))
    if os.name == "nt":
        from . import window as own
        own.icon_once(con, db_path)

    Handler.db_path = con.path
    Handler.restart = False
    again = bool(os.environ.get("TWILIGHT_RESTARTED"))
    srv = take_back(port) if again else None
    if srv is None:
        while not free_port(port) and port < PORT + 20:
            port += 1
        srv = Server((HOST, port), Handler)
    port = srv.server_address[1]
    Handler.pages = Pages(srv.shutdown if window else None)
    if window:
        # nobody came: the window never opened, or was closed while the app
        # was starting again after an update
        later(NOBODY, lambda: None if Handler.pages.heard else srv.shutdown())
    auto.start(con.path)         # SambaPOS's backups, read by themselves
    url = f"http://{HOST}:{port}/"
    print(t("cli.serving", update.RUNNING, con.path))
    print(t("cli.serving_books", rep["entries"], rep["postings"]))
    print(t("cli.serving_open", url))
    print(t("cli.serving_stop"))
    if open_browser and not again:
        later(0.6, lambda: show(url, window))
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n" + t("cli.stopped"))
    finally:
        srv.server_close()
        con.close()
    if Handler.restart:
        print(t("cli.restarting"))
        return RESTART
    return 0
