from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from agentforge.database import get_db
from agentforge.schemas.common import Envelope
from agentforge.schemas.corpus import CorpusDocumentResponse, ReindexResponse
from agentforge.services.corpus_service import CorpusService

router = APIRouter(prefix="/api/v1/corpus", tags=["corpus"])
corpus_service = CorpusService()


@router.post("/reindex", response_model=ReindexResponse, status_code=status.HTTP_202_ACCEPTED)
async def reindex_corpus(
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ReindexResponse:
    return await corpus_service.reindex(db)


@router.get("/documents", response_model=Envelope[CorpusDocumentResponse])
async def list_corpus_documents(
    db: Annotated[AsyncSession, Depends(get_db)],
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=50, ge=1, le=200),
) -> Envelope[CorpusDocumentResponse]:
    return await corpus_service.list_documents(db, page=page, per_page=per_page)
