"""Request validation: a bad request must fail fast (exit 2, status error)
without opening a window. Runs bin/anumati as a subprocess."""
import json
import os
import subprocess
import sys
import unittest

BIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bin", "anumati")


def run(request):
    env = {k: v for k, v in os.environ.items() if k not in ("WAYLAND_DISPLAY", "DISPLAY")}
    r = subprocess.run([sys.executable, BIN], input=json.dumps(request) if not isinstance(request, str) else request,
                       capture_output=True, text=True, timeout=20, env=env)
    return r.returncode, json.loads(r.stdout)


class Validation(unittest.TestCase):
    def assertRejected(self, request, words):
        code, out = run(request)
        self.assertEqual(code, 2, out)
        self.assertEqual(out["status"], "error")
        self.assertIn(words, out["message"])

    def test_needs_why(self):
        self.assertRejected({"commands": [{"cmd": "id"}]}, "needs a 'why'")

    def test_no_commands(self):
        self.assertRejected({"commands": []}, "command")

    def test_hidden_characters(self):
        self.assertRejected({"commands": [{"cmd": "echo ‮ hi", "why": "x"}]}, "invisible")
        self.assertRejected({"commands": [{"cmd": "echo hi", "why": "zero​width"}]}, "invisible")

    def test_too_many(self):
        self.assertRejected({"commands": [{"cmd": "true", "why": "x"}] * 51}, "50")

    def test_not_json(self):
        code, out = run("not json")
        self.assertEqual(code, 2)
        self.assertEqual(out["status"], "error")


class Interface(unittest.TestCase):
    def test_schema(self):
        r = subprocess.run([sys.executable, BIN, "--schema"], capture_output=True, text=True, timeout=20)
        self.assertEqual(r.returncode, 0)
        self.assertIn("request", json.loads(r.stdout))

    def test_version(self):
        r = subprocess.run([sys.executable, BIN, "--version"], capture_output=True, text=True, timeout=20)
        self.assertRegex(r.stdout.strip(), r"^\d+\.\d+\.\d+$")


if __name__ == "__main__":
    unittest.main()
