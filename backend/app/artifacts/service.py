# File: backend/app/artifacts/service.py
"""
ArtifactService — orchestrates the artifact pipeline through the same product
principles as code execution: structured plan -> approval -> real generation ->
validation -> evidence-based completion / honest failure.

    plan()     -> prepare content, build spec, resolve delivery, render plan
    generate() -> write the real file, validate it, assemble evidence

A per-session PendingArtifact store (mirrors the plan/action stores) lets the
supervisor park a plan until the user approves.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Optional

from app.artifacts.delivery import ArtifactDeliveryService, DeliveryTarget
from app.artifacts.generators import get_generator
from app.artifacts.spec import (
    ArtifactPlanBuilder,
    ArtifactSpec,
    Section,
    Slide,
    kind_noun,
    slugify,
)
from app.artifacts.styles import get_style
from app.artifacts.validator import ArtifactValidator
from app.clarification import ClarificationStore


@dataclass
class PendingArtifact:
    goal: str
    kind: str
    spec: dict                      # serialized ArtifactSpec
    delivery: dict                  # serialized DeliveryTarget (str path)
    status: str = "awaiting_plan_approval"


# Session-scoped pending-artifact store (same mechanics as plan/action stores).
artifact_store = ClarificationStore()


def _spec_to_dict(spec: ArtifactSpec) -> dict:
    return {
        "kind": spec.kind,
        "title": spec.title,
        "subtitle": spec.subtitle,
        "style": spec.style,
        "slides": [asdict(s) for s in spec.slides],
        "sections": [asdict(s) for s in spec.sections],
        "sheet_name": spec.sheet_name,
        "headers": spec.headers,
        "rows": spec.rows,
    }


def _spec_from_dict(data: dict) -> ArtifactSpec:
    return ArtifactSpec(
        kind=data["kind"],
        title=data["title"],
        subtitle=data.get("subtitle", ""),
        style=data.get("style", ""),
        slides=[Slide(**s) for s in data.get("slides", [])],
        sections=[Section(**s) for s in data.get("sections", [])],
        sheet_name=data.get("sheet_name", "Sheet1"),
        headers=list(data.get("headers", [])),
        rows=[list(r) for r in data.get("rows", [])],
    )


class ArtifactService:
    def __init__(self) -> None:
        self.builder = ArtifactPlanBuilder()
        self.delivery = ArtifactDeliveryService()
        self.validator = ArtifactValidator()

    # ── planning ─────────────────────────────────────────────────────────────

    def plan(
        self,
        goal: str,
        kind: str,
        *,
        generate: Optional[Callable[..., str]] = None,
        context: Optional[str] = None,
    ) -> tuple[PendingArtifact, str]:
        """Prepare content + delivery into a pending plan and a plan message."""
        spec = self.builder.build(
            goal, kind, generate=generate, context=context, style=get_style(kind).name
        )
        filename = f"{slugify(spec.title)}{spec.extension}"
        target = self.delivery.resolve(goal, filename)

        pending = PendingArtifact(
            goal=goal,
            kind=kind,
            spec=_spec_to_dict(spec),
            delivery=_delivery_to_dict(target),
            status=(
                "awaiting_action_approval"
                if target.requires_approval
                else "awaiting_plan_approval"
            ),
        )
        return pending, self._render_plan(spec, target)

    # ── generation ───────────────────────────────────────────────────────────

    def generate(self, pending: PendingArtifact) -> dict[str, Any]:
        """Generate + validate the real file. Completion requires validation."""
        spec = _spec_from_dict(pending.spec)
        target = _delivery_from_dict(pending.delivery)
        style = get_style(spec.kind, spec.style or None)
        generator = get_generator(spec.kind)
        if generator is None:
            return {"status": "failed", "error": f"no generator for {spec.kind}"}

        try:
            written = generator.write(spec, target.path, style)
        except Exception as error:
            return {"status": "failed", "error": f"generation failed: {error}"}

        validation = self.validator.validate(spec.kind, written)
        if not validation.get("valid"):
            return {
                "status": "failed",
                "error": validation.get("error", "artifact validation failed"),
                "validation": validation,
            }

        artifact = {
            "type": spec.kind,
            "title": spec.title,
            "subtitle": spec.subtitle,
            "filename": target.filename,
            "path": str(written),
            "download_url": target.download_url,
            "location": target.location,
            "requested_path": target.requested_path,
            "style": style.name,
            "summary": self._summary(spec, validation),
            "size_bytes": validation.get("size_bytes"),
            "validation": validation,
        }
        return {"status": "completed", "artifact": artifact, "validation": validation}

    @staticmethod
    def _summary(spec: ArtifactSpec, validation: dict) -> str:
        details = validation.get("details", {})
        if spec.kind == "pptx":
            return f"{details.get('slides', len(spec.slides))} slides"
        if spec.kind == "docx":
            return f"{len(spec.sections)} sections, {details.get('paragraphs', '?')} paragraphs"
        cols = len(spec.headers)
        return f"{details.get('rows', len(spec.rows) + 1)} rows × {cols} columns"

    # ── rendering ────────────────────────────────────────────────────────────

    def _render_plan(self, spec: ArtifactSpec, target: DeliveryTarget) -> str:
        noun = kind_noun(spec.kind)
        outline = spec.outline()
        lines = [f"I'll create a {spec.kind.upper()} {noun}: “{spec.title}”."]
        if outline:
            lines.append("")
            lines.append("Planned content:")
            for item in outline[:10]:
                lines.append(f"- {item}")
        lines.append("")
        if target.requires_approval:
            lines.append(
                f"You asked to save it to {target.requested_path}. I can't write "
                "outside the workspace for safety, so I'll generate it in the "
                "workspace download area and give you the path — approve to proceed."
            )
        else:
            lines.append(
                "It will be saved to the workspace download area and offered as a "
                "download. Approve to generate it."
            )
        return "\n".join(lines)


def _delivery_to_dict(target: DeliveryTarget) -> dict:
    return {
        "filename": target.filename,
        "path": str(target.path),
        "location": target.location,
        "requires_approval": target.requires_approval,
        "requested_path": target.requested_path,
        "download_url": target.download_url,
    }


def _delivery_from_dict(data: dict) -> DeliveryTarget:
    from pathlib import Path

    return DeliveryTarget(
        filename=data["filename"],
        path=Path(data["path"]),
        location=data["location"],
        requires_approval=data["requires_approval"],
        requested_path=data.get("requested_path"),
        download_url=data.get("download_url"),
    )
