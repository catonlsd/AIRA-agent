# AIRA-X — Engineering decisions record

Short, honest rationale for the non-obvious choices. Each entry is *decision → why →
consequence* — the reasoning a staff engineer would want before trusting the system. None
of these are accidental; they are the spine of the platform.

---

## 1. Local state is the source of truth

**Decision.** AIRA-X's own incident store is authoritative. Sync *exports* transitions
outward; the inbound `refresh` path only *observes and records* what an external tool
reports.

**Why.** The classic failure mode of an integration is letting a third party silently
become the system of record — then a vendor outage, a webhook replay, or a schema change
corrupts your truth. Keeping local state primary makes the blast radius of any external
misbehavior exactly zero.

**Consequence.** Drift between local and external is *expected and visible* rather than
hidden. It surfaces as a classified link status, not a silent overwrite. → see [#8](#8-inbound-sync-never-mutates-local-state).

---

## 2. Recovery is explicit (no auto-heal)

**Decision.** When external and local disagree, AIRA-X never reconciles automatically. It
classifies the drift and offers the operator deterministic actions — `refresh`, `apply`,
`relink`, `detach` — each with a stated blast radius.

**Why.** Auto-remediation is where integrations quietly do the wrong thing at 3 a.m. An
"apply the external resolution" that fires on its own will eventually close an incident
that was actually still burning. Making recovery a deliberate, audited operator action
trades a little convenience for a lot of trust — and it's what real on-call tooling does.

**Consequence.** Every recovery is attributable (actor + reconciliation event) and
explainable. The cost — an operator has to click — is the point.

---

## 3. Capability ≠ policy ≠ profile

**Decision.** Three separate layers govern what a target does:
- **Capability** — what the *adapter* can technically do (the hard ceiling).
- **Profile** — an onboarding preset that sets *defaults*.
- **Per-target override** — a tri-state (`null` / `true` / `false`) that can only *narrow*
  within capability, never exceed it.

Every effective decision reports its `source` (`capability` / `profile` / `override` /
`default`).

**Why.** Conflating "can" with "should" produces dishonest UIs that imply a vendor
supports something it doesn't, and brittle config where you can't tell *why* an action is
allowed. Separating the layers makes the console honest ("disabled by profile" vs
"adapter can't") and makes overrides safe by construction — they can't grant a capability
that isn't there.

**Consequence.** No fake vendor claims; adding an adapter is a capability declaration, and
policy logic doesn't have to change.

---

## 4. The profile system

**Decision.** Profiles (generic, PagerDuty, PagerDuty-observe-only, Opsgenie,
Jira-outbound) are **pure declarations over adapters** — name, label, kind, default
actions, default inbound fields. They set defaults at onboarding; they hold no vendor
logic.

**Why.** Onboarding is where mistakes happen (wrong actions enabled, surprising inbound
behavior). A preset that encodes a sane default posture — e.g. "PagerDuty observe-only"
that won't push outward until explicitly allowed — turns a 10-field config into one
choice, without hiding what it does.

**Consequence.** A profile can never exceed adapter capability (it's still policy-checked),
so a preset is convenience, not a backdoor.

---

## 5. The readiness model (computed, never stored stale)

**Decision.** A target's readiness (8 states: unverified / ready / degraded /
invalid_config / auth_failed / test_failed / disabled / stale) is **computed from durable
evidence** every time it's read — never written as a status string that can rot. Evidence
comes from two bounded, operator-triggered checks: `validate` (config + optional
connectivity) and a safe synthetic `test` (a no-op resolve through the real transport).

**Why.** A stored "status: ok" is a lie waiting to happen — it reflects the moment it was
written, not now. Computing readiness from timestamped evidence means it's always honest:
a target that passed last week but hasn't been re-checked reads `stale`, not `ready`.

**Consequence.** Trust has a half-life. Secret rotation invalidates evidence; the
scheduled sweep re-validates a bounded batch. "Is this integration actually trustworthy
right now?" has a real, derivable answer.

---

## 6. Deterministic metrics (computed on read)

**Decision.** The observability layer (`incident_metrics.py`) is a pure function over
extracted samples. The service does one bounded read of existing audit/history (capped at
the 5000 most-recent rows per stream) and feeds the math. No metrics tables, no background
aggregation, no AI summaries.

**Why.** A metrics pipeline that stores its own rollups is a second source of truth that
can disagree with reality. Computing on read guarantees the dashboard *is* the data — same
rows + same clock → same numbers — and makes every figure explainable down to the event.
Rates over zero samples are `null` (an honest "—"), never a misleading 0%/100%.

**Consequence.** Observability adds zero storage and zero drift risk; the trade-off
(scanning recent rows on request) is bounded and cheap at demo/early-production scale.

---

## 7. Demo namespace design

**Decision.** The demo seed creates data only in the `demo.aira-x.local` target namespace
and the `demo:` incident-signal namespace. Seed and reset operate *only* on those rows; a
feature flag (`demo_seed_enabled`) and operator auth gate the endpoints.

**Why.** A demo that clears the database or fakes states would be both dangerous and
dishonest. Namespacing makes the showcase non-destructive (real operator data provably
survives a reset) and the data *real* (states are set from honest evidence, so the
existing `compute_readiness` derives them — nothing is faked).

**Consequence.** The platform is instantly demonstrable on a fresh clone, safely, with one
click — and the same code paths that run the demo are the ones that run production.

---

## 8. Inbound sync never mutates local state

**Decision.** The single most load-bearing invariant: `refresh` and reconciliation **only
record** observed external state and classify drift. The *only* path that changes a local
incident from external observation is the explicit operator `apply` action.

**Why.** This is the concrete enforcement of [#1](#1-local-state-is-the-source-of-truth)
and [#2](#2-recovery-is-explicit-no-auto-heal). If inbound could mutate, every guarantee
above collapses: an external system would, in effect, be writing your truth. Drawing the
line here — observe always, mutate only on explicit, audited operator action — is what
makes "local is primary" true rather than aspirational.

**Consequence.** A vendor flapping, a stale webhook, or a mis-mapped status can never
change AIRA-X's incident state on its own. The worst it can do is show up as visible,
actionable drift.

---

## Cross-cutting: bounded, explainable, separated

Three properties recur because they're the difference between a demo and a platform:
- **Bounded** — sweeps, metrics reads, and trend windows are all capped; nothing
  fan-outs unboundedly to a vendor or the DB.
- **Explainable** — readiness, drift, metrics, and recommended actions are all derived
  deterministically and carry their reasoning (`source`, `reason`, `recommended_action`).
- **Separated** — the operator product is walled off from the user product by auth, and
  tests enforce that no operator state leaks into user responses.

See **[ARCHITECTURE.md](ARCHITECTURE.md)** for how these manifest in the flows.
