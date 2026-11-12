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
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import api, backup, db, lang, queries, update
from .close import ready
from .pos import auto

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
HOST = "127.0.0.1"
PORT = int(os.environ.get("TWILIGHT_PORT", "8788"))
RESTART = 3                      # exit code that asks the start file to run us again

# A browser will not let a page reach another origin without permission, and
# these are the only names the screens are ever served under.
ALLOWED_HOSTS = {"127.0.0.1", "localhost", "[::1]"}


class Handler(BaseHTTPRequestHandler):
    server_version = "TwilightLedger"
    protocol_version = "HTTP/1.1"
    db_path = None               # set by serve(); each thread opens its own
    restart = False              # set once an update has been put in place

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
            return self.send_json({"error": "not found"}, 404)
        # Serve nothing outside web/, whatever the URL asks for.
        try:
            path.resolve().relative_to(WEB.resolve())
        except ValueError:
            return self.send_json({"error": "not found"}, 404)
        body = path.read_bytes()
        kind = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        if path.suffix == ".js":
            kind = "text/javascript"          # Windows' registry can say otherwise
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
            return self.send_json({"error": "this server only answers on localhost"}, 403)
        url = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(url.query).items()}
        try:
            if url.path == "/api/state":
                auto.kick()           # a screen is open: look for SambaPOS backups
                return self.send_json(api.state(self.con, month=q.get("month"),
                                                on=q.get("on"),
                                                count_date=q.get("count_date")))
            if url.path == "/api/entries":
                return self.send_json(queries.entries(
                    self.con, on=q.get("on"), month=q.get("month"),
                    q=q.get("q"), detail=q.get("detail"), kind=q.get("kind"),
                    date_from=q.get("from"), date_to=q.get("to"),
                    limit=min(int(q.get("limit") or 300), 2000)))
            if url.path == "/api/supplier":
                out = queries.supplier_lines(self.con, int(q.get("id") or 0),
                                             q.get("month"))
                if out is None:
                    return self.send_json({"error": "no such supplier"}, 404)
                return self.send_json(out)
            if url.path == "/api/close":
                return self.send_json(ready(self.con, q.get("month")))
            if url.path == "/api/health":
                out = db.integrity(self.con)
                out["version"] = update.current()
                return self.send_json(out)
            if url.path == "/api/update":
                return self.send_json(update.check())
            if url.path == "/api/lang":                # the Kurdish, for the screens
                return self.send_json(lang.texts(self.con))
            if url.path == "/api/lang/todo":           # what Gemini is asked next
                limit = q.get("limit") or ""
                return self.send_json(lang.todo(self.con, min(int(limit) if limit.isdigit()
                                                              else 150, 400)))
            if url.path.startswith("/api/"):
                return self.send_json({"error": "no such endpoint"}, 404)
        except (api.ApiError, db.LedgerError) as exc:
            return self.send_error_json(exc)
        except Exception as exc:                       # noqa: BLE001
            return self.send_json({"error": f"{type(exc).__name__}: {exc}"}, 500)

        name = url.path.lstrip("/") or "index.html"
        return self.send_file(WEB / name)

    # ---------------------------------------------------------------- POST
    def do_POST(self):
        refused = ("this server only answers on localhost" if not self._safe_host() else
                   "writes are only accepted from the app's own page" if not self._own_page()
                   else None)
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = -1
        if refused or length < 0:
            # The body is left unread, so the connection ends here: what is
            # left of it must not be taken for the next request.
            self.close_connection = True
            return self.send_json({"error": refused or "that was not valid JSON"},
                                  403 if refused else 400)
        url = urlparse(self.path)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw or b"{}")
            if not isinstance(body, dict):
                raise ValueError
        except ValueError:
            return self.send_json({"error": "that was not valid JSON"}, 400)

        try:
            if url.path == "/api/update":
                out = update.download_and_apply(self.con)
                Handler.restart = True
                threading.Timer(1.0, self.server.shutdown).start()
                return self.send_json(out)
            if url.path == "/api/lang/seen":           # text the screens showed
                with db.tx(self.con):
                    new = lang.seen(self.con, body.get("keys"))
                return self.send_json({"new": new})
            if not url.path.startswith("/api/do/"):
                return self.send_json({"error": "no such endpoint"}, 404)
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
            problems.append(f"today's copy of the books could not be taken ({exc})")
        try:
            out["state"] = api.state(self.con, month=body.get("view_month"),
                                     on=body.get("view_on"),
                                     count_date=body.get("view_count"))
        except Exception as exc:                       # noqa: BLE001
            problems.append(f"the screen could not be brought up to date ({exc})")
        if problems:
            out["warning"] = "Saved, but " + " and ".join(problems) + "."
        return out


def free_port(port):
    with socket.socket() as s:
        try:
            s.bind((HOST, port))
            return True
        except OSError:
            return False


def serve(db_path=None, port=PORT, *, open_browser=True):
    con = db.connect(db_path or db.DEFAULT_DB)
    api.bootstrap(con)
    rep = db.integrity(con)
    if not rep["ok"]:
        print("The books will not be served:")
        for key in ("sqlite", "foreign_keys", "unbalanced"):
            if rep[key] and rep[key] != [{"integrity_check": "ok"}]:
                print(f"  {key}: {rep[key]}")
        raise SystemExit(2)
    try:
        backup.daily(con)
    except (db.LedgerError, OSError) as exc:
        print(f"  could not take today's backup: {exc}")

    while not free_port(port) and port < PORT + 20:
        port += 1
    Handler.db_path = con.path
    Handler.restart = False
    srv = ThreadingHTTPServer((HOST, port), Handler)
    auto.start(con.path)         # SambaPOS's backups, read by themselves
    url = f"http://{HOST}:{port}/"
    print(f"Twilight Ledger {update.current()} — {con.path}")
    print(f"  {rep['entries']} entries, {rep['postings']} postings, balanced")
    print(f"  open {url}")
    print("  press Ctrl+C to stop")
    if open_browser and not os.environ.get("TWILIGHT_RESTARTED"):
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n  stopped")
    finally:
        srv.server_close()
        con.close()
    if Handler.restart:
        print("  updated — starting again")
        return RESTART
    return 0
