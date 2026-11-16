#!/usr/bin/env python3
"""ST DevBench: a web workbench for Hatari's agent API, and the Atari game
ports (geekychris/atari_st_games) built and run from it.

    python3 tools/devbench/devbench.py [--port 3520] [--hatari-port 7777] [--open]

    /                                   web UI: screen, input, console, debugger, memory, snapshots
    /api/health                         {"ok", "hatari": running?, ...}
    /api/projects                       games from games.ini, with whether each is built
    /api/projects/{id}/build   POST     make in the game's directory
    /api/projects/{id}/run     POST     build if needed, then Hatari with the game autostarted
    /api/hatari/start          POST     {"machine": "ste"}: Hatari at the EmuTOS desktop
    /api/hatari/stop           POST     quit the Hatari on the agent port
    /api/hatari/<path>                  passed to the agent API (doc/agent-api.md), e.g.
                                        GET /api/hatari/status, POST /api/hatari/debug/step

Hatari keeps running when the DevBench stops only if it was started outside
it; one the DevBench started is in its process group.

Only needs the Python standard library.
"""
import argparse
import json
import os
import subprocess
import sys
import threading
import urllib.error
import urllib.request
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
WEB = os.path.join(HERE, "web")
sys.path.insert(0, os.path.join(REPO, "tools", "games"))
import launcher as games  # noqa: E402  (tools/games/launcher.py)

RUN_SCRIPT = games.RUN_SCRIPT
DESKTOP_TOS = os.path.join(REPO, games.DEFAULT_TOS["other"])
MACHINES = ("st", "megast", "ste", "megaste", "tt", "falcon")


class Bench:
    def __init__(self, hatari_port, ini):
        self.port = hatari_port
        self.ini = ini
        # one build or start at a time; agent API calls go straight through
        self.lock = threading.Lock()

    def launcher(self):
        lr = games.Launcher(self.ini)
        lr.port = self.port
        return lr

    def agent(self, method, path, body=None, ctype=None, timeout=60):
        """(status, content-type, bytes) from the agent API."""
        req = urllib.request.Request("http://127.0.0.1:%d%s" % (self.port, path),
                                     data=body, method=method)
        if body is not None:
            req.add_header("Content-Type", ctype or "application/x-www-form-urlencoded")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.status, r.headers.get("Content-Type", "application/json"), r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.headers.get("Content-Type", "application/json"), e.read()

    def running(self):
        try:
            self.agent("GET", "/status", timeout=1.5)
            return True
        except OSError:
            return False

    def projects(self):
        out = []
        for g in self.launcher().games:
            prg = os.path.join(g.build_dir, g.program)
            out.append({"id": g.id, "title": g.title, "machine": g.machine,
                        "machine_name": g.machine_name, "program": g.program,
                        "dir": g.dir, "built": os.path.exists(prg),
                        "description": g.description, "controls": g.controls})
        return out

    def _logged(self, fn):
        lines = []
        with self.lock:
            try:
                fn(lines.append)
                return {"ok": True, "output": "\n".join(lines)}
            except (RuntimeError, OSError, subprocess.SubprocessError) as e:
                lines.append(str(e))
                return {"ok": False, "output": "\n".join(lines)}

    def build(self, gid):
        lr = self.launcher()
        g = lr.find(gid)
        return self._logged(lambda log: lr.make(g, log))

    def run(self, gid, build=True):
        lr = self.launcher()
        g = lr.find(gid)
        return self._logged(lambda log: lr.play(g, build=build, log=log))

    def start(self, machine):
        if machine not in MACHINES:
            raise ValueError("machine: one of " + ", ".join(MACHINES))

        def go(log):
            if not self.launcher().stop(log):
                raise RuntimeError("could not stop the Hatari already running")
            env = dict(os.environ, AGENT_PORT=str(self.port))
            if os.path.exists(DESKTOP_TOS):
                env["AGENT_TOS"] = DESKTOP_TOS
            p = subprocess.run([RUN_SCRIPT, "--machine", machine, "--conout", "2",
                                "--natfeats", "on"], env=env, text=True,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            log(p.stdout.strip())
            if p.returncode:
                raise RuntimeError("Hatari did not start")
        return self._logged(go)

    def stop(self):
        def go(log):
            if not self.launcher().stop(log):
                raise RuntimeError("Hatari did not quit")
            log("Hatari stopped")
        return self._logged(go)


class Handler(BaseHTTPRequestHandler):
    bench = None  # set by serve()
    server_version = "STDevBench"

    def log_message(self, fmt, *args):
        pass

    def send(self, status, body, ctype="application/json"):
        if not isinstance(body, (bytes, bytearray)):
            body = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def error(self, status, msg):
        self.send(status, {"ok": False, "error": msg})

    def body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(n) if n else b""

    def json_body(self):
        b = self.body()
        if not b.strip():
            return {}
        d = json.loads(b)
        if not isinstance(d, dict):
            raise ValueError("body must be a JSON object")
        return d

    def do_GET(self):
        self.route("GET")

    def do_POST(self):
        self.route("POST")

    def do_DELETE(self):
        self.route("DELETE")

    def route(self, method):
        b = self.bench
        url = urlsplit(self.path)
        parts = [p for p in url.path.split("/") if p]
        try:
            if method == "GET" and url.path in ("/", "/index.html"):
                with open(os.path.join(WEB, "index.html"), "rb") as f:
                    return self.send(200, f.read(), "text/html; charset=utf-8")
            if parts[:1] != ["api"]:
                return self.error(404, "not found")
            rest = parts[1:]
            if rest == ["health"] and method == "GET":
                return self.send(200, {"ok": True, "hatari": b.running(), "hatari_port": b.port,
                                       "games_ini": b.ini, "repo": REPO})
            if rest == ["projects"] and method == "GET":
                return self.send(200, b.projects())
            if len(rest) == 3 and rest[0] == "projects" and method == "POST":
                gid, action = rest[1], rest[2]
                if action == "build":
                    return self.send(200, b.build(gid))
                if action == "run":
                    a = self.json_body()
                    return self.send(200, b.run(gid, build=a.get("build", True) is not False))
            if rest == ["hatari", "start"] and method == "POST":
                return self.send(200, b.start(self.json_body().get("machine", "ste")))
            if rest == ["hatari", "stop"] and method == "POST":
                return self.send(200, b.stop())
            if rest[:1] == ["hatari"] and len(rest) > 1:
                path = "/" + "/".join(rest[1:]) + ("?" + url.query if url.query else "")
                data = self.body() if method != "GET" else None
                try:
                    status, ctype, out = b.agent(method, path, data, self.headers.get("Content-Type"))
                except OSError as e:
                    return self.error(502, "Hatari isn't answering on port %d (%s): start it or run a game"
                                      % (b.port, getattr(e, "reason", e)))
                return self.send(status, out, ctype)
            return self.error(404, "not found")
        except KeyError as e:
            return self.error(404, "no game %s" % e)
        except (ValueError, json.JSONDecodeError) as e:
            return self.error(400, str(e))
        except FileNotFoundError as e:
            return self.error(500, "games.ini not found: %s (set ATARI_GAMES_DIR or --ini)" % e)


def serve(port, hatari_port, ini, host="127.0.0.1"):
    Handler.bench = Bench(hatari_port, ini)
    httpd = ThreadingHTTPServer((host, port), Handler)
    httpd.daemon_threads = True
    return httpd


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--port", type=int, default=3520)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--hatari-port", type=int, default=int(os.environ.get("AGENT_PORT", "7777")))
    ap.add_argument("--ini", default=games.DEFAULT_INI, help="games.ini (default: %(default)s)")
    ap.add_argument("--open", action="store_true", help="open the browser")
    a = ap.parse_args()
    httpd = serve(a.port, a.hatari_port, a.ini, a.host)
    url = "http://%s:%d/" % (a.host, a.port)
    print("ST DevBench on %s  (Hatari agent API on :%d)" % (url, a.hatari_port), flush=True)
    if a.open:
        threading.Timer(0.5, webbrowser.open, [url]).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
