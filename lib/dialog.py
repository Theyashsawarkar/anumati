#!/usr/bin/python3 -I
"""The anumati approval window: shows what an AI agent wants to run as
root and why, lets the user pick which commands to allow, takes the sudo
password once, runs the picked ones and writes the result for the agent.

Installed root-owned as /usr/local/lib/anumati/dialog.py by
anumati's install.sh, and started only by anumati, as a transient user service
(not a child of the agent, so the agent can't ptrace it) with a cleared
environment and XDG dirs pointing at root-owned directories (so no user
GTK CSS can hide a row). See ai/README.md for the threat model.

    dialog.py <request-dir>     reads request.json, writes result.json

Keys:
# keybind: Anumati/root approval | Esc | Cancel the root request (deny everything; closes the window after a run)
# keybind: Anumati/root approval | Enter (password field) | Run the selected commands as root
# keybind: Anumati/root approval | Space | Toggle the focused command
# keybind: Anumati/root approval | Enter (after a failed run) | Close the window
"""
import ctypes
import json
import os
import pwd
import subprocess
import sys
import threading
import time

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk, Pango  # noqa: E402

APP_ID = "io.github.theyashsawarkar.Anumati"
RUNNER = "/usr/local/lib/anumati/runner.py"
SUDO = "/usr/bin/sudo"
EXPIRES_AFTER = 600          # seconds the request stays open (then: denied)
MAX_ATTEMPTS = 3             # wrong passwords before the request fails
AUTO_CLOSE_MS = 1500         # after a fully successful run
STATE_LOG = os.path.join(pwd.getpwuid(os.getuid()).pw_dir, ".local/state/anumati/requests.jsonl")

# The look: Vyom's panels (github.com/Theyashsawarkar/vyom), so this window
# reads as part of the same desktop: a glass card, a mode pill in the top
# bar, rounded rows, key caps in the footer. Colours come from the user's
# varna theme only through theme() below, which accepts a palette only if
# every text stays clearly readable; anything else gets FALLBACK.
CSS = """
window.elevate {
  /* Glass like Vyom's panels, but never see-through enough to read what's
     behind (the compositor's blur does the rest): 0.84, where they're 0.55. */
  background-color: alpha(@base, 0.84);
  color: @text; font-family: "Inter", "Noto Sans", sans-serif; font-size: 13px;
}
.elevate .topbar { padding: 12px 16px; border-bottom: 1px solid alpha(@text, 0.06); }
.elevate .mode { padding: 5px 11px 5px 9px; border-radius: 10px; font-weight: 600; font-size: 12.5px;
  background-color: alpha(@error, 0.15); color: @error; }
.elevate .glyph { font-family: "JetBrainsMono Nerd Font", monospace; font-size: 15px; }
.elevate .title { font-size: 15px; font-weight: 600; color: @text; }
.elevate .requester { color: @accent; font-weight: 700; }
.elevate .body { padding: 14px 16px 6px 16px; }
.elevate .reason { color: @subtext; font-size: 13px; }
.elevate .section { color: @muted; font-size: 10.5px; font-weight: 700; letter-spacing: 1px; }
.elevate .cmd-card { background-color: alpha(@text, 0.05); border: 1px solid alpha(@accent, 0.18);
  border-radius: 12px; padding: 10px 12px; }
.elevate .cmd-card.declined { opacity: 0.5; }
.elevate .why { color: @text; font-weight: 600; font-size: 13.5px; }
.elevate .cmd { font-family: "JetBrainsMono Nerd Font", "JetBrains Mono", monospace; font-size: 12.5px;
  color: @code; background-color: alpha(@crust, 0.7); border-radius: 10px; padding: 7px 10px; }
.elevate .state { font-family: "JetBrainsMono Nerd Font", monospace; font-size: 11.5px; color: @subtext; }
.elevate .state.ok { color: @ok; }
.elevate .state.failed { color: @error; }
.elevate .state.skipped, .elevate .state.declined { color: @muted; }
.elevate .output { font-family: "JetBrainsMono Nerd Font", monospace; font-size: 11.5px; color: @subtext;
  background-color: alpha(@crust, 0.7); border-radius: 10px; padding: 7px 10px; }
.elevate .note { color: @muted; font-size: 12px; }
.elevate .error { color: @error; font-weight: 600; }
.elevate checkbutton check { border-color: @muted; background-color: alpha(@crust, 0.7); }
.elevate checkbutton check:checked { background-color: @accent; border-color: @accent; color: @on_accent; }
.elevate entry { background-color: alpha(@crust, 0.7); border-radius: 10px; min-height: 34px; }
.elevate button.btn { padding: 7px 14px; border-radius: 10px; font-weight: 600; font-size: 12.5px;
  background-color: alpha(@text, 0.06); border: 1px solid alpha(@text, 0.08); color: @text; box-shadow: none; }
.elevate button.btn.run { background-color: @accent; color: @on_accent; border-color: transparent; }
.elevate button.btn.run:disabled { background-color: alpha(@text, 0.08); color: @muted; }
.elevate button.btn.deny { background-color: alpha(@error, 0.16); color: @error; border-color: alpha(@error, 0.3); }
.elevate .foot { padding: 9px 16px; border-top: 1px solid alpha(@text, 0.06); background-color: alpha(@crust, 0.25); }
.elevate .hint { color: @muted; font-family: "JetBrainsMono Nerd Font", monospace; font-size: 11px; }
.elevate .countdown { color: @warn; font-size: 11.5px; }
"""

# Vayu's own colours (Catppuccin Mocha): used when there's no varna theme,
# or the theme fails a check.
FALLBACK = {"base": "#1e1e2e", "crust": "#11111b", "text": "#cdd6f4", "subtext": "#a6adc8",
            "muted": "#7f849c", "accent": "#cba6f7", "code": "#a6e3a1", "ok": "#a6e3a1",
            "error": "#f38ba8", "warn": "#fab387", "on_accent": "#11111b", "dark": True}


def _luminance(h):
    def ch(c):
        c = c / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (int(h[i:i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b)


def contrast(a, b):
    la, lb = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def theme(home):
    """The user's varna colours, if they keep this window unmistakable.

    palette.json is the user's file, so an agent running as the user could
    write it too: it must never be able to make a command hard to read or
    a button easy to miss. So every colour must be plain #rrggbb, the text
    must be readable on everything it's drawn on (else the whole palette is
    ignored), and any other colour that isn't readable enough is replaced by
    the text colour."""
    path = os.path.join(home, ".local/state/varna/palette.json")
    try:
        if os.path.getsize(path) > 65536:
            return FALLBACK
        with open(path) as f:
            data = json.load(f)
        c = data["colors"]
        pick = lambda *names: next(c[n] for n in names if n in c)  # noqa: E731
        t = {"base": pick("base"), "crust": pick("crust"), "text": pick("text"), "subtext": pick("subtext1", "subtext0"),
             "muted": pick("overlay2", "subtext0"), "accent": pick("accent"), "code": pick("green", "ok"),
             "ok": pick("ok", "green"), "error": pick("error", "red"), "warn": pick("warn", "yellow"),
             "dark": data.get("variant") != "light"}
    except (OSError, ValueError, KeyError, TypeError, StopIteration):
        return FALLBACK
    if not all(isinstance(v, str) and len(v) == 7 and v[0] == "#" and all(x in "0123456789abcdefABCDEF" for x in v[1:])
               for k, v in t.items() if k != "dark"):
        return FALLBACK
    t = {k: (v.lower() if k != "dark" else v) for k, v in t.items()}
    # Must hold, or the whole palette is ignored: the body text and the
    # command blocks readable (4.5:1, WCAG AA) on what they're drawn on.
    if contrast(t["text"], t["base"]) < 4.5 or contrast(t["text"], t["crust"]) < 4.5:
        return FALLBACK
    # Every other colour that isn't readable enough is replaced by the text
    # colour (always readable, see above): a faint theme colour, or one an
    # agent made faint, never makes anything hard to see.
    if contrast(t["code"], t["crust"]) < 7:          # the command itself: AAA, else plain text
        t["code"] = t["text"]
    for role, need in (("subtext", 4.5), ("error", 4.5), ("warn", 4.5), ("ok", 4.5)):
        if contrast(t[role], t["base"]) < need:
            t[role] = t["text"]
    if contrast(t["muted"], t["base"]) < 3:
        t["muted"] = t["subtext"]
    # The Run button: the accent, labelled in whichever reads better on it.
    # (the theme's own ink first, like Vyom's buttons; black or white only if needed)
    t["on_accent"] = next((c for c in (t["crust"], t["text"], "#000000", "#ffffff")
                           if contrast(c, t["accent"]) >= 4.5), t["crust"])
    if contrast(t["accent"], t["base"]) < 3 or contrast(t["on_accent"], t["accent"]) < 4.5:
        return FALLBACK
    return t


def theme_css(t):
    # libadwaita's own accent (focus rings, the selected text) is the theme's too.
    adw = f"@define-color accent_color {t['accent']};\n@define-color accent_bg_color {t['accent']};\n" \
          f"@define-color accent_fg_color {t['on_accent']};\n"
    return "".join(f"@define-color {k} {v};\n" for k, v in t.items() if k != "dark") + adw + CSS


def harden():
    # Not dumpable: other processes of this user can't ptrace this one or
    # read /proc/<pid>/mem, where the password lives while it's typed.
    try:
        ctypes.CDLL("libc.so.6", use_errno=True).prctl(4, 0, 0, 0, 0)  # PR_SET_DUMPABLE
    except OSError:
        pass


def write_json_atomic(path, obj):
    tmp = path + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(obj, f)
    os.replace(tmp, path)


class Request:
    def __init__(self, path):
        with open(path) as f:
            data = json.load(f)
        self.id = str(data["id"])[:64]
        self.requester = str(data.get("requester") or "an AI agent")[:80]
        self.reason = str(data.get("reason") or "")[:2000]
        self.commands = [(str(c["cmd"]), str(c.get("why") or "")) for c in data["commands"]][:50]


def keycap(keys, t):
    """'Esc' as a key cap (Pango), like Vyom's footer hints."""
    return (f"<span background='{t['crust']}' foreground='{t['subtext']}' font_family='JetBrainsMono Nerd Font'> "
            + GLib.markup_escape_text(keys) + " </span>")


class ElevateWindow(Adw.ApplicationWindow):
    def __init__(self, app, req, outdir, t=FALLBACK):
        super().__init__(application=app, title="Root access requested")
        self.req, self.outdir = req, outdir
        self.started = time.monotonic()
        self.attempts = 0
        self.done = False          # result written
        self.running = False
        self.results = [{"index": i, "command": c, "why": w, "decision": "approved", "state": "not_run"}
                        for i, (c, w) in enumerate(req.commands)]
        self.add_css_class("elevate")
        self.set_default_size(820, -1)
        self.connect("close-request", self.on_close)

        # Capture phase: the window sees Esc/Enter before any child, so a
        # widget that was disabled while focused can't swallow them.
        keys = Gtk.EventControllerKey()
        keys.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        keys.connect("key-pressed", self.on_key)
        self.add_controller(keys)

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)

        # Top bar, like a Vyom panel's: the mode pill, then what's asked.
        top = Gtk.Box(spacing=12)
        top.add_css_class("topbar")
        pill = Gtk.Box(spacing=7, valign=Gtk.Align.CENTER)
        pill.add_css_class("mode")
        glyph = Gtk.Label(label="\U000f0483")   # nf-md-shield_alert
        glyph.add_css_class("glyph")
        pill.append(glyph)
        pill.append(Gtk.Label(label="Root access"))
        top.append(pill)
        n = len(req.commands)
        who = Gtk.Label(label=req.requester, xalign=0)
        who.add_css_class("requester")
        top.append(who)
        t_ = Gtk.Label(label=f"wants to run {n} command{'s' if n != 1 else ''} as root", xalign=0, hexpand=True,
                       wrap=True)
        t_.add_css_class("title")
        top.append(t_)
        outer.append(top)

        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        body.add_css_class("body")
        if req.reason:
            r = Gtk.Label(label=req.reason, xalign=0, wrap=True, selectable=True)
            r.add_css_class("reason")
            body.append(r)

        sec = Gtk.Label(label="COMMANDS", xalign=0)
        sec.add_css_class("section")
        body.append(sec)
        cards = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.checks, self.states, self.outputs, self.card_boxes = [], [], [], []
        for i, (cmd, why) in enumerate(req.commands):
            card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            card.add_css_class("cmd-card")
            row = Gtk.Box(spacing=10)
            check = Gtk.CheckButton(active=True)
            check.connect("toggled", self.on_toggle, i)
            row.append(check)
            wl = Gtk.Label(label=why or "(no reason given)", xalign=0, wrap=True, hexpand=True)
            wl.add_css_class("why")
            row.append(wl)
            state = Gtk.Label(label="", xalign=1)
            state.add_css_class("state")
            row.append(state)
            card.append(row)
            # The exact text that will run: selectable, wrapped by character
            # so nothing can hide past the edge.
            cl = Gtk.Label(label=cmd, xalign=0, wrap=True, selectable=True)
            cl.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
            cl.add_css_class("cmd")
            card.append(cl)
            out = Gtk.Label(xalign=0, wrap=True, selectable=True, visible=False)
            out.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
            out.add_css_class("output")
            card.append(out)
            cards.append(card)
            self.checks.append(check)
            self.states.append(state)
            self.outputs.append(out)
            self.card_boxes.append(card)
        scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER,
                                      propagate_natural_height=True, max_content_height=520)
        scroller.set_child(cards)
        body.append(scroller)

        note = Gtk.Label(xalign=0, wrap=True,
                         label="Each ticked command runs as root with bash -c, from /, with no input. "
                               "It stops at the first command that fails. Untick anything you don't want run.")
        note.add_css_class("note")
        body.append(note)

        self.error = Gtk.Label(xalign=0, visible=False, wrap=True)
        self.error.add_css_class("error")
        body.append(self.error)

        bottom = Gtk.Box(spacing=8, margin_bottom=8)
        self.password = Gtk.PasswordEntry(show_peek_icon=True, hexpand=True,
                                          placeholder_text="Your password (for sudo)")
        self.password.connect("activate", lambda *_: self.on_run())
        bottom.append(self.password)
        self.deny_btn = Gtk.Button(label="Deny")
        self.deny_btn.add_css_class("btn")
        self.deny_btn.add_css_class("deny")
        self.deny_btn.connect("clicked", lambda *_: self.finish_denied("denied", "The user denied the request."))
        bottom.append(self.deny_btn)
        self.run_btn = Gtk.Button()
        self.run_btn.add_css_class("btn")
        self.run_btn.add_css_class("run")
        self.run_btn.connect("clicked", lambda *_: self.on_run())
        bottom.append(self.run_btn)
        body.append(bottom)
        outer.append(body)

        # Footer, like Vyom's: the keys, then the time left.
        foot = Gtk.Box(spacing=16)
        foot.add_css_class("foot")
        for keys, what in (("Space", "toggle"), ("Enter", "run"), ("Esc", "deny")):
            h = Gtk.Label(use_markup=True)
            h.set_markup(f"{keycap(keys, t)} {GLib.markup_escape_text(what)}")
            h.add_css_class("hint")
            foot.append(h)
        self.countdown = Gtk.Label(xalign=1, hexpand=True)
        self.countdown.add_css_class("countdown")
        foot.append(self.countdown)
        outer.append(foot)

        self.set_content(outer)
        self.update_run_label()
        self.tick()
        GLib.timeout_add_seconds(1, self.tick)
        self.password.grab_focus()

    # ---- selection -------------------------------------------------------
    def selected(self):
        return [i for i, c in enumerate(self.checks) if c.get_active()]

    def on_toggle(self, check, i):
        self.results[i]["decision"] = "approved" if check.get_active() else "declined"
        if check.get_active():
            self.card_boxes[i].remove_css_class("declined")
        else:
            self.card_boxes[i].add_css_class("declined")
        self.update_run_label()

    def update_run_label(self):
        n = len(self.selected())
        self.run_btn.set_label(f"Run {n} selected" if n else "Nothing selected")
        self.run_btn.set_sensitive(n > 0 and not self.running and not self.done)

    def on_key(self, _ctrl, keyval, _code, _state):
        if keyval == Gdk.KEY_Escape:
            if self.done:
                self.quit()
            elif not self.running:
                self.finish_denied("denied", "The user denied the request.")
            return True
        if keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter) and self.done:
            self.quit()
            return True
        return False  # Enter before a run reaches the password field (activate = Run)

    def quit(self):
        self.get_application().quit()

    def tick(self):
        if self.done or self.running:
            self.countdown.set_label("")
            return not self.done
        left = EXPIRES_AFTER - int(time.monotonic() - self.started)
        if left <= 0:
            self.finish_denied("timeout", f"No answer within {EXPIRES_AFTER // 60} minutes.")
            return False
        self.countdown.set_label(f"expires in {left // 60}:{left % 60:02d}, then counts as denied")
        return True

    # ---- running ---------------------------------------------------------
    def on_run(self):
        if self.running or self.done or not self.selected():
            return
        pw = self.password.get_text()
        self.running = True
        # Move focus off the password field before disabling it: disabling the
        # focused widget left GTK's focus broken and the keys stopped working.
        self.set_focus(None)
        for w in (*self.checks, self.password, self.deny_btn):
            w.set_sensitive(False)
        self.update_run_label()
        self.error.set_visible(False)
        threading.Thread(target=self.check_password, args=(pw,), daemon=True).start()

    def check_password(self, pw):
        try:
            p = subprocess.run([SUDO, "-S", "-k", "-p", "", "--", "/usr/bin/true"],
                               input=(pw + "\n").encode(), capture_output=True, timeout=30)
            ok = p.returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            ok = False
        GLib.idle_add(self.after_password, ok, pw if ok else None)

    def after_password(self, ok, pw):
        if not ok:
            self.attempts += 1
            self.running = False
            if self.attempts >= MAX_ATTEMPTS:
                self.finish_denied("auth_failed", f"Wrong password {MAX_ATTEMPTS} times.")
                return False
            self.error.set_label(f"Wrong password (attempt {self.attempts} of {MAX_ATTEMPTS}).")
            self.error.set_visible(True)
            for w in (*self.checks, self.password, self.deny_btn):
                w.set_sensitive(True)
            self.password.set_text("")
            self.password.grab_focus()
            self.update_run_label()
            return False
        self.password.set_text("")
        chosen = self.selected()
        for i, r in enumerate(self.results):
            if i not in chosen:
                r["state"] = "declined"
                self.set_state(i, "declined", "declined")
        payload = {"id": self.req.id, "requester": self.req.requester,
                   "commands": [self.req.commands[i][0] for i in chosen],
                   "stop_on_failure": True, "timeout": 1800}
        threading.Thread(target=self.run_runner, args=(pw, payload, chosen), daemon=True).start()
        return False

    def run_runner(self, pw, payload, chosen):
        try:
            p = subprocess.Popen([SUDO, "-S", "-k", "-p", "", "--", "/usr/bin/python3", "-I", RUNNER],
                                 stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            p.stdin.write((pw + "\n" + json.dumps(payload) + "\n").encode())
            p.stdin.close()
            del pw
            for line in p.stdout:
                try:
                    ev = json.loads(line)
                except ValueError:
                    continue
                GLib.idle_add(self.on_event, ev, chosen)
            p.wait()
            err = p.stderr.read().decode("utf-8", "replace").strip()
            GLib.idle_add(self.on_runner_exit, p.returncode, err)
        except OSError as e:
            GLib.idle_add(self.on_runner_exit, -1, str(e))

    def set_state(self, i, text, cls):
        lbl = self.states[i]
        for c in ("ok", "failed", "skipped", "declined"):
            lbl.remove_css_class(c)
        if cls:
            lbl.add_css_class(cls)
        lbl.set_label(text)

    def on_event(self, ev, chosen):
        kind = ev.get("event")
        if kind in ("start", "done", "skipped"):
            i = chosen[ev["index"]]
            r = self.results[i]
            if kind == "start":
                r["state"] = "running"
                self.set_state(i, "running…", None)
            elif kind == "skipped":
                r["state"] = "skipped"
                self.set_state(i, "skipped", "skipped")
            else:
                code = ev["exit_code"]
                r.update(state="ok" if code == 0 else "failed", exit_code=code, stdout=ev["stdout"],
                         stderr=ev["stderr"], duration=ev["duration"], timed_out=ev["timed_out"],
                         truncated=ev.get("truncated", False))
                self.set_state(i, f"✓ {ev['duration']}s" if code == 0 else f"✗ exit {code}",
                               "ok" if code == 0 else "failed")
                text = (ev["stdout"] + ("\n" if ev["stdout"] and ev["stderr"] else "") + ev["stderr"]).strip()
                if text:
                    lines = text.splitlines()
                    shown = "\n".join(lines[-12:])
                    if len(lines) > 12:
                        shown = f"… {len(lines) - 12} more lines (full output goes to the agent)\n" + shown
                    self.outputs[i].set_label(shown)
                    self.outputs[i].set_visible(True)
        elif kind == "finished":
            self.finish("completed", "Ran the approved commands.")
        return False

    def on_runner_exit(self, code, err):
        if not self.done:
            # The runner died before "finished" (sudo refused, python error...)
            self.finish("error", f"The root runner exited with {code}: {err[-500:]}")
        return False

    # ---- result ----------------------------------------------------------
    def finish_denied(self, status, message):
        for r in self.results:
            r["decision"] = "declined" if status == "denied" else r["decision"]
            r["state"] = "not_run"
        self.finish(status, message, close=True)

    def finish(self, status, message, close=False):
        if self.done:
            return
        self.done = True
        self.running = False
        result = {"id": self.req.id, "status": status, "message": message,
                  "approved": [r["index"] for r in self.results if r["decision"] == "approved" and status == "completed"],
                  "declined": [r["index"] for r in self.results if r["decision"] == "declined"],
                  "results": self.results}
        try:
            write_json_atomic(os.path.join(self.outdir, "result.json"), result)
        except OSError as e:
            print(f"anumati dialog: can't write the result: {e}", file=sys.stderr)
        self.log(result)
        if close:
            self.quit()
            return
        ok = sum(r["state"] == "ok" for r in self.results)
        bad = sum(r["state"] == "failed" for r in self.results)
        self.run_btn.set_label("Close")
        self.run_btn.set_sensitive(True)
        self.run_btn.connect("clicked", lambda *_: self.quit())
        self.run_btn.grab_focus()
        if status == "completed" and not bad:
            # All good: the agent has the output; show the ticks for a moment.
            self.error.set_label(f"Done: {ok} succeeded. Closing…")
            self.error.remove_css_class("error")
            self.error.set_visible(True)
            GLib.timeout_add(AUTO_CLOSE_MS, lambda: self.quit() or False)
            return
        # Something failed: stay open with the output until Enter/Esc/Close.
        self.error.set_label((f"Done: {ok} succeeded, {bad} failed" if status == "completed" else message)
                             + ". Enter or Esc closes.")
        self.error.set_visible(True)

    def log(self, result):
        try:
            os.makedirs(os.path.dirname(STATE_LOG), exist_ok=True)
            entry = {"time": time.time(), "id": self.req.id, "requester": self.req.requester,
                     "reason": self.req.reason, "status": result["status"],
                     "commands": [{"cmd": r["command"], "decision": r["decision"], "state": r["state"],
                                   "exit_code": r.get("exit_code")} for r in self.results]}
            with open(STATE_LOG, "a") as f:
                f.write(json.dumps(entry) + "\n")
        except OSError:
            pass

    def on_close(self, *_):
        if not self.done:
            if self.running:
                return True  # don't abandon a run halfway; it finishes on its own
            self.finish_denied("denied", "The user closed the window.")
        return False


def main():
    harden()
    if len(sys.argv) != 2:
        print("usage: dialog.py <request-dir>", file=sys.stderr)
        return 2
    outdir = sys.argv[1]
    try:
        req = Request(os.path.join(outdir, "request.json"))
    except (OSError, ValueError, KeyError, TypeError) as e:
        write_json_atomic(os.path.join(outdir, "result.json"),
                          {"status": "error", "message": f"bad request: {e}", "results": []})
        return 2
    Adw.init()
    t = theme(pwd.getpwuid(os.getuid()).pw_dir)
    Adw.StyleManager.get_default().set_color_scheme(
        Adw.ColorScheme.FORCE_DARK if t["dark"] else Adw.ColorScheme.FORCE_LIGHT)
    provider = Gtk.CssProvider()
    provider.load_from_string(theme_css(t))
    Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), provider,
                                              Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1)
    app = Adw.Application(application_id=APP_ID, flags=Gio.ApplicationFlags.NON_UNIQUE)
    app.connect("activate", lambda a: ElevateWindow(a, req, outdir, t).present())
    app.run([])
    return 0


if __name__ == "__main__":
    sys.exit(main())
