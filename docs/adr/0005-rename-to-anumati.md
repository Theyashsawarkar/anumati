# 5. Rename vayu-elevate to anumati, in its own repository

**Status:** Accepted  
**Date:** 2026-10-21

## Context

The tool is useful on any Linux desktop, not only Vayu, and Vayu's rule is that tools live in their own repositories.

## Decision

It became anumati ("permission") in its own repository. `/usr/local/bin/vayu-elevate` stays as a link to it, so existing agents and notes keep working.

## Consequences

- New paths (logs, state, app id); the old logs remain where they were.
