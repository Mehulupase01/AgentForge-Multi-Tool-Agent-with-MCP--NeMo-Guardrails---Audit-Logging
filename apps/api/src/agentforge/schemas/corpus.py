from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class CorpusDocumentResponse(BaseModel):
    id: UUID
    filename: str
    title: str
    tokens: int
    content_hash: str
    ingested_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ReindexResponse(BaseModel):
    indexed: int
    skipped_unchanged: int
    duration_ms: int
