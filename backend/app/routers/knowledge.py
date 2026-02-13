from datetime import datetime
from io import BytesIO
from typing import Optional
from urllib.parse import quote

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session

from app.db import SessionLocal, get_db
from app.deps import get_current_user
from app.llm_client import llm_client
from app.models import KnowledgeBase, KnowledgeChunk, KnowledgeDocument, User
from app.services.knowledge import load_text_from_upload, split_chunks

router = APIRouter(prefix='/knowledge', tags=['knowledge'])


class KnowledgeBaseCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    scope: str = Field(default='private')
    is_enabled: bool = True


class KnowledgeBaseUpdateRequest(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    scope: Optional[str] = None
    is_enabled: Optional[bool] = None


def _ensure_default_base(db: Session, user_id: int) -> KnowledgeBase:
    base = (
        db.query(KnowledgeBase)
        .filter(KnowledgeBase.owner_id == user_id, KnowledgeBase.scope == 'private')
        .order_by(KnowledgeBase.created_at.asc())
        .first()
    )
    if base is not None:
        return base
    base = KnowledgeBase(owner_id=user_id, name='默认知识库', scope='private', is_enabled=True)
    db.add(base)
    db.commit()
    db.refresh(base)
    return base


def _normalize_scope(scope: str) -> str:
    value = (scope or '').strip().lower()
    if value not in {'private', 'public'}:
        raise HTTPException(status_code=400, detail='Invalid knowledge base scope')
    return value


def _can_manage_base(current_user: User, base: KnowledgeBase) -> bool:
    if base.scope == 'public':
        return bool(current_user.is_admin)
    return base.owner_id == current_user.id


def _is_base_visible(current_user: User, base: KnowledgeBase) -> bool:
    return base.scope == 'public' or base.owner_id == current_user.id


def _update_document_progress(
    db: Session,
    doc: KnowledgeDocument,
    *,
    status: Optional[str] = None,
    progress: Optional[int] = None,
    total_chunks: Optional[int] = None,
    processed_chunks: Optional[int] = None,
    chunk_count: Optional[int] = None,
    error_message: Optional[str] = None,
) -> None:
    if status is not None:
        doc.status = status
    if progress is not None:
        doc.progress = max(0, min(progress, 100))
    if total_chunks is not None:
        doc.total_chunks = total_chunks
    if processed_chunks is not None:
        doc.processed_chunks = processed_chunks
    if chunk_count is not None:
        doc.chunk_count = chunk_count
    if error_message is not None:
        doc.error_message = error_message
    db.add(doc)
    db.commit()


def _process_document_ingestion(document_id: int, content: bytes, content_type: str, filename: str) -> None:
    db = SessionLocal()
    try:
        doc = db.query(KnowledgeDocument).filter(KnowledgeDocument.id == document_id).first()
        if doc is None or doc.deleted_at is not None:
            return

        _update_document_progress(db, doc, status='slicing', progress=10, error_message=None)
        text = load_text_from_upload(content, content_type, filename=filename)
        chunks = split_chunks(text)
        _update_document_progress(db, doc, status='embedding', progress=20, total_chunks=len(chunks), processed_chunks=0)

        if not chunks:
            _update_document_progress(db, doc, status='completed', progress=100, chunk_count=0, total_chunks=0)
            return

        inserted = 0
        for idx, chunk in enumerate(chunks):
            embedding = llm_client.embed_text(chunk)
            doc = db.query(KnowledgeDocument).filter(KnowledgeDocument.id == document_id).first()
            if doc is None or doc.deleted_at is not None:
                return
            db.add(
                KnowledgeChunk(
                    document_id=doc.id,
                    chunk_index=idx,
                    text=chunk,
                    embedding=embedding,
                    knowledge_point='general',
                )
            )
            db.commit()
            inserted += 1
            progress = 20 + int((inserted / len(chunks)) * 75)
            _update_document_progress(
                db,
                doc,
                status='embedding',
                progress=progress,
                processed_chunks=inserted,
                chunk_count=inserted,
                total_chunks=len(chunks),
            )

        _update_document_progress(
            db,
            doc,
            status='completed',
            progress=100,
            processed_chunks=inserted,
            chunk_count=inserted,
            total_chunks=len(chunks),
        )
    except Exception as exc:  # pragma: no cover
        db.rollback()
        doc = db.query(KnowledgeDocument).filter(KnowledgeDocument.id == document_id).first()
        if doc is not None:
            _update_document_progress(db, doc, status='failed', progress=100, error_message=str(exc)[:300])
    finally:
        db.close()


@router.post('/bases')
def create_base(
    payload: KnowledgeBaseCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    scope = _normalize_scope(payload.scope)
    if scope == 'public' and not current_user.is_admin:
        raise HTTPException(status_code=403, detail='Only admin can create public knowledge base')
    base = KnowledgeBase(
        owner_id=current_user.id,
        name=payload.name.strip(),
        scope=scope,
        is_enabled=payload.is_enabled,
    )
    db.add(base)
    db.commit()
    db.refresh(base)
    return {
        'id': base.id,
        'name': base.name,
        'scope': base.scope,
        'is_enabled': base.is_enabled,
        'created_at': base.created_at.isoformat(),
        'updated_at': base.updated_at.isoformat(),
    }


@router.get('/bases')
def list_bases(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> list[dict]:
    _ensure_default_base(db, current_user.id)
    bases = db.query(KnowledgeBase).filter(
        or_(KnowledgeBase.owner_id == current_user.id, KnowledgeBase.scope == 'public')
    ).order_by(KnowledgeBase.updated_at.desc()).all()

    response: list[dict] = []
    for base in bases:
        doc_count = (
            db.query(func.count(KnowledgeDocument.id))
            .filter(KnowledgeDocument.knowledge_base_id == base.id, KnowledgeDocument.deleted_at.is_(None))
            .scalar()
            or 0
        )
        chunk_count = (
            db.query(func.count(KnowledgeChunk.id))
            .join(KnowledgeDocument, KnowledgeDocument.id == KnowledgeChunk.document_id)
            .filter(KnowledgeDocument.knowledge_base_id == base.id, KnowledgeDocument.deleted_at.is_(None))
            .scalar()
            or 0
        )
        response.append(
            {
                'id': base.id,
                'name': base.name,
                'scope': base.scope,
                'is_enabled': base.is_enabled,
                'can_manage': _can_manage_base(current_user, base),
                'document_count': int(doc_count),
                'chunk_count': int(chunk_count),
                'created_at': base.created_at.isoformat(),
                'updated_at': base.updated_at.isoformat(),
            }
        )
    return response


@router.patch('/bases/{base_id}')
def update_base(
    base_id: int,
    payload: KnowledgeBaseUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    base = db.query(KnowledgeBase).filter(KnowledgeBase.id == base_id).first()
    if base is None:
        raise HTTPException(status_code=404, detail='Knowledge base not found')
    if not _can_manage_base(current_user, base):
        raise HTTPException(status_code=403, detail='No permission to modify this knowledge base')
    if payload.name is not None:
        base.name = payload.name.strip()
    if payload.scope is not None:
        scope = _normalize_scope(payload.scope)
        if scope == 'public' and not current_user.is_admin:
            raise HTTPException(status_code=403, detail='Only admin can set public knowledge base')
        base.scope = scope
    if payload.is_enabled is not None:
        base.is_enabled = payload.is_enabled
    base.updated_at = datetime.utcnow()
    db.add(base)
    db.commit()
    db.refresh(base)
    return {
        'id': base.id,
        'name': base.name,
        'scope': base.scope,
        'is_enabled': base.is_enabled,
        'created_at': base.created_at.isoformat(),
        'updated_at': base.updated_at.isoformat(),
    }


@router.post('/upload')
def upload_knowledge(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    knowledge_base_id: Optional[int] = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    if not file.content_type:
        raise HTTPException(status_code=400, detail='Missing content type')

    base: Optional[KnowledgeBase]
    if knowledge_base_id is None:
        base = _ensure_default_base(db, current_user.id)
    else:
        base = db.query(KnowledgeBase).filter(KnowledgeBase.id == knowledge_base_id).first()
        if base is None:
            raise HTTPException(status_code=404, detail='Knowledge base not found')
        if not _can_manage_base(current_user, base):
            raise HTTPException(status_code=403, detail='No permission to upload to this knowledge base')

    content = file.file.read()
    doc = KnowledgeDocument(
        owner_id=current_user.id,
        knowledge_base_id=base.id,
        filename=file.filename,
        content_type=file.content_type,
        raw_content=content,
        file_size=len(content),
        status='queued',
        progress=0,
        total_chunks=0,
        processed_chunks=0,
        chunk_count=0,
        error_message=None,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)

    background_tasks.add_task(_process_document_ingestion, doc.id, content, file.content_type, file.filename or '')

    return {
        'document_id': doc.id,
        'knowledge_base_id': base.id,
        'status': doc.status,
        'progress': doc.progress,
    }


@router.get('/docs')
def list_docs(
    knowledge_base_id: Optional[int] = Query(default=None),
    include_deleted: bool = Query(default=False),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[dict]:
    query = (
        db.query(KnowledgeDocument)
        .join(KnowledgeBase, KnowledgeBase.id == KnowledgeDocument.knowledge_base_id)
        .filter(
            or_(
                KnowledgeBase.scope == 'public',
                and_(KnowledgeBase.scope == 'private', KnowledgeBase.owner_id == current_user.id),
            )
        )
    )
    if knowledge_base_id is not None:
        base = db.query(KnowledgeBase).filter(KnowledgeBase.id == knowledge_base_id).first()
        if base is None:
            return []
        if not _is_base_visible(current_user, base):
            return []
        if include_deleted and not _can_manage_base(current_user, base):
            include_deleted = False
        query = query.filter(KnowledgeDocument.knowledge_base_id == knowledge_base_id)
    if include_deleted:
        query = query.filter(KnowledgeDocument.deleted_at.is_not(None))
    else:
        query = query.filter(KnowledgeDocument.deleted_at.is_(None))
    docs = query.order_by(KnowledgeDocument.created_at.desc()).all()
    return [
        {
            'id': d.id,
            'knowledge_base_id': d.knowledge_base_id,
            'filename': d.filename,
            'content_type': d.content_type,
            'status': d.status,
            'file_size': int(d.file_size or 0),
            'deleted_at': d.deleted_at.isoformat() if d.deleted_at else None,
            'progress': d.progress,
            'total_chunks': d.total_chunks,
            'processed_chunks': d.processed_chunks,
            'chunk_count': d.chunk_count,
            'error_message': d.error_message,
            'created_at': d.created_at.isoformat(),
        }
        for d in docs
    ]


@router.get('/docs/{document_id}/download')
def download_doc(
    document_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    doc = (
        db.query(KnowledgeDocument)
        .join(KnowledgeBase, KnowledgeBase.id == KnowledgeDocument.knowledge_base_id)
        .filter(KnowledgeDocument.id == document_id)
        .first()
    )
    if doc is None:
        raise HTTPException(status_code=404, detail='Document not found')

    base = db.query(KnowledgeBase).filter(KnowledgeBase.id == doc.knowledge_base_id).first()
    if base is None or not _is_base_visible(current_user, base):
        raise HTTPException(status_code=404, detail='Document not found')
    if doc.deleted_at is not None:
        raise HTTPException(status_code=404, detail='Document not found')
    if doc.raw_content is None:
        raise HTTPException(status_code=404, detail='Original file is not available')

    filename = doc.filename or f'document-{doc.id}'
    # HTTP header values must be latin-1 encodable. Use RFC 5987 for unicode names.
    ascii_name = filename.encode('ascii', errors='ignore').decode('ascii') or f'document-{doc.id}'
    encoded_name = quote(filename, safe='')
    return StreamingResponse(
        BytesIO(doc.raw_content),
        media_type=doc.content_type or 'application/octet-stream',
        headers={
            'Content-Disposition': (
                f'attachment; filename="{ascii_name}"; filename*=UTF-8\'\'{encoded_name}'
            )
        },
    )


@router.delete('/docs/{document_id}')
def delete_doc(
    document_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    doc = db.query(KnowledgeDocument).filter(KnowledgeDocument.id == document_id).first()
    if doc is None:
        raise HTTPException(status_code=404, detail='Document not found')

    base = db.query(KnowledgeBase).filter(KnowledgeBase.id == doc.knowledge_base_id).first()
    if base is None:
        raise HTTPException(status_code=404, detail='Knowledge base not found')
    if not _can_manage_base(current_user, base):
        raise HTTPException(status_code=403, detail='No permission to delete this document')

    if doc.deleted_at is not None:
        return {'deleted': True}
    doc.deleted_at = datetime.utcnow()
    db.add(doc)
    db.commit()
    return {'deleted': True}


@router.post('/docs/{document_id}/restore')
def restore_doc(
    document_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    doc = db.query(KnowledgeDocument).filter(KnowledgeDocument.id == document_id).first()
    if doc is None:
        raise HTTPException(status_code=404, detail='Document not found')
    base = db.query(KnowledgeBase).filter(KnowledgeBase.id == doc.knowledge_base_id).first()
    if base is None:
        raise HTTPException(status_code=404, detail='Knowledge base not found')
    if not _can_manage_base(current_user, base):
        raise HTTPException(status_code=403, detail='No permission to restore this document')
    if doc.deleted_at is None:
        return {'restored': True}
    doc.deleted_at = None
    db.add(doc)
    db.commit()
    return {'restored': True}
