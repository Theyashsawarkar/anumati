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

CSS = """
@define-color accent_color #cba6f7;
@define-color accent_bg_color #cba6f7;
@define-color accent_fg_color #11111b;
/* Nearly opaque: text behind the window shouldn't read as part of it. */
window.elevate { background: rgba(24, 24, 37, 0.97); color: #cdd6f4; }
.elevate .title { font-size: 1.35rem; font-weight: 700; color: #f5e0dc; }
.elevate .subtitle { color: #a6adc8; }
.elevate checkbutton check { border-color: #6c7086; background: rgba(17, 17, 27, 0.7); }
.elevate checkbutton check:checked { background: #cba6f7; border-color: #cba6f7; color: #11111b; }
.elevate .reason { color: #cdd6f4; }
.elevate .shield { color: #f38ba8; }
.elevate .cmd-card {
  background: rgba(49, 50, 68, 0.55); border: 1px solid rgba(203, 166, 247, 0.18);
  border-radius: 12px; padding: 10px 12px;
}
.elevate .cmd-card.declined { opacity: 0.5; }
.elevate .why { color: #cdd6f4; font-weight: 600; }
.elevate .cmd {
  font-family: "JetBrainsMono Nerd Font", "JetBrains Mono", monospace; font-size: 0.92rem;
  color: #a6e3a1; background: rgba(17, 17, 27, 0.7); border-radius: 8px; padding: 6px 8px;
}
.elevate .state { font-family: monospace; font-size: 0.85rem; color: #a6adc8; }
.elevate .state.ok { color: #a6e3a1; }
.elevate .state.failed { color: #f38ba8; }
.elevate .state.skipped, .elevate .state.declined { color: #6c7086; }
.elevate .output {
  font-family: monospace; font-size: 0.82rem; color: #bac2de;
  background: rgba(17, 17, 27, 0.7); border-radius: 8px; padding: 6px 8px;
}
.elevate .note { color: #7f849c; font-size: 0.85rem; }
.elevate .error { color: #f38ba8; font-weight: 600; }
.elevate .countdown { color: #fab387; font-size: 0.85rem; }
.elevate button.run { background: #cba6f7; color: #11111b; font-weight: 700; }
.elevate button.run:disabled { background: #45475a; color: #7f849c; }
.elevate button.deny { color: #f38ba8; }
.elevate entry { background: rgba(17, 17, 27, 0.7); }
"""


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


class ElevateWindow(Adw.ApplicationWindow):
    def __init__(self, app, req, outdir):
        super().__init__(application=app, title="Root access requested")
        self.req, self.outdir = req, outdir
        self.started = time.monotonic()
        self.attempts = 0
        self.done = False          # result written
        self.running = False
        self.results = [{"index": i, "command": c, "why": w, "decision": "approved", "state": "not_run"}
                        for i, (c, w) in enumerate(req.commands)]
        self.add_css_class("elevate")
        self.set_default_size(780, -1)
        self.connect("close-request", self.on_close)

        # Capture phase: the window sees Esc/Enter before any child, so a
        # widget that was disabled while focused can't swallow them.
        keys = Gtk.EventControllerKey()
        keys.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        keys.connect("key-pressed", self.on_key)
        self.add_controller(keys)

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14,
                        margin_top=22, margin_bottom=18, margin_start=24, margin_end=24)

        head = Gtk.Box(spacing=14)
        shield = Gtk.Image.new_from_icon_name("security-high-symbolic")
        shield.set_pixel_size(36)
        shield.add_css_class("shield")
        head.append(shield)
        titles = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        t = Gtk.Label(label="Root access requested", xalign=0)
        t.add_css_class("title")
        n = len(req.commands)
        sub = Gtk.Label(xalign=0, wrap=True, use_markup=True)
        sub.set_markup(f"<span foreground='#cba6f7' weight='bold'>{GLib.markup_escape_text(req.requester)}</span>"
                       f" wants to run {n} command{'s' if n != 1 else ''} as root")
        sub.add_css_class("subtitle")
        titles.append(t)
        titles.append(sub)
        head.append(titles)
        outer.append(head)

        if req.reason:
            r = Gtk.Label(label=req.reason, xalign=0, wrap=True, selectable=True)
            r.add_css_class("reason")
            outer.append(r)

        cards = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.checks, self.states, self.outputs, self.card_boxes = [], [], [], []
        for i, (cmd, why) in enumerate(req.commands):
            card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            card.add_css_class("cmd-card")
            top = Gtk.Box(spacing=10)
            check = Gtk.CheckButton(active=True)
            check.connect("toggled", self.on_toggle, i)
            top.append(check)
            wl = Gtk.Label(label=why or "(no reason given)", xalign=0, wrap=True, hexpand=True)
            wl.add_css_class("why")
            top.append(wl)
            state = Gtk.Label(label="", xalign=1)
            state.add_css_class("state")
            top.append(state)
            card.append(top)
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
        outer.append(scroller)

        note = Gtk.Label(xalign=0, wrap=True,
                         label="Each ticked command runs as root with bash -c, from /, with no input. "
                               "It stops at the first command that fails. Untick anything you don't want run.")
        note.add_css_class("note")
        outer.append(note)

        self.error = Gtk.Label(xalign=0, visible=False)
        self.error.add_css_class("error")
        outer.append(self.error)

        bottom = Gtk.Box(spacing=10)
        self.password = Gtk.PasswordEntry(show_peek_icon=True, hexpand=True,
                                          placeholder_text="Your password (for sudo)")
        self.password.connect("activate", lambda *_: self.on_run())
        bottom.append(self.password)
        self.deny_btn = Gtk.Button(label="Deny")
        self.deny_btn.add_css_class("deny")
        self.deny_btn.connect("clicked", lambda *_: self.finish_denied("denied", "The user denied the request."))
        bottom.append(self.deny_btn)
        self.run_btn = Gtk.Button()
        self.run_btn.add_css_class("run")
        self.run_btn.connect("clicked", lambda *_: self.on_run())
        bottom.append(self.run_btn)
        outer.append(bottom)

        self.countdown = Gtk.Label(xalign=0)
        self.countdown.add_css_class("countdown")
        outer.append(self.countdown)

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
        self.countdown.set_label(f"Expires in {left // 60}:{left % 60:02d}; then it counts as denied.")
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
    Adw.StyleManager.get_default().set_color_scheme(Adw.ColorScheme.FORCE_DARK)
    provider = Gtk.CssProvider()
    provider.load_from_string(CSS)
    Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), provider,
                                              Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1)
    app = Adw.Application(application_id=APP_ID, flags=Gio.ApplicationFlags.NON_UNIQUE)
    app.connect("activate", lambda a: ElevateWindow(a, req, outdir).present())
    app.run([])
    return 0


if __name__ == "__main__":
    sys.exit(main())
