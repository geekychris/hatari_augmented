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
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import devbench  # noqa: E402


class FakeHatari(BaseHTTPRequestHandler):
    seen = []

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
        games = json.loads(self.call("GET", "/api/projects")[2])
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

    def test_errors(self):
        self.start()
        self.assertEqual(self.call("POST", "/api/projects/nosuch/build")[0], 404)
        self.assertEqual(self.call("POST", "/api/hatari/start", '{"machine": "c64"}')[0], 400)
        self.assertEqual(self.call("GET", "/nope")[0], 404)


if __name__ == "__main__":
    unittest.main()
