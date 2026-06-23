"""Phase 7 — portfolio & commercial packaging.

These tests pin the documentation to the LIVE system so it can't silently rot or be
removed: the required docs exist, cover the required sections, and the headline counts
(adapters, profiles, operator routes) match the running registry. Documentation-only
phase — no business behavior is exercised here.
"""

from pathlib import Path

import app.routes.operator as operator_routes
from app.incident_sync import PROFILE_NAMES, _KINDS

# backend/tests/this_file → repo root is two levels up from `backend/`.
ROOT = Path(__file__).resolve().parents[2]

REQUIRED_DOCS = [
    "README.md",
    "docs/ARCHITECTURE.md",
    "docs/ENGINEERING_DECISIONS.md",
    "docs/DEMO_WALKTHROUGH.md",
    "docs/PLATFORM_SUMMARY.md",
    "docs/OPERATIONS.md",
]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_required_docs_exist_and_are_substantial():
    for rel in REQUIRED_DOCS:
        path = ROOT / rel
        assert path.exists(), f"missing required doc: {rel}"
        assert len(path.read_text(encoding="utf-8")) > 800, f"doc too thin: {rel}"


def test_readme_covers_every_platform_surface():
    readme = _read("README.md").lower()
    for keyword in ["operator console", "incident sync", "observability", "demo mode",
                    "quickstart", "local development", "production deployment", "testing",
                    "architecture", "feature matrix", "roadmap", "screenshot"]:
        assert keyword in readme, f"README missing section: {keyword}"


def test_architecture_doc_has_mermaid_and_named_flows():
    arch = _read("docs/ARCHITECTURE.md")
    assert "```mermaid" in arch, "ARCHITECTURE.md should include Mermaid diagrams"
    lower = arch.lower()
    for section in ["system boundaries", "component map", "request flow", "sync flow",
                    "operator flow", "observability flow", "deployment topology",
                    "trust boundaries", "security model", "audit model"]:
        assert section in lower, f"ARCHITECTURE.md missing: {section}"


def test_engineering_decisions_cover_every_required_choice():
    doc = _read("docs/ENGINEERING_DECISIONS.md").lower()
    for topic in ["local state is the source of truth", "recovery is explicit",
                  "capability", "policy", "profile", "readiness model",
                  "deterministic metrics", "demo namespace",
                  "inbound sync never mutates local state"]:
        assert topic in doc, f"ENGINEERING_DECISIONS.md missing: {topic}"


def test_demo_walkthrough_covers_the_evaluation_path():
    doc = _read("docs/DEMO_WALKTHROUGH.md").lower()
    for step in ["seed", "readiness", "observability", "drift", "audit", "separation"]:
        assert step in doc, f"DEMO_WALKTHROUGH.md missing step: {step}"


def test_docs_document_every_live_adapter_kind():
    """Architecture/README must mention every adapter the registry actually exposes —
    so the docs can't claim fewer or more integrations than exist."""
    corpus = (_read("docs/ARCHITECTURE.md") + _read("README.md")
              + _read("docs/PLATFORM_SUMMARY.md")).lower()
    for kind in _KINDS:
        assert kind in corpus, f"adapter kind not documented anywhere: {kind}"


def test_platform_summary_counts_match_the_live_system():
    summary = _read("docs/PLATFORM_SUMMARY.md")
    # Adapter + profile + operator-route counts are tied to the running registry.
    assert str(len(_KINDS)) in summary, "adapter count not reflected in PLATFORM_SUMMARY"
    assert str(len(PROFILE_NAMES)) in summary, "profile count not reflected in PLATFORM_SUMMARY"
    assert str(len(operator_routes.router.routes)) in summary, "operator route count stale"


def test_operations_guide_links_the_packaging_docs():
    ops = _read("docs/OPERATIONS.md")
    for rel in ["ARCHITECTURE.md", "DEMO_WALKTHROUGH.md", "ENGINEERING_DECISIONS.md",
                "PLATFORM_SUMMARY.md"]:
        assert rel in ops, f"OPERATIONS.md should link {rel}"
