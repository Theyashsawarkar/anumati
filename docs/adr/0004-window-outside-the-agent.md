# 4. The window is not a child of the agent

**Status:** Accepted  
**Date:** 2026-10-16

## Context

A window started by the agent could be inspected (ptrace, /proc) or fed a different environment.

## Decision

The window starts as a transient systemd user service with a clean environment and marks itself non-dumpable; the password goes over a pipe to `sudo -S -k` and never to disk.

## Consequences

- The agent never sees the password.
- Requires systemd's user manager and a graphical session.
