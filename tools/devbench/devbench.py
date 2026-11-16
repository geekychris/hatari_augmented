#!/usr/bin/env python3
"""ST DevBench: a web workbench for Hatari's agent API, and the Atari game
ports (geekychris/atari_st_games) built and run from it.

    tools/devbench/run.sh [--port 3520] [--hatari-port 7777] [--games DIR] [--open]

    /                                   dev page: screen, input, console, debugger, memory, snapshots
    /arcade                             the arcade: every game with picture, description,
                                        controls, Build and Play, and the running game live
    /api/health                         {"ok", "hatari": running?, toolchain checks, ...}
    /api/projects                       every project: the games in games.ini, then the other
                                        directories (demos, shared libraries), each with
                                        whether it's built, whether it can run, and why not
    /api/projects/{id}/build   POST     make in the project's directory
    /api/projects/{id}/run     POST     build if needed, then Hatari with the program autostarted
    /api/projects/{id}/picture          the game's screenshot (PNG)
    /api/projects/{id}/readme           its README.md
    /api/arcade                         {"games": [...]}: the projects that are games
    /api/arcade/play           POST     {"game": id, "build": true}: same as .../run
    /api/symbols?find=X                 the CPU symbols whose name contains X (Hatari debugger
                                        "symbols name X"): {"symbols": [{"addr", "type", "name"}]}
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
import re
import shutil
import subprocess
import sys
import threading
import urllib.error
import urllib.parse
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
GST2ASCII = os.path.join(REPO, "build", "tools", "debugger", "gst2ascii")   # PRG symbols -> nm format
HATARI_BINS = ("build/src/Hatari.app/Contents/MacOS/Hatari", "build/src/hatari")
STATIC = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
          ".css": "text/css; charset=utf-8"}


def readme_summary(path):
    """The first paragraph of prose in a README.md (not its title, images or badges)."""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            text = f.read()
    except OSError:
        return ""
    para = []
    for line in text.splitlines():
        t = line.strip()
        if not t:
            if para:
                break
            continue
        if t.startswith(("#", "<", "![", "[![", "```", "|", "---")):
            if para:
                break
            continue
        para.append(t)
    out = " ".join(para)
    out = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", out)   # [text](link) -> text
    return out.replace("`", "")


def readme_title(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                if line.startswith("# "):
                    return line[2:].strip()
    except OSError:
        pass
    return ""


class Extra(games.Game):
    """A project directory that isn't in games.ini: a demo or tool with a Makefile."""

    def __init__(self, gid, d, program, machine, drive):
        super().__init__(gid, {"title": gid, "dir": d, "program": program or "?",
                               "machine": machine}, "/")
        self.has_program = bool(program)
        self.drive = drive      # C: is build/drive, made by "make drive" (st_launcher)
        self.description = readme_summary(os.path.join(d, "README.md"))
        self.title = readme_title(os.path.join(d, "README.md")) or gid

    @property
    def build_dir(self):
        return os.path.join(self.dir, "build", "drive") if self.drive else os.path.join(self.dir, "build")


def scan_makefile(d):
    """(program, machine, has drive target) from a project's Makefile."""
    try:
        with open(os.path.join(d, "Makefile"), encoding="utf-8", errors="replace") as f:
            mk = f.read()
    except OSError:
        return None, "st", False
    prog = None
    m = re.search(r"^PRG\s*[:?]?=.*?([A-Za-z0-9_]+\.PRG)\s*$", mk, re.M | re.I)
    if m:
        prog = m.group(1).upper()
    else:
        m = re.search(r"^NAME\s*[:?]?=\s*(\w+)", mk, re.M)
        if m:
            prog = m.group(1).upper() + ".PRG"
    m = re.search(r"^MACHINE\s*[:?]?=\s*(\w+)", mk, re.M)
    machine = m.group(1).lower() if m else "st"
    return prog, machine, bool(re.search(r"^drive\s*:", mk, re.M))


class Bench:
    def __init__(self, hatari_port, ini):
        self.port = hatari_port
        self.ini = ini
        # one build or start at a time; agent API calls go straight through
        self.lock = threading.Lock()
        self.playing = None     # the project last started from here

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

    def games_dir(self):
        return os.path.dirname(os.path.abspath(self.ini))

    def hatari_bin(self):
        for h in [os.environ.get("HATARI", "")] + [os.path.join(REPO, b) for b in HATARI_BINS]:
            if h and os.access(h, os.X_OK):
                return h
        return shutil.which("hatari")

    def toolchain(self, lr=None):
        lr = lr or self.launcher()
        gcc = lr.cross + "gcc"
        return {"hatari": self.hatari_bin(), "cross": lr.cross,
                "cross_ok": bool(os.access(gcc, os.X_OK) or shutil.which(gcc)),
                "games_dir": self.games_dir()}

    def all_projects(self):
        """[(game, kind)]: the games.ini games, then the other directories."""
        lr = self.launcher()
        out = [(g, "game") for g in lr.games]
        listed = {os.path.normpath(g.dir) for g in lr.games}
        base = self.games_dir()
        for name in sorted(os.listdir(base)):
            d = os.path.join(base, name)
            if name.startswith(".") or not os.path.isdir(d) or os.path.normpath(d) in listed:
                continue
            has_mk = os.path.exists(os.path.join(d, "Makefile"))
            if not has_mk and not any(f.endswith(".mk") for f in os.listdir(d)):
                continue        # assets, dist, tools: not projects
            prog, machine, drive = scan_makefile(d) if has_mk else (None, "st", False)
            e = Extra(name, d, prog, machine if machine in MACHINES else "st", drive)
            e.make_target = "drive" if drive else None
            out.append((e, "demo" if has_mk and prog else "library"))
        return lr, out

    def find(self, gid):
        lr, ps = self.all_projects()
        for g, kind in ps:
            if g.id == gid or g.title.lower() == gid.lower():
                return lr, g, kind
        raise KeyError(gid)

    def picture(self, g):
        if g.screenshot and os.path.exists(g.screenshot):
            return g.screenshot
        docs = os.path.join(g.dir, "docs")
        for name in ("title.png", "play.png"):
            if os.path.exists(os.path.join(docs, name)):
                return os.path.join(docs, name)
        try:
            pngs = sorted(f for f in os.listdir(docs) if f.lower().endswith(".png"))
        except OSError:
            pngs = []
        return os.path.join(docs, pngs[0]) if pngs else None

    def describe(self, g, kind, tc):
        prg = os.path.join(g.build_dir, g.program)
        built = kind != "library" and os.path.exists(prg)
        playable, reason = True, ""
        if kind == "library":
            playable, reason = False, "shared code for the other ports, not a program"
        elif not tc["hatari"]:
            playable, reason = False, "Hatari isn't built (see the hatari_augmented README)"
        elif not os.path.exists(g.tos):
            playable, reason = False, "TOS image %s missing: run tools/agent/fetch-emutos.sh" % os.path.relpath(g.tos, REPO)
        elif not built and not tc["cross_ok"]:
            playable, reason = False, "not built, and the cross compiler (%sgcc) isn't installed: tools/agent/fetch-cross-mint.sh" % tc["cross"]
        elif not built:
            reason = "not built yet: Play runs %s first" % " ".join(["make"] + [t for t in [getattr(g, "make_target", None)] if t])
        pic = self.picture(g)
        rd = os.path.join(g.dir, "README.md")
        return {"id": g.id, "title": g.title, "kind": kind, "machine": g.machine,
                "machine_name": g.machine_name, "program": g.program,
                "dir": g.dir, "built": built, "playable": playable, "reason": reason,
                "description": g.description, "controls": g.controls,
                "picture": "/api/projects/%s/picture" % g.id if pic else None,
                "readme": "/api/projects/%s/readme" % g.id if os.path.exists(rd) else None}

    def projects(self):
        lr, ps = self.all_projects()
        tc = self.toolchain(lr)
        return [self.describe(g, kind, tc) for g, kind in ps]

    def _logged(self, fn):
        lines = []
        with self.lock:
            try:
                fn(lines.append)
                return {"ok": True, "output": "\n".join(lines)}
            except (RuntimeError, OSError, subprocess.SubprocessError) as e:
                lines.append(str(e))
                return {"ok": False, "output": "\n".join(lines)}

    def make(self, lr, g, log):
        target = getattr(g, "make_target", None)
        if target is None and not isinstance(g, Extra):
            return lr.make(g, log)
        log("Building %s (make %sin %s)..." % (g.title, (target + " ") if target else "", g.dir))
        p = subprocess.run(["make", "CROSS=" + lr.cross] + ([target] if target else []), cwd=g.dir,
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        if p.returncode:
            log(p.stdout[-2000:])
            raise RuntimeError("build of %s failed" % g.title)

    def build(self, gid):
        lr, g, kind = self.find(gid)
        if kind == "library":
            raise ValueError("%s is shared code; build a game that uses it" % gid)
        return self._logged(lambda log: self.make(lr, g, log))

    def run(self, gid, build=True):
        lr, g, kind = self.find(gid)
        if kind == "library":
            raise ValueError("%s is shared code, not a program" % gid)

        def go(log):
            if build:
                self.make(lr, g, log)
            lr.play(g, build=False, log=log)
            self.playing = g.id
        return self._logged(go)

    def start(self, machine):
        if machine not in MACHINES:
            raise ValueError("machine: one of " + ", ".join(MACHINES))

        def go(log):
            if not self.launcher().stop(log):
                raise RuntimeError("could not stop the Hatari already running")
            self.playing = None
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

    SYM_LINE = re.compile(r"^(0x[0-9a-fA-F]+)\s+(\S)\s+(\S.*)$")
    SYM_COUNT = re.compile(r"(\d+) CPU symbols \(of (\d+)\)")

    def debug_cmd(self, cmd):
        status, _, out = self.agent("POST", "/debug/cmd", urllib.parse.urlencode({"cmd": cmd}).encode())
        d = json.loads(out)
        if status != 200:
            raise RuntimeError(d.get("error", "debugger error %d" % status))
        return d.get("output", "")

    def program_symbols(self):
        """[(addr, type, name)] of the program started from here, read from its PRG with
        gst2ascii and moved to where it's loaded (the debugger's TEXT); None when that
        isn't possible. The debugger's own listing pages after a screenful."""
        if not self.playing:
            return None
        try:
            _, g, _ = self.find(self.playing)
        except (KeyError, OSError):
            return None
        prg = os.path.join(g.build_dir, g.program)
        tool = GST2ASCII
        if not (os.path.exists(prg) and os.access(tool, os.X_OK)):
            return None
        m = re.search(r"\$([0-9a-fA-F]+) \(hex\)", self.debug_cmd("e TEXT"))
        if not m:
            return None
        text = int(m.group(1), 16)
        key = (prg, os.path.getmtime(prg))
        if getattr(self, "_symcache", (None,))[0] != key:
            p = subprocess.run([tool, prg], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
            rel = []
            for line in p.stdout.splitlines():
                f = line.split(None, 2)
                if len(f) == 3 and f[0].startswith("0x"):
                    rel.append((int(f[0], 16), f[1], f[2]))
            self._symcache = (key, rel)
        return [(text + a, t, n) for a, t, n in self._symcache[1]]

    def symbols(self, find=""):
        """Symbols containing find: the running program's (from its PRG), else whatever the
        Hatari debugger has loaded ("symbols prg" loads the program's if nothing is)."""
        prog = self.program_symbols()
        if prog is not None:
            syms = sorted(({"addr": "0x%08x" % a, "type": t, "name": n} for a, t, n in prog if find in n),
                          key=lambda x: x["name"])
            return {"ok": True, "symbols": syms, "total": len(prog), "more": False, "source": "prg"}

        def ask():
            status, _, out = self.agent("POST", "/debug/cmd", urllib.parse.urlencode(
                {"cmd": ("symbols name " + find).strip()}).encode())
            if status != 200:
                raise RuntimeError(json.loads(out).get("error", "debugger error %d" % status))
            return json.loads(out).get("output", "")
        text = ask()
        loaded = None
        if "symbols" not in text or "no symbols" in text.lower() or "(of 0)" in text:
            _, _, out = self.agent("POST", "/debug/cmd", b"cmd=symbols+prg")
            loaded = json.loads(out).get("output", "").strip()
            text = ask()
        syms = []
        for line in text.splitlines():
            m = self.SYM_LINE.match(line.strip())
            if m:
                syms.append({"addr": m.group(1), "type": m.group(2), "name": m.group(3)})
        m = self.SYM_COUNT.search(text)
        res = {"ok": True, "symbols": syms, "total": int(m.group(2)) if m else len(syms),
               "more": "q to exit" in text, "source": "debugger"}
        if not syms and loaded:
            res["note"] = loaded.splitlines()[-1]
        return res

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
            page = {"/": "index.html", "/arcade": "arcade.html"}.get(url.path, url.path[1:])
            if method == "GET" and "/" not in page and os.path.splitext(page)[1] in STATIC \
                    and os.path.exists(os.path.join(WEB, page)):
                with open(os.path.join(WEB, page), "rb") as f:
                    return self.send(200, f.read(), STATIC[os.path.splitext(page)[1]])
            if parts[:1] != ["api"]:
                return self.error(404, "not found")
            rest = parts[1:]
            if rest == ["health"] and method == "GET":
                up = b.running()
                return self.send(200, {"ok": True, "hatari": up, "hatari_port": b.port,
                                       "playing": b.playing if up else None,
                                       "games_ini": b.ini, "repo": REPO, "toolchain": b.toolchain()})
            if rest == ["projects"] and method == "GET":
                return self.send(200, b.projects())
            if rest == ["arcade"] and method == "GET":
                up = b.running()
                return self.send(200, {"ok": True, "hatari": up, "playing": b.playing if up else None,
                                       "games": [p for p in b.projects() if p["kind"] == "game"]})
            if rest == ["arcade", "play"] and method == "POST":
                a = self.json_body()
                if not a.get("game"):
                    raise ValueError('body: {"game": id}')
                return self.send(200, b.run(a["game"], build=a.get("build", True) is not False))
            if rest == ["symbols"] and method == "GET":
                q = urllib.parse.parse_qs(url.query)
                find = (q.get("find") or [""])[0].strip()
                if not re.fullmatch(r"[\w.$]*", find):
                    raise ValueError("find: a symbol name or part of one")
                try:
                    return self.send(200, b.symbols(find))
                except OSError as e:
                    return self.error(502, "Hatari isn't answering on port %d (%s)" % (b.port, getattr(e, "reason", e)))
                except RuntimeError as e:
                    return self.error(409, str(e))
            if len(rest) == 3 and rest[0] == "projects" and method == "GET" and rest[2] in ("picture", "readme"):
                _, g, _ = b.find(rest[1])
                if rest[2] == "picture":
                    pic = b.picture(g)
                    if not pic:
                        return self.error(404, "%s has no picture" % rest[1])
                    with open(pic, "rb") as f:
                        return self.send(200, f.read(), "image/png")
                with open(os.path.join(g.dir, "README.md"), "rb") as f:
                    return self.send(200, f.read(), "text/markdown; charset=utf-8")
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
            if e.filename and not str(e.filename).endswith(".ini"):
                return self.error(404, "not found: %s" % os.path.basename(e.filename))
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
    ap.add_argument("--games", help="the atari_st_games checkout (default: $ATARI_GAMES_DIR, "
                    "else ../atari_st_games next to this repository)")
    ap.add_argument("--ini", default=games.DEFAULT_INI, help="games.ini (default: %(default)s)")
    ap.add_argument("--open", action="store_true", help="open the browser")
    a = ap.parse_args()
    if a.games:
        a.ini = os.path.join(os.path.abspath(os.path.expanduser(a.games)), "games.ini")
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
