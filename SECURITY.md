# Security policy

## Reporting a vulnerability

Please **do not** open a public issue for a security problem.

Report it privately through GitHub's *Security → Report a vulnerability* form on
this repository, or by email to the address listed in the repository profile.
Include the version, the steps to reproduce, and what an attacker gains.

Expect an acknowledgement within a few days. There is no bug bounty; this is a
volunteer project.

## Supported versions

| Version | Supported |
| --- | --- |
| 1.0.x | yes |
| < 1.0 | no |

## What is already documented

The threat model is written to be checked against the code rather than taken on
trust: [docs/security.md](docs/security.md) lists every control, the test that
proves it, and — in section 9 — the residual risks that are **not** mitigated.
Read that before reporting something it already describes, for example:

- the bridge token is readable by any process running as the same user;
- a compromised browser profile can drive the app;
- UNC source paths are accepted, which leaks NTLM hashes to a hostile server;
- the binaries are unsigned and not independently audited.

Reports that any of the above is worse than described are very welcome.
