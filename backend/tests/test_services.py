from app.services.knowledge import split_chunks
from app.services.query_logic import cosine_similarity


def test_split_chunks_returns_non_empty() -> None:
    text = 'Bonjour\n\nJe suis etudiant.\n\nNous parlons francais.'
    chunks = split_chunks(text, max_chars=20)
    assert len(chunks) >= 2
    assert all(chunks)


def test_cosine_similarity_identity() -> None:
    value = cosine_similarity([1.0, 0.0], [1.0, 0.0])
    assert value > 0.99
