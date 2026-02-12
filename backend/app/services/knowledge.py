from app.services.knowledge_logic import extract_text_payload, split_chunks_stable


def split_chunks(text: str, max_chars: int = 350) -> list[str]:
    return split_chunks_stable(text=text, max_chars=max_chars)


def load_text_from_upload(content: bytes, content_type: str, filename: str = '') -> str:
    return extract_text_payload(content=content, content_type=content_type, filename=filename)
