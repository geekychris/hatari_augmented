#!/usr/bin/env python3
"""Tests for the ST DevBench against a fake agent API (stdlib only).

    python3 tools/devbench/test_devbench.py
"""
import json
import os
import socket
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import devbench  # noqa: E402


class FakeHatari(BaseHTTPRequestHandler):
    seen = []
    symbols_loaded = True

    def log_message(self, *a):
        pass

    def _reply(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(n) if n else b""
        FakeHatari.seen.append((self.command, self.path, body))
        if self.path.startswith("/screen"):
            out, ctype, code = b"\x89PNG fake", "image/png", 200
        elif self.path.startswith("/emu/quit"):
            out, ctype, code = b'{"ok":true}', "application/json", 200
        elif self.path.startswith("/debug/cmd"):
            cmd = urllib.parse.parse_qs(body.decode()).get("cmd", [""])[0]
            if cmd == "e TEXT":
                text = "= %11011000000011000 (bin), #110616 (dec), $1b018 (hex)\n"
            elif cmd == "symbols prg":
                FakeHatari.symbols_loaded = True
                text = "Reading symbols from program 'GAME.PRG' symbol table...\nLoaded 3 symbols."
            elif not FakeHatari.symbols_loaded:
                text = "0 CPU symbols (of 0) sorted by name.\n"
            elif cmd == "symbols name main":
                text = ("0x0002a152 T __main\n0x0002909e W _main\n0x0005d9e4 B _pdomain\n"
                        "3 CPU symbols (of 711) sorted by name.\n")
            else:
                text = "0x0001b0b8 T main\n1 CPU symbols (of 711) sorted by name.\n"
            out, ctype, code = json.dumps({"ok": True, "output": text}).encode(), "application/json", 200
        elif self.path.startswith("/debug/step"):
            out, ctype, code = b'{"ok":false,"error":"not stopped"}', "application/json", 409
        else:
            out, ctype, code = b'{"ok":true,"state":"running"}', "application/json", 200
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    do_GET = do_POST = do_DELETE = _reply


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class DevBenchTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        game = os.path.join(cls.tmp.name, "lander", "build")
        os.makedirs(game)
        open(os.path.join(game, "LANDER.PRG"), "wb").close()
        docs = os.path.join(cls.tmp.name, "lander", "docs")
        os.makedirs(docs)
        with open(os.path.join(docs, "title.png"), "wb") as f:
            f.write(b"\x89PNG lander")
        with open(os.path.join(cls.tmp.name, "lander", "README.md"), "w") as f:
            f.write("# Lander\n\nLand it gently.\n")
        # not in games.ini: a demo with a Makefile, shared code (.mk only), and assets
        demo = os.path.join(cls.tmp.name, "gemdemo")
        os.makedirs(demo)
        with open(os.path.join(demo, "Makefile"), "w") as f:
            f.write("OUT = build\nPRG = $(OUT)/GEMDEMO.PRG\nall: $(PRG)\n\t@echo built gemdemo\n")
        with open(os.path.join(demo, "README.md"), "w") as f:
            f.write("# GEMDEMO: a VDI showcase\n\n<img src=x>\n\nA small [GEM](http://x) program.\nTwo lines.\n\nMore.\n")
        menu = os.path.join(cls.tmp.name, "menu")
        os.makedirs(menu)
        with open(os.path.join(menu, "Makefile"), "w") as f:
            f.write("NAME = LAUNCHER\nMACHINE = ste\ninclude ../lib/port.mk\ndrive:\n\t@echo drive\n")
        os.makedirs(os.path.join(cls.tmp.name, "lib"))
        open(os.path.join(cls.tmp.name, "lib", "port.mk"), "w").close()
        os.makedirs(os.path.join(cls.tmp.name, "assets"))
        cls.ini = os.path.join(cls.tmp.name, "games.ini")
        with open(cls.ini, "w") as f:
            f.write("[launcher]\nport = 1\n\n[lander]\ntitle = Lander\ndir = lander\n"
                    "program = lander.prg\nmachine = ste\ndescription = Land it.\n\n"
                    "[unbuilt]\ntitle = Unbuilt\ndir = nope\nprogram = x.prg\nmachine = st\n")

    def start(self, hatari=True):
        hport = free_port()
        if hatari:
            fake = ThreadingHTTPServer(("127.0.0.1", hport), FakeHatari)
            threading.Thread(target=fake.serve_forever, daemon=True).start()
            self.addCleanup(fake.shutdown)
        bench = devbench.serve(0, hport, self.ini)
        threading.Thread(target=bench.serve_forever, daemon=True).start()
        self.addCleanup(bench.shutdown)
        self.base = "http://127.0.0.1:%d" % bench.server_address[1]
        FakeHatari.seen = []

    def call(self, method, path, body=None):
        req = urllib.request.Request(self.base + path, method=method,
                                     data=body.encode() if body is not None else None)
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, r.headers.get("Content-Type"), r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.headers.get("Content-Type"), e.read()

    def test_ui_health_and_projects(self):
        self.start()
        code, ctype, body = self.call("GET", "/")
        self.assertEqual(code, 200)
        self.assertIn(b"ST DevBench", body)
        health = json.loads(self.call("GET", "/api/health")[2])
        self.assertTrue(health["hatari"])
        games = [g for g in json.loads(self.call("GET", "/api/projects")[2]) if g["kind"] == "game"]
        self.assertEqual([(g["id"], g["built"], g["program"]) for g in games],
                         [("lander", True, "LANDER.PRG"), ("unbuilt", False, "X.PRG")])
        self.assertEqual(games[0]["description"], "Land it.")

    def test_proxies_the_agent_api(self):
        self.start()
        code, ctype, body = self.call("POST", "/api/hatari/input/key?key=ctrl%2Bz")
        self.assertEqual(code, 200)
        self.assertEqual(FakeHatari.seen[-1][:2], ("POST", "/input/key?key=ctrl%2Bz"))
        code, ctype, body = self.call("GET", "/api/hatari/screen")
        self.assertEqual((code, ctype, body), (200, "image/png", b"\x89PNG fake"))
        # the agent API's errors come through with their status
        code, _, body = self.call("POST", "/api/hatari/debug/step")
        self.assertEqual(code, 409)
        self.assertEqual(json.loads(body)["error"], "not stopped")
        code, _, _ = self.call("DELETE", "/api/hatari/debug/breakpoints?index=all")
        self.assertEqual((code, FakeHatari.seen[-1][0]), (200, "DELETE"))

    def test_hatari_not_running(self):
        self.start(hatari=False)
        self.assertFalse(json.loads(self.call("GET", "/api/health")[2])["hatari"])
        code, _, body = self.call("GET", "/api/hatari/status")
        self.assertEqual(code, 502)
        self.assertIn("isn't answering", json.loads(body)["error"])

    def test_symbols(self):
        self.start()
        code, _, body = self.call("GET", "/api/symbols?find=main")
        r = json.loads(body)
        self.assertEqual(code, 200)
        self.assertEqual(r["symbols"][1], {"addr": "0x0002909e", "type": "W", "name": "_main"})
        self.assertEqual((len(r["symbols"]), r["total"]), (3, 711))
        self.assertEqual(FakeHatari.seen[-1][2], b"cmd=symbols+name+main")
        # nothing loaded yet: "symbols prg" loads the running program's, then it asks again
        FakeHatari.symbols_loaded = False
        self.addCleanup(setattr, FakeHatari, "symbols_loaded", True)
        r = json.loads(self.call("GET", "/api/symbols")[2])
        self.assertEqual([c[2] for c in FakeHatari.seen[-3:]],
                         [b"cmd=symbols+name", b"cmd=symbols+prg", b"cmd=symbols+name"])
        self.assertEqual(r["symbols"], [{"addr": "0x0001b0b8", "type": "T", "name": "main"}])
        # no debugger commands smuggled in through find
        self.assertEqual(self.call("GET", "/api/symbols?find=x%3Bc")[0], 400)
        self.assertEqual(self.call("GET", "/api/symbols?find=a+b")[0], 400)

    def test_symbols_of_the_running_program(self):
        # a game started from here: its PRG's symbols (gst2ascii), moved to TEXT
        tool = os.path.join(self.tmp.name, "gst2ascii")
        with open(tool, "w") as f:
            f.write("#!/bin/sh\necho 'Reading symbols...' >&2\n"
                    "printf '0x0000162e T game_update\\n0x00027000 B score\\n0x00000000 T _start\\n'\n")
        os.chmod(tool, 0o755)
        old = devbench.GST2ASCII
        devbench.GST2ASCII = tool
        self.addCleanup(setattr, devbench, "GST2ASCII", old)
        self.start()
        devbench.Handler.bench.playing = "lander"
        r = json.loads(self.call("GET", "/api/symbols?find=game")[2])
        self.assertEqual(r["source"], "prg")
        self.assertEqual(r["symbols"], [{"addr": "0x0001c646", "type": "T", "name": "game_update"}])
        self.assertEqual(r["total"], 3)
        r = json.loads(self.call("GET", "/api/symbols")[2])
        self.assertEqual([x["name"] for x in r["symbols"]], ["_start", "game_update", "score"])
        self.assertEqual(r["symbols"][2]["addr"], "0x00042018")

    def test_symbols_without_hatari(self):
        self.start(hatari=False)
        self.assertEqual(self.call("GET", "/api/symbols?find=main")[0], 502)

    def test_errors(self):
        self.start()
        self.assertEqual(self.call("POST", "/api/projects/nosuch/build")[0], 404)
        self.assertEqual(self.call("POST", "/api/hatari/start", '{"machine": "c64"}')[0], 400)
        self.assertEqual(self.call("GET", "/nope")[0], 404)



class ArcadeTest(DevBenchTest):
    """The arcade and project discovery: every directory, pictures, play."""

    def setUp(self):
        # the games and Hatari are found; nothing is really built or started
        self.calls = []
        tc = {"hatari": "/bin/hatari", "cross": "x-", "cross_ok": True, "games_dir": self.tmp.name}
        patches = [
            (devbench.Bench, "toolchain", lambda b, lr=None: tc),
            (devbench.games.Launcher, "play",
             lambda lr, g, build=None, log=print: (self.calls.append(("play", g.id, g.build_dir)), log("started"))),
            (devbench.games.Launcher, "make",
             lambda lr, g, log=print: (self.calls.append(("make", g.id)), log("made"))),
        ]
        real_exists = os.path.exists
        patches.append((devbench.os.path, "exists",
                        lambda p: True if p.endswith((".img",)) else real_exists(p)))
        for obj, name, fn in patches:
            old = getattr(obj, name)
            setattr(obj, name, fn)
            self.addCleanup(setattr, obj, name, old)

    def test_projects_cover_every_directory(self):
        self.start()
        ps = {p["id"]: p for p in json.loads(self.call("GET", "/api/projects")[2])}
        self.assertEqual(sorted(ps), ["gemdemo", "lander", "lib", "menu", "unbuilt"])   # not assets
        self.assertEqual(ps["gemdemo"]["kind"], "demo")
        self.assertEqual(ps["gemdemo"]["program"], "GEMDEMO.PRG")
        self.assertEqual(ps["gemdemo"]["title"], "GEMDEMO: a VDI showcase")
        self.assertEqual(ps["gemdemo"]["description"], "A small GEM program. Two lines.")
        self.assertEqual((ps["menu"]["program"], ps["menu"]["machine"]), ("LAUNCHER.PRG", "ste"))
        self.assertEqual(ps["menu"]["reason"], "not built yet: Play runs make drive first")
        self.assertEqual((ps["lib"]["kind"], ps["lib"]["playable"]), ("library", False))
        self.assertIn("shared code", ps["lib"]["reason"])
        self.assertTrue(ps["lander"]["playable"])
        self.assertEqual(ps["lander"]["reason"], "")
        self.assertEqual(ps["unbuilt"]["reason"], "not built yet: Play runs make first")
        self.assertEqual(ps["lander"]["picture"], "/api/projects/lander/picture")
        self.assertIsNone(ps["unbuilt"]["picture"])

    def test_reasons_when_tools_are_missing(self):
        devbench.Bench.toolchain = lambda b, lr=None: {"hatari": "/bin/hatari", "cross": "x-",
                                                       "cross_ok": False, "games_dir": self.tmp.name}
        self.start()
        ps = {p["id"]: p for p in json.loads(self.call("GET", "/api/projects")[2])}
        self.assertTrue(ps["lander"]["playable"])           # built: no compiler needed
        self.assertFalse(ps["unbuilt"]["playable"])
        self.assertIn("cross compiler", ps["unbuilt"]["reason"])
        devbench.Bench.toolchain = lambda b, lr=None: {"hatari": None, "cross": "x-",
                                                       "cross_ok": True, "games_dir": self.tmp.name}
        ps = {p["id"]: p for p in json.loads(self.call("GET", "/api/projects")[2])}
        self.assertFalse(ps["lander"]["playable"])
        self.assertIn("Hatari isn't built", ps["lander"]["reason"])

    def test_arcade_lists_only_games(self):
        self.start()
        a = json.loads(self.call("GET", "/api/arcade")[2])
        self.assertTrue(a["ok"])
        self.assertEqual([g["id"] for g in a["games"]], ["lander", "unbuilt"])
        code, ctype, body = self.call("GET", "/arcade")
        self.assertEqual(code, 200)
        self.assertIn(b"ST Arcade", body)
        code, ctype, body = self.call("GET", "/keys.js")
        self.assertEqual((code, ctype.split(";")[0]), (200, "text/javascript"))
        self.assertEqual(self.call("GET", "/devbench.py")[0], 404)
        self.assertEqual(self.call("GET", "/../README.md")[0], 404)

    def test_picture_and_readme(self):
        self.start()
        code, ctype, body = self.call("GET", "/api/projects/lander/picture")
        self.assertEqual((code, ctype, body), (200, "image/png", b"\x89PNG lander"))
        self.assertEqual(self.call("GET", "/api/projects/unbuilt/picture")[0], 404)
        code, ctype, body = self.call("GET", "/api/projects/lander/readme")
        self.assertEqual((code, body), (200, b"# Lander\n\nLand it gently.\n"))
        self.assertEqual(self.call("GET", "/api/projects/unbuilt/readme")[0], 404)
        self.assertEqual(self.call("GET", "/api/projects/nosuch/picture")[0], 404)

    def test_play_builds_then_runs(self):
        self.start()
        r = json.loads(self.call("POST", "/api/arcade/play", '{"game": "lander"}')[2])
        self.assertTrue(r["ok"], r)
        self.assertEqual(self.calls[0], ("make", "lander"))
        self.assertEqual(self.calls[1][:2], ("play", "lander"))
        self.assertEqual(json.loads(self.call("GET", "/api/arcade")[2])["playing"], "lander")
        self.assertEqual(json.loads(self.call("GET", "/api/health")[2])["playing"], "lander")
        self.calls.clear()
        r = json.loads(self.call("POST", "/api/arcade/play", '{"game": "lander", "build": false}')[2])
        self.assertEqual([c[0] for c in self.calls], ["play"])
        self.assertEqual(self.call("POST", "/api/arcade/play", "{}")[0], 400)
        self.assertEqual(self.call("POST", "/api/arcade/play", '{"game": "nosuch"}')[0], 404)

    def test_demo_runs_from_its_drive(self):
        self.start()
        # the menu's C: is build/drive, made by "make drive" (stubbed: no make is run)
        real = devbench.subprocess.run
        seen = []

        def fake_run(cmd, cwd=None, **kw):
            seen.append((cmd, cwd))
            return devbench.subprocess.CompletedProcess(cmd, 0, "ok")
        devbench.subprocess.run = fake_run
        self.addCleanup(setattr, devbench.subprocess, "run", real)
        r = json.loads(self.call("POST", "/api/projects/menu/run")[2])
        self.assertTrue(r["ok"], r)
        self.assertEqual((seen[0][0][0], seen[0][0][-1], seen[0][1]), ("make", "drive", os.path.join(self.tmp.name, "menu")))
        self.assertTrue(self.calls[-1][2].endswith(os.path.join("menu", "build", "drive")))
        # shared code can't be built or run on its own
        self.assertEqual(self.call("POST", "/api/projects/lib/run")[0], 400)
        self.assertEqual(self.call("POST", "/api/projects/lib/build")[0], 400)


if __name__ == "__main__":
    unittest.main()
