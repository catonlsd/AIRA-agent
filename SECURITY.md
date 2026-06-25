# Security Policy

AIRA-X takes security seriously — the platform is built around trust boundaries (see
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) §8–§9). This document explains how to report
a vulnerability and what to expect.

## Supported versions

AIRA-X is pre-1.0. Security fixes are applied to the latest `main` and the most recent
tagged minor release.

| Version | Supported |
|---|---|
| latest `main` | ✅ |
| latest `v0.MINOR.x` tag | ✅ |
| older tags | ❌ (please upgrade) |

## Reporting a vulnerability (responsible disclosure)

**Please do not open a public issue, PR, or discussion for a security report.**

Report privately via **[GitHub Security Advisories](https://github.com/catonlsd/AIRA-agent/security/advisories/new)**
(Repository → Security → *Report a vulnerability*). If you cannot use that, email the
maintainer at **paranoidjalebi@gmail.com** with the subject `AIRA-X security`.

Please include:

- A description of the issue and its impact.
- Steps to reproduce (a minimal PoC if possible).
- Affected version / commit and configuration.
- Any suggested remediation.

### What to expect

- **Acknowledgement:** within 3 business days.
- **Assessment & triage:** a severity and a remediation plan communicated back to you.
- **Fix & disclosure:** we aim to ship a fix promptly; we will coordinate a disclosure
  timeline with you and credit you (unless you prefer to remain anonymous).

We ask that you give us a reasonable window to remediate before any public disclosure.

## Scope & handling notes

- **Secrets:** incident-target signing secrets are stored for HMAC signing but are
  **never returned** by any read API (`has_secret` only). If you find a path that exposes
  a secret, that is a high-severity report.
- **Operator boundary:** the operator surface (`/operator/*`) is service-key gated. A way
  to reach operator functionality or data without the service key is in scope.
- **Out of scope:** issues requiring a misconfigured deployment that ignores the
  documented hardening (e.g. running public with `API_KEY` unset), or third-party
  vulnerabilities already tracked upstream. Report those upstream, but feel free to flag
  them so we can pin a safe version.

## Hardening reference

Production hardening guidance (secret encryption at rest, `API_KEY` enforcement, CORS,
rate limiting, readiness gating) lives in
[docs/PRODUCTION_READINESS.md](docs/PRODUCTION_READINESS.md) and
[docs/DEPLOYMENT_BLUEPRINT.md](docs/DEPLOYMENT_BLUEPRINT.md).
