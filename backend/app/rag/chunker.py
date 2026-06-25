# File: backend/app/rag/chunker.py
"""
Section- and page-aware chunking for document Q&A.

Flat fixed-width slicing splits mid-sentence and loses the heading a passage
sits under, which hurts both retrieval and answer grounding. This chunker is
more deliberate while staying simple and dependency-free:

  - never merges across page boundaries (page provenance stays exact);
  - splits on paragraph and heading boundaries, packing whole paragraphs up to
    chunk_size instead of cutting through them;
  - tracks the current heading and prepends it to each chunk for context
    continuity (so a chunk reads as "<section>\n<body>", better for QA);
  - carries a word-aligned overlap tail between consecutive body chunks within a
    section so a fact spanning a boundary still retrieves;
  - hard-splits a single oversized paragraph (with overlap) as a fallback;
  - drops degenerate (empty) chunks and folds a tiny trailing chunk back into
    its predecessor.

Output shape is unchanged for callers (`text`, `page`) plus an optional
`section` — so ingestion can store section metadata for reranking/composition.
"""

import re

_MD_OR_NUMBERED_HEADING = re.compile(r"^(#{1,6}\s+\S|\d+(\.\d+)*\.?\s+\S)")


def clean_text(text: str) -> str:
    text = text.replace("\x00", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _heading_of(paragraph: str) -> str | None:
    """Return the paragraph's leading line if it reads as a heading, else None.

    Conservative on purpose: markdown (`# …`), numbered (`1.2 …`), short
    ALL-CAPS lines, or short lines ending in a colon. Prose sentences (which end
    in . ! ?) are never treated as headings, so ordinary documents are unaffected.
    """
    line = paragraph.split("\n", 1)[0].strip()
    if not line or len(line) > 90:
        return None
    if _MD_OR_NUMBERED_HEADING.match(line):
        return line.lstrip("#").strip()
    if line.endswith(":") and len(line.split()) <= 10:
        return line
    if line.endswith((".", "!", "?", ",", ";")):
        return None
    words = line.split()
    letters = [c for c in line if c.isalpha()]
    if letters and len(words) <= 8 and all(c.isupper() for c in letters):
        return line  # ALL-CAPS short line
    # Title-style heading: short, capitalized, no terminal sentence punctuation
    # (prose ends in . ! ? and was already excluded above, so ordinary sentences
    # are never misread as headings).
    if letters and 1 <= len(words) <= 8 and line[0].isupper():
        return line
    return None


def _tail(text: str, overlap: int) -> str:
    """Last ~overlap characters of text, cut back to a word boundary."""
    if overlap <= 0 or len(text) <= overlap:
        return text if overlap > 0 else ""
    snippet = text[-overlap:]
    space = snippet.find(" ")
    return snippet[space + 1 :].strip() if space != -1 else snippet.strip()


def _with_section(section: str | None, body: str) -> str:
    if section and not body.startswith(section):
        return f"{section}\n{body}"
    return body


def _slice(text: str, size: int, overlap: int) -> list[str]:
    """Fallback flat slicing for a single oversized paragraph."""
    out: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        piece = text[start:end].strip()
        if piece:
            out.append(piece)
        if end == len(text):
            break
        start = max(end - overlap, start + 1)
    return out


def _merge_tiny(chunks: list[dict], min_len: int) -> list[dict]:
    """Fold a tiny trailing chunk into its predecessor (same page + section)."""
    if len(chunks) < 2:
        return chunks
    last, prev = chunks[-1], chunks[-2]
    body = last["text"]
    if last.get("section"):
        body = body[len(last["section"]) :].strip()
    if len(body) < min_len and prev.get("section") == last.get("section"):
        prev["text"] = f"{prev['text']}\n\n{body}".strip()
        return chunks[:-1]
    return chunks


def _chunk_page_text(text: str, chunk_size: int, overlap: int) -> list[dict]:
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    if not paragraphs:
        return []

    out: list[dict] = []
    section: str | None = None
    buffer = ""

    def emit() -> None:
        nonlocal buffer
        body = buffer.strip()
        if body:
            out.append({"text": _with_section(section, body), "section": section})
        buffer = ""

    for paragraph in paragraphs:
        heading = _heading_of(paragraph)
        if heading is not None:
            emit()
            section = heading
            remainder = paragraph[len(paragraph.split("\n", 1)[0]) :].strip()
            buffer = remainder
            continue

        candidate = f"{buffer}\n\n{paragraph}".strip() if buffer else paragraph
        if len(candidate) <= chunk_size:
            buffer = candidate
            continue

        # Adding this paragraph overflows the chunk: flush, then start fresh —
        # seeding a word-aligned overlap tail so a boundary-spanning fact survives.
        previous = buffer.strip()
        emit()
        if len(paragraph) > chunk_size:
            for segment in _slice(paragraph, chunk_size, overlap):
                out.append({"text": _with_section(section, segment), "section": section})
            buffer = ""
        else:
            tail = _tail(previous, overlap)
            buffer = f"{tail}\n\n{paragraph}".strip() if tail else paragraph

    emit()
    return _merge_tiny(out, min_len=min(120, max(1, chunk_size // 4)))


def chunk_pages(pages: list[dict], chunk_size: int, overlap: int) -> list[dict]:
    chunks: list[dict] = []
    for page in pages:
        text = clean_text(page.get("text", ""))
        if not text:
            continue
        page_no = page.get("page")
        for piece in _chunk_page_text(text, chunk_size, overlap):
            piece["page"] = page_no
            chunks.append(piece)
    return chunks
