"""Phase 8 — production delivery & open-source professionalization.

Pins the OSS governance, CI workflows, release docs, security docs, and portfolio assets
so they cannot silently disappear or drift — same philosophy as the Phase 7 docs gate.
Process/infra only; no business behavior is exercised.
"""

from pathlib import Path

# backend/tests/this_file → repo root is two levels up from `backend/`.
ROOT = Path(__file__).resolve().parents[2]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def _exists(rel: str) -> bool:
    return (ROOT / rel).exists()


# ── A. GitHub professionalization ─────────────────────────────────────────────

def test_oss_governance_files_exist():
    for rel in ["CODE_OF_CONDUCT.md", "CONTRIBUTING.md", "SECURITY.md", "LICENSE"]:
        assert _exists(rel), f"missing OSS file: {rel}"
        assert len(_read(rel)) > 300, f"OSS file too thin: {rel}"


def test_github_templates_exist():
    for rel in [".github/ISSUE_TEMPLATE/bug_report.md",
                ".github/ISSUE_TEMPLATE/feature_request.md",
                ".github/PULL_REQUEST_TEMPLATE.md"]:
        assert _exists(rel), f"missing template: {rel}"


def test_contributing_documents_workflow_and_release():
    doc = _read("CONTRIBUTING.md").lower()
    for token in ["branch strategy", "release", "pytest -q -p no:randomly", "pull request"]:
        assert token in doc, f"CONTRIBUTING.md missing: {token}"


def test_security_documents_responsible_disclosure():
    doc = _read("SECURITY.md").lower()
    assert "do not open a public issue" in doc
    assert "advisor" in doc or "disclosure" in doc
    assert "supported versions" in doc


# ── B. CI/CD pipeline ─────────────────────────────────────────────────────────

def test_three_focused_workflows_exist():
    for rel in [".github/workflows/fast-check.yml",
                ".github/workflows/e2e.yml",
                ".github/workflows/docs.yml"]:
        assert _exists(rel), f"missing workflow: {rel}"
        body = _read(rel)
        # Minimal structural sanity without a YAML dependency.
        for key in ["name:", "on:", "jobs:"]:
            assert key in body, f"{rel} missing `{key}`"


def test_monolithic_ci_was_replaced():
    # The old single ci.yml is superseded by the three focused workflows.
    assert not _exists(".github/workflows/ci.yml"), "ci.yml should be replaced"


def test_fast_check_runs_backend_and_frontend_gates():
    body = _read(".github/workflows/fast-check.yml")
    assert "pytest" in body
    assert "tsc --noEmit" in body
    assert "node --test" in body
    assert "npm run lint" in body
    assert "npm run build" in body


def test_e2e_workflow_runs_playwright():
    body = _read(".github/workflows/e2e.yml").lower()
    assert "playwright" in body and "npm run e2e" in body


def test_docs_workflow_runs_the_packaging_gates():
    body = _read(".github/workflows/docs.yml")
    assert "test_docs_packaging.py" in body
    assert "test_repo_professionalization.py" in body


# ── C. Release management ─────────────────────────────────────────────────────

def test_release_process_and_changelog_exist():
    assert _exists("docs/RELEASE_PROCESS.md")
    rp = _read("docs/RELEASE_PROCESS.md").lower()
    for token in ["semantic versioning", "release checklist", "rollback", "changelog"]:
        assert token in rp, f"RELEASE_PROCESS.md missing: {token}"

    assert _exists("CHANGELOG.md")
    cl = _read("CHANGELOG.md")
    assert "[Unreleased]" in cl
    assert "0.1.0" in cl                      # seeded milestone
    assert "Keep a Changelog" in cl


# ── D. Deployment blueprint ───────────────────────────────────────────────────

def test_deployment_blueprint_covers_all_tiers_and_components():
    doc = _read("docs/DEPLOYMENT_BLUEPRINT.md").lower()
    for tier in ["single vm", "docker-compose", "kubernetes"]:
        assert tier in doc, f"DEPLOYMENT_BLUEPRINT.md missing tier: {tier}"
    for component in ["backend", "frontend", "worker", "database", "secret"]:
        assert component in doc, f"DEPLOYMENT_BLUEPRINT.md missing component: {component}"


# ── E. Portfolio assets ───────────────────────────────────────────────────────

def test_portfolio_assets_exist_and_cover_audiences():
    guide = _read("docs/PORTFOLIO_GUIDE.md").lower()
    for token in ["recruiter", "cto", "staff", "demo script",
                  "architecture talking points", "interview"]:
        assert token in guide, f"PORTFOLIO_GUIDE.md missing: {token}"

    bullets = _read("docs/RESUME_BULLETS.md").lower()
    for token in ["resume bullet", "linkedin", "github project summary"]:
        assert token in bullets, f"RESUME_BULLETS.md missing: {token}"
