from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user
from app.llm_client import llm_client
from app.models import KnowledgeChunk, KnowledgeDocument, User
from app.services.knowledge import load_text_from_upload, split_chunks

router = APIRouter(prefix='/knowledge', tags=['knowledge'])


@router.post('/upload')
def upload_knowledge(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    if not file.content_type:
        raise HTTPException(status_code=400, detail='Missing content type')

    content = file.file.read()
    text = load_text_from_upload(content, file.content_type)
    chunks = split_chunks(text)

    doc = KnowledgeDocument(owner_id=current_user.id, filename=file.filename, content_type=file.content_type)
    db.add(doc)
    db.commit()
    db.refresh(doc)

    inserted = 0
    for idx, chunk in enumerate(chunks):
        embedding = llm_client.embed_text(chunk)
        db.add(
            KnowledgeChunk(
                document_id=doc.id,
                chunk_index=idx,
                text=chunk,
                embedding=embedding,
                knowledge_point='general',
            )
        )
        inserted += 1

    db.commit()
    return {'document_id': doc.id, 'chunks': inserted}


@router.get('/docs')
def list_docs(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> list[dict]:
    docs = db.query(KnowledgeDocument).filter(KnowledgeDocument.owner_id == current_user.id).all()
    return [{'id': d.id, 'filename': d.filename, 'content_type': d.content_type} for d in docs]
