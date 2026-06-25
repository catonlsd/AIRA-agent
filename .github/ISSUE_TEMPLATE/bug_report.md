---
name: Bug report
about: Report a defect so it can be reproduced and fixed
title: "bug: <short summary>"
labels: ["bug", "needs-triage"]
---

## Summary
<!-- One sentence: what's broken? -->

## Surface
<!-- Which part of the platform? -->
- [ ] User product (chat / documents / execution)
- [ ] Operator console / incident sync
- [ ] Observability / metrics
- [ ] Demo seed
- [ ] Build / CI / tooling
- [ ] Docs

## Steps to reproduce
1.
2.
3.

## Expected behavior
<!-- What should have happened? -->

## Actual behavior
<!-- What happened instead? Include exact error text / status codes. -->

## Environment
- AIRA-X version / commit:
- OS:
- Python / Node version:
- Backend deployment (local / docker / VM):

## Logs & evidence
<!-- Relevant logs, a failing request, a screenshot. NEVER paste secrets, API keys,
     or signing secrets — redact them. -->

## Regression check
- [ ] I confirmed this is not already covered by an existing test that fails
- [ ] I can reproduce it deterministically
