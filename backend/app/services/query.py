import uuid

from sqlalchemy.orm import Session

from app.llm_client import llm_client
from app.models import InteractionLog, KnowledgeChunk
from app.services.query_logic import rank_by_similarity


def retrieve_top_chunks(db: Session, question: str, top_k: int = 4) -> list[KnowledgeChunk]:
    question_embedding = llm_client.embed_text(question)

    bind = db.get_bind()
    if bind is not None and bind.dialect.name == 'postgresql':
        return (
            db.query(KnowledgeChunk)
            .order_by(KnowledgeChunk.embedding.cosine_distance(question_embedding))
            .limit(top_k)
            .all()
        )

    all_chunks = db.query(KnowledgeChunk).all()
    # sqlite returns numpy arrays for pgvector columns; normalize to lists for pure Python ranking.
    candidates = [{'chunk': chunk, 'embedding': list(chunk.embedding)} for chunk in all_chunks]
    ranked = rank_by_similarity(question_embedding, candidates, top_k=top_k)
    return [item['chunk'] for item in ranked]


def answer_question(db: Session, user_id: int, question: str) -> tuple[str, list[dict], str]:
    chunks = retrieve_top_chunks(db, question)
    context = '\n\n'.join(chunk.text for chunk in chunks)
    prompt = f'问题: {question}\n\n参考资料:\n{context}'
    answer = llm_client.chat(
        '你是法语学习助教。仅基于参考资料回答，并保持简洁与准确。',
        prompt,
    )

    citations = [{'chunk_id': c.id, 'preview': c.text[:120]} for c in chunks]
    trace_id = uuid.uuid4().hex

    log = InteractionLog(
        user_id=user_id,
        question=question,
        answer=answer,
        citations=citations,
        trace_id=trace_id,
    )
    db.add(log)
    db.commit()

    return answer, citations, trace_id
