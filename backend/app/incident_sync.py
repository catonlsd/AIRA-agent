# File: backend/app/incident_sync.py
"""
External incident sync — operator-only OUTBOUND export of incident transitions.

A small, durable foundation for mirroring operator incident workflow
(open / acknowledge / silence / assign / note / recover / …) to an external
incident or ticket tool. Deliberately one-way (outbound from AIRA-X) and honest
about it — there is no inbound/bidirectional sync pretence.

Kept DISTINCT from webhook *event/alert routing* (`app/webhooks.py`): that fans
job-lifecycle events and alerts to subscribers; this mirrors *incident workflow
transitions* to incident tooling. Different concern, different tables, different
operator config — so neither muddies the other.

Each export is a durable `IncidentSyncRecord` snapshotting the curated incident
fields (never raw payloads/traces/secrets/owners), correlated to the source
incident. Sending is the single injectable primitive `_send` (HMAC-signed, like
the delivery layer) so the state machine and tests are network-free. Status runs
pending → synced | failed; retry is bounded by `incident_sync_max_attempts`, and a
terminal-failed record is operator-redrivable (bounded by
`incident_sync_max_redrives`). The whole surface is operator-gated at the routes.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime, timezone
from typing import Any, Callable, Optional
from uuid import uuid4

from app.core.config import settings
from app.db.database import Base, SessionLocal, engine
from app.db.models import (
    ExternalIncidentTarget,
    IncidentExternalLink,
    IncidentReconciliationEvent,
    IncidentSyncRecord,
)

STATUS_PENDING = "pending"
STATUS_SYNCED = "synced"
STATUS_FAILED = "failed"


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _csv_set(value: Optional[str]) -> Optional[set[str]]:
    if not value:
        return None
    items = {part.strip() for part in value.split(",") if part.strip()}
    return items or None


# ── adapter registry (target-kind-specific shaping + response parsing) ────────
#
# Every adapter keeps the SAME curated contract: it shapes the stable internal
# snapshot into the body a given target expects, and parses a target response into
# (external_ref, external_url) — nothing else changes in the state machine, so retry,
# redrive, linkage, and tests stay adapter-agnostic. The transport (`_send`) is a
# single injectable primitive. New vendors are a one-class addition; AIRA-X stays
# strictly OUTBOUND — no adapter reads external state back.


class GenericIncidentAdapter:
    """Default: send the curated envelope as-is; read a ref/url from common response
    headers or a small JSON body (never invents a link the target didn't return)."""

    kind = "generic"
    supports_refresh = True        # bounded inbound GET of {exists,status,url}
    supports_push_outward = True   # operator can explicitly re-send local state outward
    supports_status_sync = False   # only basic existence/status — NOT richer vendor fields
    # Richer BOUNDED inbound fields this adapter can normalize (G-13). Generic knows
    # none beyond the core exists/status/url. An adapter NEVER advertises a field it
    # can't safely normalize — and per-target policy can still narrow this further.
    inbound_fields = frozenset()
    # Per-action capabilities (G-11). Capability = what the adapter CAN do; the apply
    # policy (in `apply_policy`) checks this + state before allowing an action.
    supports_apply_resolved = True   # generic: if we observed resolved, operator may apply local recovery
    supports_apply_missing = True    # generic: if external is gone, operator may detach
    supports_external_resolve = False  # generic push has no typed "resolve" — just state notification
    supports_external_reopen = False   # ditto for reopen
    supports_external_acknowledge = False

    def shape(self, payload: dict) -> dict:
        return payload

    def parse(self, status_code: Optional[int], headers: dict, body: Optional[dict]) -> tuple[Optional[str], Optional[str]]:
        ref = (headers.get("X-Incident-Ref") or headers.get("x-incident-ref"))
        url = (headers.get("Location") or headers.get("location"))
        if body:
            ref = ref or body.get("ref") or body.get("id") or body.get("dedup_key")
            url = url or body.get("url") or body.get("html_url") or body.get("link")
        return ((str(ref)[:120] if ref else None), (str(url)[:500] if url else None))

    def parse_status(self, status_code: Optional[int], headers: dict, body: Optional[dict]) -> tuple[Optional[bool], Optional[str], Optional[str]]:
        """Bounded inbound parse → (external_exists, normalized_status, external_url).
        404 means the external incident is gone. Never raises."""
        if status_code == 404:
            return (False, EXT_MISSING, None)
        if not body:
            return (True, EXT_UNKNOWN, None)
        exists = body.get("exists")
        exists = True if exists is None else bool(exists)
        url = body.get("url") or body.get("html_url") or body.get("link")
        return (exists, _normalize_status(body.get("status") or body.get("state")),
                (str(url)[:500] if url else None))

    def parse_snapshot(self, status_code: Optional[int], headers: dict, body: Optional[dict]) -> dict:
        """Bounded normalized inbound snapshot. The base (generic) adapter only knows
        existence/status/url — richer fields are None. Adapters with
        `supports_status_sync` override this to add a few SAFE bounded fields. Never
        returns raw vendor bodies/comments."""
        exists, status, url = self.parse_status(status_code, headers, body)
        return _external_state(exists=exists, status=status, url=url)


class PagerDutyIncidentAdapter:
    """Adapter-specific pathway shaping the snapshot into a PagerDuty Events-v2-style
    envelope (event_action mapped from the incident transition, `dedup_key` = the
    incident signal) and parsing the returned `dedup_key`/url. This is real shaping +
    response parsing — it does NOT claim a verified PagerDuty connection; point a
    target of kind=pagerduty at any endpoint speaking this shape."""

    kind = "pagerduty"
    supports_refresh = True
    supports_push_outward = True   # event_action maps recovered→resolve, reopen→trigger
    supports_status_sync = True    # richer bounded inbound: assignee / urgency / updated / count
    inbound_fields = frozenset({"assignee", "severity", "updated_at", "comment_count"})
    # Vendor-specific outbound action mapping (G-11): a PagerDuty push of a local
    # `recovered` maps to a typed `resolve` event; a local `reopened` maps to a typed
    # `trigger` event. Generic targets can only re-send state, not a typed action.
    supports_apply_resolved = True
    supports_apply_missing = True
    supports_external_resolve = True
    supports_external_reopen = True
    supports_external_acknowledge = True   # PagerDuty event_action: acknowledge
    _EVENT_ACTION = {
        "opened": "trigger", "reopened": "trigger", "recovered": "resolve",
        "acknowledged": "acknowledge",
    }
    _URGENCY = {"high": "critical", "low": "warning"}

    def shape(self, payload: dict) -> dict:
        incident = payload.get("incident", {})
        action = payload.get("action", "")
        return {
            "event_action": self._EVENT_ACTION.get(action, "trigger"),
            "dedup_key": incident.get("signal") or incident.get("id"),
            "payload": {
                "summary": f"{incident.get('classification') or 'incident'} · {incident.get('subject') or ''}".strip(" ·"),
                "severity": incident.get("severity") or "warning",
                "source": "AIRA-X",
                "custom_details": {
                    "incident_id": incident.get("id"),
                    "state": incident.get("state"),
                    "assignee": incident.get("assignee"),
                    "note": incident.get("note"),
                    "action": action,
                    "actor": payload.get("actor"),
                },
            },
        }

    def parse(self, status_code: Optional[int], headers: dict, body: Optional[dict]) -> tuple[Optional[str], Optional[str]]:
        ref = url = None
        if body:
            ref = body.get("dedup_key") or body.get("id")
            url = body.get("url") or body.get("html_url") or (headers.get("Location") if headers else None)
        else:
            ref = (headers.get("X-Incident-Ref") if headers else None)
        return ((str(ref)[:120] if ref else None), (str(url)[:500] if url else None))

    def parse_status(self, status_code: Optional[int], headers: dict, body: Optional[dict]) -> tuple[Optional[bool], Optional[str], Optional[str]]:
        """PagerDuty incidents expose status triggered/acknowledged/resolved."""
        if status_code == 404:
            return (False, EXT_MISSING, None)
        if not body:
            return (True, EXT_UNKNOWN, None)
        url = body.get("url") or body.get("html_url")
        return (True, _normalize_status(body.get("status")), (str(url)[:500] if url else None))

    def parse_snapshot(self, status_code: Optional[int], headers: dict, body: Optional[dict]) -> dict:
        """Richer BOUNDED PagerDuty snapshot: a few safe normalized fields parsed from
        an incident-shaped response (the `assignments[].assignee.summary`, `urgency`,
        `last_status_change_at`, and an alert/note *count* — never the bodies)."""
        exists, status, url = self.parse_status(status_code, headers, body)
        if not body:
            return _external_state(exists=exists, status=status, url=url)
        # Assignee display name (first assignment) — bounded, no contact details.
        assignee = None
        assignments = body.get("assignments")
        if isinstance(assignments, list) and assignments:
            who = (assignments[0] or {}).get("assignee") or {}
            assignee = who.get("summary") or who.get("name")
        assignee = assignee or body.get("assignee")
        severity = self._URGENCY.get(str(body.get("urgency") or "").lower())
        updated = body.get("last_status_change_at") or body.get("updated_at")
        # A bounded COUNT only — never the alert/note contents.
        count = None
        for key in ("alert_counts", "alerts", "notes"):
            value = body.get(key)
            if isinstance(value, dict) and "all" in value:
                count = value.get("all")
                break
            if isinstance(value, list):
                count = len(value)
                break
        return _external_state(exists=exists, status=status, url=url, assignee=assignee,
                               severity=severity, updated_at=updated, comment_count=count)


class OpsgenieIncidentAdapter:
    """Second first-class richer adapter (G-14): shapes the snapshot into an Opsgenie
    Alert-API-style envelope (`action` create/close/acknowledge, `alias` = the incident
    signal) and parses an alert-shaped response (status open/acked/closed, owner,
    priority P1–P5). Real shaping + bounded parsing — it does NOT claim a verified
    Opsgenie connection; point a target of kind=opsgenie at any endpoint speaking this
    shape. Honestly has NO clean `reopen` mapping, so `external_reopen` stays False."""

    kind = "opsgenie"
    supports_refresh = True
    supports_push_outward = True
    supports_status_sync = True
    inbound_fields = frozenset({"assignee", "severity", "updated_at"})  # no bounded note count in basic alert
    supports_apply_resolved = True
    supports_apply_missing = True
    supports_external_resolve = True       # → close the alert
    supports_external_reopen = False       # Opsgenie has no clean reopen — honest
    supports_external_acknowledge = True   # → acknowledge the alert
    _ACTION = {"opened": "create", "reopened": "create", "recovered": "close",
               "acknowledged": "acknowledge"}
    _PRIORITY = {"p1": "critical", "p2": "critical", "p3": "warning", "p4": "warning", "p5": "info"}

    def shape(self, payload: dict) -> dict:
        incident = payload.get("incident", {})
        action = payload.get("action", "")
        return {
            "action": self._ACTION.get(action, "create"),
            "alias": incident.get("signal") or incident.get("id"),
            "message": f"{incident.get('classification') or 'incident'} · {incident.get('subject') or ''}".strip(" ·"),
            "source": "AIRA-X",
            "details": {
                "incident_id": incident.get("id"),
                "state": incident.get("state"),
                "assignee": incident.get("assignee"),
                "note": incident.get("note"),
                "action": action,
                "actor": payload.get("actor"),
            },
        }

    def parse(self, status_code: Optional[int], headers: dict, body: Optional[dict]) -> tuple[Optional[str], Optional[str]]:
        ref = url = None
        if body:
            ref = body.get("alias") or body.get("id") or body.get("tinyId")
            url = body.get("url") or body.get("html_url") or (headers.get("Location") if headers else None)
        else:
            ref = (headers.get("X-Incident-Ref") if headers else None)
        return ((str(ref)[:120] if ref else None), (str(url)[:500] if url else None))

    def parse_status(self, status_code: Optional[int], headers: dict, body: Optional[dict]) -> tuple[Optional[bool], Optional[str], Optional[str]]:
        if status_code == 404:
            return (False, EXT_MISSING, None)
        if not body:
            return (True, EXT_UNKNOWN, None)
        # Opsgenie surfaces both a status (open/closed) and an acknowledged flag.
        raw = body.get("status")
        if body.get("acknowledged") is True and raw != "closed":
            raw = "acknowledged"
        url = body.get("url") or body.get("html_url")
        return (True, _normalize_status(raw), (str(url)[:500] if url else None))

    def parse_snapshot(self, status_code: Optional[int], headers: dict, body: Optional[dict]) -> dict:
        exists, status, url = self.parse_status(status_code, headers, body)
        if not body:
            return _external_state(exists=exists, status=status, url=url)
        owner = body.get("owner")
        if isinstance(owner, dict):
            owner = owner.get("username") or owner.get("name")
        severity = self._PRIORITY.get(str(body.get("priority") or "").lower())
        updated = body.get("updatedAt") or body.get("updated_at")
        return _external_state(exists=exists, status=status, url=url, assignee=owner,
                               severity=severity, updated_at=updated)


class OutboundOnlyAdapter(GenericIncidentAdapter):
    """Reserved target kinds with no real inbound adapter yet: outbound shaping +
    push-outward work (via the generic envelope), but refresh / relink-validation are
    honestly unsupported — AIRA-X will not claim to KNOW external state for these
    until a real adapter lands. (Outbound-only = it can send, it can't read back.)"""

    supports_refresh = False
    # supports_push_outward stays True (inherited): outbound is exactly what it does.
    # Cannot observe → cannot apply external state locally. Cannot map typed actions.
    supports_apply_resolved = False
    supports_apply_missing = False
    supports_external_resolve = False
    supports_external_reopen = False
    supports_external_acknowledge = False


_ADAPTERS = {
    "generic": GenericIncidentAdapter(),
    "pagerduty": PagerDutyIncidentAdapter(),
    "opsgenie": OpsgenieIncidentAdapter(),
    "jira": OutboundOnlyAdapter(),
}
_GENERIC = _ADAPTERS["generic"]
_KINDS = set(_ADAPTERS)


def adapter_for(kind: Optional[str]):
    return _ADAPTERS.get(kind or "generic", _GENERIC)


def adapter_capabilities(kind: Optional[str]) -> dict[str, Any]:
    """The honest, explicit capability set for a target kind. `relink_validation`
    needs a bounded inbound check, so it tracks `supports_refresh`. `status_sync` is
    the richer-than-generic inbound (bounded assignee/severity/updated/count).
    Per-action capabilities (G-11): `apply_resolved`/`apply_missing` are bounded
    INBOUND-state→LOCAL applications (only meaningful when the adapter can observe);
    `external_resolve`/`external_reopen` are vendor-typed OUTBOUND actions a richer
    adapter maps onto a real vendor event (vs generic push which just sends state).
    `support_level` is a single label for the console: rich / refresh / outbound_only."""
    adapter = adapter_for(kind)
    refresh = bool(getattr(adapter, "supports_refresh", False))
    status_sync = bool(getattr(adapter, "supports_status_sync", False))
    level = "rich" if status_sync else ("refresh" if refresh else "outbound_only")
    fields = adapter_inbound_fields(kind)
    return {
        "refresh": refresh,
        "push_outward": bool(getattr(adapter, "supports_push_outward", False)),
        "relink_validation": refresh,
        "status_sync": status_sync,
        "apply_resolved": bool(getattr(adapter, "supports_apply_resolved", False)),
        "apply_missing": bool(getattr(adapter, "supports_apply_missing", False)),
        "external_resolve": bool(getattr(adapter, "supports_external_resolve", False)),
        "external_reopen": bool(getattr(adapter, "supports_external_reopen", False)),
        "external_acknowledge": bool(getattr(adapter, "supports_external_acknowledge", False)),
        # Richer BOUNDED inbound fields this adapter can normalize (G-13).
        "inbound_fields": {f: (f in fields) for f in _INBOUND_FIELDS},
        "support_level": level,
    }


def adapter_inbound_fields(kind: Optional[str]) -> frozenset:
    """The bounded set of richer inbound fields a target kind can normalize."""
    return frozenset(getattr(adapter_for(kind), "inbound_fields", frozenset()))


# ── Action policy (G-11 → G-12): capability + PER-TARGET override, audited refusals ──
#
# Three honest layers, in precedence order:
#   1. adapter CAPABILITY  — what the adapter kind can technically do (class flags).
#   2. target OVERRIDE     — per-target tri-state: NULL = adapter default, True =
#                            explicitly permitted (still bounded by capability),
#                            False = explicitly denied for THIS target. An override
#                            can only NARROW capability, never enable beyond it.
#   3. incident STATE      — whether the action is applicable right now (handled by
#                            the caller / `available_actions`).
# `target_action_policy` resolves layers 1+2; codes are stable so the audit trail and
# console group refusals reliably.

POLICY_ALLOWED = "allowed"
POLICY_DENIED_CAPABILITY = "denied:capability"
POLICY_DENIED_TARGET = "denied:target_policy"
POLICY_DENIED_PROFILE = "denied:profile"      # disabled by the target's profile default (G-14)
POLICY_DENIED_UNKNOWN = "denied:unknown_action"

# action → (capability key, per-target override field). The single source of truth
# tying an action to the adapter flag and the target column that can narrow it.
_ACTION_POLICY = {
    "accept_resolved": ("apply_resolved", "allow_apply_resolved"),
    "accept_missing": ("apply_missing", "allow_apply_missing"),
    "external_resolve": ("external_resolve", "allow_external_resolve"),
    "external_reopen": ("external_reopen", "allow_external_reopen"),
    "external_acknowledge": ("external_acknowledge", "allow_external_acknowledge"),
    "resend_current_state": ("push_outward", "allow_push_outward"),
}
# The per-target override columns operators can tune (read + PATCH).
TARGET_OVERRIDE_FIELDS = tuple(field for _cap, field in _ACTION_POLICY.values())

# ── Inbound-state policy (G-13): per-target visibility of richer external fields ──
#
# Same three-layer model, applied to INBOUND data instead of outbound actions:
#   1. adapter CAPABILITY  — which richer fields the adapter can normalize at all.
#   2. target OVERRIDE     — per-target tri-state: NULL = adapter default (visible if
#                            capable), True = explicitly permitted, False = hidden for
#                            THIS target. Can only NARROW, never reveal beyond capability.
#   3. read-time MASK      — refresh stores only permitted fields AND reads mask any
#                            field a later policy change disabled.
# Suggestions never become state — they are derived ONLY from permitted fields, and a
# target can suppress them wholesale.

# richer field → (capability key in adapter.inbound_fields, per-target override column)
_INBOUND_FIELD_POLICY = {
    "assignee": ("assignee", "allow_external_assignee"),
    "severity": ("severity", "allow_external_severity"),
    "updated_at": ("updated_at", "allow_external_updated_at"),
    "comment_count": ("comment_count", "allow_external_comment_count"),
}
_INBOUND_FIELDS = tuple(_INBOUND_FIELD_POLICY)
# Suggestions are a derived view (capability = any refresh-capable adapter), gated by
# their own master override so a target can stay observable but silent on suggestions.
TARGET_INBOUND_OVERRIDE_FIELDS = (
    tuple(field for _cap, field in _INBOUND_FIELD_POLICY.values()) + ("allow_external_suggestions",))
# Every per-target override an operator can tune (outbound actions + inbound fields).
ALL_TARGET_OVERRIDE_FIELDS = TARGET_OVERRIDE_FIELDS + TARGET_INBOUND_OVERRIDE_FIELDS


# ── Adapter profiles / presets (G-14): default policy that sits BETWEEN capability ──
# and per-target overrides. A profile bundles a vendor/use-case's sane defaults so an
# operator can onboard a target without hand-setting every override. Precedence:
#   1. CAPABILITY      — adapter can do it at all (hard ceiling; profile never exceeds).
#   2. PROFILE default — sane baseline for this profile (`default_actions`/`default_inbound`;
#                        a value of False disables-by-default; missing = capability default).
#   3. target OVERRIDE — explicit per-target tri-state; MORE specific than the profile,
#                        so an explicit True can re-enable what a profile disabled.
#   4. incident STATE  — applicability right now (handled by the caller).
# Profiles are pure declarations over EXISTING adapters — no new vendor logic hides here.

_PROFILES: dict[str, dict[str, Any]] = {
    "generic": {
        "name": "generic", "label": "Generic webhook", "kind": "generic",
        "summary": "Bounded outbound export + existence/status refresh. No richer fields.",
        "default_actions": {}, "default_inbound": {},
    },
    "pagerduty": {
        "name": "pagerduty", "label": "PagerDuty", "kind": "pagerduty",
        "summary": "Rich: status sync (assignee/severity/updated/notes), typed resolve/reopen/acknowledge.",
        "default_actions": {}, "default_inbound": {},
    },
    "pagerduty-readonly": {
        "name": "pagerduty-readonly", "label": "PagerDuty (observe-only)", "kind": "pagerduty",
        "summary": "Same rich inbound observation, but NO outbound mutations by default — watch, don't push.",
        # Disable every action that changes the EXTERNAL system; local apply stays available.
        "default_actions": {"external_resolve": False, "external_reopen": False,
                            "external_acknowledge": False, "resend_current_state": False},
        "default_inbound": {},
    },
    "opsgenie": {
        "name": "opsgenie", "label": "Opsgenie", "kind": "opsgenie",
        "summary": "Rich: status sync (owner/priority/updated), typed close/acknowledge. No reopen.",
        "default_actions": {}, "default_inbound": {},
    },
    "jira-outbound": {
        "name": "jira-outbound", "label": "Jira (outbound-only)", "kind": "jira",
        "summary": "Outbound export only — Jira state is not read back (no refresh / inbound).",
        "default_actions": {}, "default_inbound": {},
    },
}
# Profile names selectable when creating/updating a target.
PROFILE_NAMES = tuple(_PROFILES)
# The default profile for a bare adapter kind (back-compat: kind == profile name).
_KIND_DEFAULT_PROFILE = {"generic": "generic", "pagerduty": "pagerduty",
                         "opsgenie": "opsgenie", "jira": "jira-outbound"}


def profile_for(name: Optional[str]) -> Optional[dict[str, Any]]:
    return _PROFILES.get(name or "")


def default_profile_for_kind(kind: Optional[str]) -> str:
    return _KIND_DEFAULT_PROFILE.get(kind or "generic", kind or "generic")


def profile_default(profile_name: Optional[str], category: str, key: str) -> Optional[bool]:
    """The profile's default for one action/inbound key, or None if the profile leaves
    it at the capability default. `category` is 'actions' or 'inbound'."""
    prof = _PROFILES.get(profile_name or "")
    if prof is None:
        return None
    table = prof.get("default_actions" if category == "actions" else "default_inbound", {})
    return table.get(key)


def _clean_profile(prof: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": prof["name"], "label": prof["label"], "kind": prof["kind"],
        "summary": prof["summary"],
        "support_level": adapter_capabilities(prof["kind"])["support_level"],
        "default_actions": prof["default_actions"], "default_inbound": prof["default_inbound"],
    }


def list_profiles() -> list[dict[str, Any]]:
    return [_clean_profile(p) for p in _PROFILES.values()]


def inbound_field_policy(adapter_kind: Optional[str], overrides: Optional[dict],
                         field: str, profile: Optional[str] = None) -> tuple[bool, str, str]:
    """Resolve capability → profile default → per-target override for one inbound field
    (or the special `suggestions` master) → (allowed, code, reason)."""
    if field == "suggestions":
        capable = adapter_capabilities(adapter_kind)["refresh"]
        override_field = "allow_external_suggestions"
        label = "external suggestions"
    else:
        mapping = _INBOUND_FIELD_POLICY.get(field)
        if mapping is None:
            return (False, POLICY_DENIED_UNKNOWN, f"unknown inbound field: {field!r}")
        cap_name, override_field = mapping
        capable = cap_name in adapter_inbound_fields(adapter_kind)
        label = f"external {field}"
    if not capable:
        return (False, POLICY_DENIED_CAPABILITY, f"adapter cannot provide {label}")
    override = (overrides or {}).get(override_field)
    if override is False:
        return (False, POLICY_DENIED_TARGET, f"target policy hides {label}")
    if override is None and profile_default(profile, "inbound", field) is False:
        return (False, POLICY_DENIED_PROFILE, f"profile default hides {label}")
    return (True, POLICY_ALLOWED, f"{label} is permitted for this target")


def inbound_field_allowed(adapter_kind: Optional[str], overrides: Optional[dict], field: str,
                          profile: Optional[str] = None) -> bool:
    return inbound_field_policy(adapter_kind, overrides, field, profile)[0]


def target_action_policy(adapter_kind: Optional[str], overrides: Optional[dict],
                         action: str, profile: Optional[str] = None) -> tuple[bool, str, str]:
    """Resolve capability → profile default → per-target override for one action →
    (allowed, code, reason). An explicit override is MORE specific than the profile."""
    mapping = _ACTION_POLICY.get(action)
    if mapping is None:
        return (False, POLICY_DENIED_UNKNOWN, f"unknown action: {action!r}")
    cap_key, override_field = mapping
    caps = adapter_capabilities(adapter_kind)
    if not caps.get(cap_key):
        return (False, POLICY_DENIED_CAPABILITY, f"adapter does not support {action}")
    override = (overrides or {}).get(override_field)
    if override is False:
        return (False, POLICY_DENIED_TARGET, f"target policy disables {action}")
    if override is None and profile_default(profile, "actions", action) is False:
        return (False, POLICY_DENIED_PROFILE, f"profile default disables {action}")
    return (True, POLICY_ALLOWED, f"{action} is permitted for this target")


def apply_policy(adapter_kind: Optional[str], apply_action: str,
                 overrides: Optional[dict] = None, profile: Optional[str] = None) -> tuple[bool, str, str]:
    """Back-compat wrapper for the inbound-apply actions (accept_resolved /
    accept_missing). Delegates to `target_action_policy`."""
    return target_action_policy(adapter_kind, overrides, apply_action, profile)


def _decision_source(capable: bool, override: Optional[bool], code: str) -> str:
    """Where the EFFECTIVE decision came from — for honest console explainability."""
    if not capable:
        return "capability"
    if override is not None:
        return "override"
    if code == POLICY_DENIED_PROFILE:
        return "profile"
    return "default"


def effective_target_policy(adapter_kind: Optional[str], overrides: Optional[dict],
                            profile: Optional[str] = None) -> dict[str, Any]:
    """Curated capability-vs-profile-vs-override-vs-effective view for one target —
    exactly what `GET /operator/incident-targets/{id}/policy` returns. Each entry's
    `source` says whether the effective decision is from capability / profile / override."""
    caps = adapter_capabilities(adapter_kind)
    actions = {}
    for action in _ACTION_POLICY:
        cap_key, override_field = _ACTION_POLICY[action]
        capable = bool(caps.get(cap_key))
        override = (overrides or {}).get(override_field)
        allowed, code, reason = target_action_policy(adapter_kind, overrides, action, profile)
        actions[action] = {
            "capable": capable,
            "profile_default": profile_default(profile, "actions", action),
            "override": override,          # None / True / False
            "effective": allowed,
            "source": _decision_source(capable, override, code),
            "code": code,
            "reason": reason,
        }
    inbound = {}
    for field in (*_INBOUND_FIELDS, "suggestions"):
        override_field = ("allow_external_suggestions" if field == "suggestions"
                          else _INBOUND_FIELD_POLICY[field][1])
        capable = (caps["refresh"] if field == "suggestions"
                   else field in adapter_inbound_fields(adapter_kind))
        override = (overrides or {}).get(override_field)
        allowed, code, reason = inbound_field_policy(adapter_kind, overrides, field, profile)
        inbound[field] = {
            "capable": capable,
            "profile_default": profile_default(profile, "inbound", field),
            "override": override,
            "effective": allowed,
            "source": _decision_source(capable, override, code),
            "code": code,
            "reason": reason,
        }
    return {"kind": adapter_kind, "profile": profile, "capabilities": caps,
            "actions": actions, "inbound": inbound}


# ── external status normalization + link-status classification (pure) ─────────

EXT_OPEN = "open"
EXT_ACKNOWLEDGED = "acknowledged"
EXT_RESOLVED = "resolved"
EXT_MISSING = "missing"
EXT_UNKNOWN = "unknown"

LINK_LINKED = "linked"
LINK_NEVER = "never_linked"
LINK_STALE = "stale"
LINK_MISSING = "missing_external"
LINK_DRIFTED = "drifted"
LINK_REFRESHED = "refreshed"
LINK_DETACHED = "detached"

_LOCAL_OPEN = {"open", "acknowledged", "silenced"}
_EXT_CLOSED = {EXT_RESOLVED, "closed", "done"}
_EXT_OPEN = {EXT_OPEN, "triggered", EXT_ACKNOWLEDGED}


def _normalize_status(raw: Optional[str]) -> str:
    if not raw:
        return EXT_UNKNOWN
    value = str(raw).strip().lower()
    if value in _EXT_CLOSED:
        return EXT_RESOLVED
    if value in ("triggered", "open", "firing"):
        return EXT_OPEN
    if value in ("acknowledged", "ack", "acked"):
        return EXT_ACKNOWLEDGED
    return value[:24]


_HIGH_SEVERITY = {"critical", "high", "urgent", "sev1", "p1"}


def _external_state(*, exists: Optional[bool], status: Optional[str], url: Optional[str] = None,
                    assignee: Optional[str] = None, severity: Optional[str] = None,
                    updated_at: Optional[str] = None, comment_count: Optional[int] = None) -> dict[str, Any]:
    """A BOUNDED, normalized external snapshot. Every field is size-clamped and there
    is NO raw-payload escape hatch — adapters can only ever surface these few fields."""
    try:
        count = int(comment_count) if comment_count is not None else None
    except (TypeError, ValueError):
        count = None
    return {
        "exists": exists,
        "status": status,
        "url": (str(url)[:500] if url else None),
        "assignee": (str(assignee)[:120] if assignee else None),
        "severity": (str(severity)[:24] if severity else None),
        "updated_at": (str(updated_at)[:40] if updated_at else None),
        "comment_count": (count if (count is None or 0 <= count <= 100000) else None),
    }


def external_state_suggestions(local_incident: Optional[dict], link: dict) -> list[dict[str, str]]:
    """Pure, bounded operator suggestions derived from the last observed external
    snapshot vs the local incident. Suggestions are advisory only — never mutations.
    Empty until a refresh has actually observed external state."""
    out: list[dict[str, str]] = []
    if not link or link.get("detached"):
        return out
    local = local_incident or {}
    local_state = local.get("state")
    local_owner = local.get("assignee")
    ext_status = link.get("external_status")
    ext_assignee = link.get("external_assignee")
    ext_severity = link.get("external_severity")
    if link.get("external_exists") is False:
        out.append({"code": "external_missing", "tone": "bad",
                    "text": "External incident no longer exists — consider detaching."})
        return out
    if ext_status is None:
        return out  # nothing observed yet
    open_local = local_state in _LOCAL_OPEN
    if ext_status in _EXT_CLOSED and open_local:
        out.append({"code": "external_resolved", "tone": "bad",
                    "text": "External is resolved while this incident is still open — consider applying."})
    if ext_status == EXT_ACKNOWLEDGED and open_local:
        who = f" by {ext_assignee}" if ext_assignee else ""
        out.append({"code": "external_acknowledged", "tone": "warn",
                    "text": f"Acknowledged externally{who}."})
    if ext_assignee and local_owner and ext_assignee != local_owner:
        out.append({"code": "owner_mismatch", "tone": "warn",
                    "text": f"External owner ({ext_assignee}) differs from local owner ({local_owner})."})
    if (ext_severity or "").lower() in _HIGH_SEVERITY:
        out.append({"code": "high_severity", "tone": "warn",
                    "text": f"External severity is {ext_severity} — worth a review."})
    if not out:
        aligned = (ext_status in _EXT_OPEN and open_local) or (ext_status in _EXT_CLOSED and local_state == "recovered")
        if aligned:
            out.append({"code": "aligned", "tone": "good", "text": "Aligned with external — no action needed."})
    return out[:4]


# Effect of an action on truth: which side does it actually mutate? Operators see this
# label so a button's blast radius is never a surprise.
EFFECT_NONE = "none"          # observe only (e.g. refresh)
EFFECT_LOCAL = "local"        # changes the LOCAL incident state (only apply_resolved)
EFFECT_LINKAGE = "linkage"    # changes incident↔external link state, not the incident
EFFECT_EXTERNAL = "external"  # pushes a change to the external system


_ACTION_LABELS = {
    "refresh": "Refresh", "redrive": "Redrive failed sync", "detach": "Detach",
    "relink": "Relink", "apply_resolved": "Apply external resolution",
    "apply_missing": "Detach missing external", "push": "Push outward",
    "external_resolve": "Resolve externally", "external_reopen": "Reopen externally",
    "external_acknowledge": "Acknowledge externally",
}


def _any_target_allows(active_links: list[dict], action: str) -> tuple[bool, str]:
    """Is `action` permitted (capability + per-target override) for ANY active link?
    Returns (available, reason). The reason explains the *closest* refusal so the
    operator sees whether capability or target policy is the blocker."""
    if not active_links:
        return (False, "no active external link")
    reasons: list[str] = []
    for link in active_links:
        allowed, _code, reason = target_action_policy(
            link.get("target_kind"), link.get("policy_overrides"), action, link.get("profile"))
        if allowed:
            return (True, "")
        reasons.append(reason)
    return (False, reasons[0] if reasons else "not permitted")


def _available_actions(*, links: list[dict], active_links: list[dict],
                       failed: list[dict], latest: Optional[dict],
                       apply_action: Optional[str], worst_link: Optional[dict]) -> list[dict]:
    """Per-action availability list — `{action, label, available, reason, effect}`.
    Combines adapter capability + PER-TARGET policy override + current incident state
    into one curated list, so the console (and `/sync/actions`) doesn't re-derive
    gating logic. Precedence: capability → target override → incident-state."""
    out: list[dict] = []

    def push(action: str, available: bool, reason: str, effect: str) -> None:
        out.append({"action": action, "label": _ACTION_LABELS[action],
                    "available": available, "reason": reason, "effect": effect})

    # Refresh — observe only. Available if any active link has a refresh-capable adapter.
    refresh_ok = any(link["refresh_supported"] and not link["detached"] for link in links)
    push("refresh", refresh_ok, "" if refresh_ok else "no refresh-capable target",
         EFFECT_NONE)

    # Redrive — re-send a previously failed external sync.
    redrive_ok = bool(failed and (latest is None or latest["status"] != STATUS_SYNCED))
    push("redrive", redrive_ok,
         "" if redrive_ok else ("no failed sync to redrive" if not failed else "external sync is already up to date"),
         EFFECT_EXTERNAL)

    # Detach — linkage only.
    detach_ok = any(not link["detached"] for link in links)
    push("detach", detach_ok, "" if detach_ok else "no active link to detach", EFFECT_LINKAGE)

    # Relink — linkage only (adapter must support verification).
    relink_ok = any(link["refresh_supported"] for link in links)
    push("relink", relink_ok, "" if relink_ok else "adapter cannot verify links",
         EFFECT_LINKAGE)

    # Apply-from-external (split into the two distinct typed actions). Available only
    # when the observed disagreement offers it AND capability + per-target policy
    # allow it — evaluated against the SPECIFIC link the disagreement comes from.
    for typed in ("accept_resolved", "accept_missing"):
        action_key = "apply_resolved" if typed == "accept_resolved" else "apply_missing"
        effect = EFFECT_LOCAL if typed == "accept_resolved" else EFFECT_LINKAGE
        if apply_action == typed and worst_link is not None:
            allowed, _code, reason = target_action_policy(
                worst_link.get("target_kind"), worst_link.get("policy_overrides"), typed,
                worst_link.get("profile"))
            push(action_key, allowed, "" if allowed else reason, effect)
        else:
            push(action_key, False, "external state does not currently offer this", effect)

    # Push outward — external. Available if any active link's target permits it.
    push_ok, push_reason = _any_target_allows(active_links, "resend_current_state")
    push("push", push_ok, "" if push_ok else (push_reason or "no push-capable target"),
         EFFECT_EXTERNAL)

    # Vendor-typed external actions (G-12) — external effect, capability + policy gated.
    for action in ("external_resolve", "external_reopen", "external_acknowledge"):
        ok, reason = _any_target_allows(active_links, action)
        push(action, ok, "" if ok else reason, EFFECT_EXTERNAL)
    return out


def classify_link_status(*, local_state: Optional[str], last_synced_at: Optional[datetime],
                         last_checked_at: Optional[datetime], external_exists: Optional[bool],
                         external_status: Optional[str], now: datetime,
                         stale_seconds: int, detached: bool = False) -> tuple[str, str]:
    """Pure, bounded reconciliation verdict for one link → (status, reason). Local
    state stays primary; this only *describes* alignment, it never mutates anything."""
    if detached:
        return (LINK_DETACHED, "intentionally detached")
    if last_synced_at is None:
        return (LINK_NEVER, "never linked")
    open_local = (local_state in _LOCAL_OPEN)
    closed_local = (local_state == "recovered")
    # Inbound facts (only meaningful once a refresh has happened).
    if external_exists is False:
        return (LINK_MISSING, "external incident not found")
    if external_status in _EXT_CLOSED and open_local:
        return (LINK_DRIFTED, "external resolved but incident still open")
    if external_status in _EXT_OPEN and closed_local:
        return (LINK_DRIFTED, "incident recovered but external still open")
    # Age-based staleness (no successful sync within the bounded window).
    age = (now - last_synced_at).total_seconds()
    if age > max(1, stale_seconds):
        return (LINK_STALE, "no successful sync recently")
    if last_checked_at is not None:
        return (LINK_REFRESHED, "checked and aligned")
    return (LINK_LINKED, "linked")


# Severity ordering for the incident-level rollup (worst link wins). Detached is an
# intentional operator choice → lowest, never flagged as actionable drift.
_LINK_SEVERITY = {LINK_DETACHED: 0, LINK_NEVER: 0, LINK_LINKED: 1, LINK_REFRESHED: 1,
                  LINK_STALE: 2, LINK_DRIFTED: 3, LINK_MISSING: 4}
_ACTIONABLE = {LINK_DRIFTED, LINK_MISSING, LINK_STALE}


class IncidentSyncService:
    def __init__(self, session_factory: Callable[[], Any] = SessionLocal) -> None:
        self._session_factory = session_factory
        self._ensure_tables()

    def _ensure_tables(self) -> None:
        try:
            ExternalIncidentTarget.__table__.create(bind=engine, checkfirst=True)
            IncidentSyncRecord.__table__.create(bind=engine, checkfirst=True)
            IncidentExternalLink.__table__.create(bind=engine, checkfirst=True)
            IncidentReconciliationEvent.__table__.create(bind=engine, checkfirst=True)
        except Exception:
            Base.metadata.create_all(bind=engine)
        from app.db.database import ensure_runtime_columns
        ensure_runtime_columns()  # additive: external_url / link reconciliation columns

    # ── targets (operator-only config) ────────────────────────────────────────

    def create_target(self, *, name: str, url: str, kind: str = "generic",
                      profile: Optional[str] = None, sync_actions: Optional[str] = None,
                      secret: Optional[str] = None, enabled: bool = True) -> Optional[dict[str, Any]]:
        name, url = (name or "").strip(), (url or "").strip()
        if not name or not url.lower().startswith(("http://", "https://")):
            return None
        # A profile, if given, is the source of truth for the adapter kind (onboarding
        # from a preset). Otherwise the kind picks its default profile.
        if profile is not None:
            prof = profile_for(profile)
            if prof is None:
                return None
            kind = prof["kind"]
        else:
            profile = default_profile_for_kind(kind)
        if kind not in _KINDS:
            return None
        with self._session_factory() as session:
            row = ExternalIncidentTarget(
                id=uuid4().hex, name=name[:120], url=url[:500], kind=kind, profile=profile,
                enabled=bool(enabled), sync_actions=(sync_actions or None),
                secret=(secret or None))
            session.add(row)
            session.commit()
            return self._clean_target(row)

    def update_target(self, target_id: str, **changes: Any) -> Optional[dict[str, Any]]:
        allowed = {"name", "url", "kind", "enabled", "sync_actions", "secret"}
        # Per-target overrides (outbound actions + inbound fields) are tri-state —
        # None means "leave unchanged" here; explicit True/False set the override.
        override_fields = set(ALL_TARGET_OVERRIDE_FIELDS)
        with self._session_factory() as session:
            row = session.get(ExternalIncidentTarget, target_id)
            if row is None:
                return None
            for key, value in changes.items():
                if value is None:
                    continue
                if key in override_fields:
                    setattr(row, key, bool(value))
                    continue
                if key == "profile":
                    prof = profile_for(value)
                    if prof is None:
                        return None
                    row.profile = value
                    row.kind = prof["kind"]  # switching profile re-points the adapter kind
                    continue
                if key not in allowed:
                    continue
                if key == "kind" and value not in _KINDS:
                    return None
                if key == "url" and not str(value).lower().startswith(("http://", "https://")):
                    return None
                setattr(row, key, value)
            session.commit()
            return self._clean_target(row)

    def delete_target(self, target_id: str) -> bool:
        with self._session_factory() as session:
            row = session.get(ExternalIncidentTarget, target_id)
            if row is None:
                return False
            session.delete(row)
            session.commit()
            return True

    def list_targets(self) -> list[dict[str, Any]]:
        try:
            with self._session_factory() as session:
                rows = session.query(ExternalIncidentTarget).order_by(ExternalIncidentTarget.created_at.desc()).all()
                return [self._clean_target(r) for r in rows]
        except Exception:
            return []

    def get_target(self, target_id: str) -> Optional[dict[str, Any]]:
        with self._session_factory() as session:
            row = session.get(ExternalIncidentTarget, target_id)
            return self._clean_target(row) if row is not None else None

    # ── export (the incident workflow hook calls this on each transition) ──────

    def export(self, incident: dict[str, Any], action: str, *, actor: Optional[str] = None) -> int:
        """Mirror one incident transition to every enabled target that opted into
        this action. Creates a durable record per target and attempts it once.
        Best-effort and bounded — returns how many records were created. Never
        raises (incident workflow must never break on a sync hiccup)."""
        if not incident or not incident.get("id"):
            return 0
        try:
            with self._session_factory() as session:
                targets = session.query(ExternalIncidentTarget).filter(
                    ExternalIncidentTarget.enabled.is_(True)).all()
                created = []
                for target in targets:
                    allow = _csv_set(target.sync_actions)
                    if allow is not None and action not in allow:
                        continue
                    record = IncidentSyncRecord(
                        id=uuid4().hex, target_id=target.id,
                        incident_id=incident.get("id"), signal=incident.get("signal"),
                        action=action, actor=actor, state=incident.get("state"),
                        severity=incident.get("severity"), classification=incident.get("classification"),
                        subject=incident.get("subject"), assignee=incident.get("assignee"),
                        note=(incident.get("note") or None), status=STATUS_PENDING, attempts=0)
                    session.add(record)
                    created.append(record.id)
                session.commit()
            # Attempt each new record once, outside the create txn.
            for record_id in created:
                self._attempt(record_id)
            return len(created)
        except Exception:
            return 0

    def flush_pending(self, *, max_records: int = 50) -> dict[str, int]:
        """Retry pending records still under the attempt cap (sweep / recovery)."""
        counts = {STATUS_SYNCED: 0, STATUS_FAILED: 0, STATUS_PENDING: 0}
        try:
            with self._session_factory() as session:
                rows = (session.query(IncidentSyncRecord.id)
                        .filter(IncidentSyncRecord.status == STATUS_PENDING)
                        .order_by(IncidentSyncRecord.created_at.asc())
                        .limit(max_records).all())
                ids = [r[0] for r in rows]
            for record_id in ids:
                result = self._attempt(record_id)
                counts[result] = counts.get(result, 0) + 1
        except Exception:
            return counts
        return counts

    def _attempt(self, record_id: str) -> str:
        """One send attempt for a record. Returns the resulting status bucket."""
        with self._session_factory() as session:
            record = session.get(IncidentSyncRecord, record_id)
            if record is None or record.status == STATUS_SYNCED:
                return STATUS_SYNCED if record else STATUS_FAILED
            target = session.get(ExternalIncidentTarget, record.target_id)
            if target is None:
                record.status = STATUS_FAILED
                record.last_error = "target_deleted"
                session.commit()
                return STATUS_FAILED
            adapter = adapter_for(target.kind)
            payload = self._payload(record, target)
            body_json = json.dumps(adapter.shape(payload))
            record.attempts = (record.attempts or 0) + 1
            ok, code, err, ref, url = self._send(target.url, body_json, target.secret, adapter)
            if ok:
                record.status = STATUS_SYNCED
                record.last_error = None
                record.external_ref = ref
                record.external_url = url
                target.consecutive_failures = 0
                # Upsert the durable incident→external link from this success.
                self._upsert_link(session, record, ref, url)
            else:
                record.last_error = (err or (f"HTTP{code}" if code else "error"))[:200]
                target.consecutive_failures = (target.consecutive_failures or 0) + 1
                cap = max(1, int(getattr(settings, "incident_sync_max_attempts", 4)))
                record.status = STATUS_FAILED if record.attempts >= cap else STATUS_PENDING
            session.commit()
            return record.status

    @staticmethod
    def _upsert_link(session, record: IncidentSyncRecord, ref: Optional[str], url: Optional[str]) -> None:
        """Record/refresh the incident→external linkage on a successful sync. One row
        per (incident, target); a later success (incl. a redrive) updates it in place.
        Keeps the last good ref/url even if the latest ref is empty (don't lose a link)."""
        link = (session.query(IncidentExternalLink)
                .filter(IncidentExternalLink.incident_id == record.incident_id,
                        IncidentExternalLink.target_id == record.target_id).first())
        now = _now()
        if link is None:
            link = IncidentExternalLink(
                id=uuid4().hex, incident_id=record.incident_id, target_id=record.target_id,
                created_at=now)
            session.add(link)
        if ref:
            link.external_ref = ref
        if url:
            link.external_url = url
        link.last_action = record.action
        link.last_record_id = record.id
        link.last_synced_at = now

    # ── redrive (operator recovery of a terminal-failed sync) ─────────────────

    def redrive(self, record_id: str) -> dict[str, Any]:
        with self._session_factory() as session:
            record = session.get(IncidentSyncRecord, record_id)
            if record is None:
                return {"ok": False, "message": "Sync record not found."}
            if record.status != STATUS_FAILED:
                return {"ok": False, "message": "Only a terminally-failed sync can be redriven."}
            children = (session.query(IncidentSyncRecord)
                        .filter(IncidentSyncRecord.redrive_of == record_id).all())
            open_child = next((c for c in children if c.status in (STATUS_PENDING, STATUS_SYNCED)), None)
            if open_child is not None:
                return {"ok": True, "record": self._clean_record(open_child),
                        "message": "A redrive is already in flight or succeeded."}
            if len(children) >= max(1, int(getattr(settings, "incident_sync_max_redrives", 3))):
                return {"ok": False, "message": "Redrive limit reached for this sync."}
            child = IncidentSyncRecord(
                id=uuid4().hex, target_id=record.target_id, incident_id=record.incident_id,
                signal=record.signal, action=record.action, actor=record.actor,
                state=record.state, severity=record.severity, classification=record.classification,
                subject=record.subject, assignee=record.assignee, note=record.note,
                status=STATUS_PENDING, attempts=0, redrive_of=record_id)
            session.add(child)
            session.commit()
            child_id = child.id
        self._attempt(child_id)
        return {"ok": True, "record": self.get_record(child_id), "message": "Redrive attempted."}

    # ── reads (operator-only; curated) ────────────────────────────────────────

    def list_records(self, *, status: Optional[str] = None, incident_id: Optional[str] = None,
                     limit: int = 50) -> list[dict[str, Any]]:
        try:
            with self._session_factory() as session:
                query = session.query(IncidentSyncRecord)
                if status:
                    query = query.filter(IncidentSyncRecord.status == status)
                if incident_id:
                    query = query.filter(IncidentSyncRecord.incident_id == incident_id)
                rows = query.order_by(IncidentSyncRecord.created_at.desc()).limit(min(limit, 200)).all()
                names = self._target_names(session)
                return [self._clean_record(r, names) for r in rows]
        except Exception:
            return []

    def get_record(self, record_id: str) -> Optional[dict[str, Any]]:
        with self._session_factory() as session:
            row = session.get(IncidentSyncRecord, record_id)
            if row is None:
                return None
            return self._clean_record(row, self._target_names(session))

    # ── transport (single injectable primitive; overridden in tests) ──────────

    def _send(self, url: str, body_json: str, secret: Optional[str],
              adapter=None) -> tuple[bool, Optional[int], Optional[str], Optional[str], Optional[str]]:
        """POST the (already adapter-shaped) signed snapshot. Returns
        (ok, status_code, error_class, external_ref, external_url). The adapter parses
        ref/url from the response. Injectable/overridable in tests. Never raises."""
        adapter = adapter or _GENERIC
        try:
            import requests

            headers = {"Content-Type": "application/json", "User-Agent": "AIRA-X-IncidentSync/1"}
            body = body_json.encode("utf-8")
            if secret:
                sig = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
                headers["X-AIRA-Signature"] = f"sha256={sig}"
            resp = requests.post(url, data=body, headers=headers,
                                 timeout=getattr(settings, "webhook_timeout_seconds", 5.0))
            ok = 200 <= resp.status_code < 300
            resp_headers, resp_body = {}, None
            try:
                resp_headers = dict(resp.headers)
            except Exception:
                resp_headers = {}
            try:
                resp_body = resp.json()
            except Exception:
                resp_body = None
            ref, link = adapter.parse(resp.status_code, resp_headers, resp_body)
            return (ok, resp.status_code, None if ok else f"HTTP{resp.status_code}", ref, link)
        except Exception as error:
            return (False, None, type(error).__name__, None, None)

    @staticmethod
    def _payload(record: IncidentSyncRecord, target: ExternalIncidentTarget) -> dict[str, Any]:
        """The curated, stable outbound payload — incident identity + snapshot."""
        return {
            "type": "incident.transition",
            "target_kind": target.kind,
            "action": record.action,
            "actor": record.actor,
            "incident": {
                "id": record.incident_id,
                "signal": record.signal,
                "state": record.state,
                "severity": record.severity,
                "classification": record.classification,
                "subject": record.subject,
                "assignee": record.assignee,
                "note": record.note,
            },
            "at": (record.created_at.isoformat() if record.created_at else None),
        }

    @staticmethod
    def _target_overrides(row: ExternalIncidentTarget) -> dict[str, Any]:
        """All tri-state per-target overrides (outbound actions + inbound fields)."""
        return {field: getattr(row, field, None) for field in ALL_TARGET_OVERRIDE_FIELDS}

    @staticmethod
    def _resolve_profile(row: ExternalIncidentTarget) -> str:
        """The effective profile name for a target (NULL → the kind's default profile)."""
        return row.profile or default_profile_for_kind(row.kind)

    @staticmethod
    def _target_names(session) -> dict[str, dict[str, Any]]:
        return {t.id: {"name": t.name, "kind": t.kind,
                       "profile": IncidentSyncService._resolve_profile(t),
                       "overrides": IncidentSyncService._target_overrides(t)}
                for t in session.query(ExternalIncidentTarget).all()}

    @staticmethod
    def _clean_target(row: ExternalIncidentTarget) -> dict[str, Any]:
        overrides = IncidentSyncService._target_overrides(row)
        profile = IncidentSyncService._resolve_profile(row)
        prof = profile_for(profile)
        return {
            "id": row.id,
            "name": row.name,
            "kind": row.kind,
            "profile": profile,
            "profile_label": prof["label"] if prof else profile,
            "url": row.url,
            "enabled": bool(row.enabled),
            "sync_actions": row.sync_actions,
            "has_secret": bool(row.secret),   # presence only — never the value
            "consecutive_failures": row.consecutive_failures or 0,
            "capabilities": adapter_capabilities(row.kind),
            "policy_overrides": overrides,    # tri-state per-action + inbound overrides
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }

    @staticmethod
    def _clean_record(row: IncidentSyncRecord, target_names: Optional[dict] = None) -> dict[str, Any]:
        target = (target_names or {}).get(row.target_id, {})
        return {
            "id": row.id,
            "target_id": row.target_id,
            "target_name": target.get("name"),
            "target_kind": target.get("kind"),
            "incident_id": row.incident_id,
            "signal": row.signal,
            "action": row.action,
            "actor": row.actor,
            "state": row.state,
            "severity": row.severity,
            "classification": row.classification,
            "subject": row.subject,
            "assignee": row.assignee,
            "note": row.note,
            "status": row.status,
            "attempts": row.attempts or 0,
            "last_error": row.last_error,
            "external_ref": row.external_ref,
            "external_url": row.external_url,
            "redrive_of": row.redrive_of,
            "is_redrive": row.redrive_of is not None,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }

    def _clean_link(self, row: IncidentExternalLink, target_names: Optional[dict] = None,
                    *, local_state: Optional[str] = None, now: Optional[datetime] = None) -> dict[str, Any]:
        target = (target_names or {}).get(row.target_id, {})
        now = now or _now()
        stale_seconds = max(1, int(getattr(settings, "incident_link_stale_seconds", 86400)))
        kind = target.get("kind")
        overrides = target.get("overrides") or {}
        profile = target.get("profile")
        caps = adapter_capabilities(kind)
        supports_refresh = caps["refresh"]
        detached = row.detached_at is not None
        status, reason = classify_link_status(
            local_state=local_state, last_synced_at=row.last_synced_at,
            last_checked_at=row.last_checked_at, external_exists=row.external_exists,
            external_status=row.external_status, now=now, stale_seconds=stale_seconds,
            detached=detached)
        # Read-time MASK (G-13 + G-14 profile defaults): present a richer field only if
        # THIS target's inbound policy (profile default + override) permits it.
        def _field(name: str, value):
            return value if inbound_field_allowed(kind, overrides, name, profile) else None
        inbound_visibility = {f: inbound_field_allowed(kind, overrides, f, profile) for f in _INBOUND_FIELDS}
        return {
            "target_id": row.target_id,
            "target_name": target.get("name"),
            "target_kind": kind,
            "profile": profile,
            "external_ref": row.external_ref,
            "external_url": row.external_url,
            "last_action": row.last_action,
            "last_synced_at": row.last_synced_at.isoformat() if row.last_synced_at else None,
            "last_checked_at": row.last_checked_at.isoformat() if row.last_checked_at else None,
            "external_status": row.external_status,
            "external_exists": row.external_exists,
            # Richer bounded inbound snapshot — masked by per-target inbound policy.
            "external_assignee": _field("assignee", row.external_assignee),
            "external_severity": _field("severity", row.external_severity),
            "external_updated_at": _field("updated_at", row.external_updated_at),
            "external_comment_count": _field("comment_count", row.external_comment_count),
            "inbound_visibility": inbound_visibility,
            "suggestions_allowed": inbound_field_allowed(kind, overrides, "suggestions", profile),
            "detached": detached,
            "detached_at": row.detached_at.isoformat() if row.detached_at else None,
            "capabilities": caps,
            "policy_overrides": overrides,  # per-target tri-state (actions + inbound)
            "refresh_supported": supports_refresh,
            "link_status": status,
            "reason": reason,
        }

    # ── per-incident sync status & linkage (operator-only; curated) ───────────

    def incident_sync_status(self, incident_id: str, *, incident_state: Optional[str] = None) -> dict[str, Any]:
        """Curated sync-health + external linkage for one incident: durable links,
        recent attempts, and an honest summary (linked? behind? drifted? stale?
        missing? recovered by redrive?). Outbound stays primary — inbound facts are
        only what the last bounded refresh observed, never silent overwrites."""
        empty = {"linked": False, "links": [], "records": [], "reconciliation": [],
                 "summary": {"linked": False, "synced": False, "behind": False,
                             "last_synced_at": None, "last_failed_at": None, "last_error": None,
                             "recovered_after_redrive": False, "link_status": LINK_NEVER,
                             "reason": "never linked", "refresh_supported": False,
                             "last_checked_at": None,
                             "actions": {"can_refresh": False, "can_redrive": False,
                                         "can_detach": False, "can_relink": False,
                                         "can_apply": False, "apply_action": None,
                                         "can_push": False},
                             "available_actions": [],
                             "support_level": "none", "suggestions": []}}
        try:
            local_incident = self._local_incident(incident_id)
            local_state = incident_state if incident_state is not None else (local_incident or {}).get("state")
            now = _now()
            with self._session_factory() as session:
                names = self._target_names(session)
                link_rows = (session.query(IncidentExternalLink)
                             .filter(IncidentExternalLink.incident_id == incident_id)
                             .order_by(IncidentExternalLink.last_synced_at.desc()).all())
                rec_rows = (session.query(IncidentSyncRecord)
                            .filter(IncidentSyncRecord.incident_id == incident_id)
                            .order_by(IncidentSyncRecord.created_at.desc()).limit(50).all())
                evt_rows = (session.query(IncidentReconciliationEvent)
                            .filter(IncidentReconciliationEvent.incident_id == incident_id)
                            .order_by(IncidentReconciliationEvent.id.desc()).limit(10).all())
            links = [self._clean_link(r, names, local_state=local_state, now=now) for r in link_rows]
            records = [self._clean_record(r, names) for r in rec_rows]
            reconciliation = [self._clean_event(e) for e in evt_rows]
            synced = [r for r in records if r["status"] == STATUS_SYNCED]
            failed = [r for r in records if r["status"] == STATUS_FAILED]
            latest = records[0] if records else None
            active_links = [link for link in links if not link["detached"]]
            # Incident-level rollup: the worst (most actionable) active link wins.
            overall, reason = LINK_NEVER, "never linked"
            if active_links:
                worst = max(active_links, key=lambda link: _LINK_SEVERITY.get(link["link_status"], 0))
                overall, reason = worst["link_status"], worst["reason"]
            elif links:
                overall, reason = LINK_DETACHED, "intentionally detached"
            # What apply-from-external (if any) the observed disagreement supports.
            # Bounded + honest: only when external state was actually observed.
            apply_action = None
            if overall == LINK_MISSING:
                apply_action = "accept_missing"      # → detach the dead link
            elif overall == LINK_DRIFTED:
                worst_link = next((link for link in active_links if link["link_status"] == LINK_DRIFTED), None)
                if worst_link and worst_link["external_status"] in _EXT_CLOSED and local_state in _LOCAL_OPEN:
                    apply_action = "accept_resolved"  # → recover the local incident
            # Bounded, honest action availability (what the operator can actually do).
            actions = {
                "can_refresh": any(link["refresh_supported"] and not link["detached"] for link in links),
                "can_redrive": bool(failed and (latest is None or latest["status"] != STATUS_SYNCED)),
                "can_detach": any(not link["detached"] for link in links),
                "can_relink": any(link["refresh_supported"] for link in links),
                "can_apply": apply_action is not None,
                "apply_action": apply_action,
                "can_push": any(link["capabilities"]["push_outward"] and not link["detached"] for link in links),
            }
            # G-11: curated PER-ACTION availability + effect. Each entry tells the
            # operator exactly what an action will change (local / linkage / external
            # / none) and why it's available or not. The console renders from this
            # list directly so action-gating logic doesn't live in two places.
            # Operator-facing suggestions from the worst active link's observed state.
            primary = max(active_links, key=lambda link: _LINK_SEVERITY.get(link["link_status"], 0)) if active_links else None
            available_actions = _available_actions(
                links=links, active_links=active_links, failed=failed, latest=latest,
                apply_action=apply_action, worst_link=primary)
            # Suggestions derive ONLY from the masked link (hidden fields can't drive
            # a suggestion) AND are suppressed wholesale if the target disables them.
            suggestions = (external_state_suggestions(local_incident, primary)
                           if (primary and primary.get("suggestions_allowed", True)) else [])
            support_level = primary["capabilities"]["support_level"] if primary else (
                links[0]["capabilities"]["support_level"] if links else "none")
            summary = {
                "linked": bool(active_links),
                "synced": bool(synced),
                "behind": bool(latest and latest["status"] != STATUS_SYNCED),
                "last_synced_at": synced[0]["created_at"] if synced else None,
                "last_failed_at": failed[0]["created_at"] if failed else None,
                "last_error": failed[0]["last_error"] if failed else None,
                "recovered_after_redrive": bool(latest and latest["status"] == STATUS_SYNCED and latest["is_redrive"]),
                "link_status": overall,
                "reason": reason,
                "refresh_supported": any(link["refresh_supported"] for link in active_links),
                "last_checked_at": max([link["last_checked_at"] for link in links if link["last_checked_at"]], default=None),
                "actions": actions,
                "available_actions": available_actions,
                "support_level": support_level,
                "suggestions": suggestions,
            }
            return {"linked": bool(active_links), "links": links, "records": records,
                    "reconciliation": reconciliation, "summary": summary}
        except Exception:
            return empty

    @staticmethod
    def _clean_event(row: IncidentReconciliationEvent) -> dict[str, Any]:
        return {
            "action": row.action,
            "outcome": row.outcome,
            "actor": row.actor,
            "detail": row.detail,
            "at": row.created_at.isoformat() if row.created_at else None,
        }

    @staticmethod
    def _local_incident(incident_id: str) -> Optional[dict[str, Any]]:
        """Read the current local incident (guarded lazy import — sync must not
        hard-depend on the incident service)."""
        try:
            from app.incidents import incident_service
            return incident_service.get(incident_id)
        except Exception:
            return None

    def _local_state(self, incident_id: str) -> Optional[str]:
        inc = self._local_incident(incident_id)
        return inc.get("state") if inc else None

    # ── bounded inbound reconciliation (refresh / drift) ──────────────────────

    def refresh(self, incident_id: str, *, incident_state: Optional[str] = None,
                actor: Optional[str] = None) -> Optional[dict[str, Any]]:
        """Bounded inbound recheck of each linked external incident (only for
        adapters that support it). Updates the link's last-observed external
        status/existence/url — it NEVER mutates the local incident. Returns the
        refreshed sync status, or None if the incident has no links to check."""
        local_state = incident_state if incident_state is not None else self._local_state(incident_id)
        try:
            with self._session_factory() as session:
                links = (session.query(IncidentExternalLink)
                         .filter(IncidentExternalLink.incident_id == incident_id,
                                 IncidentExternalLink.detached_at.is_(None)).all())
                if not links:
                    return None
                now = _now()
                for link in links:
                    target = session.get(ExternalIncidentTarget, link.target_id)
                    if target is None:
                        continue
                    adapter = adapter_for(target.kind)
                    if not getattr(adapter, "supports_refresh", False):
                        self._log_reconcile(session, incident_id, link.target_id, "refresh", "unsupported",
                                            actor=actor, detail="adapter is outbound-only")
                        continue  # outbound-only adapter — honestly skipped
                    ok, snap, err = self._fetch(target.url, link.external_ref, target.secret, adapter)
                    link.last_checked_at = now
                    exists = snap.get("exists") if snap else None
                    if snap is not None and (ok or exists is False):
                        link.external_exists = exists
                        if snap.get("status"):
                            link.external_status = snap["status"]
                        if snap.get("url"):
                            link.external_url = snap["url"]
                        # Richer bounded fields ONLY for status-sync adapters, and
                        # ONLY the ones THIS target's inbound policy permits (G-13).
                        # Data minimization: a field the operator disabled is never
                        # even imported (stored as None).
                        if getattr(adapter, "supports_status_sync", False):
                            overrides = self._target_overrides(target)
                            prof = self._resolve_profile(target)
                            link.external_assignee = (snap.get("assignee")
                                if inbound_field_allowed(target.kind, overrides, "assignee", prof) else None)
                            link.external_severity = (snap.get("severity")
                                if inbound_field_allowed(target.kind, overrides, "severity", prof) else None)
                            link.external_updated_at = (snap.get("updated_at")
                                if inbound_field_allowed(target.kind, overrides, "updated_at", prof) else None)
                            link.external_comment_count = (snap.get("comment_count")
                                if inbound_field_allowed(target.kind, overrides, "comment_count", prof) else None)
                        outcome = "missing" if exists is False else "ok"
                        self._log_reconcile(session, incident_id, link.target_id, "refresh", outcome,
                                            actor=actor, detail=(snap.get("status") or ("not found" if exists is False else None)))
                    else:
                        self._log_reconcile(session, incident_id, link.target_id, "refresh", "failed",
                                            actor=actor, detail=err)
                session.commit()
        except Exception:
            return self.incident_sync_status(incident_id, incident_state=local_state)
        return self.incident_sync_status(incident_id, incident_state=local_state)

    def _fetch(self, target_url: str, ref: Optional[str], secret: Optional[str],
               adapter=None) -> tuple[bool, Optional[dict], Optional[str]]:
        """Bounded inbound GET of an external incident's current state. Returns
        (ok, snapshot, error_class), where `snapshot` is the adapter's BOUNDED
        normalized `_external_state` dict (exists/status/url + richer fields only for
        status-sync adapters). Injectable/overridable in tests. Never raises."""
        adapter = adapter or _GENERIC
        try:
            import requests

            headers = {"Accept": "application/json", "User-Agent": "AIRA-X-IncidentSync/1"}
            params = {"ref": ref} if ref else {}
            resp = requests.get(target_url, params=params, headers=headers,
                                timeout=getattr(settings, "webhook_timeout_seconds", 5.0))
            ok = 200 <= resp.status_code < 300
            resp_headers, resp_body = {}, None
            try:
                resp_headers = dict(resp.headers)
            except Exception:
                resp_headers = {}
            try:
                resp_body = resp.json()
            except Exception:
                resp_body = None
            snapshot = adapter.parse_snapshot(resp.status_code, resp_headers, resp_body)
            return (ok, snapshot, None if ok else f"HTTP{resp.status_code}")
        except Exception as error:
            return (False, None, type(error).__name__)

    def drifted(self, *, limit: int = 50) -> list[dict[str, Any]]:
        """Operator triage: active (non-detached) links whose reconciliation verdict
        is actionable (drifted / missing_external / stale). Curated, operator-only."""
        out: list[dict[str, Any]] = []
        try:
            now = _now()
            with self._session_factory() as session:
                names = self._target_names(session)
                rows = (session.query(IncidentExternalLink)
                        .filter(IncidentExternalLink.detached_at.is_(None))
                        .order_by(IncidentExternalLink.last_synced_at.desc())
                        .limit(min(limit, 200)).all())
                resolved = [(r, self._local_state(r.incident_id)) for r in rows]
            for row, local_state in resolved:
                clean = self._clean_link(row, names, local_state=local_state, now=now)
                if clean["link_status"] in _ACTIONABLE:
                    clean["incident_id"] = row.incident_id
                    out.append(clean)
        except Exception:
            return []
        return out

    # ── drift resolution / link repair (operator-only; never touches local state) ─

    def detach(self, incident_id: str, target_id: str, *, actor: Optional[str] = None,
               incident_state: Optional[str] = None) -> Optional[dict[str, Any]]:
        """Intentionally detach an incident's external link (e.g. the external issue
        is gone or wrong). The link row is preserved for lineage but excluded from
        drift/reconciliation. Does NOT touch local incident state."""
        try:
            with self._session_factory() as session:
                link = (session.query(IncidentExternalLink)
                        .filter(IncidentExternalLink.incident_id == incident_id,
                                IncidentExternalLink.target_id == target_id).first())
                if link is None:
                    return None
                if link.detached_at is None:
                    link.detached_at = _now()
                self._log_reconcile(session, incident_id, target_id, "detach", "ok",
                                    actor=actor, detail="link detached")
                session.commit()
        except Exception:
            return None
        return self.incident_sync_status(incident_id, incident_state=incident_state)

    def relink(self, incident_id: str, target_id: str, external_ref: str, *,
               external_url: Optional[str] = None, actor: Optional[str] = None,
               incident_state: Optional[str] = None) -> dict[str, Any]:
        """Repair/establish an external link to a known ref, VALIDATED through the
        adapter (a bounded inbound check that it exists). Refused honestly when the
        adapter is outbound-only or the external incident can't be verified. Never
        trusts an arbitrary link blindly; never mutates local incident state."""
        external_ref = (external_ref or "").strip()[:120]
        if not external_ref:
            return {"ok": False, "message": "An external reference is required to relink."}
        try:
            with self._session_factory() as session:
                target = session.get(ExternalIncidentTarget, target_id)
                if target is None:
                    return {"ok": False, "message": "Target not found."}
                adapter = adapter_for(target.kind)
                if not getattr(adapter, "supports_refresh", False):
                    self._log_reconcile(session, incident_id, target_id, "relink", "unsupported",
                                        actor=actor, detail="adapter cannot verify links")
                    session.commit()
                    return {"ok": False, "message": "This target's adapter is outbound-only and cannot verify a relink."}
                ok, snap, err = self._fetch(target.url, external_ref, target.secret, adapter)
                exists = snap.get("exists") if snap else None
                status = snap.get("status") if snap else None
                url = snap.get("url") if snap else None
                if not ok or exists is False:
                    self._log_reconcile(session, incident_id, target_id, "relink",
                                        "missing" if exists is False else "failed",
                                        actor=actor, detail=(err or "external incident not found"))
                    session.commit()
                    return {"ok": False, "message": "Could not verify that external reference; relink refused."}
                now = _now()
                link = (session.query(IncidentExternalLink)
                        .filter(IncidentExternalLink.incident_id == incident_id,
                                IncidentExternalLink.target_id == target_id).first())
                if link is None:
                    link = IncidentExternalLink(id=uuid4().hex, incident_id=incident_id,
                                                target_id=target_id, created_at=now)
                    session.add(link)
                link.external_ref = external_ref
                link.external_url = external_url or url or link.external_url
                link.external_status = status
                link.external_exists = True
                link.last_checked_at = now
                link.last_synced_at = link.last_synced_at or now  # operator-established linkage time
                link.last_action = "relink"
                link.detached_at = None  # a verified relink reattaches
                self._log_reconcile(session, incident_id, target_id, "relink", "ok",
                                    actor=actor, detail=f"→ {external_ref}")
                session.commit()
        except Exception:
            return {"ok": False, "message": "Relink failed."}
        return {"ok": True, "status": self.incident_sync_status(incident_id, incident_state=incident_state),
                "message": "Relinked and verified."}

    def redrive_incident_latest(self, incident_id: str) -> dict[str, Any]:
        """Redrive the most recent terminally-failed sync for an incident, straight
        from its context (a convenience over per-record redrive)."""
        try:
            with self._session_factory() as session:
                latest = (session.query(IncidentSyncRecord)
                          .filter(IncidentSyncRecord.incident_id == incident_id)
                          .order_by(IncidentSyncRecord.created_at.desc()).first())
                # Already landed (e.g. a prior redrive succeeded) → nothing to do.
                if latest is not None and latest.status == STATUS_SYNCED:
                    return {"ok": False, "message": "External sync is already up to date."}
                latest_failed = (session.query(IncidentSyncRecord)
                                 .filter(IncidentSyncRecord.incident_id == incident_id,
                                         IncidentSyncRecord.status == STATUS_FAILED)
                                 .order_by(IncidentSyncRecord.created_at.desc()).first())
                record_id = latest_failed.id if latest_failed else None
            if record_id is None:
                return {"ok": False, "message": "No failed sync to redrive for this incident."}
            result = self.redrive(record_id)
            with self._session_factory() as session:
                self._log_reconcile(session, incident_id, None, "redrive",
                                    "ok" if result.get("ok") else "failed",
                                    detail=result.get("message"))
                session.commit()
            return result
        except Exception:
            return {"ok": False, "message": "Redrive failed."}

    # ── explicit local-vs-external resolution (operator-driven only) ──────────

    def apply_from_external(self, incident_id: str, apply_action: str, *,
                            actor: Optional[str] = None) -> dict[str, Any]:
        """EXPLICIT, operator-chosen application of observed external state to the
        LOCAL side. This is the only path that may change local incident state from
        an external observation — refresh/reconcile never do. Bounded to the cases the
        observed disagreement actually supports; refused otherwise.

        - `accept_resolved`: external reports resolved/closed while local is open →
          recover the local incident (an explicit operator recovery, on the trail).
        - `accept_missing`: external is gone → detach the dead link.
        """
        # G-11: unknown apply actions are audited as policy refusals (so an attempt
        # against a future/unrecognized action leaves a trail too).
        if apply_action not in ("accept_resolved", "accept_missing"):
            self._record_apply(incident_id, None, apply_action or "unknown",
                               "refused:" + POLICY_DENIED_UNKNOWN.split(":", 1)[1],
                               actor=actor, detail="unknown apply action")
            return {"ok": False, "code": POLICY_DENIED_UNKNOWN, "message": "Unknown apply action."}
        status = self.incident_sync_status(incident_id)
        if not status["links"]:
            self._record_apply(incident_id, None, apply_action, "refused:state",
                               actor=actor, detail="no external link")
            return {"ok": False, "code": "denied:state", "message": "Incident has no external link."}
        offered = status["summary"]["actions"].get("apply_action")
        if offered != apply_action:
            self._record_apply(incident_id, None, apply_action, "refused:state", actor=actor,
                               detail=f"not currently applicable (offered={offered})")
            return {"ok": False, "code": "denied:state",
                    "message": "That external state is not currently applicable."}
        active = [link for link in status["links"] if not link["detached"]]
        # Pick the relevant link FIRST so the policy check is per-target-kind.
        if apply_action == "accept_missing":
            link = next((l for l in active if l["link_status"] == LINK_MISSING), active[0] if active else None)
        else:  # accept_resolved
            link = next((l for l in active if l["link_status"] == LINK_DRIFTED), None)
        if link is None:
            self._record_apply(incident_id, None, apply_action, "refused:state", actor=actor,
                               detail="no matching active link for action")
            return {"ok": False, "code": "denied:state",
                    "message": "No matching external link for that action."}
        # Policy gate: adapter capability → profile default → per-target override, audited.
        allowed, code, reason = target_action_policy(
            link["target_kind"], link.get("policy_overrides"), apply_action, link.get("profile"))
        if not allowed:
            self._record_apply(incident_id, link["target_id"], apply_action, "refused:" + code.split(":", 1)[1],
                               actor=actor, detail=reason)
            return {"ok": False, "code": code, "message": reason}
        if apply_action == "accept_missing":
            self.detach(incident_id, link["target_id"], actor=actor)
            self._record_apply(incident_id, link["target_id"], "accept_missing", "ok",
                               actor=actor, detail="detached missing external link (linkage only)")
            return {"ok": True, "changed_local": False, "code": POLICY_ALLOWED,
                    "status": self.incident_sync_status(incident_id),
                    "message": "Detached the missing external link."}
        # accept_resolved → explicit LOCAL recovery (the only path that changes local).
        applied = None
        try:
            from app.incidents import incident_service
            applied = incident_service.mark_recovered(
                incident_id, actor=actor, reason="applied external resolution")
        except Exception:
            applied = None
        outcome = "ok" if applied else "failed"
        self._record_apply(incident_id, link["target_id"], "accept_resolved", outcome, actor=actor,
                           detail="local incident recovered from external resolved")
        if not applied:
            return {"ok": False, "code": "failed",
                    "message": "Could not apply external resolution."}
        return {"ok": True, "changed_local": True, "code": POLICY_ALLOWED,
                "status": self.incident_sync_status(incident_id),
                "message": "Applied external resolution — local incident recovered."}

    def push_outward(self, incident_id: str, *, target_id: Optional[str] = None,
                     actor: Optional[str] = None, incident: Optional[dict] = None) -> dict[str, Any]:
        """EXPLICITLY re-send the CURRENT local incident state outward to push-capable
        targets (e.g. push a local `recovered` so the external incident resolves). The
        action mirrors the local state honestly; targets whose adapter can't push are
        skipped. Never changes local state."""
        snapshot = incident
        if snapshot is None:
            try:
                from app.incidents import incident_service
                snapshot = incident_service.get(incident_id)
            except Exception:
                snapshot = None
        if not snapshot:
            return {"ok": False, "message": "Incident not found."}
        action = "recovered" if snapshot.get("state") == "recovered" else "opened"
        created: list[str] = []
        pushed_targets = 0
        try:
            with self._session_factory() as session:
                query = session.query(ExternalIncidentTarget).filter(ExternalIncidentTarget.enabled.is_(True))
                if target_id:
                    query = query.filter(ExternalIncidentTarget.id == target_id)
                targets = query.all()
                if not targets:
                    return {"ok": False, "message": "No matching enabled target."}
                for target in targets:
                    if not getattr(adapter_for(target.kind), "supports_push_outward", False):
                        self._log_reconcile(session, incident_id, target.id, "push", "unsupported",
                                            actor=actor, detail="adapter cannot push outward")
                        continue
                    record = IncidentSyncRecord(
                        id=uuid4().hex, target_id=target.id, incident_id=incident_id,
                        signal=snapshot.get("signal"), action=action, actor=actor,
                        state=snapshot.get("state"), severity=snapshot.get("severity"),
                        classification=snapshot.get("classification"), subject=snapshot.get("subject"),
                        assignee=snapshot.get("assignee"), note=(snapshot.get("note") or None),
                        status=STATUS_PENDING, attempts=0)
                    session.add(record)
                    created.append(record.id)
                    pushed_targets += 1
                session.commit()
            for record_id in created:
                self._attempt(record_id)
            with self._session_factory() as session:
                self._log_reconcile(session, incident_id, target_id, "push",
                                    "ok" if pushed_targets else "unsupported", actor=actor,
                                    detail=f"pushed local '{action}' to {pushed_targets} target(s)")
                session.commit()
        except Exception:
            return {"ok": False, "message": "Push failed."}
        if not pushed_targets:
            return {"ok": False, "message": "No push-capable target for this incident."}
        return {"ok": True, "changed_local": False,
                "status": self.incident_sync_status(incident_id), "message": "Pushed local state outward."}

    def _record_apply(self, incident_id: str, target_id: Optional[str], action: str, outcome: str,
                      *, actor: Optional[str], detail: Optional[str]) -> None:
        try:
            with self._session_factory() as session:
                self._log_reconcile(session, incident_id, target_id, f"apply:{action}", outcome,
                                    actor=actor, detail=detail)
                session.commit()
        except Exception:
            pass

    # Maps a vendor-typed external action → the incident transition the adapter shapes.
    _EXTERNAL_ACTION_TRANSITION = {
        "external_resolve": "recovered",       # → PagerDuty event_action: resolve
        "external_reopen": "reopened",         # → PagerDuty event_action: trigger
        "external_acknowledge": "acknowledged",  # → PagerDuty event_action: acknowledge
    }

    def external_action(self, incident_id: str, action: str, *, target_id: Optional[str] = None,
                        actor: Optional[str] = None, incident: Optional[dict] = None) -> dict[str, Any]:
        """Invoke a richer VENDOR-TYPED outbound action (resolve / reopen / acknowledge)
        on the external incident, gated by adapter capability AND per-target policy.
        Effect is strictly EXTERNAL — local incident state is never changed here. Each
        target is policy-checked individually; refusals are audited per target."""
        if action not in self._EXTERNAL_ACTION_TRANSITION:
            return {"ok": False, "code": POLICY_DENIED_UNKNOWN, "message": "Unknown external action."}
        snapshot = incident
        if snapshot is None:
            try:
                from app.incidents import incident_service
                snapshot = incident_service.get(incident_id)
            except Exception:
                snapshot = None
        if not snapshot:
            return {"ok": False, "message": "Incident not found."}
        transition = self._EXTERNAL_ACTION_TRANSITION[action]
        created: list[str] = []
        applied_targets = 0
        last_refusal: Optional[tuple[str, str]] = None
        try:
            with self._session_factory() as session:
                # Only targets this incident is actually LINKED to (not detached).
                links = (session.query(IncidentExternalLink)
                         .filter(IncidentExternalLink.incident_id == incident_id,
                                 IncidentExternalLink.detached_at.is_(None)).all())
                if target_id:
                    links = [l for l in links if l.target_id == target_id]
                if not links:
                    return {"ok": False, "code": "denied:state",
                            "message": "Incident has no active external link for that target."}
                for link in links:
                    target = session.get(ExternalIncidentTarget, link.target_id)
                    if target is None or not target.enabled:
                        continue
                    overrides = self._target_overrides(target)
                    allowed, code, reason = target_action_policy(
                        target.kind, overrides, action, self._resolve_profile(target))
                    if not allowed:
                        last_refusal = (code, reason)
                        self._log_reconcile(session, incident_id, target.id, f"external:{action}",
                                            "refused:" + code.split(":", 1)[1], actor=actor, detail=reason)
                        continue
                    record = IncidentSyncRecord(
                        id=uuid4().hex, target_id=target.id, incident_id=incident_id,
                        signal=snapshot.get("signal"), action=transition, actor=actor,
                        state=snapshot.get("state"), severity=snapshot.get("severity"),
                        classification=snapshot.get("classification"), subject=snapshot.get("subject"),
                        assignee=snapshot.get("assignee"), note=(snapshot.get("note") or None),
                        status=STATUS_PENDING, attempts=0)
                    session.add(record)
                    created.append(record.id)
                    applied_targets += 1
                session.commit()
            for record_id in created:
                self._attempt(record_id)
            if applied_targets:
                with self._session_factory() as session:
                    self._log_reconcile(session, incident_id, target_id, f"external:{action}", "ok",
                                        actor=actor, detail=f"sent vendor '{transition}' to {applied_targets} target(s)")
                    session.commit()
        except Exception:
            return {"ok": False, "message": "External action failed."}
        if not applied_targets:
            code = last_refusal[0] if last_refusal else "denied:state"
            msg = last_refusal[1] if last_refusal else "No target permits this action."
            return {"ok": False, "code": code, "message": msg}
        return {"ok": True, "changed_local": False, "code": POLICY_ALLOWED,
                "status": self.incident_sync_status(incident_id),
                "message": f"Sent external {action.replace('external_', '')} to {applied_targets} target(s)."}

    def target_policy(self, target_id: str) -> Optional[dict[str, Any]]:
        """Curated capability-vs-profile-vs-override-vs-effective view for one target."""
        with self._session_factory() as session:
            target = session.get(ExternalIncidentTarget, target_id)
            if target is None:
                return None
            profile = self._resolve_profile(target)
            policy = effective_target_policy(target.kind, self._target_overrides(target), profile)
            policy["target_id"] = target.id
            policy["name"] = target.name
            prof = profile_for(profile)
            policy["profile_label"] = prof["label"] if prof else profile
            policy["profile_summary"] = prof["summary"] if prof else None
            return policy

    def target_profile(self, target_id: str) -> Optional[dict[str, Any]]:
        """Onboarding view (G-14): the target's profile + its defaults + effective
        policy with per-decision sources. Operator-only; no secrets."""
        with self._session_factory() as session:
            target = session.get(ExternalIncidentTarget, target_id)
            if target is None:
                return None
            profile = self._resolve_profile(target)
            prof = profile_for(profile)
            return {
                "target_id": target.id,
                "name": target.name,
                "kind": target.kind,
                "profile": (_clean_profile(prof) if prof else {"name": profile}),
                "policy": effective_target_policy(target.kind, self._target_overrides(target), profile),
            }

    def reconcile(self, *, max_incidents: Optional[int] = None, actor: Optional[str] = None) -> dict[str, int]:
        """Bounded scheduled reconciliation: recheck the active, refresh-capable links
        that most need it (stale / never-checked / already drifted), capped per sweep
        so external systems are never spammed. Never mutates local incident state."""
        cap = max_incidents if max_incidents is not None else int(getattr(settings, "incident_reconcile_max_per_sweep", 25))
        cap = max(1, int(cap))
        stale_seconds = max(1, int(getattr(settings, "incident_link_stale_seconds", 86400)))
        counts = {"checked": 0, "ok": 0, "missing": 0, "failed": 0, "skipped": 0}
        try:
            now = _now()
            with self._session_factory() as session:
                names = self._target_names(session)
                # NULL last_checked_at (never reconciled) sorts first under SQLite ASC,
                # so the longest-unchecked links are prioritized.
                rows = (session.query(IncidentExternalLink)
                        .filter(IncidentExternalLink.detached_at.is_(None))
                        .order_by(IncidentExternalLink.last_checked_at.asc())
                        .limit(200).all())
                candidates = []
                for link in rows:
                    kind = names.get(link.target_id, {}).get("kind")
                    if not getattr(adapter_for(kind), "supports_refresh", False):
                        continue
                    needs = (link.last_checked_at is None
                             or (link.last_synced_at is not None and (now - link.last_synced_at).total_seconds() > stale_seconds)
                             or (link.last_checked_at is not None and (now - link.last_checked_at).total_seconds() > stale_seconds))
                    if needs:
                        candidates.append(link.incident_id)
                    if len(candidates) >= cap:
                        break
            for incident_id in candidates:
                status = self.refresh(incident_id, actor=actor)
                if status is None:
                    counts["skipped"] += 1
                    continue
                counts["checked"] += 1
                verdict = status["summary"]["link_status"]
                if verdict == LINK_MISSING:
                    counts["missing"] += 1
                elif verdict in (LINK_REFRESHED, LINK_LINKED, LINK_DRIFTED):
                    counts["ok"] += 1
        except Exception:
            return counts
        return counts

    def reconciliation_events(self, incident_id: str, *, limit: int = 20) -> list[dict[str, Any]]:
        try:
            with self._session_factory() as session:
                rows = (session.query(IncidentReconciliationEvent)
                        .filter(IncidentReconciliationEvent.incident_id == incident_id)
                        .order_by(IncidentReconciliationEvent.id.desc()).limit(min(limit, 100)).all())
                return [self._clean_event(r) for r in rows]
        except Exception:
            return []

    def incident_actions(self, incident_id: str, *,
                         incident_state: Optional[str] = None) -> list[dict[str, Any]]:
        """Curated per-action availability + effect for one incident (G-11). Mirrors
        what `incident_sync_status` returns as `summary.available_actions`, exposed
        directly so the console (or an external review tool) can grab just the
        actionable preview without the full status payload."""
        status = self.incident_sync_status(incident_id, incident_state=incident_state)
        return status["summary"].get("available_actions", [])

    @staticmethod
    def _log_reconcile(session, incident_id: str, target_id: Optional[str], action: str,
                       outcome: str, *, actor: Optional[str] = None, detail: Optional[str] = None) -> None:
        actor = (actor or "").strip()[:80] or None
        session.add(IncidentReconciliationEvent(
            incident_id=incident_id, target_id=target_id, action=action, outcome=outcome,
            actor=actor, detail=(detail[:200] if detail else None), created_at=_now()))

    def target_health(self, target_id: str) -> Optional[dict[str, Any]]:
        """Curated health for one target: recent attempt mix + last success/failure."""
        with self._session_factory() as session:
            target = session.get(ExternalIncidentTarget, target_id)
            if target is None:
                return None
            rows = (session.query(IncidentSyncRecord)
                    .filter(IncidentSyncRecord.target_id == target_id)
                    .order_by(IncidentSyncRecord.created_at.desc()).limit(100).all())
            synced = [r for r in rows if r.status == STATUS_SYNCED]
            failed = [r for r in rows if r.status == STATUS_FAILED]
            pending = [r for r in rows if r.status == STATUS_PENDING]
            healthy = (target.consecutive_failures or 0) == 0
            clean = self._clean_target(target)
            clean.update({
                "health": "healthy" if healthy else "degraded",
                "recent": {"synced": len(synced), "failed": len(failed), "pending": len(pending)},
                "last_synced_at": (synced[0].created_at.isoformat() if synced and synced[0].created_at else None),
                "last_failed_at": (failed[0].created_at.isoformat() if failed and failed[0].created_at else None),
                "last_error": (failed[0].last_error if failed else None),
            })
            return clean

    def clear_all(self) -> None:
        try:
            with self._session_factory() as session:
                session.query(IncidentReconciliationEvent).delete()
                session.query(IncidentExternalLink).delete()
                session.query(IncidentSyncRecord).delete()
                session.query(ExternalIncidentTarget).delete()
                session.commit()
        except Exception:
            pass


incident_sync_service = IncidentSyncService()
