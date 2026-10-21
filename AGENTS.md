# anumati -- notes for AI agents (same as CLAUDE.md)

Root commands for AI agents, approved by the user in a window. Its own repo,
pulled into Vayu (github.com/Theyashsawarkar/vayu, whose CLAUDE.md
"Plugins" rules apply); it must work on any Linux desktop on its own. It was
called vayu-elevate until v1.1.0 (`/usr/local/bin/vayu-elevate` is a link).

- `bin/anumati` (what agents call), `lib/dialog.py` (the window), `lib/runner.py`
  (runs as root). `install.sh` installs them root-owned into `/usr/local`:
  never make the installed copies user-writable or load code from the user's
  home at runtime.
- Security first: what the window shows is exactly what runs; the agent never
  sees the password; nothing is left with root access afterwards. Read
  SECURITY.md before changing the flow.
- Keys: `# keybind: Anumati/root approval | <keys> | <Verb> ...` in
  `lib/dialog.py`'s header, and a README row (CI checks).
- Every change: a CHANGELOG.md entry; releases are tags with `VERSION` in
  `bin/anumati` bumped. `python -m py_compile bin/anumati lib/*.py`,
  `python -m unittest discover -s tests` and `shellcheck install.sh` must pass.
- Test with harmless requests only (`--cmd id`), through the real window; the
  user approves each.
