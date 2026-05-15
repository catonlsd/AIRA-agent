from pathlib import Path

from docx import Document as DocxDocument
from pypdf import PdfReader


SUPPORTED_EXTENSIONS = {".pdf", ".txt", ".docx", ".md", ".markdown"}


def extract_text(path: str) -> list[dict]:
    file_path = Path(path)
    suffix = file_path.suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise ValueError(f"Unsupported file type: {suffix}")
    if suffix == ".pdf":
        return _extract_pdf(file_path)
    if suffix == ".docx":
        return [{"page": None, "text": _extract_docx(file_path)}]
    return [{"page": None, "text": file_path.read_text(encoding="utf-8", errors="ignore")}]


def _extract_pdf(path: Path) -> list[dict]:
    reader = PdfReader(str(path))
    pages = []
    for index, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        if text.strip():
            pages.append({"page": index, "text": text})
    return pages


def _extract_docx(path: Path) -> str:
    document = DocxDocument(str(path))
    paragraphs = [p.text for p in document.paragraphs if p.text.strip()]
    return "\n\n".join(paragraphs)
