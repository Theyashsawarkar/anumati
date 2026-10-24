"""The window's theme: the user's varna colours, but only when every text
stays clearly readable. palette.json is a file any process of the user (an
agent too) can write, so a palette that would hide or fake anything must
be ignored, whole."""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib"))
import gi  # noqa: E402

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
import dialog  # noqa: E402

ROSE_PINE = {"base": "#191724", "crust": "#111019", "text": "#e0def4", "subtext1": "#bcb8d6", "subtext0": "#908caa",
             "overlay2": "#908caa", "accent": "#c4a7e7", "green": "#9ccfd8", "ok": "#9ccfd8", "error": "#eb6f92",
             "red": "#eb6f92", "warn": "#f6c177", "yellow": "#f6c177"}


class Theme(unittest.TestCase):
    def home_with(self, colors, variant="dark", raw=None):
        home = tempfile.mkdtemp()
        d = os.path.join(home, ".local/state/varna")
        os.makedirs(d)
        with open(os.path.join(d, "palette.json"), "w") as f:
            f.write(raw if raw is not None else json.dumps({"variant": variant, "colors": colors}))
        return home

    def test_a_readable_theme_is_used(self):
        t = dialog.theme(self.home_with(ROSE_PINE))
        self.assertEqual(t["accent"], "#c4a7e7")
        self.assertEqual(t["base"], "#191724")
        self.assertTrue(t["dark"])

    def test_no_palette_is_the_fallback(self):
        self.assertIs(dialog.theme(tempfile.mkdtemp()), dialog.FALLBACK)

    def test_invisible_text_is_refused(self):
        # An agent writes text = background: the command would vanish.
        self.assertIs(dialog.theme(self.home_with(dict(ROSE_PINE, text="#191724"))), dialog.FALLBACK)
        self.assertIs(dialog.theme(self.home_with(dict(ROSE_PINE, text="#2a2838"))), dialog.FALLBACK)

    def test_a_faint_status_colour_becomes_the_text_colour(self):
        # A faint error (wrong password) or deny colour is replaced, never used.
        t = dialog.theme(self.home_with(dict(ROSE_PINE, error="#201e2c", warn="#1a1825")))
        self.assertIsNot(t, dialog.FALLBACK)
        self.assertEqual(t["error"], t["text"])
        self.assertEqual(t["warn"], t["text"])

    def test_every_colour_in_use_is_readable(self):
        t = dialog.theme(self.home_with(ROSE_PINE))
        self.assertGreaterEqual(dialog.contrast(t["text"], t["base"]), 4.5)
        self.assertGreaterEqual(dialog.contrast(t["code"], t["crust"]), 7)
        for role in ("subtext", "error", "warn", "ok"):
            self.assertGreaterEqual(dialog.contrast(t[role], t["base"]), 4.5, role)
        self.assertGreaterEqual(dialog.contrast(t["on_accent"], t["accent"]), 4.5)

    def test_a_run_button_without_readable_label_is_refused(self):
        self.assertIs(dialog.theme(self.home_with(dict(ROSE_PINE, accent="#191724"))), dialog.FALLBACK)

    def test_only_plain_hex_colours(self):
        for bad in ("#c4a7e7; } window { opacity: 0", "red", "#c4a7e780", "#zzzzzz", 7):
            with self.subTest(bad=bad):
                self.assertIs(dialog.theme(self.home_with(dict(ROSE_PINE, accent=bad))), dialog.FALLBACK)

    def test_garbage_or_huge_files_are_ignored(self):
        self.assertIs(dialog.theme(self.home_with({}, raw="{not json")), dialog.FALLBACK)
        self.assertIs(dialog.theme(self.home_with({}, raw=" " * 70000)), dialog.FALLBACK)

    def test_low_contrast_code_colour_falls_back_to_text(self):
        t = dialog.theme(self.home_with(dict(ROSE_PINE, green="#3e8f4f")))
        self.assertIsNot(t, dialog.FALLBACK)
        self.assertEqual(t["code"], t["text"])

    def test_the_fallback_passes_its_own_checks(self):
        f = dialog.FALLBACK
        self.assertGreaterEqual(dialog.contrast(f["text"], f["base"]), 7)
        self.assertGreaterEqual(dialog.contrast(f["code"], f["crust"]), 7)
        self.assertGreaterEqual(dialog.contrast(f["crust"], f["accent"]), 4.5)


if __name__ == "__main__":
    unittest.main()
