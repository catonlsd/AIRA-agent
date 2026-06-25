# Portfolio audit

An honest, role-by-role assessment of how AIRA-X *presents* — what lands, what doesn't,
and what proof is still missing. This is a presentation audit, not a code review: the
platform is feature-complete and tested (951 backend / 104 frontend / 6 E2E); the question
is whether a stranger reaches the right verdict fast.

> Companion to **[PORTFOLIO_GUIDE.md](PORTFOLIO_GUIDE.md)** (how to read the repo) and
> **[screenshots/CAPTURE_PLAN.md](screenshots/CAPTURE_PLAN.md)** (the visual proof plan).

---

## By audience

### Recruiter (skims ~3 minutes, mostly the README top)
- **Wants:** instant signal of scope and seriousness.
- **Lands:** the headline metrics table (951/104/6 tests, 4 adapters, 68 gated routes), CI
  + license badges, the two-surface framing.
- **Falls flat:** **no images.** A recruiter reacts to a screenshot in 3 seconds and a wall
  of text in zero. The Screenshots section currently lists *paths*, not pictures.
- **Fix:** capture the 8 stills + a 30s GIF (see capture plan). This is the #1 gap.

### Staff / senior engineer (reads ~15 min, code + docs)
- **Wants:** evidence of judgment — boundaries, determinism, failure handling.
- **Lands:** `ENGINEERING_DECISIONS.md` (decision → why → consequence), the computed-not-
  stored readiness model, the pure deterministic metrics, tests that pin guarantees, and a
  clean three-workflow CI. The recent CI debugging (reproduce → root-cause → minimal fix)
  is itself a strong signal in the commit history.
- **Falls flat:** the "legacy file-based vector store" vs ChromaDB dual-write is a visible
  rough edge; the heavy ML dependency footprint (torch/transformers) is large for what the
  demo exercises.
- **Fix:** a short note in `ARCHITECTURE.md` acknowledging the legacy-store seam (already
  partly documented) and the dependency posture; nothing code-level required for portfolio.

### Startup CTO (10 min: can my team run this?)
- **Wants:** operability, a deployment story, no magic.
- **Lands:** runbooks + troubleshooting matrix, the deployment blueprint (single-VM →
  compose → k8s), explicit/audited recovery, `/health` + `/ready`, SLOs that observe
  rather than enforce.
- **Falls flat:** there's **no live, clickable demo** — they must clone to see it. The
  SQLite-default + heavy deps make "5-minute try" feel heavier than it is.
- **Fix:** a hosted demo URL (seeded, gated, rate-limited) is the highest-leverage CTO
  asset after visuals.

### Technical founder (skims for "is this real and differentiated?")
- **Wants:** a crisp story and a defensible core idea.
- **Lands:** the invariant spine — *local state is the source of truth, recovery is
  explicit, observability is deterministic* — is genuinely differentiated vs. typical
  "AI wrapper" projects.
- **Falls flat:** the chat product and the operator platform can read as two projects; the
  connective tissue (ops alerts → incidents → sync) is documented but not *shown*.
- **Fix:** the demo GIF that walks alert → incident → drift → recovery makes the single-
  platform story obvious in 30 seconds.

---

## Strongest selling points (lead with these)
1. **Computed-not-stored readiness + deterministic observability** — reads like real SRE
   tooling, not a CRUD demo. Hard to fake, easy to verify.
2. **Trust model as a spine** — local-state-is-truth, no auto-heal, operator/user
   separation, all *enforced by tests*. Mature, opinionated, defensible.
3. **Test depth + determinism** — 951 deterministic backend tests, hermetic E2E, and
   docs/packaging tests that pin the docs to the live registry.
4. **One-click deterministic demo** — namespaced, non-destructive, instantly populated.
5. **Production packaging** — architecture (Mermaid), decisions record, runbooks, release
   + rollback process, deployment blueprint, OSS governance, three-workflow CI.

## Weakest presentation points (fix in priority order)
1. **No visuals** — screenshots are paths, not pictures; no hero GIF. *(Milestone B)*
2. **No live demo** — clone-required to experience it.
3. **No tagged release yet** — `v0.1.0` not cut; the work still lives on a branch ahead of
   `main` (merge is the gate for everything else).
4. **Dependency heft** — large ML stack for a demo that runs on hashing embeddings; reads
   heavier than it is.
5. **Two-surface framing risk** — without the GIF, the chat ↔ operator connection is told,
   not shown.

## Missing proof points (what would remove all doubt)
- [ ] **8 screenshots** on the demo seed (see `screenshots/CAPTURE_PLAN.md`).
- [ ] **A 30–45s demo GIF** (alert → incident → drift → deliberate recovery).
- [ ] **A live, clickable demo URL** (seeded, gated, rate-limited).
- [ ] **`main` shows the platform + a `v0.1.0` release** (default-branch credibility).
- [ ] **Green CI badges on `main`** (the workflows have run; tie them to the default branch).
- [ ] *(Optional)* a one-paragraph "how the two surfaces connect" callout near the README top.

---

## Bottom line
The **substance is already portfolio-grade**; the **presentation is the bottleneck.** In
priority order: **(1) ship to `main` + tag `v0.1.0`**, **(2) add the visuals**, **(3) host a
live demo.** None require new product features — they make the existing system *provable at
a glance*, which is exactly what converts "good project" into "obviously built by someone
who understands production systems."
