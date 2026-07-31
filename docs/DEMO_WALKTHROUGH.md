# AIRA-X — Demo walkthrough (5–10 minutes)

A guided evaluation path that takes you from a fresh clone to "I've seen every important
capability, and I trust it." Everything here is deterministic — the seed produces the same
scenario every time — so what you see matches what's described.

**Audience:** a recruiter, staff engineer, CTO, or customer evaluating AIRA-X without a
live guide. Budget ~7 minutes.

---

## 0. Prerequisites (2 min)

```bash
# Backend
cd backend && python -m venv venv
# Windows: venv\Scripts\activate | macOS/Linux: source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
#  → set GROQ_API_KEY (any provider key) and set API_KEY to a value, e.g. demo-operator-key
python -m uvicorn app.main:app --reload --port 8000

# Frontend (new terminal)
cd frontend && npm install && npm run dev
```

- User product: `http://localhost:3000`
- Operator route: `http://localhost:3000/operator` (restricted notice only)
- The `API_KEY` you set is the **operator service key**.

> The operator service key is server-side only. The browser operator console is disabled
> until a server-side operator-auth boundary is designed and implemented.

---

## 1. Seed the demo (30 sec)

Use a trusted server-side client:

`curl -s -X POST localhost:8000/operator/demo/seed -H "X-API-Key: $API_KEY"`

You'll immediately see a **guided tour** render inline, plus the console populate. What was
created — deterministically, in the `demo.aira-x.local` namespace:
- **6 targets** across every readiness state
- **5 incidents** spanning healthy / drifted / missing / stale
- **audit history** dated across 24h / 7d / 30d

The legacy browser walkthrough below is retained as historical design context only; its
interactive operator steps are unavailable in this phase.

---

## 2. Inspect readiness (1 min)

In the **External sync** panel, look at the six targets. You should see a spread of states
with a **recommended next action** on each non-ready one:

| Target | State | Recommended action |
|---|---|---|
| PagerDuty Prod (demo) | **Ready** | — |
| Opsgenie EU (demo) | **Ready** | — |
| PagerDuty Staging (demo) | **Stale** | Validate |
| Generic Webhook (demo) | **Unverified** | Validate |
| PagerDuty Legacy (demo) | **Auth failed** | Rotate secret |
| Jira Bridge (demo) | **Disabled** | Re-enable |

✅ *What to notice:* readiness isn't a stored label — it's **computed from evidence**. The
"stale" target passed validation 9 days ago; the "auth failed" target's last connectivity
check was rejected. Each state carries a deterministic next step (a fixed table, not AI).

---

## 3. Inspect observability (1–2 min)

Look at the **Sync observability** panel (top of the Incidents tab).

- **SLO tiles** — target readiness ≈ **40%** (2 ready of 5 enabled), validation pass (24h)
  ≈ **33%**, reconciliation ≈ **67%**, sync ≈ **67%**. Tones are deterministic bands.
- **Targets by state** — the readiness rollup as chips.
- **Trend pass rates** — 24h per-category (validation / reconciliation / refresh / apply /
  external-action / sync). Switch your mental model to 7d/30d via the API to see trends.
- **Drift backlog: 3** — one drifted, one missing-external, one stale link, with the oldest
  item's age.
- **Candidate alert** — a **`repeated_auth_failures`** observation on *PagerDuty Legacy
  (demo)* (4 auth-failed validations in 24h).

✅ *What to notice:* this entire dashboard is **computed on read** from existing audit
history — no metrics tables, no background jobs. The alert is an *observation*, not a page;
nothing fires automatically. Rates with no data show "—", never a fake 0%.

```bash
# See the raw, deterministic computation:
curl -s localhost:8000/operator/incident-sync/metrics -H "X-API-Key: $API_KEY" | jq .slo,.drift,.alerts
```

---

## 4. Recover a drift (1–2 min)

Find the **ingest-worker** incident (its external incident was resolved, but the local
incident is still open → **drifted**). Expand it → **History**.

- The sync line reads **drifted** with the recommended action **Apply resolution**.
- **Refresh** re-observes external state — and *never* changes the local incident.
- **Apply** is the *only* action that brings the local incident in line with the observed
  external state — and it's explicit, attributable, and audited.

✅ *What to notice:* there is **no auto-heal**. Recovery is a deliberate operator action
with a stated blast radius. Inbound observation and local mutation are strictly separated.

---

## 5. Review the audit trail (1 min)

On any target, open its **health** view; on any incident, view its **reconciliation
history**.

- **Check events** — every validate / test / rotate / enable-disable, with the resulting
  readiness and a brief, **secret-free** reason.
- **Reconciliation events** — every refresh / apply / relink / detach, with outcome.
- Summaries surface the *latest meaningful event*, *last validation pass vs fail*, and
  *last reconciliation* without dumping the whole trail.

✅ *What to notice:* every state the dashboard shows is backed by a durable, explainable
event. Nothing is unexplained; nothing leaks a secret.

---

## 6. Verify operator/user separation (30 sec)

Open the **user product** at `http://localhost:3000` and use the chat. Notice that **none**
of the operator surface — targets, readiness, metrics, audit — is visible or reachable
here. The operator console is entirely service-key gated.

```bash
# Prove it: the operator endpoint rejects a request without the service key.
curl -s -o /dev/null -w "%{http_code}\n" localhost:8000/operator/incident-sync/metrics   # → 403
```

✅ *What to notice:* the user/operator boundary is a hard auth wall, and it's enforced by
tests (operator state never appears in user responses).

---

## 7. Reset (optional, 10 sec)

**Demo data** card → **Reset** (or `curl -s -X POST localhost:8000/operator/demo/reset -H
"X-API-Key: $API_KEY"`). Only the demo namespace is removed; any real data you created is
untouched.

---

## What you just evaluated

In ~7 minutes you saw: a computed readiness model, a deterministic observability
dashboard, capability-honest integrations, deliberate audited recovery, a durable
secret-free audit trail, and a hard operator/user boundary — on data that was seeded with
one click and is provably non-destructive. That's the difference between an AI demo and a
platform.

Next: **[ENGINEERING_DECISIONS.md](ENGINEERING_DECISIONS.md)** for *why* each of those
choices was made, or **[ARCHITECTURE.md](ARCHITECTURE.md)** for the flows behind them.
