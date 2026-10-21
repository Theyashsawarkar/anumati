# Changelog

Newest first. Releases are tags (`vX.Y.Z`) with `VERSION` in `bin/anumati`.

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
