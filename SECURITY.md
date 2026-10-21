# Security policy

anumati decides what runs as root, so security reports matter more here
than anywhere else in the project.

## Supported versions

Only the latest release gets fixes.

## Reporting a vulnerability

Please **don't open a public issue**. Report it privately through
[GitHub's security advisories](https://github.com/Theyashsawarkar/anumati/security/advisories/new):
what an attacker could do (for example, run a command the user didn't see,
or read the password), from what position (an agent running as the user, a
local user, ...), and how to reproduce it. You'll get a reply within a
week; a fix and a release follow as soon as it's confirmed, with credit to
you unless you'd rather not.

Out of scope, as the README explains: a program already running as your
user that is actively malicious (it could draw a lookalike window). In
scope: anything that makes the window show one thing and run another, lets
an agent see the password, leaves root access behind, or bypasses approval.
