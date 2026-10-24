# Changelog

Newest first. Releases are tags (`vX.Y.Z`) with `VERSION` in `bin/anumati`.

## v1.2.1 -- 2026-10-24

- The look and the theme check moved into `lib/theme.py` (pure Python),
  loaded by path by the window: the tests that check a tampered theme can't
  hide anything now run in CI, which has no GTK (1.2.0's CI failed there).
  install.sh installs it next to dialog.py.

## v1.2.0 -- 2026-10-24

- **Looks like the rest of the desktop.** The window has Vyom's layout: a
  "Root access" pill and the request in the top bar, the commands as
  rounded cards, the password and buttons, then the keys (Space, Enter,
  Esc) and the time left in the footer; Vyom's type, buttons and a 20 px
  glass card (0.84, never see-through enough to read what's behind).
- **In your theme, safely** (ADR 6). The colours come from varna's
  `palette.json`, read as plain `#rrggbb` data only, never CSS. The body
  text and the commands must stay readable (4.5:1) or the palette is
  ignored; the command is the theme's green only at 7:1, else plain text;
  any other colour that isn't readable enough becomes the text colour; the
  Run button's label is picked to read on the accent. A light theme gets a
  light window. Without varna: anumati's own colours, as before.
- Focus rings and selected text use the theme's accent (not GTK's blue).

## v1.1.1 -- 2026-10-21

- A website (GitHub Pages, https://theyashsawarkar.github.io/anumati/): the README as a home page, the
  changelog, and architecture decision records (`docs/adr/`), built from these files by
  `scripts/build-site.py`; CI checks the site is up to date.

## v1.1.0 -- 2026-10-21

- Renamed from `vayu-elevate` to **anumati** (अनुमति, "permission") and
  moved into its own repository. Everything moves with the name:
  `/usr/local/bin/anumati`, `/usr/local/lib/anumati/`,
  `/var/log/anumati.log`, `~/.local/state/anumati/requests.jsonl`, the
  window's app id `io.github.theyashsawarkar.Anumati`, the MCP server name.
- `install.sh` (was Vayu's `ai/apply.sh`) installs it root-owned, keeps
  `/usr/local/bin/vayu-elevate` as a link so the old name still works,
  removes the old `/usr/local/lib/vayu-elevate`, and gains `--uninstall`.
- Tests for request validation, and CI.

## v1.0.0 -- 2026-10-16

- First version, as `vayu-elevate` inside Vayu: the approval window, the
  root runner, JSON in and out, the MCP server, the audit logs.
