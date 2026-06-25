# Contributing to AIRA-X

Thanks for your interest. AIRA-X is a production-minded platform with firm invariants, so
this guide is short and specific: it explains how to set up, what we expect of a change,
and the workflow from branch to release.

By participating you agree to the [Code of Conduct](CODE_OF_CONDUCT.md). By contributing
code you agree it is licensed under the project [LICENSE](LICENSE).

---

## What belongs here (scope)

AIRA-X is **feature-complete for portfolio and commercial demonstration**. The most
valuable contributions are:

- Bug fixes with a regression test.
- Documentation, examples, and developer-experience improvements.
- CI / tooling / quality improvements.
- Performance or clarity refactors that change no behavior.

**Intentionally out of scope** (please open a discussion before a PR): new vendor
adapters, speculative AI features, and any form of auto-remediation. These would weaken
the platform's core guarantees — see [docs/ENGINEERING_DECISIONS.md](docs/ENGINEERING_DECISIONS.md).

## Non-negotiable invariants

Every change must preserve these (the PR template asks you to confirm them):

1. **Local state is the source of truth** — inbound sync observes, it never mutates.
2. **Recovery is explicit and audited** — no auto-remediation.
3. **Operator/user separation** — operator state never leaks into user responses.
4. **Deterministic & explainable** — no opaque or AI-driven operational advice.
5. **Additive only** — no breaking API / DB / UX changes.

---

## Local setup

```bash
# Backend
cd backend
python -m venv venv          # Python 3.12
# Windows: venv\Scripts\activate | macOS/Linux: source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # set GROQ_API_KEY; set API_KEY to use the operator surface

# Frontend
cd ../frontend
npm install
```

Full walkthrough: [README.md](README.md) → Quickstart. Hands-on tour:
[docs/DEMO_WALKTHROUGH.md](docs/DEMO_WALKTHROUGH.md).

## Running the checks (must pass before a PR)

```bash
# Backend — run in ISOLATION (the test DB is shared SQLite; concurrent runs collide)
cd backend && python -m pytest -q -p no:randomly

# Frontend fast wall
cd frontend
./node_modules/.bin/tsc --noEmit
node --test "lib/**/*.test.mts"
npm run lint
npm run build

# End-to-end (hermetic; boots its own dev server)
npm run e2e:install   # one-time
npm run e2e
```

CI runs the same gates: **fast-check** (backend + frontend), **e2e** (Playwright), and
**docs** (packaging/professionalization tests). A PR is mergeable when all are green.

## Tests are required

- Any bug fix lands with a test that fails before and passes after.
- Any new behavior is covered by a test.
- **Do not remove existing tests.** They are the platform's regression wall.

---

## Workflow

1. **Branch** off `main` using a descriptive prefix: `feat/…`, `fix/…`, `docs/…`,
   `chore/…`, `refactor/…`. `main` is always releasable.
2. **Commit** in small, logical units. Use imperative, present-tense subjects
   (`Fix stale readiness rollup`). Reference issues (`Closes #NN`).
3. **Open a pull request** (PR) to `main` using the template. Keep PRs focused and reviewable.
4. **Green CI** — fast-check, e2e, and docs must pass.
5. **Review** — at least one maintainer approval. Address feedback by pushing follow-up
   commits (don't force-push during review unless asked).
6. **Merge** — squash-merge to keep `main` history linear and readable.
7. **Changelog** — user/operator-facing changes add an entry under `[Unreleased]` in
   [CHANGELOG.md](CHANGELOG.md).

### Branch strategy (summary)

- `main` — protected, always green, always releasable.
- `feat/* | fix/* | docs/* | chore/* | refactor/*` — short-lived topic branches → PR → squash-merge.
- Release tags `vMAJOR.MINOR.PATCH` are cut from `main` (see below).

## Releases

Releases follow Semantic Versioning and a written checklist — see
[docs/RELEASE_PROCESS.md](docs/RELEASE_PROCESS.md). Maintainers cut releases; contributors
just keep `[Unreleased]` in the changelog accurate.

## Reporting bugs & vulnerabilities

- **Bugs:** open an issue with the bug template (steps to reproduce + environment).
- **Security:** do **not** open a public issue — follow [SECURITY.md](SECURITY.md).

## Questions

Start a GitHub Discussion or read [docs/PORTFOLIO_GUIDE.md](docs/PORTFOLIO_GUIDE.md) and
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).
