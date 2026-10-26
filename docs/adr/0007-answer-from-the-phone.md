# 7. Answering from the phone, through ekatva, by the same path as typing

**Status:** Accepted  
**Date:** 2026-10-26

## Context

Agents run long jobs while you're away from the laptop, and stop when they need root. [ekatva](https://github.com/Theyashsawarkar/ekatva) links your phone and laptop end to end; users asked to approve root requests from the phone, typing the sudo password there.

## Decision

When ekatva runs, the window also hands the request to ekatva's socket, `/run/user/<uid>/ekatva-root.sock`, and accepts an answer from it: approve or deny, which commands, and the password. An answer is applied exactly as if typed: the chosen commands are ticked in the window, the password goes into the password field, and the same `on_run` follows (the `sudo -S -k` check, then the root-owned runner). A wrong password is reported back so the phone can retry; the three-attempt limit is the window's, as before.

- **Only answers come in; nothing secret goes out.** The window sends ekatva the request it shows (what the agent sent, nothing more), "wrong" with the attempt count, and "done" with the status. It never sends a password.
- **The path comes from the uid, not the environment**: the agent that started the request controls the environment, and could otherwise point the window at a socket of its own.
- **Answers are validated strictly** (`lib/remote.py`, pure Python, tested in CI): a boolean approval, command indexes in range, a non-empty password without newlines, at most 1 KB; anything else is ignored.
- **Optional and harmless when absent**: without ekatva, nothing changes.

## Consequences

- The window's guarantees hold: what runs is what it shows (the ticks change visibly before anything runs) and the agent never sees the password (it goes phone → ekatva's end-to-end encrypted link → this window, never through the agent).
- A process running as you that listens on that socket when ekatva doesn't could see the request (which the agent already knows) and send wrong passwords, as any of your processes can already do with sudo directly; it can't learn the password. This stays within the threat model of [ADR 2](0002-consent-gate-not-sandbox.md).
- ekatva decides who may answer (a paired phone with the "root" capability, which is off by default, with a fingerprint each time) and keeps both devices' logs, with the password redacted.
