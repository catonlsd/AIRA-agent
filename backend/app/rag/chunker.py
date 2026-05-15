import re


def clean_text(text: str) -> str:
    text = text.replace("\x00", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def chunk_pages(pages: list[dict], chunk_size: int, overlap: int) -> list[dict]:
    chunks: list[dict] = []
    for page in pages:
        text = clean_text(page["text"])
        if not text:
            continue
        start = 0
        while start < len(text):
            end = min(start + chunk_size, len(text))
            chunk = text[start:end].strip()
            if chunk:
                chunks.append({"page": page.get("page"), "text": chunk})
            if end == len(text):
                break
            start = max(end - overlap, start + 1)
    return chunks
