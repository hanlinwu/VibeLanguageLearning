import json
from io import BytesIO
from collections.abc import Iterable


def decode_text_content(content: bytes) -> str:
    for encoding in ('utf-8', 'utf-8-sig', 'gb18030'):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    return content.decode('latin-1', errors='replace')


def extract_pdf_payload(content: bytes) -> str:
    try:
        from pypdf import PdfReader
    except Exception as exc:  # pragma: no cover - dependency/runtime issues
        raise RuntimeError('PDF parser is not available. Please install pypdf.') from exc

    reader = PdfReader(BytesIO(content))
    pages: list[str] = []
    for page in reader.pages:
        pages.append((page.extract_text() or '').strip())
    return '\n'.join(part for part in pages if part)


def extract_docx_payload(content: bytes) -> str:
    try:
        from docx import Document
    except Exception as exc:  # pragma: no cover - dependency/runtime issues
        raise RuntimeError('DOCX parser is not available. Please install python-docx.') from exc

    doc = Document(BytesIO(content))
    lines = [p.text.strip() for p in doc.paragraphs if p.text and p.text.strip()]
    return '\n'.join(lines)


def extract_text_payload(content: bytes, content_type: str, filename: str = '') -> str:
    ctype = (content_type or '').lower()
    name = filename.lower()
    if 'pdf' in ctype or name.endswith('.pdf'):
        return extract_pdf_payload(content)
    if (
        'wordprocessingml.document' in ctype
        or 'msword' in ctype
        or name.endswith('.docx')
        or name.endswith('.doc')
    ):
        return extract_docx_payload(content)

    raw = decode_text_content(content)
    if 'json' not in ctype and not name.endswith('.json'):
        return raw

    data = json.loads(raw)
    if isinstance(data, dict):
        values: Iterable = data.values()
    elif isinstance(data, list):
        values = data
    else:
        return str(data)

    return '\n'.join(str(item) for item in values)


def split_chunks_stable(text: str, max_chars: int = 350) -> list[str]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    chunks: list[str] = []
    current = ''

    for line in lines:
        if len(current) + len(line) + 1 > max_chars and current:
            chunks.append(current)
            current = line
        else:
            current = f'{current}\n{line}'.strip()

    if current:
        chunks.append(current)
    return chunks
