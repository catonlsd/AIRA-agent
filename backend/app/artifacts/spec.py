# File: backend/app/artifacts/spec.py
"""
Artifact content model + content preparation.

The artifact pipeline separates concerns deliberately:

    prepare content (this module) -> generate file (generators) ->
    validate (validator) -> deliver (delivery)

`ArtifactSpec` is the structured, library-agnostic description of what to
build. `ArtifactPlanBuilder` prepares that content intentionally — via the LLM
when available, with a deterministic fallback so the pipeline never depends on
a provider for structural correctness.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

ARTIFACT_KINDS = ("pptx", "docx", "xlsx")
_EXTENSIONS = {"pptx": ".pptx", "docx": ".docx", "xlsx": ".xlsx"}
_KIND_NOUNS = {"pptx": "presentation", "docx": "document", "xlsx": "spreadsheet"}

_MAX_SLIDES = 12
_MAX_SECTIONS = 10
_MAX_ROWS = 200


@dataclass
class Slide:
    title: str
    bullets: list[str] = field(default_factory=list)
    layout: str = "content"  # title | agenda | section | content | summary
    notes: str = ""                 # speaker notes (presenter detail)
    image_query: str | None = None  # what an image, if any, should depict
    image_path: str | None = None   # resolved local image path (else text-only)


@dataclass
class Section:
    heading: str
    paragraphs: list[str] = field(default_factory=list)
    bullets: list[str] = field(default_factory=list)
    level: int = 1


@dataclass
class ArtifactSpec:
    """Structured, format-agnostic content for one artifact."""

    kind: str  # pptx | docx | xlsx
    title: str
    subtitle: str = ""
    style: str = ""                                          # style profile name
    slides: list[Slide] = field(default_factory=list)        # pptx
    sections: list[Section] = field(default_factory=list)    # docx
    sheet_name: str = "Sheet1"                                # xlsx
    headers: list[str] = field(default_factory=list)         # xlsx
    rows: list[list[Any]] = field(default_factory=list)      # xlsx

    @property
    def extension(self) -> str:
        return _EXTENSIONS.get(self.kind, ".bin")

    def outline(self) -> list[str]:
        """User-facing plan outline (slide titles / headings / columns)."""
        if self.kind == "pptx":
            return [s.title for s in self.slides]
        if self.kind == "docx":
            return [s.heading for s in self.sections]
        if self.kind == "xlsx":
            return [f"Columns: {', '.join(self.headers)}"] if self.headers else []
        return []


def kind_noun(kind: str) -> str:
    return _KIND_NOUNS.get(kind, "file")


# Generic slide titles that shouldn't drive an image search.
_NON_VISUAL_TITLES = ("agenda", "summary", "conclusion", "overview", "introduction", "references")


def _image_query_from_title(slide_title: str, deck_title: str) -> str | None:
    """A concrete image subject derived from a slide title (fallback when the
    model omits one). Strips filler prefixes; falls back to the deck topic."""
    cleaned = _TITLE_PREFIXES.sub("", (slide_title or "").strip()).strip()
    lowered = cleaned.lower()
    if not cleaned or any(word == lowered for word in _NON_VISUAL_TITLES):
        # Generic divider slide → use the deck topic instead of a vague word.
        deck = (deck_title or "").strip()
        return deck or None
    return cleaned


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", (text or "").lower()).strip("_")
    return slug[:48] or "artifact"


_TITLE_PREFIXES = re.compile(
    r"^(introduction to|overview of|significance of|importance of|what is an?|what is|"
    r"types of|kinds of|applications of|advantages of|benefits of|growth in|the|an?)\s+",
    re.IGNORECASE,
)


def derive_title(goal: str, kind: str) -> str:
    """A clean title from the request ("Make me a PPT on X" -> "X")."""
    text = (goal or "").strip()
    # A quoted topic ("Topic 'Semiconductors'...") is the strongest, cleanest signal.
    quoted = re.search(r"[\"“‘']([^\"”’']{2,60})[\"”’']", text)
    if quoted and quoted.group(1).strip():
        topic = quoted.group(1).strip()
        topic = re.sub(r"\s+", " ", topic).strip(" .,-")
        return topic.title() if topic else kind_noun(kind).title()
    match = re.search(r"\b(?:on|about|for|of|titled|called)\s+(.+)", text, re.IGNORECASE)
    topic = match.group(1) if match else text
    topic = re.sub(
        r"\b(a|an|the|me|please|ppt|pptx|powerpoint|presentation|slides?|deck|"
        r"docx?|document|report|xlsx|excel|spreadsheet|workbook|sheet|tracker|"
        r"make|create|generate|build|write|draft|produce|prepare|and let me download.*)\b",
        "",
        topic,
        flags=re.IGNORECASE,
    )
    topic = re.sub(r"\s+", " ", topic).strip(" .,-")
    return topic.title() if topic else f"{kind_noun(kind).title()}"


class ArtifactPlanBuilder:
    """Prepares structured content for an artifact (LLM-first, safe fallback)."""

    def build(
        self,
        goal: str,
        kind: str,
        *,
        generate: Optional[Callable[..., str]] = None,
        context: Optional[str] = None,
        style: str = "",
        title: Optional[str] = None,
    ) -> ArtifactSpec:
        # `title` lets a revision keep the original clean title instead of
        # re-deriving it from a goal that now carries revision instructions.
        resolved_title = title or derive_title(goal, kind)
        data = self._prepare_content(goal, kind, resolved_title, generate, context)
        spec = self._spec_from_data(kind, resolved_title, data)
        spec.style = style
        return spec

    # ── content preparation ──────────────────────────────────────────────────

    def _prepare_content(
        self,
        goal: str,
        kind: str,
        title: str,
        generate: Optional[Callable[..., str]],
        context: Optional[str],
    ) -> Optional[dict]:
        if generate is None:
            return None
        schema = {
            "pptx": (
                '{"subtitle": "one-line subtitle", "slides": [{"title": "...", '
                '"bullets": ["full, informative point", "..."], "notes": '
                '"3-4 sentences of speaker notes (a real paragraph) expanding the '
                'slide with explanation, context, and detail", "image_query": '
                '"a concrete, depictable visual subject for THIS slide"}]}'
                "  — 6-9 content slides. Each bullet must be a COMPLETE, specific "
                "point of ~12-20 words (a real fact, figure, example, or "
                "explanation) — NEVER one- or two-word fragments. 4-5 bullets per "
                "slide. ALWAYS include substantive `notes` (a full paragraph) and, "
                "for any slide describing a physical/visual subject, a concrete "
                "`image_query` (e.g. the specific plant, place, or object)."
            ),
            "docx": (
                '{"subtitle": "...", "sections": [{"heading": "...", '
                '"paragraphs": ["2-4 full, substantive sentences each"], '
                '"bullets": ["optional supporting points"]}]}  — start with an '
                "Executive Summary, then 4-6 substantive sections each with real "
                "explanatory paragraphs (not one-liners), ending with a Conclusion."
            ),
            "xlsx": (
                '{"sheet_name": "short tab name", "headers": ["...", "..."], '
                '"rows": [["...", "..."]]}  — a clear, consistent column order and '
                "useful, realistic sample rows (aim for 8-15 rows)."
            ),
        }[kind]
        grounding = (
            "\n\nGround the content in this researched source material — use its "
            f"facts, figures, and specifics:\n{context}"
            if context
            else ""
        )
        try:
            raw = generate(
                system=(
                    "You are AIRA-X's artifact content planner. Produce ONLY a JSON "
                    f"object for a professional {kind_noun(kind)} titled '{title}'. "
                    f"Shape: {schema}. Be substantive, specific, and informative — "
                    "real content a professional would present, with concrete "
                    "detail. No markdown fences, no prose outside the JSON."
                ),
                prompt=f"{goal}{grounding}",
                temperature=0.5,
            )
        except Exception:
            return None
        return self._parse_json_object(raw)

    @staticmethod
    def _parse_json_object(raw: str) -> Optional[dict]:
        if not raw:
            return None
        match = re.search(r"\{[\s\S]*\}", raw)
        if not match:
            return None
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
        return data if isinstance(data, dict) else None

    # ── spec assembly (validates/bounds the prepared content) ────────────────

    def _spec_from_data(self, kind: str, title: str, data: Optional[dict]) -> ArtifactSpec:
        if kind == "pptx":
            return self._pptx_spec(title, data)
        if kind == "docx":
            return self._docx_spec(title, data)
        return self._xlsx_spec(title, data)

    def _pptx_spec(self, title: str, data: Optional[dict]) -> ArtifactSpec:
        subtitle = str((data or {}).get("subtitle") or "").strip() if isinstance(data, dict) else ""
        content: list[Slide] = []
        raw_slides = (data or {}).get("slides") if isinstance(data, dict) else None
        if isinstance(raw_slides, list):
            for item in raw_slides:
                if not isinstance(item, dict):
                    continue
                stitle = str(item.get("title") or "").strip()
                if not stitle:
                    continue
                bullets = [str(b).strip() for b in (item.get("bullets") or []) if str(b).strip()]
                image_query = item.get("image_query")
                image_query = str(image_query).strip() if image_query else None
                notes = str(item.get("notes") or "").strip()
                # If the model didn't supply an image subject, derive one from the
                # slide title so visual slides still get a relevant image.
                if not image_query:
                    image_query = _image_query_from_title(stitle, title)
                content.append(
                    Slide(
                        title=stitle, bullets=bullets[:6], layout="content",
                        notes=notes, image_query=image_query,
                    )
                )
        if not content:  # deterministic fallback content
            for heading in ("Overview", "Key Points", "Details"):
                content.append(Slide(title=heading, bullets=[f"{heading} for {title}."], layout="content"))
        content = content[: _MAX_SLIDES - 3]

        # Intentional deck structure: title -> agenda -> content -> summary.
        slides: list[Slide] = [
            Slide(title=title, bullets=[subtitle] if subtitle else [], layout="title")
        ]
        body = [s for s in content if "summary" not in s.title.lower() and "conclusion" not in s.title.lower()]
        if len(body) >= 3:
            slides.append(Slide(title="Agenda", bullets=[s.title for s in body[:6]], layout="agenda"))
        slides.extend(content)
        if not any("summary" in s.title.lower() or "conclusion" in s.title.lower() for s in content):
            slides.append(
                Slide(title="Summary", bullets=[f"Key takeaways on {title}."], layout="summary")
            )
        return ArtifactSpec(kind="pptx", title=title, subtitle=subtitle, slides=slides)

    def _docx_spec(self, title: str, data: Optional[dict]) -> ArtifactSpec:
        subtitle = str((data or {}).get("subtitle") or "").strip() if isinstance(data, dict) else ""
        sections: list[Section] = []
        raw_sections = (data or {}).get("sections") if isinstance(data, dict) else None
        if isinstance(raw_sections, list) and raw_sections:
            for item in raw_sections[:_MAX_SECTIONS]:
                if not isinstance(item, dict):
                    continue
                heading = str(item.get("heading") or "").strip()
                paras = [str(p).strip() for p in (item.get("paragraphs") or []) if str(p).strip()]
                bullets = [str(b).strip() for b in (item.get("bullets") or []) if str(b).strip()]
                if heading or paras or bullets:
                    sections.append(
                        Section(heading=heading or "Section", paragraphs=paras, bullets=bullets[:8], level=1)
                    )
        if not sections:
            sections = [
                Section(heading="Executive Summary", paragraphs=[f"This report covers {title}."], level=1),
                Section(heading="Overview", paragraphs=[f"Key aspects of {title}."], level=1),
                Section(heading="Conclusion", paragraphs=[f"Concluding notes on {title}."], level=1),
            ]
        # Ensure a leading summary and a closing section for clean report flow.
        if not any("summary" in s.heading.lower() for s in sections):
            sections.insert(0, Section(heading="Executive Summary", paragraphs=[f"An overview of {title}."], level=1))
        if not any(h in sections[-1].heading.lower() for h in ("summary", "conclusion")):
            sections.append(Section(heading="Conclusion", paragraphs=[f"Closing notes on {title}."], level=1))
        return ArtifactSpec(kind="docx", title=title, subtitle=subtitle, sections=sections)

    def _xlsx_spec(self, title: str, data: Optional[dict]) -> ArtifactSpec:
        headers: list[str] = []
        rows: list[list[Any]] = []
        sheet_name = "Sheet1"
        if isinstance(data, dict):
            sheet_name = str(data.get("sheet_name") or "Sheet1")[:31] or "Sheet1"
            headers = [str(h).strip() for h in (data.get("headers") or []) if str(h).strip()]
            for raw_row in (data.get("rows") or [])[:_MAX_ROWS]:
                if isinstance(raw_row, list):
                    rows.append([("" if c is None else c) for c in raw_row])
        if not headers:
            headers = ["Item", "Value", "Notes"]
            rows = rows or [["Example", "", ""]]
        # A meaningful tab name beats the generic "Sheet1".
        if sheet_name in ("Sheet1", "Sheet", ""):
            sheet_name = (slugify(title).replace("_", " ").title() or "Data")[:31]
        return ArtifactSpec(kind="xlsx", title=title, sheet_name=sheet_name, headers=headers, rows=rows)
