"""Commands run as the user (lib/userrun.py): nothing the agent can set
adds code to what the window showed."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib"))
import userrun  # noqa: E402  (pure Python: no GTK needed, so CI runs it)


class Env(unittest.TestCase):
    def test_only_the_allowlist_gets_through(self):
        env = userrun.build_env({"HOME": "/x", "LANG": "C", "LC_ALL": "C", "BASH_ENV": "/tmp/evil",
                                 "ENV": "/tmp/evil", "LD_PRELOAD": "/tmp/evil.so", "SHELLOPTS": "xtrace",
                                 "BASH_FUNC_ls%%": "() { evil; }", "PROMPT_COMMAND": "evil"}, "/home/me")
        self.assertEqual(set(env), {"HOME", "USER", "LOGNAME", "SHELL", "LANG", "LC_ALL", "PATH", "TERM"})
        self.assertEqual(env["HOME"], "/home/me")

    def test_path_drops_relative_missing_and_world_writable(self):
        with tempfile.TemporaryDirectory() as d:
            ok, open_ = os.path.join(d, "ok"), os.path.join(d, "open")
            os.mkdir(ok, 0o755)
            os.mkdir(open_)
            os.chmod(open_, 0o777)
            path = userrun.safe_path(f"bin:{open_}:{ok}:/nonexistent:{ok}:/tmp", "/home/nobody")
            dirs = path.split(":")
            self.assertEqual(dirs[0], ok)
            self.assertEqual(dirs.count(ok), 1)
            for bad in ("bin", open_, "/nonexistent", "/tmp"):
                self.assertNotIn(bad, dirs)
            self.assertIn("/usr/bin", dirs)


class Run(unittest.TestCase):
    def test_runs_in_cwd_without_stdin(self):
        with tempfile.TemporaryDirectory() as d:
            r = userrun.run("pwd; cat; echo err >&2; exit 3", d, {"PATH": "/usr/bin"})
            self.assertEqual(r["exit_code"], 3)
            self.assertEqual(r["stdout"].strip(), os.path.realpath(d))
            self.assertEqual(r["stderr"].strip(), "err")
            self.assertFalse(r["timed_out"])

    def test_bash_env_is_not_sourced(self):
        with tempfile.TemporaryDirectory() as d:
            rc = os.path.join(d, "rc")
            with open(rc, "w") as f:
                f.write("echo injected\n")
            env = userrun.build_env({"BASH_ENV": rc, "PATH": "/usr/bin"}, d)
            r = userrun.run("echo shown", d, env)
            self.assertEqual(r["stdout"], "shown\n")

    def test_missing_directory_fails(self):
        r = userrun.run("true", "/nonexistent/dir", {"PATH": "/usr/bin"})
        self.assertEqual(r["exit_code"], 1)
        self.assertIn("no such directory", r["stderr"])

    def test_timeout(self):
        r = userrun.run("sleep 5", "/", {"PATH": "/usr/bin"}, timeout=0.3)
        self.assertTrue(r["timed_out"])
        self.assertEqual(r["exit_code"], 124)

    def test_output_is_capped(self):
        r = userrun.run(f"head -c {userrun.MAX_OUTPUT + 10} /dev/zero", "/", {"PATH": "/usr/bin"})
        self.assertTrue(r["truncated"])
        self.assertEqual(len(r["stdout"]), userrun.MAX_OUTPUT)


if __name__ == "__main__":
    unittest.main()
